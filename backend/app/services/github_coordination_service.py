"""Durable Leader backlog assessment, without dispatch or approval authority."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from httpx import HTTPError
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.coordination import CoordinationAssessment, CoordinationPolicy
from app.models.database import (
    AgentTeamPreset, AgentTeamSlot, GithubApprovalRequest, GithubBacklogCoordination,
    GithubWorkItem, GithubWorkspace, MailAgentSession, MailTeamMember, TeamGithubScope,
)
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import (
    MCP_HEARTBEAT_TTL_SECONDS, agent_mail_service,
)
from app.services.github_client import GithubClient, github_client
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_recovery_gate import configured_recovery_only_attempt
from app.utils import peer_process

logger = logging.getLogger(__name__)
_BOOT_ID = uuid4().hex
_MAX_SNAPSHOT_REQUESTS = 3
_MAX_CONTEXT_ROWS = 64
_READ_SECRET = secrets.token_bytes(32)
_READ_TTL_SECONDS = 300


def _read_token(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()).decode()
    return payload + "." + hmac.new(_READ_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def _read_claims(token: str) -> dict:
    try:
        if len(token) > 2048:
            raise ValueError()
        payload, signature = token.split(".")
        expected = hmac.new(_READ_SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        claims = json.loads(base64.b64decode(payload, altchars=b"-_", validate=True))
        integer_keys = ("scope", "leader", "policy", "revision", "generation", "sequence", "expires")
        if (not isinstance(claims, dict)
            or set(claims) != {*integer_keys, "fingerprint", "nonce"}
            or any(type(claims[k]) is not int or claims[k] < 0 for k in integer_keys)
            or not isinstance(claims["fingerprint"], str) or len(claims["fingerprint"]) != 64
            or not isinstance(claims["nonce"], str) or len(claims["nonce"]) != 32):
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise CoordinationError("coordination_read_invalid") from None
    now = time.time()
    if not now < claims["expires"] <= now + _READ_TTL_SECONDS + 1:
        raise CoordinationError("coordination_read_expired")
    return claims


class CoordinationError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


def hold_code() -> str | None:
    try:
        if configured_recovery_only_attempt() is not None:
            return "recovery_only"
        for configured in settings.github_coordination_hold_paths:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                return "hold_unavailable"
            try:
                path.lstat()  # A dangling symlink is still a HOLD marker.
            except FileNotFoundError:
                continue
            return "hold"
    except (OSError, ValueError):
        return "hold_unavailable"
    return None


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _autonomous(scope_id: int):
    return exists(select(TeamGithubScope.id).join(
        AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id,
    ).where(
        TeamGithubScope.id == scope_id, TeamGithubScope.enabled.is_(True),
        AgentTeamPreset.autonomy_enabled.is_(True),
    ))


def _current_authority(scope, preset, leader):
    designated = select(AgentTeamSlot.id).where(
        AgentTeamSlot.preset_id == scope.preset_id, AgentTeamSlot.enabled.is_(True),
    ).order_by(AgentTeamSlot.position, AgentTeamSlot.id).limit(1).scalar_subquery()
    member = select(MailTeamMember.id).where(
        MailTeamMember.team_slot_id == leader.team_slot_id,
    ).order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).limit(1).scalar_subquery()
    return exists(select(MailAgentSession.id).where(
        MailAgentSession.id == leader.id, MailAgentSession.member_id == member,
        MailAgentSession.team_preset_id == scope.preset_id,
        MailAgentSession.team_slot_id == designated,
        MailAgentSession.source == "mcp", MailAgentSession.closed_at.is_(None),
        MailAgentSession.mailbox_status == "connected",
        MailAgentSession.wake_enabled.is_(True),
        MailAgentSession.capability_token_hash == leader.capability_token_hash,
        MailAgentSession.bound_pane_pid == leader.bound_pane_pid,
        MailAgentSession.bound_pane_proc_start == leader.bound_pane_proc_start,
        MailAgentSession.last_seen_at >= datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS),
    )) & exists(select(TeamGithubScope.id).join(
        AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id,
    ).where(
        TeamGithubScope.id == scope.id, TeamGithubScope.updated_at == scope.updated_at,
        TeamGithubScope.enabled.is_(True), AgentTeamPreset.autonomy_enabled.is_(True),
        AgentTeamPreset.updated_at == preset.updated_at,
    )) & exists(select(MailTeamMember.id).where(
        MailTeamMember.id == leader.member_id,
        MailTeamMember.team_slot_id == leader.team_slot_id,
        MailTeamMember.team_preset_id == scope.preset_id,
    ))


class GithubCoordinationService:
    async def state(self, db: AsyncSession, scope_id: int):
        return await db.get(GithubBacklogCoordination, scope_id, populate_existing=True)

    async def scope(self, db: AsyncSession, scope_id: int):
        scope = await db.get(TeamGithubScope, scope_id, populate_existing=True)
        if scope is None:
            raise CoordinationError("scope_not_found", 404)
        return scope

    async def configure(self, db: AsyncSession, scope_id: int, policy: CoordinationPolicy):
        await self.scope(db, scope_id)
        row = await self.state(db, scope_id)
        values = policy.model_dump(exclude={"expected_version"})
        values["issue_numbers"] = sorted(policy.issue_numbers)
        if row is None:
            if policy.expected_version != 0:
                raise CoordinationError("coordination_policy_changed")
            row = GithubBacklogCoordination(scope_id=scope_id, version=1, **values)
            db.add(row)
            await db.flush()
        else:
            result = await db.execute(update(GithubBacklogCoordination).where(
                GithubBacklogCoordination.scope_id == scope_id,
                GithubBacklogCoordination.version == policy.expected_version,
            ).values(
                **values, version=policy.expected_version + 1,
                policy_revision=GithubBacklogCoordination.policy_revision + 1,
                snapshot_hash=None, error_code=None,
            ).execution_options(synchronize_session=False))
            if result.rowcount != 1:
                raise CoordinationError("coordination_policy_changed")
        # Configuration never resets quota, sequence or prior authority evidence.
        await db.commit()

    async def current_leader(self, db: AsyncSession, scope: TeamGithubScope):
        if not settings.mail_capability_tokens_required:
            raise CoordinationError("leader_identity_unavailable")
        slots = list((await db.scalars(select(AgentTeamSlot).where(
            AgentTeamSlot.preset_id == scope.preset_id,
        ).order_by(AgentTeamSlot.position, AgentTeamSlot.id).limit(_MAX_CONTEXT_ROWS + 1))).all())
        if len(slots) > _MAX_CONTEXT_ROWS:
            raise CoordinationError("coordination_context_limit")
        leader = github_dispatch_service._leader_slot(slots)
        member = await github_dispatch_service._slot_member(db, leader.id) if leader else None
        if member is None or member.team_preset_id != scope.preset_id:
            raise CoordinationError("leader_unavailable")
        sessions = list((await db.scalars(select(MailAgentSession).where(
            MailAgentSession.member_id == member.id,
            MailAgentSession.team_preset_id == scope.preset_id,
            MailAgentSession.team_slot_id == leader.id,
            MailAgentSession.source == "mcp",
            MailAgentSession.closed_at.is_(None),
            MailAgentSession.mailbox_status == "connected",
            MailAgentSession.wake_enabled.is_(True),
            MailAgentSession.capability_token_hash.is_not(None),
            MailAgentSession.last_seen_at >= datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS),
        ).limit(_MAX_CONTEXT_ROWS + 1).execution_options(populate_existing=True))).all())
        if len(sessions) > _MAX_CONTEXT_ROWS:
            raise CoordinationError("coordination_context_limit")
        sessions = [s for s in sessions if s.bound_pane_pid is not None
                    and s.bound_pane_proc_start
                    and peer_process.pane_is_alive(s.bound_pane_pid, s.bound_pane_proc_start) is True]
        if len(sessions) != 1:
            raise CoordinationError("leader_unavailable")
        return sessions[0], slots

    async def require_leader(self, db: AsyncSession, scope_id: int, principal: MailAgentSession):
        scope = await self.scope(db, scope_id)
        leader, _slots = await self.current_leader(db, scope)
        if principal.id != leader.id:
            raise CoordinationError("current_leader_required", 403)
        return leader

    async def _context(self, db: AsyncSession, scope_id: int, numbers: list[int], issues: dict):
        scope = await self.scope(db, scope_id)
        preset = await db.get(AgentTeamPreset, scope.preset_id, populate_existing=True)
        if not scope.enabled or not preset.autonomy_enabled:
            raise CoordinationError("autonomy_off")
        if code := hold_code():
            raise CoordinationError(code)
        count = await db.scalar(select(func.count()).select_from(TeamGithubScope).where(
            TeamGithubScope.preset_id == scope.preset_id, TeamGithubScope.enabled.is_(True),
        ))
        if count != 1:
            raise CoordinationError("single_scope_required")
        leader, slots = await self.current_leader(db, scope)
        # Historical unrelated attempts cannot change capacity or assigned gates.
        relevant_items = (GithubWorkItem.scope_id == scope_id) & or_(
            GithubWorkItem.issue_number.in_(numbers),
            GithubWorkItem.dispatch_status.in_(["dispatched", "verifying"]),
        )
        items = list((await db.scalars(select(GithubWorkItem).where(relevant_items)
            .limit(_MAX_CONTEXT_ROWS + 1).execution_options(populate_existing=True))).all())
        by_number = {i.issue_number: i for i in items}
        workspaces = list((await db.scalars(select(GithubWorkspace).where(
            GithubWorkspace.scope_id == scope_id,
        ).limit(_MAX_CONTEXT_ROWS + 1).execution_options(populate_existing=True))).all())
        relevant_approvals = relevant_items & (GithubApprovalRequest.dispatch_nonce == GithubWorkItem.dispatch_nonce)
        approvals = list((await db.scalars(select(GithubApprovalRequest).join(
            GithubWorkItem, GithubWorkItem.id == GithubApprovalRequest.work_item_id,
        ).where(relevant_approvals).limit(_MAX_CONTEXT_ROWS + 1)
            .execution_options(populate_existing=True))).all())
        if any(len(rows) > _MAX_CONTEXT_ROWS for rows in (items, workspaces, approvals)):
            raise CoordinationError("coordination_context_limit")
        enabled_slots = [slot.id for slot in slots if slot.enabled]
        ranked_members = select(
            MailTeamMember.id, func.row_number().over(
                partition_by=MailTeamMember.team_slot_id,
                order_by=(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()),
            ).label("position"),
        ).where(MailTeamMember.team_slot_id.in_(enabled_slots)).subquery()
        current_members = (MailTeamMember.id.in_(select(ranked_members.c.id).where(
            ranked_members.c.position == 1,
        ))) & (MailTeamMember.team_preset_id == scope.preset_id)
        members = list((await db.scalars(select(MailTeamMember).where(current_members)
            .limit(_MAX_CONTEXT_ROWS + 1).execution_options(populate_existing=True))).all())
        available_sessions = (
            MailAgentSession.member_id.in_(select(MailTeamMember.id).where(current_members))
            & (MailAgentSession.team_slot_id == select(MailTeamMember.team_slot_id).where(
                MailTeamMember.id == MailAgentSession.member_id,
            ).correlate(MailAgentSession).scalar_subquery())
            & (MailAgentSession.team_preset_id == scope.preset_id)
            & MailAgentSession.team_slot_id.in_(enabled_slots)
            & (MailAgentSession.source == "mcp") & MailAgentSession.closed_at.is_(None)
            & (MailAgentSession.mailbox_status == "connected") & MailAgentSession.wake_enabled.is_(True)
            & MailAgentSession.capability_token_hash.is_not(None)
            & MailAgentSession.bound_pane_pid.is_not(None) & MailAgentSession.bound_pane_proc_start.is_not(None)
            & (MailAgentSession.last_seen_at >= datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS))
        )
        participants = list((await db.scalars(select(MailAgentSession).where(available_sessions)
            .limit(_MAX_CONTEXT_ROWS + 1).execution_options(populate_existing=True))).all())
        if len(members) > _MAX_CONTEXT_ROWS or len(participants) > _MAX_CONTEXT_ROWS:
            raise CoordinationError("coordination_context_limit")
        observations = []
        for number in numbers:
            issue = issues.get(number)
            expected_repo = f"https://api.github.com/repos/{scope.repo_owner}/{scope.repo_name}"
            if (not isinstance(issue, dict) or type(issue.get("number")) is not int or issue.get("number") != number
                or str(issue.get("repository_url", "")).casefold() != expected_repo.casefold()
                or issue.get("state") not in {"open", "closed"}
                or not isinstance(issue.get("updated_at"), str)
                or not isinstance(issue.get("labels"), list)):
                raise CoordinationError("backlog_unavailable")
            try:
                changed_at = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
                if changed_at.tzinfo is None:
                    raise ValueError("timezone_required")
            except ValueError:
                raise CoordinationError("backlog_unavailable")
            labels = issue["labels"]
            if any(not isinstance(label, dict) or not isinstance(label.get("name"), str) for label in labels):
                raise CoordinationError("backlog_unavailable")
            item = by_number.get(number)
            observations.append({
                "issue_number": number, "github_state": issue["state"],
                "github_updated_at": issue["updated_at"],
                "dispatch_ready": any(label["name"] == scope.dispatch_label for label in labels),
                "work_status": item.dispatch_status if item else None,
                "pr_number": item.pr_number if item else None,
            })
        public = {
            "issues": observations,
            "active_implementations": sum(i.dispatch_status in {"dispatched", "verifying"} for i in items),
            "execution_limit": scope.max_concurrent_dispatched,
            "available_workspaces": sum(w.enabled and w.dispatchable and not w.provision_error
                                        and w.leased_item_id is None and w.lease_token is None
                                        for w in workspaces),
            "leased_workspaces": sum(w.leased_item_id is not None or w.lease_token is not None for w in workspaces),
        }
        # Private identity/authority material is hashed transiently, never projected.
        identity = {
            "boot": _BOOT_ID, "resume": preset.updated_at.isoformat(),
            "scope_revision": scope.updated_at.isoformat(),
            "scope_policy": {k: getattr(scope, k) for k in (
                "base_ref", "dispatch_label", "merge_policy", "max_approval_rounds",
                "max_verification_retries", "max_auto_merges_per_day", "continuation_enabled",
                "max_build_parallelism",
            )},
            "leader": [leader.id, leader.member_id, leader.bound_pane_pid, leader.bound_pane_proc_start,
                       leader.capability_token_hash],
            "slots": [[s.id, s.position, s.enabled, s.role, s.area_labels] for s in slots],
            "members": [[m.id, m.team_slot_id] for m in sorted(members, key=lambda m: m.id)],
            "participants": [[s.id, s.member_id, s.team_slot_id, s.bound_pane_pid,
                s.bound_pane_proc_start, s.capability_token_hash,
                peer_process.pane_is_alive(s.bound_pane_pid, s.bound_pane_proc_start) is True]
                for s in sorted(participants, key=lambda s: s.id)],
            "items": [[i.id, i.dispatch_status, i.owner_slot_id, i.dispatch_nonce,
                       i.pr_number, i.last_verified_sha, i.active_scope_revision,
                       i.attempt_phase, i.ack_evidence_message_id, i.retry_count]
                      for i in sorted(items, key=lambda x: x.id)],
            "leases": [[w.id, w.enabled, w.dispatchable, bool(w.provision_error),
                        w.leased_item_id, w.lease_token, w.leased_owner_pid, w.leased_owner_proc_start]
                       for w in sorted(workspaces, key=lambda x: x.id)],
            "approvals": [[a.id, a.work_item_id, a.request_kind, a.status,
                           a.dispatch_nonce, a.approval_round, a.owner_member_id,
                           a.leader_member_id, a.request_message_id, a.decision_message_id]
                          for a in sorted(approvals, key=lambda x: x.id)],
        }
        authority = _current_authority(scope, preset, leader)
        # Keep the observed dispatch/lease/approval identities current at the
        # write boundary, including supported databases without SQLite's writer lock.
        for item in items:
            authority &= exists(select(GithubWorkItem.id).where(
                GithubWorkItem.id == item.id, GithubWorkItem.dispatch_status == item.dispatch_status,
                GithubWorkItem.owner_slot_id == item.owner_slot_id,
                GithubWorkItem.dispatch_nonce == item.dispatch_nonce,
                GithubWorkItem.pr_number == item.pr_number,
                GithubWorkItem.last_verified_sha == item.last_verified_sha,
                GithubWorkItem.active_scope_revision == item.active_scope_revision,
                GithubWorkItem.attempt_phase == item.attempt_phase,
                GithubWorkItem.ack_evidence_message_id == item.ack_evidence_message_id,
                GithubWorkItem.retry_count == item.retry_count,
            ))
        for workspace in workspaces:
            authority &= exists(select(GithubWorkspace.id).where(
                GithubWorkspace.id == workspace.id, GithubWorkspace.enabled == workspace.enabled,
                GithubWorkspace.dispatchable == workspace.dispatchable,
                GithubWorkspace.leased_item_id == workspace.leased_item_id,
                GithubWorkspace.lease_token == workspace.lease_token,
                GithubWorkspace.leased_owner_pid == workspace.leased_owner_pid,
                GithubWorkspace.leased_owner_proc_start == workspace.leased_owner_proc_start,
                GithubWorkspace.provision_error == workspace.provision_error,
            ))
        for approval in approvals:
            authority &= exists(select(GithubApprovalRequest.id).where(
                GithubApprovalRequest.id == approval.id, GithubApprovalRequest.status == approval.status,
                GithubApprovalRequest.request_kind == approval.request_kind,
                GithubApprovalRequest.approval_round == approval.approval_round,
                GithubApprovalRequest.dispatch_nonce == approval.dispatch_nonce,
                GithubApprovalRequest.owner_member_id == approval.owner_member_id,
                GithubApprovalRequest.leader_member_id == approval.leader_member_id,
                GithubApprovalRequest.request_message_id == approval.request_message_id,
                GithubApprovalRequest.decision_message_id == approval.decision_message_id,
            ))
        for slot in slots:
            authority &= exists(select(AgentTeamSlot.id).where(
                AgentTeamSlot.id == slot.id, AgentTeamSlot.updated_at == slot.updated_at,
            ))
        for member in members:
            authority &= exists(select(MailTeamMember.id).where(
                current_members, MailTeamMember.id == member.id,
                MailTeamMember.team_slot_id == member.team_slot_id,
            ))
        for participant in participants:
            authority &= exists(select(MailAgentSession.id).where(
                available_sessions, MailAgentSession.id == participant.id,
                MailAgentSession.member_id == participant.member_id,
                MailAgentSession.team_slot_id == participant.team_slot_id,
                MailAgentSession.bound_pane_pid == participant.bound_pane_pid,
                MailAgentSession.bound_pane_proc_start == participant.bound_pane_proc_start,
                MailAgentSession.capability_token_hash == participant.capability_token_hash,
            ))
        authority &= select(func.count()).select_from(MailTeamMember).where(current_members).scalar_subquery() == len(members)
        authority &= select(func.count()).select_from(MailAgentSession).where(available_sessions).scalar_subquery() == len(participants)
        authority &= select(func.count()).select_from(GithubWorkItem).where(relevant_items).scalar_subquery() == len(items)
        authority &= select(func.count()).select_from(GithubWorkspace).where(
            GithubWorkspace.scope_id == scope_id,
        ).scalar_subquery() == len(workspaces)
        authority &= select(func.count()).select_from(GithubApprovalRequest).join(
            GithubWorkItem, GithubWorkItem.id == GithubApprovalRequest.work_item_id,
        ).where(relevant_approvals).scalar_subquery() == len(approvals)
        authority &= select(func.count()).select_from(AgentTeamSlot).where(
            AgentTeamSlot.preset_id == scope.preset_id,
        ).scalar_subquery() == len(slots)
        authority &= select(func.count()).select_from(TeamGithubScope).where(
            TeamGithubScope.preset_id == scope.preset_id, TeamGithubScope.enabled.is_(True),
        ).scalar_subquery() == 1
        return public, _digest([public, identity]), leader, authority

    async def _issues(self, scope, numbers, client):
        return await asyncio.wait_for(client.get_issues_by_number(
            scope.repo_owner, scope.repo_name, numbers,
        ), timeout=30)

    async def reconcile(self, db: AsyncSession, scope_id: int, client: GithubClient | None = None):
        row = await self.state(db, scope_id)
        if row is None or not row.enabled:
            return
        scope = await self.scope(db, scope_id)
        version, numbers = row.version, list(row.issue_numbers)
        if hold_code() or not await db.scalar(select(_autonomous(scope_id))):
            return
        await db.commit()  # Never retain a SQLite read transaction across HTTP.
        try:
            issues = await self._issues(scope, numbers, client or github_client)
            public, fingerprint, leader, authority = await self._context(db, scope_id, numbers, issues)
        except CoordinationError as exc:
            await self._record_error(db, scope_id, version, exc.code)
            return
        except Exception:
            await self._record_error(db, scope_id, version, "backlog_unavailable")
            return
        row = await self.state(db, scope_id)
        if row is None or row.version != version or not row.enabled:
            await db.rollback()
            return
        now = datetime.utcnow()
        changed = row.snapshot_hash != fingerprint
        generation = row.generation + int(changed)
        # One pending Mail asks the Leader to read the latest request. Intermediate
        # snapshots can supersede that request without buying another wake-up.
        pending = (row.message_id is not None and row.leader_session_id == leader.id
                   and row.assessed_sequence != row.request_sequence
                   and row.last_requested_at is not None
                   and (now - row.last_requested_at).total_seconds() < row.fallback_seconds)
        requests = row.snapshot_requests if pending else (0 if changed else row.snapshot_requests)
        day = now.strftime("%Y-%m-%d")
        daily = row.daily_requests if row.budget_day == day else 0
        assessed_current = (not changed and row.assessed_generation == generation
                            and row.assessed_sequence == row.request_sequence and row.last_assessed_at)
        needs_current_request = (changed or row.requested_generation != generation) and not assessed_current
        delay = 60 if needs_current_request else row.fallback_seconds
        anchor = row.last_requested_at
        if assessed_current and (anchor is None or row.last_assessed_at > anchor):
            anchor = row.last_assessed_at
        due = anchor is None or (now - anchor).total_seconds() >= delay
        capped = daily >= row.max_daily_requests or requests >= _MAX_SNAPSHOT_REQUESTS
        want_request = due and not capped and not pending
        values = dict(snapshot=public, snapshot_hash=fingerprint, generation=generation,
                      snapshot_requests=requests, last_polled_at=now, version=version + 1,
                      budget_day=day, daily_requests=daily,
                      error_code="coordination_capped" if capped and due else None)
        if pending and changed:
            values["requested_generation"] = generation
        if want_request:
            # Resolve the actual opted-in wake target before spending a persisted quota.
            try:
                pane = await agent_mail_service._nudge_session_for_member(db, leader.member_id, now)
                if pane.pid != leader.bound_pane_pid:
                    raise CoordinationError("leader_unavailable")
            except Exception:
                values["error_code"] = "leader_unavailable"
                want_request = False
        if hold_code():
            await db.rollback()
            return
        if want_request:
            values.update(request_sequence=row.request_sequence + 1, daily_requests=daily + 1,
                          snapshot_requests=requests + 1, last_requested_at=now,
                          leader_session_id=leader.id, requested_generation=generation)
        claim = await db.execute(update(GithubBacklogCoordination).where(
            GithubBacklogCoordination.scope_id == scope_id,
            GithubBacklogCoordination.version == version,
            GithubBacklogCoordination.enabled.is_(True), authority,
        ).values(**values).execution_options(synchronize_session=False))
        if claim.rowcount != 1:
            await db.rollback()
            return
        if want_request:
            sequence = values["request_sequence"]
            message = await agent_mail_service.send_message(db, MailMessageCreate(
                kind="message", recipient_member_id=leader.member_id,
                subject="Reconcile assigned backlog and independent work",
                body_markdown=(
                    f"Assess the assigned backlog for scope {scope_id}. Call "
                    f"deck_get_backlog_coordination(scope_id={scope_id}) for the current request, "
                    "then inspect the assigned GitHub issues and reviewed dependency/milestone packet. "
                    "Reconcile already-landed fixes before assigning new implementation. Submit exactly "
                    "one evidenced disposition per assigned issue using deck_report_backlog_assessment. "
                    "Read again immediately before publishing and pass its private snapshot_token. "
                    "A pending notification can cover newer generations; use the fresh read, not this "
                    "Mail's original payload. Current authenticated publication spends no notification quota. "
                    "The assessment is advisory: it is not approval or permission to change labels, "
                    "release a lease, merge a PR or satisfy a milestone. Use your existing authorized "
                    "workflow to admit independent eligible work only after verifying scope, all gates, "
                    "owner/file assignments and resources. Continue permitted standing validation/docs "
                    "work without a dummy dispatch. Waiting for one human merge need not pause unrelated "
                    "work; spare capacity alone does not authorize blocked work. Preserve human merge, "
                    "exact-head review, approval/lease identities and finite budgets. Stop on OFF/HOLD."
                ), payload={"kind": "github_backlog_reconcile", "scope_id": scope_id,
                            "generation": generation, "request_sequence": sequence},
            ), auto_nudge=False, commit=False,
                delivery_key=f"backlog:{scope_id}:{generation}:{sequence}")
            await db.execute(update(GithubBacklogCoordination).where(
                GithubBacklogCoordination.scope_id == scope_id,
                GithubBacklogCoordination.version == version + 1,
            ).values(message_id=message.id))
        await db.commit()  # Mail, linkage, generation and finite quota become durable together.
        if want_request and not hold_code() and await db.scalar(select(_autonomous(scope_id))):
            live = await self.state(db, scope_id)
            if (live is None or not live.enabled or live.version != version + 1
                or live.generation != generation or live.request_sequence != sequence
                or not await db.scalar(select(authority))):
                return
            current, _ = await self.current_leader(db, await self.scope(db, scope_id))
            if current.id == leader.id and not hold_code():
                await agent_mail_service.auto_nudge_members(db, {leader.member_id})

    async def _record_error(self, db, scope_id, version, code):
        await db.rollback()
        if hold_code() or not await db.scalar(select(_autonomous(scope_id))):
            return
        await db.execute(update(GithubBacklogCoordination).where(
            GithubBacklogCoordination.scope_id == scope_id,
            GithubBacklogCoordination.version == version,
            GithubBacklogCoordination.enabled.is_(True), _autonomous(scope_id),
        ).values(error_code=code, version=version + 1))
        await db.commit()

    async def assess(self, db, scope_id, principal, report: CoordinationAssessment, client=None):
        row = await self.state(db, scope_id)
        if row is None or not row.enabled:
            raise CoordinationError("coordination_not_requested")
        version, numbers = row.version, list(row.issue_numbers)
        principal_id = principal.id
        signed = report.snapshot_token is not None
        claims = _read_claims(report.snapshot_token) if signed else None
        if signed:
            if (claims["scope"] != scope_id or claims["leader"] != principal_id
                or claims["policy"] != row.policy_revision
                or claims["generation"] != report.generation
                or claims["sequence"] != report.request_sequence):
                raise CoordinationError("coordination_read_changed")
        elif (row.message_id is None or report.request_sequence == 0):
            raise CoordinationError("coordination_not_requested")
        elif (report.generation != row.generation or report.generation != row.requested_generation
              or report.request_sequence != row.request_sequence):
            raise CoordinationError("coordination_request_changed")
        if len(report.entries) != len(numbers) or {e.issue_number for e in report.entries} != set(numbers):
            raise CoordinationError("complete_assessment_required", 422)
        if any(set(e.evidence_issue_numbers) - set(numbers) for e in report.entries):
            raise CoordinationError("assigned_evidence_required", 422)
        scope = await self.scope(db, scope_id)
        if code := hold_code():
            raise CoordinationError(code)
        if not await db.scalar(select(_autonomous(scope_id))):
            raise CoordinationError("autonomy_off")
        leader = await self.require_leader(db, scope_id, principal)
        if not signed and leader.id != row.leader_session_id:
            raise CoordinationError("coordination_leader_changed")
        await db.commit()
        issues = await self._issues(scope, numbers, client or github_client)
        public, fingerprint, leader, authority = await self._context(db, scope_id, numbers, issues)
        row = await self.state(db, scope_id)
        if row is None or not row.enabled or principal_id != leader.id:
            raise CoordinationError("coordination_snapshot_changed")
        generation = row.generation + int(row.snapshot_hash != fingerprint) if signed else report.generation
        if signed:
            # Ordinary polls may update version while preserving this exact read.
            # Configuration, publication, request and authority changes may not.
            _read_claims(report.snapshot_token)  # Recheck expiry after bounded HTTP.
            if (row.policy_revision != claims["policy"] or fingerprint != claims["fingerprint"]
                or generation != claims["generation"] or row.request_sequence != claims["sequence"]):
                raise CoordinationError("coordination_read_changed")
        elif (row.version != version or row.snapshot_hash != fingerprint
              or row.leader_session_id != leader.id):
            raise CoordinationError("coordination_snapshot_changed")
        observed = {i["issue_number"]: i for i in public["issues"]}
        for entry in report.entries:
            issue = observed[entry.issue_number]
            if entry.disposition == "eligible" and (
                issue["github_state"] != "open"
                or issue["work_status"] not in {None, "pending"}
                or public["available_workspaces"] == 0
                or public["active_implementations"] >= public["execution_limit"]
            ):
                raise CoordinationError("implementation_not_available")
        entries = [e.model_dump() for e in sorted(report.entries, key=lambda e: e.issue_number)]
        token_hash = hashlib.sha256(report.snapshot_token.encode()).hexdigest() if signed else None
        replay = (row.assessed_generation == generation and row.assessed_sequence == report.request_sequence)
        if signed and row.assessment_revision != claims["revision"]:
            if (row.assessment_revision != claims["revision"] + 1 or not replay
                or row.last_assessment_token_hash != token_hash or row.assessments != entries):
                raise CoordinationError("coordination_read_changed")
            if not await db.scalar(select(authority)):
                raise CoordinationError("coordination_snapshot_changed")
            return  # Only the exact accepted challenge/payload is an idempotent retry.
        if not signed and replay:
            if row.assessments != entries:
                raise CoordinationError("coordination_already_assessed")
            if not await db.scalar(select(authority)):
                raise CoordinationError("coordination_snapshot_changed")
            return
        if code := hold_code():
            raise CoordinationError(code)
        version = row.version
        revision = row.assessment_revision
        values = dict(assessments=entries, assessed_generation=generation,
                      assessed_sequence=report.request_sequence, last_assessed_at=datetime.utcnow(),
                      assessment_revision=revision + 1, last_assessment_token_hash=token_hash,
                      error_code=None, version=version + 1)
        if signed:
            values.update(snapshot=public, snapshot_hash=fingerprint, generation=generation,
                          leader_session_id=leader.id, last_polled_at=datetime.utcnow())
        result = await db.execute(update(GithubBacklogCoordination).where(
            GithubBacklogCoordination.scope_id == scope_id,
            GithubBacklogCoordination.version == version,
            GithubBacklogCoordination.assessment_revision == revision,
            GithubBacklogCoordination.policy_revision == row.policy_revision,
            GithubBacklogCoordination.enabled.is_(True), authority,
        ).values(**values).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise CoordinationError("coordination_snapshot_changed")
        if code := hold_code():
            await db.rollback()
            raise CoordinationError(code)
        await db.commit()

    async def summary(self, db, scope_id):
        scope = await self.scope(db, scope_id)
        preset = await db.get(AgentTeamPreset, scope.preset_id, populate_existing=True)
        row = await self.state(db, scope_id)
        status = "disabled"
        code = hold_code()
        if row and row.enabled:
            status = "paused" if not scope.enabled or not preset.autonomy_enabled else "awaiting_assessment"
            if code:
                status = code
            elif status != "paused":
                if row.error_code and row.error_code != "coordination_capped":
                    status = row.error_code
                elif not row.last_polled_at:
                    status = "unknown"
                elif not row.snapshot_hash:
                    status = "awaiting_assessment"
                elif (datetime.utcnow() - row.last_polled_at).total_seconds() > max(120, settings.github_dispatch_interval_seconds * 2):
                    status = "stale"
                elif row.assessed_generation == row.generation and row.assessed_sequence == row.request_sequence and row.last_assessed_at:
                    status = "assessed"
                if status in {"assessed", "awaiting_assessment"} and row.snapshot_hash and row.snapshot:
                    cached = {i["issue_number"]: {
                        "number": i["issue_number"], "state": i["github_state"],
                        "updated_at": i["github_updated_at"],
                        "repository_url": f"https://api.github.com/repos/{scope.repo_owner}/{scope.repo_name}",
                        "labels": [{"name": scope.dispatch_label}] if i["dispatch_ready"] else [],
                    } for i in row.snapshot.get("issues", [])}
                    try:
                        _public, fingerprint, _leader, _guard = await self._context(db, scope_id, row.issue_numbers, cached)
                        if fingerprint != row.snapshot_hash:
                            status = "stale"
                    except CoordinationError as error:
                        status = error.code
        current = status == "assessed"
        now = datetime.utcnow()
        daily = row.daily_requests if row and row.budget_day == now.strftime("%Y-%m-%d") else 0
        cap_reason = ("daily" if row and daily >= row.max_daily_requests else
                      "snapshot" if row and row.snapshot_requests >= _MAX_SNAPSHOT_REQUESTS else None)
        # A notification-only limit cannot invalidate a current signed assessment.
        if not current and cap_reason and status == "awaiting_assessment":
            status = "coordination_capped"
        snapshot = row.snapshot or {} if row else {}
        entries = row.assessments if row else []
        return {
            "scope_id": scope_id, "repo": f"{scope.repo_owner}/{scope.repo_name}",
            "enabled": bool(row and row.enabled), "version": row.version if row else 0,
            "issue_numbers": row.issue_numbers if row else [],
            "fallback_seconds": row.fallback_seconds if row else 1800,
            "max_daily_requests": row.max_daily_requests if row else 12,
            "requests_today": daily,
            "notifications_remaining": max(0, row.max_daily_requests - daily) if row else 0,
            "notification_cap_reason": cap_reason,
            "notification_budget_resets_at": (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat() + "Z",
            "assessment_age_seconds": max(0, int((now - row.last_assessed_at).total_seconds())) if row and row.last_assessed_at else None,
            "autonomy_enabled": bool(scope.enabled and preset.autonomy_enabled),
            "status": status, "last_polled_at": row.last_polled_at if row else None,
            "observation_expires_at": (row.last_polled_at + timedelta(
                seconds=max(120, settings.github_dispatch_interval_seconds * 2),
            )) if row and row.last_polled_at else None,
            "last_assessed_at": row.last_assessed_at if row else None,
            "active_implementations": snapshot.get("active_implementations"),
            "execution_limit": scope.max_concurrent_dispatched,
            "available_workspaces": snapshot.get("available_workspaces"),
            "leased_workspaces": snapshot.get("leased_workspaces"),
            "eligible_count": sum(e["disposition"] == "eligible" for e in entries) if current else None,
            "entries": entries, "assessment_current": current,
            "observations": snapshot.get("issues", []),
        }

    async def request(self, db, scope_id, *, principal=None, client=None):
        result = await self.summary(db, scope_id)
        row = await self.state(db, scope_id)
        result.update(generation=row.generation if row else 0,
                      request_sequence=row.request_sequence if row else 0,
                      observations=(row.snapshot or {}).get("issues", []) if row else [])
        if (principal is None or row is None or not row.enabled or hold_code()
            or not await db.scalar(select(_autonomous(scope_id)))):
            return result  # Operator/OFF/HOLD reads never mint a publication token.
        policy_revision, numbers = row.policy_revision, list(row.issue_numbers)
        principal_id = principal.id
        scope = await self.scope(db, scope_id)
        await self.require_leader(db, scope_id, principal)
        await db.commit()
        try:
            issues = await self._issues(scope, numbers, client or github_client)
        except (TimeoutError, OSError, HTTPError):
            raise CoordinationError("backlog_unavailable") from None
        public, fingerprint, leader, authority = await self._context(db, scope_id, numbers, issues)
        # HTTP can overlap a poll or a signed correction. Rebuild all historical
        # assessment fields from the post-read row before attaching its challenge.
        result = await self.summary(db, scope_id)
        row = await self.state(db, scope_id)
        if (row is None or not row.enabled or row.policy_revision != policy_revision
            or principal_id != leader.id or not await db.scalar(select(authority))):
            raise CoordinationError("coordination_snapshot_changed")
        if code := hold_code():
            raise CoordinationError(code)
        generation = row.generation + int(row.snapshot_hash != fingerprint)
        result.update(generation=generation, request_sequence=row.request_sequence,
                      observations=public["issues"], version=row.version,
                      active_implementations=public["active_implementations"],
                      available_workspaces=public["available_workspaces"],
                      leased_workspaces=public["leased_workspaces"])
        if row.snapshot_hash != fingerprint:
            result.update(assessment_current=False, eligible_count=None)
        result["snapshot_token"] = _read_token({
            "scope": scope_id, "leader": leader.id, "policy": row.policy_revision,
            "revision": row.assessment_revision, "fingerprint": fingerprint,
            "generation": generation, "sequence": row.request_sequence,
            "expires": int(time.time()) + _READ_TTL_SECONDS, "nonce": uuid4().hex,
        })
        return result


github_coordination_service = GithubCoordinationService()
