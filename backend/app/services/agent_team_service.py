"""Agent Team presets: saved rosters, launch planning, and launch execution."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentTeamLaunch,
    AgentTeamLaunchItem,
    AgentTeamPreset,
    AgentTeamSlot,
    MailAgentSession,
    MailTeamMember,
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
from app.services.agent_mail_service import agent_mail_service
from app.services.providers import get_provider, get_providers
from app.services.providers.base import SpawnCommandOptions
from app.utils.repo_utils import derive_repo_identity


class PlanConflictError(ValueError):
    """Raised when a launch request confirms an outdated launch plan."""

    def __init__(self, message: str, plan: AgentTeamLaunchPlan | None = None):
        super().__init__(message)
        self.plan = plan


_OPTION_FIELDS = {field.name for field in fields(SpawnCommandOptions)}
_PROVIDER_IDS = {provider.id for provider in get_providers()}
_ALLOWED_REPO_ROOTS_ENV = "CLAUDE_DECK_ALLOWED_REPO_ROOTS"


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

    async def create_preset(
        self, db: AsyncSession, request: AgentTeamPresetCreate
    ) -> AgentTeamPresetResponse:
        name = self._clean_required(request.name, "Team name")
        await self._ensure_preset_name_is_unique(db, name)
        preset = AgentTeamPreset(
            name=name,
            description=self._clean_optional(request.description),
            created_by=self._clean_optional(request.created_by),
        )
        db.add(preset)
        await db.flush()

        normalized_slots = [
            self._normalize_slot_create(slot, index)
            for index, slot in enumerate(request.slots)
        ]
        self._validate_enabled_repo_uniqueness(normalized_slots)
        for slot_data in normalized_slots:
            db.add(AgentTeamSlot(preset_id=preset.id, **slot_data))

        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def update_preset(
        self,
        db: AsyncSession,
        preset_id: int,
        name: str | None = None,
        description: str | None = None,
    ) -> AgentTeamPresetResponse:
        preset = await self._require_preset(db, preset_id)
        if name is not None:
            cleaned_name = self._clean_required(name, "Team name")
            await self._ensure_preset_name_is_unique(db, cleaned_name, exclude_preset_id=preset.id)
            preset.name = cleaned_name
        if description is not None:
            preset.description = self._clean_optional(description)
        preset.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def delete_preset(self, db: AsyncSession, preset_id: int) -> None:
        preset = await self._require_preset(db, preset_id)
        slots = await self._slots_for_preset(db, preset_id)
        slot_ids = [slot.id for slot in slots]
        statement = update(MailAgentSession).where(MailAgentSession.team_preset_id == preset_id)
        if slot_ids:
            statement = update(MailAgentSession).where(
                or_(
                    MailAgentSession.team_preset_id == preset_id,
                    MailAgentSession.team_slot_id.in_(slot_ids),
                )
            )
        await db.execute(statement.values(team_preset_id=None, team_slot_id=None))
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
                    bootstrap_prompt=slot.bootstrap_prompt,
                    launch_mode=slot.launch_mode,
                    launch_options=slot.launch_options or {},
                    enabled=slot.enabled,
                )
            )
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
        seen_repo_ids: set[str] = set()

        for session in sessions:
            provider = self._clean_optional(session.get("provider"))
            cwd = self._clean_optional(session.get("cwd"))
            if provider not in _PROVIDER_IDS or cwd is None:
                continue
            try:
                repo_path, identity = self._normalize_repo(cwd)
            except ValueError:
                continue
            if identity["repo_id"] in seen_repo_ids:
                continue
            seen_repo_ids.add(identity["repo_id"])

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
        await self._ensure_enabled_repo_is_unique(
            db,
            preset_id,
            repo_id=slot_data["repo_id"],
            enabled=slot_data["enabled"],
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
        slot = await self._require_slot(db, slot_id)
        preset = await self._require_preset(db, slot.preset_id)
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
        if request.bootstrap_prompt is not None:
            updates["bootstrap_prompt"] = self._clean_optional(request.bootstrap_prompt)
        if request.launch_mode is not None:
            updates["launch_mode"] = request.launch_mode.strip() or "plain"
        if request.launch_options is not None:
            updates["launch_options"] = self._clean_launch_options(request.launch_options)
        if request.enabled is not None:
            updates["enabled"] = request.enabled
        if request.position is not None:
            updates["position"] = request.position

        final_repo_id = updates.get("repo_id", slot.repo_id)
        final_enabled = updates.get("enabled", slot.enabled)
        await self._ensure_enabled_repo_is_unique(
            db,
            slot.preset_id,
            repo_id=final_repo_id,
            enabled=final_enabled,
            exclude_slot_id=slot.id,
        )

        identity_changed = (
            ("repo_id" in updates and updates["repo_id"] != slot.repo_id)
            or ("provider" in updates and updates["provider"] != slot.provider)
        )
        if identity_changed:
            await db.execute(
                update(MailAgentSession)
                .where(MailAgentSession.team_slot_id == slot.id)
                .values(team_preset_id=None, team_slot_id=None)
            )

        for key, value in updates.items():
            setattr(slot, key, value)
        slot.updated_at = datetime.utcnow()
        preset.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(preset)
        return await self._preset_response(db, preset)

    async def delete_slot(self, db: AsyncSession, slot_id: int) -> AgentTeamPresetResponse:
        slot = await self._require_slot(db, slot_id)
        preset = await self._require_preset(db, slot.preset_id)
        await db.execute(
            update(MailAgentSession)
            .where(MailAgentSession.team_slot_id == slot.id)
            .values(team_preset_id=None, team_slot_id=None)
        )
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
    ) -> AgentTeamLaunchPlan:
        request = request or AgentTeamLaunchRequest()
        preset = await self._require_preset(db, preset_id)
        slots = await self._selected_slots(
            db,
            preset_id,
            request.slot_ids,
            include_disabled=request.include_disabled,
        )
        await agent_mail_service.sync_observed_sessions(db)
        discovered = self._discover_sessions()
        install_status = await agent_mail_install_service.get_install_status()

        items: list[AgentTeamLaunchPlanItem] = []
        for slot in slots:
            matching = self._matching_session(slot, discovered) if request.reuse_existing else None
            item = self._plan_slot(slot, matching, install_status)
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
                raise PlanConflictError("confirm_plan_hash is required unless skip_plan_confirmation is true")
            if request.confirm_plan_hash != plan.plan_hash:
                raise PlanConflictError("Launch plan changed; review the latest plan before launching", plan)
        if not plan.can_launch:
            raise ValueError("Launch plan is blocked; resolve blocked slots before launching")

        launch = AgentTeamLaunch(
            preset_id=preset.id,
            requested_by=self._clean_optional(request.requested_by),
            plan_hash=plan.plan_hash,
            status="running",
            summary={
                "reuse_count": plan.reuse_count,
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
            result_item = await self._execute_plan_item(db, launch.id, preset, slot, item)
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
    ) -> AgentTeamLaunchResultItem:
        if plan_item.action == "reuse":
            agent_mail_member_id = await self._attach_team_context_to_existing_session(
                db,
                slot,
                plan_item.matching_session,
            )
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action="reuse",
                status="reused",
                provider=slot.provider,
                repo_path=slot.repo_path,
                session_name=plan_item.matching_session.get("session_name") if plan_item.matching_session else None,
                tmux_target=plan_item.matching_session.get("tmux_target") if plan_item.matching_session else None,
                agent_mail_member_id=agent_mail_member_id,
                message="A matching wakeable tmux session was reused",
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
            )
            self._record_launch_item(db, launch_id, result)
            return result

        try:
            options = self._spawn_options_for_slot(slot, self._bootstrap_prompt(preset, slot))
            spawned = spawn_session(
                slot.provider,
                options,
                extra_env={
                    "CLAUDE_DECK_TEAM_PRESET_ID": str(preset.id),
                    "CLAUDE_DECK_TEAM_PRESET_NAME": preset.name,
                    "CLAUDE_DECK_TEAM_SLOT_ID": str(slot.id),
                    "CLAUDE_DECK_TEAM_SLOT_NAME": slot.display_name,
                },
            )
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action="spawn",
                status="pending_registration",
                provider=slot.provider,
                repo_path=slot.repo_path,
                session_name=spawned.get("session_name"),
                tmux_target=spawned.get("tmux_target"),
                message="Session spawned; waiting for Agent Mail registration",
            )
        except Exception as exc:
            result = AgentTeamLaunchResultItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                action="spawn",
                status="failed",
                provider=slot.provider,
                repo_path=slot.repo_path,
                error=str(exc),
            )
        self._record_launch_item(db, launch_id, result)
        return result

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
    ) -> AgentTeamLaunchPlanItem:
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
            return AgentTeamLaunchPlanItem(
                slot_id=slot.id,
                slot_name=slot.display_name,
                provider=slot.provider,
                repo_id=slot.repo_id,
                repo_path=slot.repo_path,
                repo_name=slot.repo_name,
                action="reuse",
                status="ready",
                reasons=["A matching running session is already available"],
                matching_session=matching_session,
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
        )

    def _agent_mail_ready_reason(self, provider: str, install_status: Any) -> str | None:
        if provider == "claude-code":
            if not install_status.claude_code_mcp_installed:
                return "Claude Code Agent Mail MCP is not installed"
            if install_status.claude_code_hooks_missing:
                return "Claude Code Agent Mail hooks are missing"
            return None
        if provider == "codex-cli":
            if not install_status.codex_cli_available:
                return "Codex CLI is not available on this machine"
            if not install_status.codex_mcp_installed:
                return "Codex Agent Mail MCP is not installed"
            if install_status.codex_hooks_missing:
                return "Codex Agent Mail hooks are missing"
            return None
        return None

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

    def _matching_session(
        self,
        slot: AgentTeamSlot,
        discovered: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for session in discovered:
            if session.get("provider") != slot.provider:
                continue
            cwd = session.get("cwd")
            if cwd and derive_repo_identity(cwd)["repo_id"] == slot.repo_id:
                return {
                    "source": "bridge",
                    "provider": session.get("provider"),
                    "session_name": session.get("session_name"),
                    "tmux_target": session.get("tmux_target"),
                    "cwd": cwd,
                    "pid": session.get("pid"),
                }
        return None

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
        else:
            return None
        result = await db.execute(
            statement.order_by(MailAgentSession.last_seen_at.desc()).limit(1)
        )
        now = datetime.utcnow()
        for session, member in result.all():
            if agent_mail_service._effective_status(session, now) == "offline":
                continue
            session.team_preset_id = slot.preset_id
            session.team_slot_id = slot.id
            return member.id
        return None

    def _validate_spawn_options(self, slot: AgentTeamSlot) -> str | None:
        try:
            get_provider(slot.provider).build_spawn_command(self._spawn_options_for_slot(slot, prompt=None))
            return None
        except Exception as exc:
            return str(exc)

    def _spawn_options_for_slot(self, slot: AgentTeamSlot, prompt: str | None) -> SpawnCommandOptions:
        raw_options = dict(slot.launch_options or {})
        raw_prompt = self._clean_optional(raw_options.pop("prompt", None))
        if prompt and raw_prompt:
            prompt = f"{prompt}\n\nInitial task:\n{raw_prompt}"
        elif raw_prompt:
            prompt = raw_prompt

        values: dict[str, Any] = {
            "directory": slot.repo_path,
            "mode": slot.launch_mode or "plain",
            "prompt": prompt,
        }
        for key, value in raw_options.items():
            if key in _OPTION_FIELDS and key not in {"directory", "mode", "prompt"}:
                values[key] = value
        return SpawnCommandOptions(**values)

    def _bootstrap_prompt(self, preset: AgentTeamPreset, slot: AgentTeamSlot) -> str:
        if slot.bootstrap_prompt:
            return slot.bootstrap_prompt
        parts = [
            f'You are being started by Claude Deck as part of Agent Team "{preset.name}".',
            f'Your team slot is "{slot.display_name}" for repo "{slot.repo_name}".',
            "Call `deck_whoami` when the session starts, then check your inbox with `deck_check_inbox(unread_only=False)`.",
        ]
        if slot.role:
            parts.append(f"Role: {slot.role}")
        if slot.charter:
            parts.append(f"Charter: {slot.charter}")
        return "\n".join(parts)

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
                    "matching_session": {
                        key: value
                        for key, value in (item.matching_session or {}).items()
                        if key in {"source", "provider", "session_key", "session_name", "tmux_target", "cwd"}
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
            bootstrap_prompt=slot.bootstrap_prompt,
            launch_mode=slot.launch_mode,
            launch_options=slot.launch_options or {},
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

    async def _ensure_enabled_repo_is_unique(
        self,
        db: AsyncSession,
        preset_id: int,
        *,
        repo_id: str,
        enabled: bool,
        exclude_slot_id: int | None = None,
    ) -> None:
        if not enabled:
            return
        statement = select(AgentTeamSlot).where(
            AgentTeamSlot.preset_id == preset_id,
            AgentTeamSlot.repo_id == repo_id,
            AgentTeamSlot.enabled.is_(True),
        )
        if exclude_slot_id is not None:
            statement = statement.where(AgentTeamSlot.id != exclude_slot_id)
        existing = (await db.execute(statement)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("A team preset cannot have duplicate enabled slots for the same repo")

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

    def _validate_enabled_repo_uniqueness(self, slots: list[dict[str, Any]]) -> None:
        seen: set[str] = set()
        for slot in slots:
            if not slot["enabled"]:
                continue
            repo_id = slot["repo_id"]
            if repo_id in seen:
                raise ValueError("A team preset cannot have duplicate enabled slots for the same repo")
            seen.add(repo_id)

    def _normalize_slot_create(
        self,
        slot: AgentTeamSlotCreate,
        fallback_position: int,
    ) -> dict[str, Any]:
        repo_path, ident = self._normalize_repo(slot.repo_path)
        return {
            "position": fallback_position if slot.position is None else slot.position,
            "display_name": self._clean_required(slot.display_name, "Slot name"),
            "provider": self._validate_provider(slot.provider),
            "repo_id": ident["repo_id"],
            "repo_path": repo_path,
            "repo_name": ident["repo_name"],
            "role": self._clean_optional(slot.role),
            "charter": self._clean_optional(slot.charter),
            "bootstrap_prompt": self._clean_optional(slot.bootstrap_prompt),
            "launch_mode": slot.launch_mode.strip() or "plain",
            "launch_options": self._clean_launch_options(slot.launch_options),
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
        resolved = os.path.realpath(expanded)

        allowed_roots = self._allowed_repo_roots()
        if not any(self._path_is_under_root(resolved, root) for root in allowed_roots):
            roots = ", ".join(allowed_roots)
            raise ValueError(f"Repo path must be under an allowed root: {roots}")

        if not os.path.isdir(resolved):
            raise ValueError(f"Repo path does not exist or is not a directory: {repo_path}")
        return resolved, derive_repo_identity(resolved)

    def _allowed_repo_roots(self) -> list[str]:
        roots = [str(Path.home())]
        configured_roots = os.environ.get(_ALLOWED_REPO_ROOTS_ENV, "")
        roots.extend(root for root in configured_roots.split(os.pathsep) if root.strip())
        return [os.path.realpath(os.path.expanduser(root)) for root in roots]

    def _path_is_under_root(self, path: str, root: str) -> bool:
        if root == os.path.sep:
            return True
        return path == root or path.startswith(root + os.path.sep)

    def _validate_provider(self, provider: str) -> str:
        provider = provider.strip()
        if provider not in _PROVIDER_IDS:
            raise ValueError(f"Unknown provider: {provider}")
        return provider

    def _clean_launch_options(self, value: dict[str, Any] | None) -> dict[str, Any]:
        if not value:
            return {}
        return {key: option for key, option in value.items() if key in _OPTION_FIELDS}

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


agent_team_service = AgentTeamService()
