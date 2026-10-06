"""Agent Team presets: saved rosters, launch planning, and launch execution."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, or_, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentPaneBinding,
    AgentTeamLaunch,
    AgentTeamLaunchItem,
    AgentTeamPreset,
    AgentTeamSlot,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailTeamMember,
    TeamGithubScope,
)
from app.models.schemas import (
    AgentTeamCreateFromBridgeRequest,
    AgentTeamCreateFromMailRequest,
    AgentTeamLaunchPlan,
    AgentTeamLaunchPlanItem,
    AgentTeamLaunchRequest,
    AgentTeamLaunchResult,
    AgentTeamLaunchResultItem,
    AgentTeamPresetCreate,
    AgentTeamPresetResponse,
    AgentTeamSlotCreate,
    AgentTeamSlotResponse,
    AgentTeamSlotUpdate,
)
from app.services import agent_mail_install_service
from app.services.agent_bridge.discovery import discover_agent_sessions
from app.services.agent_bridge.spawn import spawn_session
from app.services.agent_mail_service import MCP_HEARTBEAT_TTL_SECONDS, agent_mail_service
from app.services.github_recovery_gate import configured_recovery_only_attempt
from app.services.providers import get_provider, get_providers
from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions
from app.services.providers.launch_contract import (
    PROVIDER_CODEX_CLI,
    launch_modes_for,
    option_keys_for,
    reasoning_efforts_for,
    supports_bedrock,
)
from app.services.providers.platform_env import PLATFORM_BEDROCK
from app.utils.peer_process import read_proc_stat
from app.utils.repo_utils import derive_repo_identity
from app.services.team_communication_policy import team_communication_guidance


class PlanConflictError(ValueError):
    """Raised when a launch request confirms an outdated launch plan.

    proven_non_write is True only for refusals checked before any launch
    action. Conflicts raised while executing plan items can follow session
    actions and must never claim a proven non-write.
    """

    def __init__(self, message: str, plan: AgentTeamLaunchPlan | None = None,
                 proven_non_write: bool = False):
        super().__init__(message)
        self.plan = plan
        self.proven_non_write = proven_non_write


class TeamDeletionConflictError(ValueError):
    """A safe refusal shared by direct service callers and the operator API."""

    def __init__(self, blockers: list[dict], block_code: str = "team_in_use"):
        message = (
            "Team cannot be deleted while automation or blocking work, approvals, revisions, "
            "workspace leases, or recovery authority remain. Pause automation and inspect team activity."
            if block_code == "team_in_use" else
            "Team deletion cannot verify safe state. Inspect team activity before deleting."
        )
        super().__init__(message)
        self.block_code = block_code
        self.blockers = blockers


_OPTION_FIELDS = {field.name for field in fields(SpawnCommandOptions)}
_PROVIDER_IDS = {provider.id for provider in get_providers()}
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_CONCRETE_MODEL_MARKERS = (".", "/", ":")
_BEDROCK_LAUNCH_OPTION_KEYS = {"platform", "aws_region", "aws_profile", "bedrock_model"}
_TEAM_SLOT_UI_COLORS = {"blue", "purple", "green", "amber", "red", "cyan", "slate"}


class AgentTeamService:
    """Persistence and orchestration for local saved agent rosters."""

    async def list_presets(self, db: AsyncSession) -> list[AgentTeamPresetResponse]:
        presets = (
            await db.execute(select(AgentTeamPreset).order_by(AgentTeamPreset.updated_at.desc()))
        ).scalars().all()
        return [await self._preset_response(db, preset) for preset in presets]

    async def get_preset(self, db: AsyncSession, preset_id: int) -> AgentTeamPresetResponse:
        preset = await self._require_preset(db, preset_id)
        return await self._preset_response(db, preset)

    async def require_preset_row(self, db: AsyncSession, preset_id: int) -> AgentTeamPreset:
        return await self._require_preset(db, preset_id)

    def normalize_repo_path(self, repo_path: str) -> tuple[str, dict[str, str]]:
        return self._normalize_repo(repo_path)

    async def create_preset(
        self, db: AsyncSession, request: AgentTeamPresetCreate
    ) -> AgentTeamPresetResponse:
        name = self._clean_required(request.name, "Team name")
        await self._ensure_preset_name_is_unique(db, name)
        preset = AgentTeamPreset(
            name=name,
            description=self._clean_optional(request.description),
            created_by=self._clean_optional(request.created_by),
            autonomy_enabled=False,
        )
        db.add(preset)
        await db.flush()

        normalized_slots = [
            self._normalize_slot_create(slot, index)
            for index, slot in enumerate(request.slots)
        ]
        for slot_data in normalized_slots:
            db.add(AgentTeamSlot(preset_id=preset.id, **slot_data))

        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def set_leader(
        self,
        db: AsyncSession,
        preset_id: int,
        *,
        leader_slot_id: int,
        expected_leader_slot_id: int | None,
        expected_updated_at: datetime,
        reason: str,
    ) -> AgentTeamPresetResponse:
        """Change Leader authority only while the team is stopped and quiescent."""
        preset = await self._lock_preset_for_slot_mutation(db, preset_id)
        expected_time = expected_updated_at.replace(tzinfo=None)
        if (preset.leader_slot_id != expected_leader_slot_id
                or preset.updated_at != expected_time):
            await db.rollback()
            raise ValueError("leader_assignment_changed")
        if preset.autonomy_enabled:
            await db.rollback()
            raise ValueError("leader_assignment_team_active")
        slot = (await db.execute(select(AgentTeamSlot).where(
            AgentTeamSlot.id == leader_slot_id,
            AgentTeamSlot.preset_id == preset_id,
            AgentTeamSlot.enabled.is_(True),
        ))).scalar_one_or_none()
        if slot is None:
            await db.rollback()
            raise ValueError("leader_slot_unavailable")

        scope_ids = select(TeamGithubScope.id).where(TeamGithubScope.preset_id == preset_id)
        item_ids = select(GithubWorkItem.id).where(GithubWorkItem.scope_id.in_(scope_ids))
        active_item = (await db.execute(select(GithubWorkItem.id).where(
            GithubWorkItem.id.in_(item_ids),
            GithubWorkItem.dispatch_status.in_(("dispatched", "verifying")),
        ).limit(1))).scalar_one_or_none()
        pending_approval = (await db.execute(select(GithubApprovalRequest.id).where(
            GithubApprovalRequest.work_item_id.in_(item_ids),
            GithubApprovalRequest.status == "pending",
        ).limit(1))).scalar_one_or_none()
        active_revision = (await db.execute(select(GithubAttemptScopeRevision.id).where(
            GithubAttemptScopeRevision.work_item_id.in_(item_ids),
            GithubAttemptScopeRevision.status.not_in(
                ("completed", "exhausted", "rejected", "superseded", "expired")
            ),
        ).limit(1))).scalar_one_or_none()
        active_workspace = (await db.execute(select(GithubWorkspace.id).where(
            GithubWorkspace.scope_id.in_(scope_ids),
            or_(GithubWorkspace.leased_item_id.is_not(None),
                GithubWorkspace.lease_token.is_not(None),
                GithubWorkspace.leased_owner_pid.is_not(None),
                GithubWorkspace.leased_owner_proc_start.is_not(None),
                GithubWorkspace.push_token_expires_at.is_not(None),
                and_(GithubWorkspace.leased_at.is_not(None),
                     GithubWorkspace.released_at.is_(None))),
        ).limit(1))).scalar_one_or_none()
        if active_item is not None or pending_approval is not None or active_revision is not None or active_workspace is not None:
            await db.rollback()
            raise ValueError("leader_assignment_team_not_quiescent")
        if not reason.strip():
            await db.rollback()
            raise ValueError("leader_assignment_reason_required")
        preset.leader_slot_id = slot.id
        preset.updated_at = datetime.utcnow()
        # A03: the Leader event persists in the same transaction as the
        # Leader change. An audit-write failure rolls back the change.
        from app.services import factory_audit_service as _audit
        await _audit.record_event(
            db,
            event_kind="leader_assignment",
            source="agent_team_service.set_leader",
            occurred_at=datetime.utcnow(),
            actor=_audit.derive_actor(actor_kind="operator"),
            team_preset_id=preset.id,
            before_values={"leader_slot_id": expected_leader_slot_id},
            after_values={"leader_slot_id": slot.id},
            context_snapshot={
                "team_created_at": preset.created_at.isoformat() if preset.created_at else None,
                "configured_provider": slot.provider,
                "observed_runtime_provider": None,
                "github_auth_mode": None,
                "slot_display_name": slot.display_name,
                "event_time_labels": ("configured_provider", "observed_runtime_provider",
                                      "slot_display_name", "team_created_at"),
            },
            sanitized_reason=reason,
            action_outcome="applied",
            correlation_id=f"leader-assignment:{preset.id}:{slot.id}",
        )
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def update_preset(
        self,
        db: AsyncSession,
        preset_id: int,
        name: str | None = None,
        description: str | None = None,
        autonomy_enabled: bool | None = None,
    ) -> AgentTeamPresetResponse:
        preset = await self._require_preset(db, preset_id)
        if name is not None:
            cleaned_name = self._clean_required(name, "Team name")
            await self._ensure_preset_name_is_unique(db, cleaned_name, exclude_preset_id=preset.id)
            preset.name = cleaned_name
        if description is not None:
            preset.description = self._clean_optional(description)
        if autonomy_enabled is not None:
            if autonomy_enabled:
                leader = await db.execute(select(AgentTeamSlot.id).where(
                    AgentTeamSlot.id == preset.leader_slot_id,
                    AgentTeamSlot.preset_id == preset.id,
                    AgentTeamSlot.enabled.is_(True),
                ))
                if leader.scalar_one_or_none() is None:
                    raise ValueError("leader_assignment_required")
            preset.autonomy_enabled = autonomy_enabled
        preset.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def delete_preset(self, db: AsyncSession, preset_id: int) -> None:
        try:
            # SQLite is the supported persistence engine. A row lock alone on
            # another dialect would not serialize inserts into child tables.
            if db.get_bind().dialect.name != "sqlite":
                raise TeamDeletionConflictError([], "team_deletion_protection_unavailable")
            # Reserve the SQLite writer before ANY authoritative guard reads.
            # Keep it until deletion commits, so competing dispatch/approval/
            # lease writes either precede the checks or follow the cascade.
            # A no-op UPDATE also works in an existing SQLAlchemy transaction;
            # a stale WAL snapshot fails closed instead of being upgraded.
            with db.no_autoflush:
                result = await db.execute(
                    update(AgentTeamPreset)
                    .where(AgentTeamPreset.id == preset_id)
                    .values(id=AgentTeamPreset.id)
                    .execution_options(synchronize_session=False)
                )
            if result.rowcount != 1:
                raise ValueError("Agent team preset not found")
            await db.flush()
            preset = (
                await db.execute(
                    select(AgentTeamPreset)
                    .where(AgentTeamPreset.id == preset_id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            await self._guard_preset_deletion(db, preset)
            await self._delete_quiescent_preset(db, preset)
        except OperationalError as exc:
            await db.rollback()
            raise TeamDeletionConflictError([], "team_deletion_state_busy") from exc
        except Exception:
            await db.rollback()
            raise

    async def _guard_preset_deletion(self, db: AsyncSession, preset: AgentTeamPreset) -> None:
        """Only known terminal authority is deletable; never expose private rows."""
        preset_id = preset.id
        scope_ids = select(TeamGithubScope.id).where(TeamGithubScope.preset_id == preset_id)
        slot_ids = select(AgentTeamSlot.id).where(AgentTeamSlot.preset_id == preset_id)
        item_ids = select(GithubWorkItem.id).where(
            or_(
                GithubWorkItem.scope_id.in_(scope_ids),
                GithubWorkItem.owner_slot_id.in_(slot_ids),
                GithubWorkItem.handoff_target_slot_id.in_(slot_ids),
            )
        )
        workspace_ids = select(GithubWorkspace.id).where(GithubWorkspace.scope_id.in_(scope_ids))
        work_href = f"/api/v1/agent-teams/presets/{preset_id}/github-work-items"
        blockers = []
        if preset.autonomy_enabled:
            blockers.append({"kind": "automation", "id": preset_id, "scope_id": None,
                             "href": f"/api/v1/agent-teams/presets/{preset_id}"})

        # The existing scope-deletion predicate includes queued, review,
        # escalated and failed work. Only merged/completed are known safe.
        items = (await db.execute(
            select(GithubWorkItem.id, GithubWorkItem.scope_id)
            .where(GithubWorkItem.id.in_(item_ids),
                   GithubWorkItem.dispatch_status.not_in(("merged", "completed")))
            .order_by(GithubWorkItem.id).limit(25)
        )).all()
        blockers.extend({"kind": "work_item", "id": row.id, "scope_id": row.scope_id,
                         "href": work_href} for row in items)

        # Residual identity is authority too, even without a leased item FK.
        workspaces = (await db.execute(
            select(GithubWorkspace.id, GithubWorkspace.scope_id).where(
                or_(GithubWorkspace.scope_id.in_(scope_ids),
                    GithubWorkspace.leased_item_id.in_(item_ids)),
                or_(GithubWorkspace.leased_item_id.is_not(None),
                    GithubWorkspace.lease_token.is_not(None),
                    GithubWorkspace.leased_owner_pid.is_not(None),
                    GithubWorkspace.leased_owner_proc_start.is_not(None),
                    GithubWorkspace.push_token_expires_at.is_not(None),
                    and_(GithubWorkspace.leased_at.is_not(None),
                         GithubWorkspace.released_at.is_(None))),
            ).order_by(GithubWorkspace.id).limit(25)
        )).all()
        blockers.extend({"kind": "workspace", "id": row.id, "scope_id": row.scope_id,
                         "href": f"/api/v1/agent-teams/github-scopes/{row.scope_id}/workspaces"}
                        for row in workspaces)

        approvals = (await db.execute(
            select(GithubApprovalRequest.id).where(
                GithubApprovalRequest.work_item_id.in_(item_ids),
                GithubApprovalRequest.status.not_in(("approved", "rejected", "superseded", "expired")),
            ).order_by(GithubApprovalRequest.id).limit(25)
        )).scalars().all()
        blockers.extend({"kind": "approval", "id": approval_id, "scope_id": None,
                         "href": work_href} for approval_id in approvals)
        revisions = (await db.execute(
            select(GithubAttemptScopeRevision.id, GithubAttemptScopeRevision.work_item_id).where(
                or_(GithubAttemptScopeRevision.work_item_id.in_(item_ids),
                    GithubAttemptScopeRevision.owner_slot_id.in_(slot_ids),
                    GithubAttemptScopeRevision.expected_workspace_id.in_(workspace_ids)),
                GithubAttemptScopeRevision.status.not_in(
                    ("completed", "exhausted", "rejected", "superseded", "expired")
                ),
            ).order_by(GithubAttemptScopeRevision.id).limit(25)
        )).all()
        blockers.extend({"kind": "revision", "id": row.id, "scope_id": None,
                         "href": f"/api/v1/agent-teams/github-work-items/{row.work_item_id}/scope-revisions"}
                        for row in revisions)
        try:
            recovery = configured_recovery_only_attempt()
        except ValueError:
            raise TeamDeletionConflictError([], "team_deletion_protection_unavailable") from None
        if recovery is not None:
            affected = (await db.execute(
                select(TeamGithubScope.id).where(
                    TeamGithubScope.id.in_(scope_ids), TeamGithubScope.id == recovery.scope_id
                )
            )).scalar_one_or_none()
            if affected is not None:
                # Do not disclose the protected recovery target or identity.
                blockers.append({"kind": "recovery", "id": preset_id, "scope_id": None,
                                 "href": "/api/v1/agent-teams/github-recovery-gate/active"})
        if blockers:
            raise TeamDeletionConflictError(blockers)

    async def _delete_quiescent_preset(self, db: AsyncSession, preset: AgentTeamPreset) -> None:
        preset_id = preset.id
        slots = await self._slots_for_preset(db, preset_id)
        slot_ids = [slot.id for slot in slots]
        session_condition = MailAgentSession.team_preset_id == preset_id
        if slot_ids:
            session_condition = or_(
                MailAgentSession.team_preset_id == preset_id,
                MailAgentSession.team_slot_id.in_(slot_ids),
            )
        await self._move_sessions_to_repo_members(db, session_condition)
        launch_ids = (
            await db.execute(select(AgentTeamLaunch.id).where(AgentTeamLaunch.preset_id == preset_id))
        ).scalars().all()
        if launch_ids:
            await db.execute(
                delete(AgentTeamLaunchItem).where(AgentTeamLaunchItem.launch_id.in_(launch_ids))
            )
        await db.execute(delete(AgentTeamLaunch).where(AgentTeamLaunch.preset_id == preset_id))
        await db.execute(delete(AgentTeamSlot).where(AgentTeamSlot.preset_id == preset_id))
        await db.delete(preset)
        await db.commit()

    async def duplicate_preset(
        self,
        db: AsyncSession,
        preset_id: int,
        *,
        name: str | None = None,
    ) -> AgentTeamPresetResponse:
        source = await self._require_preset(db, preset_id)
        slots = await self._slots_for_preset(db, preset_id)
        clone = AgentTeamPreset(
            name=self._clean_required(name or f"{source.name} copy", "Team name"),
            description=source.description,
            created_by=source.created_by,
        )
        await self._ensure_preset_name_is_unique(db, clone.name)
        db.add(clone)
        await db.flush()
        for slot in slots:
            db.add(
                AgentTeamSlot(
                    preset_id=clone.id,
                    position=slot.position,
                    display_name=slot.display_name,
                    provider=slot.provider,
                    repo_id=slot.repo_id,
                    repo_path=slot.repo_path,
                    repo_name=slot.repo_name,
                    role=slot.role,
                    charter=slot.charter,
                    ui_color=slot.ui_color,
                    bootstrap_prompt=slot.bootstrap_prompt,
                    controlled_language_enabled=slot.controlled_language_enabled,
                    launch_mode=slot.launch_mode,
                    launch_options=slot.launch_options or {},
                    area_labels=slot.area_labels,
                    expertise=slot.expertise,
                    enabled=slot.enabled,
                )
            )
        if source.leader_slot_id is not None:
            mapped_leader_index = next(
                (index for index, slot in enumerate(slots) if slot.id == source.leader_slot_id),
                None,
            )
            if mapped_leader_index is not None:
                await db.flush()
                cloned_slots = await self._slots_for_preset(db, clone.id)
                clone.leader_slot_id = cloned_slots[mapped_leader_index].id
        await db.commit()
        await db.refresh(clone)
        return await self._preset_response(db, clone)

    async def create_from_agent_mail(
        self,
        db: AsyncSession,
        request: AgentTeamCreateFromMailRequest,
    ) -> AgentTeamPresetResponse:
        await agent_mail_service.sync_observed_sessions(db)
        member_statement = select(MailTeamMember)
        if request.member_ids is not None:
            if len(set(request.member_ids)) != len(request.member_ids):
                raise ValueError("member_ids must not contain duplicates")
            member_statement = member_statement.where(MailTeamMember.id.in_(request.member_ids))
        members = (await db.execute(member_statement)).scalars().all()
        if request.member_ids is not None:
            by_id = {member.id: member for member in members}
            missing = [member_id for member_id in request.member_ids if member_id not in by_id]
            if missing:
                raise ValueError(f"Unknown Agent Mail member ids: {', '.join(map(str, missing))}")
            members = [by_id[member_id] for member_id in request.member_ids]
        sessions = (await db.execute(select(MailAgentSession))).scalars().all()
        latest_by_member: dict[int, MailAgentSession] = {}
        now = datetime.utcnow()
        for session in sessions:
            if agent_mail_service._effective_status(session, now) not in {"connected", "observed"}:
                continue
            current = latest_by_member.get(session.member_id)
            if current is None or session.last_seen_at > current.last_seen_at:
                latest_by_member[session.member_id] = session

        slot_requests: list[AgentTeamSlotCreate] = []
        fallback_provider = await self._fallback_provider()
        for member in members:
            session = latest_by_member.get(member.id)
            if not request.include_offline and session is None:
                continue
            provider = session.provider if session and session.provider in _PROVIDER_IDS else fallback_provider
            slot_requests.append(
                AgentTeamSlotCreate(
                    display_name=member.display_name,
                    provider=provider,
                    repo_path=member.repo_path,
                    role=member.role,
                    charter=member.charter,
                )
            )

        return await self.create_preset(
            db,
            AgentTeamPresetCreate(
                name=request.name,
                description=request.description,
                created_by="agent-mail",
                slots=slot_requests,
            ),
        )

    async def create_from_agent_bridge(
        self,
        db: AsyncSession,
        request: AgentTeamCreateFromBridgeRequest,
    ) -> AgentTeamPresetResponse:
        sessions = sorted(
            self._discover_sessions(),
            key=lambda session: (
                str(session.get("cwd") or ""),
                str(session.get("provider") or ""),
                str(session.get("tmux_target") or ""),
            ),
        )
        slot_requests: list[AgentTeamSlotCreate] = []

        for session in sessions:
            provider = self._clean_optional(session.get("provider"))
            cwd = self._clean_optional(session.get("cwd"))
            if provider not in _PROVIDER_IDS or cwd is None:
                continue
            try:
                repo_path, identity = self._normalize_repo(cwd)
            except ValueError:
                continue

            slot_requests.append(
                AgentTeamSlotCreate(
                    display_name=self._clean_optional(session.get("session_name")) or identity["repo_name"],
                    provider=provider,
                    repo_path=repo_path,
                )
            )

        if not slot_requests:
            raise ValueError("No Agent Bridge sessions were found")

        return await self.create_preset(
            db,
            AgentTeamPresetCreate(
                name=request.name,
                description=request.description,
                created_by="agent-bridge",
                slots=slot_requests,
            ),
        )

    async def add_slot(
        self,
        db: AsyncSession,
        preset_id: int,
        request: AgentTeamSlotCreate,
    ) -> AgentTeamPresetResponse:
        preset = await self._require_preset(db, preset_id)
        slot_data = self._normalize_slot_create(
            request,
            await self._next_slot_position(db, preset_id) if request.position is None else request.position,
        )
        db.add(AgentTeamSlot(preset_id=preset.id, **slot_data))
        preset.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def update_slot(
        self,
        db: AsyncSession,
        slot_id: int,
        request: AgentTeamSlotUpdate,
    ) -> AgentTeamPresetResponse:
        slot, preset = await self._lock_slot_and_preset(db, slot_id)
        updates: dict[str, Any] = {}

        if request.display_name is not None:
            updates["display_name"] = self._clean_required(request.display_name, "Slot name")
        if request.provider is not None:
            updates["provider"] = self._validate_provider(request.provider)
        if request.repo_path is not None:
            repo_path, ident = self._normalize_repo(request.repo_path)
            updates.update(
                repo_path=repo_path,
                repo_id=ident["repo_id"],
                repo_name=ident["repo_name"],
            )
        if request.role is not None:
            updates["role"] = self._clean_optional(request.role)
        if request.charter is not None:
            updates["charter"] = self._clean_optional(request.charter)
        if "ui_color" in request.model_fields_set:
            updates["ui_color"] = self._clean_ui_color(request.ui_color)
        if request.bootstrap_prompt is not None:
            updates["bootstrap_prompt"] = self._clean_optional(request.bootstrap_prompt)
        if request.controlled_language_enabled is not None:
            updates["controlled_language_enabled"] = request.controlled_language_enabled
        if "area_labels" in request.model_fields_set:
            updates["area_labels"] = self._clean_area_labels(request.area_labels)
        if request.expertise is not None:
            updates["expertise"] = self._clean_optional(request.expertise)
        if request.launch_mode is not None:
            updates["launch_mode"] = request.launch_mode.strip() or "plain"
        if request.launch_options is not None:
            provider_for_options = updates.get("provider", slot.provider)
            updates["launch_options"] = self._clean_launch_options(
                request.launch_options,
                provider=provider_for_options,
            )
        if request.enabled is not None:
            if request.enabled is False and preset.leader_slot_id == slot.id:
                raise ValueError("leader_slot_replacement_required")
            updates["enabled"] = request.enabled
        if request.position is not None:
            updates["position"] = request.position

        candidate_provider = updates.get("provider", slot.provider)
        candidate_mode = updates.get("launch_mode", slot.launch_mode)
        candidate_options = updates.get("launch_options", slot.launch_options or {})
        self._validate_slot_options(candidate_provider, candidate_mode, candidate_options)

        identity_changed = (
            ("repo_id" in updates and updates["repo_id"] != slot.repo_id)
            or ("provider" in updates and updates["provider"] != slot.provider)
        )
        if identity_changed:
            await self._move_sessions_to_repo_members(db, MailAgentSession.team_slot_id == slot.id)

        for key, value in updates.items():
            setattr(slot, key, value)
        slot.updated_at = datetime.utcnow()
        preset.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def delete_slot(self, db: AsyncSession, slot_id: int) -> AgentTeamPresetResponse:
        slot, preset = await self._lock_slot_and_preset(db, slot_id)
        if preset.leader_slot_id == slot.id:
            raise ValueError("leader_slot_replacement_required")
        await self._move_sessions_to_repo_members(db, MailAgentSession.team_slot_id == slot.id)
        await db.delete(slot)
        preset.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def reorder_slots(
        self,
        db: AsyncSession,
        preset_id: int,
        slot_ids: list[int],
    ) -> AgentTeamPresetResponse:
        preset = await self._require_preset(db, preset_id)
        slots = await self._slots_for_preset(db, preset_id)
        by_id = {slot.id: slot for slot in slots}
        if len(slot_ids) != len(by_id) or len(set(slot_ids)) != len(slot_ids) or set(slot_ids) != set(by_id):
            raise ValueError("slot_ids must include exactly this preset's slots")
        for index, slot_id in enumerate(slot_ids):
            by_id[slot_id].position = index
            by_id[slot_id].updated_at = datetime.utcnow()
        preset.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def plan_launch(
        self,
        db: AsyncSession,
        preset_id: int,
        request: AgentTeamLaunchRequest | None = None,
        *,
        synchronize: bool = True,
    ) -> AgentTeamLaunchPlan:
        request = request or AgentTeamLaunchRequest()
        preset = await self._require_preset(db, preset_id)
        preset_slots = await self._slots_for_preset(db, preset_id)
        slots = self._select_slots(
            preset_slots,
            request.slot_ids,
            include_disabled=request.include_disabled,
        )
        if synchronize:
            await agent_mail_service.sync_observed_sessions(db)
        discovered = self._discover_sessions()
        install_status = await agent_mail_install_service.get_install_status()
        reuse_group_counts = self._reuse_group_counts(preset_slots)
        attached_sessions = (
            await db.execute(
                select(MailAgentSession).where(MailAgentSession.team_slot_id.is_not(None))
            )
        ).scalars().all()
        pane_bindings = (await db.execute(select(AgentPaneBinding))).scalars().all()
        unsafe_resume_last_slot_ids = self._unsafe_resume_last_slot_ids(slots)

        items: list[AgentTeamLaunchPlanItem] = []
        used_matching_sessions: set[str] = set()
        for slot in slots:
            matching = (
                await self._matching_session(
                    db,
                    slot,
                    discovered,
                    used_matching_sessions,
                    requires_disambiguation=reuse_group_counts.get((slot.provider, slot.repo_id), 0) > 1,
                    attached_sessions=attached_sessions,
                    pane_bindings=pane_bindings,
                )
                if request.reuse_existing and slot.enabled
                else None
            )
            item = self._plan_slot(
                slot,
                matching,
                install_status,
                adopt_unbound_sessions=request.adopt_unbound_sessions,
                force_spawn_with_existing_pane=(
                    not request.reuse_existing
                    and any(self._discovered_session_matches_slot(session, slot) for session in discovered)
                ),
                unsafe_spawn_reason=(
                    self._resume_last_block_reason(slot.provider)
                    if matching is None and slot.id in unsafe_resume_last_slot_ids
                    else None
                ),
            )
            items.append(item)

        plan_hash = self._plan_hash(preset, slots, items)
        return AgentTeamLaunchPlan(
            preset_id=preset.id,
            preset_name=preset.name,
            plan_hash=plan_hash,
            generated_at=datetime.utcnow(),
            can_launch=not any(item.action == "blocked" for item in items),
            items=items,
            reuse_count=sum(1 for item in items if item.action == "reuse"),
            adopt_count=sum(1 for item in items if item.action == "adopt"),
            spawn_count=sum(1 for item in items if item.action == "spawn"),
            skipped_count=sum(1 for item in items if item.action == "skip"),
            blocked_count=sum(1 for item in items if item.action == "blocked"),
        )

    async def launch(
        self,
        db: AsyncSession,
        preset_id: int,
        request: AgentTeamLaunchRequest,
    ) -> AgentTeamLaunchResult:
        preset = await self._require_preset(db, preset_id)
        slots = await self._selected_slots(
            db,
            preset_id,
            request.slot_ids,
            include_disabled=request.include_disabled,
        )
        slot_by_id = {slot.id: slot for slot in slots}
        plan = await self.plan_launch(db, preset_id, request)

        if not request.skip_plan_confirmation:
            if not request.confirm_plan_hash:
                raise PlanConflictError(
                    "confirm_plan_hash is required unless skip_plan_confirmation is true",
                    proven_non_write=True)
            if request.confirm_plan_hash != plan.plan_hash:
                raise PlanConflictError(
                    "Launch plan changed; review the latest plan before launching", plan,
                    proven_non_write=True)
        if not plan.can_launch:
            raise ValueError("Launch plan is blocked; resolve blocked slots before launching")

        launch = AgentTeamLaunch(
            preset_id=preset.id,
            requested_by=self._clean_optional(request.requested_by),
            plan_hash=plan.plan_hash,
            status="running",
            summary={
                "reuse_count": plan.reuse_count,
                "adopt_count": plan.adopt_count,
                "spawn_count": plan.spawn_count,
                "skipped_count": plan.skipped_count,
                "blocked_count": plan.blocked_count,
            },
        )
        db.add(launch)
        await db.flush()

        results: list[AgentTeamLaunchResultItem] = []
        for item in plan.items:
            slot = slot_by_id[item.slot_id]
            prompt_override = (request.slot_prompt_overrides or {}).get(slot.id)
            result_item = await self._execute_plan_item(
                db,
                launch.id,
                preset,
                slot,
                item,
                request.repo_path_override,
                prompt_override,
            )
            results.append(result_item)

        failed = sum(1 for item in results if item.status == "failed")
        launch.status = "completed_with_errors" if failed else "completed"
        launch.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(launch)

        return AgentTeamLaunchResult(
            launch_id=launch.id,
            preset_id=preset.id,
            preset_name=preset.name,
            plan_hash=plan.plan_hash,
            status=launch.status,
            launched_at=launch.created_at,
            completed_at=launch.completed_at or datetime.utcnow(),
            items=results,
        )

    async def _execute_plan_item(
        self,
        db: AsyncSession,
        launch_id: int,
        preset: AgentTeamPreset,
        slot: AgentTeamSlot,
        plan_item: AgentTeamLaunchPlanItem,
        repo_path_override: str | None = None,
        prompt_override: str | None = None,
    ) -> AgentTeamLaunchResultItem:
        if plan_item.action in {"reuse", "adopt"}:
            matching = plan_item.matching_session or {}
            pane_pid = matching.get("pid")
            stat = read_proc_stat(int(pane_pid)) if pane_pid is not None else None
            if stat is None or stat[1] != matching.get("pane_proc_start"):
                raise PlanConflictError("The selected pane changed; review a new launch plan")
            binding = (
                await db.execute(
                    select(AgentPaneBinding).where(
                        AgentPaneBinding.pane_pid == int(pane_pid),
                        AgentPaneBinding.pane_proc_start == stat[1],
                    )
                )
            ).scalar_one_or_none()
            if (
                (plan_item.action == "reuse" and binding is None)
                or (
                    binding is not None
                    and (binding.slot_id != slot.id or binding.preset_id != preset.id)
                )
            ):
                raise PlanConflictError("The selected pane binding changed; review a new launch plan")
            agent_mail_member_id = await self._attach_team_context_to_existing_session(
                db,
                slot,
                plan_item.matching_session,
            )
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action=plan_item.action,
                status="reused",
                provider=slot.provider,
                repo_path=slot.repo_path,
                session_name=plan_item.matching_session.get("session_name") if plan_item.matching_session else None,
                tmux_target=plan_item.matching_session.get("tmux_target") if plan_item.matching_session else None,
                pane_pid=plan_item.matching_session.get("pid") if plan_item.matching_session else None,
                agent_mail_member_id=agent_mail_member_id,
                message=(
                    "An unbound pane was explicitly adopted by the operator"
                    if plan_item.action == "adopt"
                    else "A bound tmux session was reused"
                ),
                warnings=plan_item.warnings,
            )
            await self._write_pane_binding(
                db,
                pane_pid=result.pane_pid,
                slot=slot,
                preset=preset,
                tmux_target=result.tmux_target,
            )
            self._record_launch_item(db, launch_id, result)
            return result

        if plan_item.action == "skip":
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action="skip",
                status="skipped_disabled",
                provider=slot.provider,
                repo_path=slot.repo_path,
                message="Slot is disabled",
                error="; ".join(plan_item.reasons) or None,
                warnings=plan_item.warnings,
            )
            self._record_launch_item(db, launch_id, result)
            return result

        if plan_item.action == "blocked":
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action="blocked",
                status=self._blocked_result_status(plan_item.block_code),
                provider=slot.provider,
                repo_path=slot.repo_path,
                block_code=plan_item.block_code,
                error="; ".join(plan_item.reasons) or "Blocked by launch plan",
                warnings=plan_item.warnings,
            )
            self._record_launch_item(db, launch_id, result)
            return result

        try:
            if prompt_override:
                bootstrap_prompt = await self._bootstrap_prompt(
                    db, preset, slot, prompt_override=prompt_override
                )
            else:
                bootstrap_prompt = await self._bootstrap_prompt(db, preset, slot)
            options = self._spawn_options_for_slot(
                slot,
                bootstrap_prompt,
                repo_path_override,
            )
            spawned = spawn_session(
                slot.provider,
                options,
                extra_env={
                    "CLAUDE_DECK_TEAM_PRESET_ID": str(preset.id),
                    "CLAUDE_DECK_TEAM_PRESET_NAME": preset.name,
                    "CLAUDE_DECK_TEAM_SLOT_ID": str(slot.id),
                    "CLAUDE_DECK_TEAM_SLOT_NAME": slot.display_name,
                    **({"CLAUDE_DECK_TEAM_SLOT_ROLE": slot.role} if slot.role else {}),
                    **({"CLAUDE_DECK_TEAM_SLOT_COLOR": slot.ui_color} if slot.ui_color else {}),
                },
            )
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action="spawn",
                status="pending_registration",
                provider=slot.provider,
                repo_path=repo_path_override or slot.repo_path,
                session_name=spawned.get("session_name"),
                tmux_target=spawned.get("tmux_target"),
                pane_pid=spawned.get("pane_pid"),
                message="Session spawned; waiting for Agent Mail registration",
                warnings=plan_item.warnings,
            )
            await self._write_pane_binding(
                db,
                pane_pid=result.pane_pid,
                slot=slot,
                preset=preset,
                tmux_target=result.tmux_target,
            )
        except Exception as exc:
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action="spawn",
                status="failed",
                provider=slot.provider,
                repo_path=repo_path_override or slot.repo_path,
                error=str(exc),
                warnings=plan_item.warnings,
            )
        self._record_launch_item(db, launch_id, result)
        return result

    async def _write_pane_binding(
        self,
        db: AsyncSession,
        *,
        pane_pid: int | None,
        slot: AgentTeamSlot,
        preset: AgentTeamPreset,
        tmux_target: str | None,
    ) -> None:
        """Record which slot owns a pane so registration can derive it.

        The commit is deliberately mid-loop on the caller's session. It makes
        the row visible to a shim registering on another connection without
        deadlocking on the launch transaction's existing SQLite write lock.
        """
        if pane_pid is None:
            return
        stat = read_proc_stat(pane_pid)
        if stat is None:
            return
        _parent_pid, proc_start = stat

        existing = (
            await db.execute(
                select(AgentPaneBinding).where(
                    AgentPaneBinding.pane_pid == pane_pid,
                    AgentPaneBinding.pane_proc_start == proc_start,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            db.add(
                AgentPaneBinding(
                    pane_pid=pane_pid,
                    pane_proc_start=proc_start,
                    slot_id=slot.id,
                    preset_id=preset.id,
                    tmux_target=tmux_target,
                )
            )
        else:
            if existing.slot_id != slot.id or existing.preset_id != preset.id:
                raise PlanConflictError("The selected pane belongs to another slot")
            existing.slot_id = slot.id
            existing.preset_id = preset.id
            existing.tmux_target = tmux_target
        await db.commit()

    def _record_launch_item(
        self,
        db: AsyncSession,
        launch_id: int,
        result: AgentTeamLaunchResultItem,
    ) -> None:
        db.add(
            AgentTeamLaunchItem(
                launch_id=launch_id,
                slot_id=result.slot_id,
                action=result.action,
                status=result.status,
                provider=result.provider,
                repo_path=result.repo_path,
                session_name=result.session_name,
                tmux_target=result.tmux_target,
                message=result.message,
                block_code=result.block_code,
                error=result.error,
            )
        )

    def _plan_slot(
        self,
        slot: AgentTeamSlot,
        matching_session: dict[str, Any] | None,
        install_status: Any,
        *,
        adopt_unbound_sessions: bool = False,
        force_spawn_with_existing_pane: bool = False,
        unsafe_spawn_reason: str | None = None,
    ) -> AgentTeamLaunchPlanItem:
        warnings = self._slot_launch_warnings(slot.provider, slot.launch_options or {})
        if force_spawn_with_existing_pane:
            warnings.append(
                "Forced fresh spawn ignores an existing same-repository pane; verify it will not duplicate this slot"
            )
        if not slot.enabled:
            return AgentTeamLaunchPlanItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                provider=slot.provider,
                repo_id=slot.repo_id,
                repo_path=slot.repo_path,
                repo_name=slot.repo_name,
                action="skip",
                status="skipped",
                reasons=["Slot is disabled"],
                warnings=warnings,
            )

        reasons: list[str] = []
        block_code: str | None = None
        try:
            provider = get_provider(slot.provider)
            if not provider.get_status().get("installed"):
                reasons.append(f"{provider.display_name} is not available on this machine")
                block_code = "provider_unavailable"
        except ValueError:
            reasons.append(f"Unknown provider: {slot.provider}")
            block_code = "provider_unknown"

        mail_reason = self._agent_mail_ready_reason(slot.provider, install_status)
        if mail_reason:
            reasons.append(mail_reason)
            block_code = block_code or "agent_mail_not_configured"

        if block_code is None and matching_session:
            if matching_session.get("binding_status") == "ambiguous":
                return AgentTeamLaunchPlanItem(
                    slot_id=slot.id,
                    slot_name=slot.display_name,
                    provider=slot.provider,
                    repo_id=slot.repo_id,
                    repo_path=slot.repo_path,
                    repo_name=slot.repo_name,
                    action="blocked",
                    status="blocked",
                    reasons=["Multiple unbound panes match this slot; stop or isolate them before launching"],
                    block_code="unbound_pane_ambiguous",
                    warnings=warnings,
                )
            unbound = matching_session.get("binding_status") == "unbound"
            if unbound and (
                matching_session.get("pid") is None
                or matching_session.get("pane_proc_start") is None
                or matching_session.get("tmux_target") is None
            ):
                return AgentTeamLaunchPlanItem(
                    slot_id=slot.id,
                    slot_name=slot.display_name,
                    provider=slot.provider,
                    repo_id=slot.repo_id,
                    repo_path=slot.repo_path,
                    repo_name=slot.repo_name,
                    action="blocked",
                    status="blocked",
                    reasons=["An unbound pane was found, but its process identity cannot be verified"],
                    matching_session=matching_session,
                    block_code="unbound_pane_unverifiable",
                    warnings=warnings,
                )
            if unbound and not adopt_unbound_sessions:
                return AgentTeamLaunchPlanItem(
                    slot_id=slot.id,
                    slot_name=slot.display_name,
                    provider=slot.provider,
                    repo_id=slot.repo_id,
                    repo_path=slot.repo_path,
                    repo_name=slot.repo_name,
                    action="blocked",
                    status="blocked",
                    reasons=["An unbound pane is present; only an operator may explicitly adopt it or force a fresh spawn"],
                    matching_session=matching_session,
                    block_code="unbound_pane_requires_operator_adoption",
                    warnings=warnings,
                )
            return AgentTeamLaunchPlanItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                provider=slot.provider,
                repo_id=slot.repo_id,
                repo_path=slot.repo_path,
                repo_name=slot.repo_name,
                action="adopt" if unbound else "reuse",
                status="ready",
                reasons=[
                    "Operator explicitly selected an unbound pane for adoption"
                    if unbound else "A bound running session is already available"
                ],
                matching_session=matching_session,
                warnings=warnings,
            )

        if block_code is None and unsafe_spawn_reason:
            reasons.append(unsafe_spawn_reason)
            block_code = (
                "unsafe_copilot_continue"
                if slot.provider == "copilot-cli"
                else "unsafe_opencode_continue"
                if slot.provider == "opencode-cli"
                else "unsafe_codex_resume_last"
            )

        if block_code is None:
            validation_error = self._validate_spawn_options(slot)
            if validation_error:
                reasons.append(validation_error)
                block_code = "invalid_launch_options"

        if block_code:
            return AgentTeamLaunchPlanItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                provider=slot.provider,
                repo_id=slot.repo_id,
                repo_path=slot.repo_path,
                repo_name=slot.repo_name,
                action="blocked",
                status="blocked",
                reasons=reasons,
                matching_session=matching_session,
                block_code=block_code,
                warnings=warnings,
            )

        return AgentTeamLaunchPlanItem(
            slot_id=slot.id,
            slot_name=slot.display_name,
            provider=slot.provider,
            repo_id=slot.repo_id,
            repo_path=slot.repo_path,
            repo_name=slot.repo_name,
            action="spawn",
            status="ready",
            reasons=["No matching running session found"],
            warnings=warnings,
        )

    def _agent_mail_ready_reason(self, provider: str, install_status: Any) -> str | None:
        from app.services.provider_readiness_service import agent_mail_ready_reason

        return agent_mail_ready_reason(provider, install_status)

    def _unsafe_resume_last_slot_ids(self, slots: list[AgentTeamSlot]) -> set[int]:
        groups: dict[tuple[str, str], list[AgentTeamSlot]] = {}
        for slot in slots:
            if not slot.enabled or not self._is_resume_last_slot(slot):
                continue
            key = (slot.provider, slot.repo_id)
            groups.setdefault(key, []).append(slot)
        return {
            slot.id
            for grouped_slots in groups.values()
            if len(grouped_slots) > 1
            for slot in grouped_slots
        }

    def _is_resume_last_slot(self, slot: AgentTeamSlot) -> bool:
        if slot.provider not in {"codex-cli", "copilot-cli", "opencode-cli", "pi-cli"}:
            return False
        if (slot.launch_mode or "plain").strip() != "resume":
            return False
        return self._truthy_launch_option((slot.launch_options or {}).get("use_last"))

    def _truthy_launch_option(self, value: Any) -> bool:
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _resume_last_block_reason(self, provider: str) -> str:
        label = (
            "GitHub Copilot CLI --continue"
            if provider == "copilot-cli"
            else "OpenCode --continue"
            if provider == "opencode-cli"
            else "Codex resume --last"
        )
        return (
            f"{label} cannot be used for multiple same-repo team slots. "
            "Use fresh/plain sessions, or provide a distinct session_id per slot."
        )

    async def _fallback_provider(self) -> str:
        install_status = await agent_mail_install_service.get_install_status()
        if getattr(install_status, "codex_cli_available", False):
            return "codex-cli"
        try:
            if get_provider("claude-code").get_status().get("installed"):
                return "claude-code"
        except ValueError:
            pass
        raise ValueError("No default agent provider is available; choose a provider manually")

    def _blocked_result_status(self, block_code: str | None) -> str:
        if block_code == "provider_unavailable":
            return "blocked_provider_unavailable"
        if block_code == "agent_mail_not_configured":
            return "blocked_agent_mail_not_configured"
        return "failed"

    def _reuse_group_counts(self, slots: list[AgentTeamSlot]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for slot in slots:
            if not slot.enabled:
                continue
            key = (slot.provider, slot.repo_id)
            counts[key] = counts.get(key, 0) + 1
        return counts

    async def _matching_session(
        self,
        db: AsyncSession,
        slot: AgentTeamSlot,
        discovered: list[dict[str, Any]],
        used_matching_sessions: set[str],
        *,
        requires_disambiguation: bool,
        attached_sessions: list[MailAgentSession],
        pane_bindings: list[AgentPaneBinding],
    ) -> dict[str, Any] | None:
        eligible = [
            session
            for session in discovered
            if not self._session_owned_by_other_slot(
                session,
                slot,
                attached_sessions,
                pane_bindings,
            )
        ]
        attached = await self._matching_attached_session(
            db, slot, eligible, used_matching_sessions, pane_bindings
        )
        if attached is not None and attached.get("binding_status") == "ambiguous":
            return attached
        if slot.provider == "pi-cli":
            eligible_panes = await agent_mail_service.nudgeable_sessions_for_slot(db, slot.id)
            if attached is not None and any(
                self._discovered_session_matches_registered(attached, pane)
                for pane in eligible_panes
            ):
                return attached
            return None
        if attached is not None:
            return attached
        candidates = [
            session for session in eligible
            if self._matching_session_key(session) not in used_matching_sessions
            and self._discovered_session_matches_slot(session, slot)
        ]
        named = [
            session for session in candidates if self._session_name_matches_slot(session, slot)
        ]
        if len(named) > 1:
            return {"binding_status": "ambiguous"}
        if len(named) == 1:
            selected = named[0]
        elif requires_disambiguation:
            return {"binding_status": "ambiguous"} if candidates else None
        elif len(candidates) == 1:
            selected = candidates[0]
        else:
            return {"binding_status": "ambiguous"} if candidates else None
        used_matching_sessions.add(self._matching_session_key(selected))
        return {**self._matching_session_payload(selected), "binding_status": "unbound"}

    def _session_owned_by_other_slot(
        self,
        session: dict[str, Any],
        slot: AgentTeamSlot,
        attached_sessions: list[MailAgentSession],
        pane_bindings: list[AgentPaneBinding],
    ) -> bool:
        for attached in attached_sessions:
            if not self._discovered_session_matches_registered(session, attached):
                continue
            if attached.team_slot_id != slot.id or attached.team_preset_id != slot.preset_id:
                return True

        try:
            pane_pid = int(str(session.get("pid")))
        except (TypeError, ValueError):
            return False
        stat = read_proc_stat(pane_pid)
        if stat is None:
            return False
        _parent_pid, proc_start = stat
        for binding in pane_bindings:
            if binding.pane_pid != pane_pid or binding.pane_proc_start != proc_start:
                continue
            return binding.slot_id != slot.id or binding.preset_id != slot.preset_id
        return False

    async def _matching_attached_session(
        self,
        db: AsyncSession,
        slot: AgentTeamSlot,
        discovered: list[dict[str, Any]],
        used_matching_sessions: set[str],
        pane_bindings: list[AgentPaneBinding],
    ) -> dict[str, Any] | None:
        result = await db.execute(
            select(MailAgentSession)
            .where(
                MailAgentSession.team_slot_id == slot.id,
                MailAgentSession.provider == slot.provider,
            )
            .order_by(MailAgentSession.last_seen_at.desc())
        )
        attached_sessions = result.scalars().all()
        now = datetime.utcnow()
        matches: list[tuple[str, dict[str, Any]]] = []
        for attached in attached_sessions:
            if agent_mail_service._effective_status(attached, now) == "offline":
                continue
            member = await db.get(MailTeamMember, attached.member_id)
            if (
                member is None
                or member.participant_kind != "team_slot"
                or member.team_slot_id != slot.id
                or member.team_preset_id != slot.preset_id
            ):
                continue
            for session in discovered:
                match_key = self._matching_session_key(session)
                if match_key in used_matching_sessions:
                    continue
                if not self._discovered_session_matches_slot(session, slot):
                    continue
                if (
                    attached.team_preset_id == slot.preset_id
                    and attached.source == "mcp"
                    and attached.capability_token_hash is not None
                    and attached.mailbox_status == "connected"
                    and attached.closed_at is None
                    and attached.last_seen_at >= now - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS)
                    and self._discovered_session_matches_registered(session, attached)
                    and self._session_has_live_slot_binding(
                        session, attached, slot, pane_bindings
                    )
                ):
                    matches.append((match_key, session))
        if len(matches) > 1:
            return {"binding_status": "ambiguous"}
        if not matches:
            return None
        match_key, session = matches[0]
        used_matching_sessions.add(match_key)
        return {**self._matching_session_payload(session), "binding_status": "bound"}

    def _session_has_live_slot_binding(
        self,
        discovered: dict[str, Any],
        attached: MailAgentSession,
        slot: AgentTeamSlot,
        pane_bindings: list[AgentPaneBinding],
    ) -> bool:
        try:
            pane_pid = int(str(discovered.get("pid")))
        except (TypeError, ValueError):
            return False
        stat = read_proc_stat(pane_pid)
        if stat is None or attached.bound_pane_pid != pane_pid:
            return False
        proc_start = stat[1]
        if attached.bound_pane_proc_start != proc_start:
            return False
        return any(
            binding.pane_pid == pane_pid
            and binding.pane_proc_start == proc_start
            and binding.slot_id == slot.id
            and binding.preset_id == slot.preset_id
            for binding in pane_bindings
        )

    def _session_name_matches_slot(self, session: dict[str, Any], slot: AgentTeamSlot) -> bool:
        slot_terms = [slot.display_name, slot.role]
        session_terms = [session.get("session_name"), session.get("tmux_target")]
        slot_tokens = {
            token for term in slot_terms if term for token in self._match_tokens(term)
        }
        session_tokens = {
            token for term in session_terms if term for token in self._match_tokens(term)
        }
        return bool(slot_tokens & session_tokens)

    def _match_tokens(self, value: Any) -> list[str]:
        return [token for token in re.split(r"[^a-z0-9]+", str(value).lower()) if len(token) >= 3]

    def _discovered_session_matches_slot(
        self,
        session: dict[str, Any],
        slot: AgentTeamSlot,
    ) -> bool:
        if session.get("provider") != slot.provider:
            return False
        cwd = session.get("cwd")
        return bool(cwd and derive_repo_identity(cwd)["repo_id"] == slot.repo_id)

    def _discovered_session_matches_registered(
        self,
        session: dict[str, Any],
        registered: MailAgentSession,
    ) -> bool:
        payload = self._matching_session_payload(session)
        if registered.session_key and payload.get("session_key") == registered.session_key:
            return True
        if registered.tmux_target and payload.get("tmux_target") == registered.tmux_target:
            return True
        if registered.pane_id and payload.get("pane_id") == registered.pane_id:
            return True
        if registered.pid and payload.get("pid"):
            try:
                return registered.pid == int(str(payload["pid"]))
            except (TypeError, ValueError):
                return False
        return False

    def _matching_session_payload(self, session: dict[str, Any]) -> dict[str, Any]:
        pane_id = session.get("pane_id")
        session_key = session.get("session_key") or (f"tmux:{pane_id}" if pane_id else None)
        try:
            pane_pid = int(str(session.get("pid")))
        except (TypeError, ValueError):
            pane_pid = None
        stat = read_proc_stat(pane_pid) if pane_pid is not None else None
        return {
            "source": "bridge",
            "provider": session.get("provider"),
            "session_key": session_key,
            "session_name": session.get("session_name"),
            "tmux_target": session.get("tmux_target"),
            "pane_id": pane_id,
            "cwd": session.get("cwd"),
            "pid": pane_pid,
            "pane_proc_start": stat[1] if stat is not None else None,
        }

    def _matching_session_key(self, session: dict[str, Any]) -> str:
        for key in ("session_key", "tmux_target", "pane_id", "pid", "session_name"):
            value = session.get(key)
            if value:
                return f"{key}:{value}"
        return f"{session.get('provider')}:{session.get('cwd')}"

    async def _attach_team_context_to_existing_session(
        self,
        db: AsyncSession,
        slot: AgentTeamSlot,
        matching_session: dict[str, Any] | None,
    ) -> int | None:
        if not matching_session:
            return None
        statement = (
            select(MailAgentSession, MailTeamMember)
            .join(MailTeamMember, MailTeamMember.id == MailAgentSession.member_id)
            .where(MailTeamMember.repo_id == slot.repo_id, MailAgentSession.provider == slot.provider)
        )
        if matching_session.get("session_key"):
            statement = statement.where(MailAgentSession.session_key == matching_session["session_key"])
        elif matching_session.get("tmux_target"):
            statement = statement.where(MailAgentSession.tmux_target == matching_session["tmux_target"])
        elif matching_session.get("pane_id"):
            statement = statement.where(MailAgentSession.pane_id == matching_session["pane_id"])
        else:
            return None
        result = await db.execute(
            statement.order_by(MailAgentSession.last_seen_at.desc()).limit(1)
        )
        now = datetime.utcnow()
        for session, member in result.all():
            if agent_mail_service._effective_status(session, now) == "offline":
                continue
            slot_member = await agent_mail_service.get_or_create_slot_member(db, slot)
            if member.id != slot_member.id:
                old_member_id = member.id
                session.member_id = slot_member.id
                await db.flush()
                await agent_mail_service._remove_empty_observed_member(db, old_member_id)
            session.team_preset_id = slot.preset_id
            session.team_slot_id = slot.id
            return slot_member.id
        return None

    async def _move_sessions_to_repo_members(self, db: AsyncSession, condition: Any) -> None:
        sessions = (await db.execute(select(MailAgentSession).where(condition))).scalars().all()
        for session in sessions:
            if session.cwd:
                try:
                    repo_member = await agent_mail_service.get_or_create_repo_member(db, session.cwd)
                    session.member_id = repo_member.id
                except Exception:
                    pass
            session.team_preset_id = None
            session.team_slot_id = None

    def _validate_spawn_options(self, slot: AgentTeamSlot) -> str | None:
        try:
            get_provider(slot.provider).build_spawn_command(self._spawn_options_for_slot(slot, prompt=None))
            return None
        except Exception as exc:
            return str(exc)

    def _spawn_options_for_slot(
        self, slot: AgentTeamSlot, prompt: str | None, repo_path_override: str | None = None
    ) -> SpawnCommandOptions:
        raw_options = dict(slot.launch_options or {})
        raw_prompt = self._clean_optional(raw_options.pop("prompt", None))
        if prompt and raw_prompt:
            prompt = f"{prompt}\n\nInitial task:\n{raw_prompt}"
        elif raw_prompt:
            prompt = raw_prompt

        values: dict[str, Any] = {
            "directory": repo_path_override or slot.repo_path,
            "mode": slot.launch_mode or "plain",
            "prompt": prompt,
        }
        for key, value in raw_options.items():
            if key in _OPTION_FIELDS and key not in {"directory", "mode", "prompt"}:
                values[key] = value
        if slot.provider == "pi-cli":
            values["platform"] = self._clean_optional(raw_options.get("platform")) or "openrouter"
        return SpawnCommandOptions(**values)

    async def _bootstrap_prompt(
        self,
        db: AsyncSession,
        preset: AgentTeamPreset,
        slot: AgentTeamSlot,
        *,
        prompt_override: str | None = None,
    ) -> str:
        is_leader = await self._slot_is_leader(db, preset, slot)
        if prompt_override:
            base = prompt_override
        elif slot.bootstrap_prompt:
            base = slot.bootstrap_prompt
        else:
            parts = [
                f'You are being started by Claude Deck as part of Agent Team "{preset.name}".',
                f'Your team slot is "{slot.display_name}" for repo "{slot.repo_name}".',
                "Call `deck_whoami` when the session starts, then check your inbox with `deck_check_inbox(unread_only=False)`.",
            ]
            if slot.role:
                parts.append(f"Role: {slot.role}")
            if slot.charter:
                parts.append(f"Charter: {slot.charter}")
            base = "\n".join(parts)
        if is_leader:
            from app.services.github_dispatch_service import github_dispatch_service

            base = f"{base}\n\n{github_dispatch_service._leader_unblock_instructions()}"
        guidance = team_communication_guidance(slot.controlled_language_enabled is not False)
        return f"{base}\n\n{guidance}"

    async def _slot_is_leader(
        self,
        db: AsyncSession,
        preset: AgentTeamPreset,
        slot: AgentTeamSlot,
    ) -> bool:
        return preset.leader_slot_id == slot.id and slot.enabled

    def _discover_sessions(self) -> list[dict[str, Any]]:
        try:
            return discover_agent_sessions()
        except Exception:
            return []

    def _plan_hash(
        self,
        preset: AgentTeamPreset,
        slots: list[AgentTeamSlot],
        items: list[AgentTeamLaunchPlanItem],
    ) -> str:
        slot_lookup = {slot.id: slot for slot in slots}
        payload = {
            "preset_id": preset.id,
            "preset_updated_at": preset.updated_at.isoformat(),
            "items": [
                {
                    "slot_id": item.slot_id,
                    "slot_updated_at": slot_lookup[item.slot_id].updated_at.isoformat(),
                    "action": item.action,
                    "status": item.status,
                    "reasons": item.reasons,
                    "warnings": item.warnings,
                    "matching_session": {
                        key: value
                        for key, value in (item.matching_session or {}).items()
                        if key in {"source", "provider", "session_key", "session_name", "tmux_target", "cwd", "pid", "pane_proc_start", "binding_status"}
                    },
                }
                for item in items
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _preset_response(
        self,
        db: AsyncSession,
        preset: AgentTeamPreset,
    ) -> AgentTeamPresetResponse:
        slots = await self._slots_for_preset(db, preset.id)
        return AgentTeamPresetResponse(
            id=preset.id,
            name=preset.name,
            description=preset.description,
            created_by=preset.created_by,
            created_at=preset.created_at,
            updated_at=preset.updated_at,
            autonomy_enabled=preset.autonomy_enabled,
            leader_slot_id=preset.leader_slot_id,
            slots=[self._slot_response(slot) for slot in slots],
        )

    def _slot_response(self, slot: AgentTeamSlot) -> AgentTeamSlotResponse:
        return AgentTeamSlotResponse(
            id=slot.id,
            preset_id=slot.preset_id,
            position=slot.position,
            display_name=slot.display_name,
            provider=slot.provider,
            repo_id=slot.repo_id,
            repo_path=slot.repo_path,
            repo_name=slot.repo_name,
            role=slot.role,
            charter=slot.charter,
            ui_color=slot.ui_color,
            bootstrap_prompt=slot.bootstrap_prompt,
            controlled_language_enabled=slot.controlled_language_enabled is not False,
            launch_mode=slot.launch_mode,
            launch_options=slot.launch_options or {},
            area_labels=slot.area_labels,
            expertise=slot.expertise,
            warnings=self._slot_launch_warnings(slot.provider, slot.launch_options or {}),
            enabled=slot.enabled,
            created_at=slot.created_at,
            updated_at=slot.updated_at,
        )

    async def _require_preset(self, db: AsyncSession, preset_id: int) -> AgentTeamPreset:
        preset = await db.get(AgentTeamPreset, preset_id)
        if preset is None:
            raise ValueError("Agent team preset not found")
        return preset

    async def _require_slot(self, db: AsyncSession, slot_id: int) -> AgentTeamSlot:
        slot = await db.get(AgentTeamSlot, slot_id)
        if slot is None:
            raise ValueError("Agent team slot not found")
        return slot

    async def _lock_preset_for_slot_mutation(
        self, db: AsyncSession, preset_id: int
    ) -> AgentTeamPreset:
        """Serialize slot changes with authority assignment before reading state."""
        if db.get_bind().dialect.name != "sqlite":
            raise ValueError("leader_assignment_protection_unavailable")
        if not db.in_transaction():
            await db.execute(text("BEGIN IMMEDIATE"))
        result = await db.execute(
            update(AgentTeamPreset).where(AgentTeamPreset.id == preset_id)
            .values(id=AgentTeamPreset.id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await db.rollback()
            raise ValueError("team_not_found")
        return (await db.execute(
            select(AgentTeamPreset).where(AgentTeamPreset.id == preset_id)
            .execution_options(populate_existing=True)
        )).scalar_one()

    async def _lock_slot_and_preset(
        self, db: AsyncSession, slot_id: int
    ) -> tuple[AgentTeamSlot, AgentTeamPreset]:
        if db.get_bind().dialect.name != "sqlite":
            raise ValueError("leader_assignment_protection_unavailable")
        # Acquire the SQLite writer before reading slot or authority state.
        # This prevents a deferred-read snapshot from bypassing Leader guards.
        if not db.in_transaction():
            await db.execute(text("BEGIN IMMEDIATE"))
        preset_id = (await db.execute(
            select(AgentTeamSlot.preset_id).where(AgentTeamSlot.id == slot_id)
        )).scalar_one_or_none()
        if preset_id is None:
            raise ValueError("Agent team slot not found")
        preset = await self._lock_preset_for_slot_mutation(db, preset_id)
        slot = (await db.execute(
            select(AgentTeamSlot).where(
                AgentTeamSlot.id == slot_id,
                AgentTeamSlot.preset_id == preset.id,
            ).execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if slot is None:
            await db.rollback()
            raise ValueError("Agent team slot not found")
        return slot, preset

    async def bounded_slots_for_preset(
        self, db: AsyncSession, preset_id: int, limit: int
    ) -> tuple[list[AgentTeamSlot], bool]:
        """Bounded roster projection. The query itself carries the bound.

        Returns the observed slots within the bound and whether the bound was
        hit. Work is bounded regardless of concurrent roster growth.
        """
        rows = list((await db.scalars(
            select(AgentTeamSlot)
            .where(AgentTeamSlot.preset_id == preset_id)
            .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
            .limit(limit + 1)
        )).all())
        return rows[:limit], len(rows) > limit

    async def _slots_for_preset(self, db: AsyncSession, preset_id: int) -> list[AgentTeamSlot]:
        return (
            await db.execute(
                select(AgentTeamSlot)
                .where(AgentTeamSlot.preset_id == preset_id)
                .order_by(AgentTeamSlot.position.asc(), AgentTeamSlot.id.asc())
            )
        ).scalars().all()

    async def _selected_slots(
        self,
        db: AsyncSession,
        preset_id: int,
        slot_ids: list[int] | None,
        *,
        include_disabled: bool = False,
    ) -> list[AgentTeamSlot]:
        slots = await self._slots_for_preset(db, preset_id)
        return self._select_slots(slots, slot_ids, include_disabled=include_disabled)

    def _select_slots(
        self,
        slots: list[AgentTeamSlot],
        slot_ids: list[int] | None,
        *,
        include_disabled: bool = False,
    ) -> list[AgentTeamSlot]:
        if slot_ids is None:
            return slots if include_disabled else [slot for slot in slots if slot.enabled]
        requested = set(slot_ids)
        selected = [slot for slot in slots if slot.id in requested]
        if len(selected) != len(requested):
            raise ValueError("slot_ids must belong to this preset")
        return selected

    async def _next_slot_position(self, db: AsyncSession, preset_id: int) -> int:
        slots = await self._slots_for_preset(db, preset_id)
        return (max((slot.position for slot in slots), default=-1) + 1)

    async def _ensure_preset_name_is_unique(
        self,
        db: AsyncSession,
        name: str,
        *,
        exclude_preset_id: int | None = None,
    ) -> None:
        statement = select(AgentTeamPreset).where(AgentTeamPreset.name == name)
        if exclude_preset_id is not None:
            statement = statement.where(AgentTeamPreset.id != exclude_preset_id)
        existing = (await db.execute(statement)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("An Agent Team preset with this name already exists")

    def _normalize_slot_create(
        self,
        slot: AgentTeamSlotCreate,
        fallback_position: int,
    ) -> dict[str, Any]:
        repo_path, ident = self._normalize_repo(slot.repo_path)
        provider = self._validate_provider(slot.provider)
        launch_mode = slot.launch_mode.strip() or "plain"
        launch_options = self._clean_launch_options(slot.launch_options, provider=provider)
        self._validate_slot_options(provider, launch_mode, launch_options)
        return {
            "position": fallback_position if slot.position is None else slot.position,
            "display_name": self._clean_required(slot.display_name, "Slot name"),
            "provider": provider,
            "repo_id": ident["repo_id"],
            "repo_path": repo_path,
            "repo_name": ident["repo_name"],
            "role": self._clean_optional(slot.role),
            "charter": self._clean_optional(slot.charter),
            "ui_color": self._clean_ui_color(slot.ui_color),
            "bootstrap_prompt": self._clean_optional(slot.bootstrap_prompt),
            "controlled_language_enabled": slot.controlled_language_enabled,
            "launch_mode": launch_mode,
            "launch_options": launch_options,
            "area_labels": self._clean_area_labels(slot.area_labels),
            "expertise": self._clean_optional(slot.expertise),
            "enabled": slot.enabled,
        }

    def _normalize_repo(self, repo_path: str) -> tuple[str, dict[str, str]]:
        repo_path = repo_path.strip()
        if not repo_path:
            raise ValueError("Repo path is required")
        if "\x00" in repo_path:
            raise ValueError("Repo path contains an invalid character")

        expanded = os.path.expanduser(repo_path)
        if not os.path.isabs(expanded):
            raise ValueError("Repo path must be absolute")

        home_root = os.path.realpath(os.path.expanduser("~"))
        normalized = os.path.normpath(expanded)
        if not (normalized == home_root or normalized.startswith(home_root + os.path.sep)):
            raise ValueError(f"Repo path must be under the current user's home directory: {home_root}")

        relative_path = os.path.relpath(normalized, home_root)
        resolved = os.path.realpath(os.path.join(home_root, relative_path))
        if not (resolved == home_root or resolved.startswith(home_root + os.path.sep)):
            raise ValueError(f"Repo path must be under the current user's home directory: {home_root}")

        return resolved, derive_repo_identity(resolved)

    def _validate_provider(self, provider: str) -> str:
        provider = provider.strip()
        if provider not in _PROVIDER_IDS:
            raise ValueError(f"Unknown provider: {provider}")
        return provider

    def _clean_launch_options(
        self,
        value: dict[str, Any] | None,
        *,
        provider: str | None = None,
    ) -> dict[str, Any]:
        if not value:
            return {}
        if provider is not None:
            allowed = set(option_keys_for(provider))
            if not supports_bedrock(provider):
                allowed |= _BEDROCK_LAUNCH_OPTION_KEYS
            unknown = sorted(key for key in value if key not in allowed)
            if unknown:
                raise ValueError(f"Unsupported launch_options for {provider}: {', '.join(unknown)}")
        return {key: option for key, option in value.items() if key in _OPTION_FIELDS}

    def _validate_slot_options(
        self,
        provider: str,
        launch_mode: str,
        launch_options: dict[str, Any] | None,
    ) -> None:
        options = launch_options or {}
        unsupported_bedrock_keys = sorted(
            key for key in _BEDROCK_LAUNCH_OPTION_KEYS if key in options
            and not (provider == "pi-cli" and key == "platform")
        )
        if unsupported_bedrock_keys and not supports_bedrock(provider):
            raise ValueError(
                f"{provider} does not support Bedrock launch options: "
                f"{', '.join(unsupported_bedrock_keys)}"
            )

        allowed_keys = set(option_keys_for(provider))
        if not supports_bedrock(provider):
            allowed_keys |= _BEDROCK_LAUNCH_OPTION_KEYS
        unknown = sorted(key for key in options if key not in allowed_keys)
        if unknown:
            raise ValueError(f"Unsupported launch_options for {provider}: {', '.join(unknown)}")

        if launch_mode not in launch_modes_for(provider):
            allowed_modes = ", ".join(launch_modes_for(provider))
            raise ValueError(
                f"Unsupported launch_mode for {provider}: {launch_mode}. "
                f"Expected one of: {allowed_modes}"
            )

        platform = self._clean_optional(options.get("platform"))
        if provider == "pi-cli":
            if "platform" in options and options["platform"] is None:
                raise ProviderLaunchError("launch_options.platform must not be null", "pi_platform_null")
            if platform and platform != "openrouter":
                raise ProviderLaunchError("Pi requires platform=openrouter", "pi_platform_unsupported")
        if platform == PLATFORM_BEDROCK and not supports_bedrock(provider):
            raise ValueError(f"{provider} does not support platform=bedrock")

        reasoning_effort = self._clean_optional(options.get("reasoning_effort"))
        if reasoning_effort:
            allowed_efforts = reasoning_efforts_for(provider)
            if not allowed_efforts:
                raise ProviderLaunchError(
                    f"{provider} does not support reasoning_effort",
                    "reasoning_effort_unsupported",
                )
            if reasoning_effort not in allowed_efforts:
                raise ProviderLaunchError(
                    f"Unsupported reasoning_effort for {provider}: {reasoning_effort}. "
                    f"Expected one of: {', '.join(allowed_efforts)}",
                    "invalid_reasoning_effort",
                )

        for key in ("model", "bedrock_model"):
            value = self._clean_optional(options.get(key))
            if value and any(char in value for char in ("\n", "\r", "\x00")):
                raise ValueError(f"launch_options.{key} must not contain control characters")
            if value:
                self._validate_model_id(key, value)

    def _slot_launch_warnings(self, provider: str, launch_options: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        platform = self._clean_optional(launch_options.get("platform"))
        if platform != PLATFORM_BEDROCK:
            return warnings

        aws_region = self._clean_optional(launch_options.get("aws_region"))
        aws_profile = self._clean_optional(launch_options.get("aws_profile"))
        has_ambient_region = bool(os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
        has_ambient_profile = bool(os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE"))
        if not (aws_region or has_ambient_region) or not (aws_profile or has_ambient_profile):
            warnings.append(
                "Bedrock launch relies on ambient AWS configuration; set aws_region/aws_profile "
                "if the host environment does not provide them."
            )

        effective_model = self._clean_optional(
            launch_options.get("bedrock_model") or launch_options.get("model")
        )
        if provider == PROVIDER_CODEX_CLI and effective_model and not effective_model.startswith("anthropic."):
            warnings.append(
                "Codex Bedrock model requires an AWS account or gateway that exposes this model."
            )
        return warnings

    def _validate_model_id(self, key: str, value: str) -> None:
        if not _MODEL_ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"launch_options.{key} must be a concrete provider model ID, not a display name"
            )
        if not any(char.isdigit() for char in value) and not any(
            marker in value for marker in _CONCRETE_MODEL_MARKERS
        ):
            raise ValueError(
                f"launch_options.{key} must be a concrete provider model ID, not a display name"
            )

    def _clean_required(self, value: str, label: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{label} is required")
        return value

    def _clean_optional(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _clean_ui_color(self, value: Any) -> str | None:
        color = self._clean_optional(value)
        if color is None:
            return None
        if color not in _TEAM_SLOT_UI_COLORS:
            allowed = ", ".join(sorted(_TEAM_SLOT_UI_COLORS))
            raise ValueError(f"Unsupported ui_color: {color}. Expected one of: {allowed}")
        return color

    def _clean_area_labels(self, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        labels: list[str] = []
        seen: set[str] = set()
        for raw_label in value:
            label = self._clean_optional(raw_label)
            if label is None or label in seen:
                continue
            labels.append(label)
            seen.add(label)
        return labels or None


agent_team_service = AgentTeamService()
