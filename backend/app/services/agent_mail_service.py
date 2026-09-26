"""Agent Mail: durable team members, ephemeral sessions, messages, delivery context."""

import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import time
from uuid import uuid4
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentPaneBinding,
    AgentTeamPreset,
    AgentTeamSlot,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    MailAgentSession,
    MailPaneLifecycle,
    MailExternalActor,
    MailMessage,
    MailReceipt,
    MailTeamMember,
    MailWakeAttempt,
    TeamGithubScope,
)
from app.models.schemas import (
    MAIL_MESSAGE_KINDS,
    MAIL_REQUEST_KINDS,
    MailAgentRegisterRequest,
    MailInboxResponse,
    MailMemberResponse,
    MailMessageCreate,
    MailMessageResponse,
    MailSessionResponse,
    MailThreadResponse,
)
from app.services.agent_bridge.discovery import discover_agent_sessions
from app.utils import peer_process
from app.utils.repo_utils import derive_repo_identity

logger = logging.getLogger(__name__)

HEARTBEAT_TTL_SECONDS = 180
MCP_HEARTBEAT_TTL_SECONDS = 3600
OBSERVED_TTL_SECONDS = 300
STALE_REQUEST_MINUTES = 15
AUTO_NUDGE_COOLDOWN_SECONDS = 30
TMUX_ENTER_DELAY_SECONDS = 0.25
TMUX_WAKE_PROVIDERS = {"claude-code", "codex-cli", "copilot-cli", "opencode-cli", "pi-cli"}
INBOX_CHECK_PROMPT = (
    "Claude Deck Agent Mail: please call `deck_check_inbox(unread_only=False)` now, "
    "then answer any pending context requests or handoffs before continuing."
)


class MailAuthorityError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 403):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class MailDeliveryIntegrityError(RuntimeError):
    detail = "delivery_key_conflict"
    status_code = 409


class MailWakeError(ValueError):
    def __init__(self, code: str, *, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class AgentMailService:
    """Registry, messaging, and delivery-context behavior for Agent Mail."""

    def __init__(self) -> None:
        self._last_auto_nudge_at: dict[int, datetime] = {}

    def _repo_member_values(self, cwd: str) -> dict[str, str | int | None]:
        ident = derive_repo_identity(cwd)
        return {
            "identity_key": f"repo:{ident['repo_id']}",
            "repo_id": ident["repo_id"],
            "repo_path": ident["repo_root"],
            "repo_name": ident["repo_name"],
            "display_name": ident["repo_name"],
            "participant_kind": "repo",
            "team_preset_id": None,
            "team_slot_id": None,
            "role": None,
            "charter": None,
        }

    def _slot_identity_key(self, slot: AgentTeamSlot) -> str:
        created_at = slot.created_at.isoformat(timespec="microseconds")
        return f"slot:{slot.preset_id}:{slot.id}:{created_at}"

    def _slot_member_values(self, slot: AgentTeamSlot) -> dict[str, str | int | None]:
        return {
            "identity_key": self._slot_identity_key(slot),
            "repo_id": slot.repo_id,
            "repo_path": slot.repo_path,
            "repo_name": slot.repo_name,
            "display_name": slot.display_name,
            "participant_kind": "team_slot",
            "team_preset_id": slot.preset_id,
            "team_slot_id": slot.id,
            "role": slot.role,
            "charter": slot.charter,
        }

    async def _registration_member_values(
        self,
        db: AsyncSession,
        request: MailAgentRegisterRequest,
        team_preset_id: int | None,
        team_slot_id: int | None,
    ) -> dict[str, str | int | None]:
        if team_slot_id is not None:
            slot = await db.get(AgentTeamSlot, team_slot_id)
            if slot is not None and self._slot_matches_registration(slot, request):
                return self._slot_member_values(slot)
        values = self._repo_member_values(request.cwd)
        if team_preset_id is not None:
            values["team_preset_id"] = team_preset_id
        return values

    async def _get_or_create_member_by_values(
        self,
        db: AsyncSession,
        values: dict[str, str | int | None],
    ) -> MailTeamMember:
        result = await db.execute(
            select(MailTeamMember).where(MailTeamMember.identity_key == values["identity_key"])
        )
        member = result.scalar_one_or_none()
        if member is None:
            member = MailTeamMember(**values)
            try:
                async with db.begin_nested():
                    db.add(member)
                    await db.flush()
            except IntegrityError:
                result = await db.execute(
                    select(MailTeamMember).where(
                        MailTeamMember.identity_key == values["identity_key"]
                    )
                )
                member = result.scalar_one()
        else:
            member.repo_id = str(values["repo_id"])
            member.repo_path = str(values["repo_path"])
            member.repo_name = str(values["repo_name"])
            member.participant_kind = str(values["participant_kind"])
            member.team_preset_id = values["team_preset_id"]  # type: ignore[assignment]
            member.team_slot_id = values["team_slot_id"]  # type: ignore[assignment]
            if member.participant_kind == "team_slot":
                member.display_name = str(values["display_name"])
                member.role = values["role"]  # type: ignore[assignment]
                member.charter = values["charter"]  # type: ignore[assignment]
            member.updated_at = datetime.utcnow()
        return member

    async def _get_or_create_repo_member(self, db: AsyncSession, cwd: str) -> MailTeamMember:
        return await self._get_or_create_member_by_values(db, self._repo_member_values(cwd))

    async def get_or_create_repo_member(self, db: AsyncSession, cwd: str) -> MailTeamMember:
        return await self._get_or_create_repo_member(db, cwd)

    async def get_or_create_slot_member(
        self,
        db: AsyncSession,
        slot: AgentTeamSlot,
    ) -> MailTeamMember:
        return await self._get_or_create_member_by_values(db, self._slot_member_values(slot))

    async def register_session(
        self, db: AsyncSession, request: MailAgentRegisterRequest,
        *, pane: Optional[peer_process.PeerPane] = None,
        require_existing_token: bool = False, capability_token: str | None = None,
    ) -> tuple[MailTeamMember, MailAgentSession]:
        if pane is not None:
            await db.execute(sqlite_insert(MailPaneLifecycle).values(
                pane_pid=pane.pane_pid, pane_proc_start=pane.pane_proc_start,
            ).on_conflict_do_nothing())
            admission = await db.execute(update(MailPaneLifecycle).where(
                MailPaneLifecycle.pane_pid == pane.pane_pid,
                MailPaneLifecycle.pane_proc_start == pane.pane_proc_start,
                MailPaneLifecycle.retired_at.is_(None),
            ).values(retired_at=None))
            if admission.rowcount != 1:
                await db.rollback()
                raise MailAuthorityError("pane_retired", status_code=409)
        inferred_team_preset_id, inferred_team_slot_id = await self._infer_team_context_from_process(
            db,
            request,
        )
        if (
            request.team_preset_id is None
            and request.team_slot_id is None
            and (inferred_team_preset_id is not None or inferred_team_slot_id is not None)
        ):
            request = request.model_copy(
                update={
                    "team_preset_id": inferred_team_preset_id,
                    "team_slot_id": inferred_team_slot_id,
                }
            )
        has_team_context = request.team_preset_id is not None or request.team_slot_id is not None
        team_preset_id, team_slot_id = await self._resolve_team_context(db, request)
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == request.session_key)
        )
        session = result.scalar_one_or_none()
        if session is not None:
            guard = await db.execute(update(MailAgentSession).where(
                MailAgentSession.id == session.id, MailAgentSession.closed_at.is_(None),
            ).values(last_seen_at=datetime.utcnow()))
            if guard.rowcount != 1:
                await db.rollback()
                raise MailAuthorityError("session_token_closed", status_code=409)
            if require_existing_token:
                if not capability_token or not session.capability_token_hash:
                    await db.rollback()
                    raise MailAuthorityError("token_required_for_rebind", status_code=409)
                if not hmac.compare_digest(session.capability_token_hash, self.hash_capability_token(capability_token)):
                    await db.rollback()
                    raise MailAuthorityError("session_token_invalid", status_code=401)
                if session.team_slot_id is not None and (
                    pane is None or session.bound_pane_pid != pane.pane_pid
                    or session.bound_pane_proc_start != pane.pane_proc_start
                ):
                    await db.rollback()
                    raise MailAuthorityError("session_token_stale", status_code=401)
        is_new_session = session is None
        old_member_id = session.member_id if session is not None else None
        old_provider = session.provider if session is not None else None
        old_cwd = session.cwd if session is not None else None
        old_pid = session.pid if session is not None else None
        old_team_preset_id = session.team_preset_id if session is not None else None
        old_team_slot_id = session.team_slot_id if session is not None else None
        if not has_team_context and session is not None and session.team_slot_id is not None:
            existing_member = await db.get(MailTeamMember, session.member_id)
            if existing_member is not None and await self._session_team_context_matches_registration(
                db,
                session,
                existing_member,
                request,
            ):
                member = existing_member
                team_preset_id = session.team_preset_id
                team_slot_id = session.team_slot_id
            else:
                member = await self._get_or_create_member_by_values(
                    db,
                    await self._registration_member_values(db, request, team_preset_id, team_slot_id),
                )
        else:
            member = await self._get_or_create_member_by_values(
                db,
                await self._registration_member_values(db, request, team_preset_id, team_slot_id),
            )
        if session is None:
            session = MailAgentSession(
                member_id=member.id,
                source=request.source,
                session_key=request.session_key,
            )
            db.add(session)
        session.member_id = member.id
        session.provider = request.provider
        session.cwd = request.cwd
        session.pid = request.pid
        session.team_preset_id = team_preset_id
        session.team_slot_id = team_slot_id
        try:
            old_repo_id = derive_repo_identity(old_cwd or "")["repo_id"]
            new_repo_id = derive_repo_identity(request.cwd)["repo_id"]
        except Exception:
            old_repo_id = os.path.realpath(old_cwd or "")
            new_repo_id = os.path.realpath(request.cwd)
        registration_rebound = (
            old_member_id != member.id
            or old_provider != request.provider
            or old_repo_id != new_repo_id
            or old_pid != request.pid
            or old_team_preset_id != team_preset_id
            or old_team_slot_id != team_slot_id
        )
        if is_new_session:
            session.wake_enabled = (
                request.source == "mcp" and team_slot_id is not None
            )
        elif request.source != "mcp" or registration_rebound:
            session.wake_enabled = False
        if registration_rebound:
            session.bound_pane_pid = None
            session.bound_pane_proc_start = None
        session.mailbox_status = "connected"
        session.last_seen_at = datetime.utcnow()
        if pane is not None:
            session.bound_pane_pid = pane.pane_pid
            session.bound_pane_proc_start = pane.pane_proc_start
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise MailAuthorityError("session_key_conflict", status_code=409) from exc
        await db.refresh(member)
        await db.refresh(session)
        return member, session

    @staticmethod
    def hash_capability_token(token: str) -> str:
        """Hash a capability token for storage.

        Same construction as external_agent_mail_service._hash_token, so the
        two credential families are verified identically.
        """
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def ensure_capability_token(
        self, db: AsyncSession, session: MailAgentSession
    ) -> Optional[str]:
        """Mint this session's capability token, or None if it already has one.

        Called by the register_agent route, never by the hook registration path
        (a hook returns {} and has nowhere to put the plaintext).

        The token is minted once and NEVER rotated: the MCP shim re-registers
        before every tool call, so rotating here would invalidate the token the
        shim is holding on every single call. A row therefore keeps its hash for
        life -- including after the shim dies -- which locks nobody out, because
        a restarted shim generates a fresh session_key and so gets a fresh row.
        """
        if session.capability_token_hash is not None:
            return None
        token = secrets.token_urlsafe(32)
        session_id = session.id
        written = await db.execute(update(MailAgentSession).where(
            MailAgentSession.id == session.id,
            MailAgentSession.closed_at.is_(None),
            MailAgentSession.capability_token_hash.is_(None),
        ).values(capability_token_hash=self.hash_capability_token(token)))
        if written.rowcount != 1:
            await db.rollback()
            current = await db.get(MailAgentSession, session_id, populate_existing=True)
            if current is not None and current.closed_at is None and current.capability_token_hash:
                return None
            raise MailAuthorityError("session_token_closed", status_code=409)
        await db.commit()
        await db.refresh(session)
        return token

    async def resolve_pane_binding(
        self, db: AsyncSession, pane: "peer_process.PeerPane"
    ) -> Optional[AgentPaneBinding]:
        """Find the live binding row for this pane, pruning dead ones."""
        rows = (await db.execute(select(AgentPaneBinding))).scalars().all()
        match: Optional[AgentPaneBinding] = None
        pruned = False
        for row in rows:
            if row.pane_pid == pane.pane_pid and row.pane_proc_start == pane.pane_proc_start:
                match = row
                continue
            if peer_process.pane_is_alive(row.pane_pid, row.pane_proc_start) is False:
                await db.delete(row)
                pruned = True
        if pruned:
            await db.commit()
        return match

    async def peek_session_by_key(
        self, db: AsyncSession, session_key: str
    ) -> Optional[MailAgentSession]:
        """Look up a session by key without writing anything.

        The register route's rebind check needs to know whether a row already
        exists, and with what hash, before register_session can rewrite that row
        in place. Reusing register_session for the check would inspect a row
        already repointed at the caller.
        """
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == session_key)
        )
        return result.scalar_one_or_none()

    async def _infer_team_context_from_process(
        self,
        db: AsyncSession,
        request: MailAgentRegisterRequest,
    ) -> tuple[int | None, int | None]:
        if request.team_preset_id is not None or request.team_slot_id is not None or request.pid is None:
            return None, None
        try:
            repo_id = derive_repo_identity(request.cwd)["repo_id"]
        except Exception:
            repo_id = None
        now = datetime.utcnow()
        result = await db.execute(
            select(MailAgentSession)
            .where(
                MailAgentSession.source != "observed",
                MailAgentSession.provider == request.provider,
                MailAgentSession.team_slot_id.is_not(None),
                MailAgentSession.pid.is_not(None),
                MailAgentSession.last_seen_at >= now - timedelta(seconds=HEARTBEAT_TTL_SECONDS),
            )
            .order_by(MailAgentSession.last_seen_at.desc())
        )
        for session in result.scalars().all():
            if not session.pid or not self._pids_related(int(request.pid), int(session.pid)):
                continue
            if repo_id is not None:
                try:
                    if derive_repo_identity(session.cwd or "")["repo_id"] != repo_id:
                        continue
                except Exception:
                    continue
            if self._effective_status(session, now) == "offline":
                continue
            return session.team_preset_id, session.team_slot_id
        return None, None

    async def _session_team_context_matches_registration(
        self,
        db: AsyncSession,
        session: MailAgentSession,
        member: MailTeamMember,
        request: MailAgentRegisterRequest,
    ) -> bool:
        if session.team_slot_id is None or member.participant_kind != "team_slot":
            return False
        if member.team_slot_id != session.team_slot_id:
            return False
        slot = await db.get(AgentTeamSlot, session.team_slot_id)
        if slot is None or slot.provider != request.provider:
            return False
        try:
            return derive_repo_identity(request.cwd)["repo_id"] == slot.repo_id
        except Exception:
            return False

    async def _resolve_team_context(
        self,
        db: AsyncSession,
        request: MailAgentRegisterRequest,
    ) -> tuple[int | None, int | None]:
        if request.team_slot_id is not None:
            slot = await db.get(AgentTeamSlot, request.team_slot_id)
            if slot is not None and (
                request.team_preset_id is None or request.team_preset_id == slot.preset_id
            ):
                if self._slot_matches_registration(slot, request):
                    return slot.preset_id, slot.id
            return None, None
        if request.team_preset_id is not None:
            preset = await db.get(AgentTeamPreset, request.team_preset_id)
            if preset is not None:
                return preset.id, None
        return None, None

    def _slot_matches_registration(
        self,
        slot: AgentTeamSlot,
        request: MailAgentRegisterRequest,
    ) -> bool:
        if request.provider != slot.provider:
            return False
        try:
            return derive_repo_identity(request.cwd)["repo_id"] == slot.repo_id
        except Exception:
            return False

    @staticmethod
    def _same_repo(left_cwd: str | None, right_cwd: str | None, repo_id: str) -> bool:
        if not left_cwd or not right_cwd:
            return False
        try:
            return (
                derive_repo_identity(left_cwd)["repo_id"] == repo_id
                and derive_repo_identity(right_cwd)["repo_id"] == repo_id
            )
        except Exception:
            return os.path.realpath(left_cwd) == os.path.realpath(right_cwd)

    async def heartbeat_session(
        self, db: AsyncSession, session_key: str, activity: Optional[str] = None
    ) -> Optional[MailAgentSession]:
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == session_key)
        )
        session = result.scalar_one_or_none()
        if session is None or session.closed_at is not None:
            return None
        values = {
            "last_seen_at": datetime.utcnow(),
            "mailbox_status": "connected" if session.source != "observed" else "observed",
        }
        if activity:
            values["activity"] = activity[:200]
        await db.execute(update(MailAgentSession).where(
            MailAgentSession.id == session.id, MailAgentSession.closed_at.is_(None)
        ).values(**values))
        await db.commit()
        return session

    async def mark_session_offline(self, db: AsyncSession, session_key: str) -> None:
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == session_key)
        )
        session = result.scalar_one_or_none()
        if session is not None:
            session.mailbox_status = "offline"
            await db.commit()

    async def heartbeat_member_mcp_session(self, db: AsyncSession, member_id: int) -> None:
        """Refresh the newest MCP session for a member when an MCP tool calls in."""
        result = await db.execute(
            select(MailAgentSession)
            .where(
                MailAgentSession.member_id == member_id,
                MailAgentSession.source == "mcp",
                MailAgentSession.closed_at.is_(None),
            )
            .order_by(MailAgentSession.last_seen_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session is None:
            return
        await db.execute(update(MailAgentSession).where(
            MailAgentSession.id == session.id, MailAgentSession.closed_at.is_(None)
        ).values(last_seen_at=datetime.utcnow(), mailbox_status="connected"))
        await db.commit()

    async def sync_observed_sessions(
        self, db: AsyncSession, *, strict: bool = False
    ) -> None:
        """Upsert Agent Bridge tmux discoveries as observed sessions."""
        try:
            discovered = discover_agent_sessions()
        except Exception as exc:
            logger.warning("agent bridge discovery failed: %s", exc)
            if strict:
                raise
            return
        active_observed_keys: set[str] = set()
        affected_member_ids: set[int] = set()
        for info in discovered:
            pane_id = info.get("pane_id")
            cwd = info.get("cwd")
            if not pane_id or not cwd:
                continue
            session_key = f"tmux:{pane_id}"
            active_observed_keys.add(session_key)
            result = await db.execute(
                select(MailAgentSession).where(MailAgentSession.session_key == session_key)
            )
            session = result.scalar_one_or_none()
            member = await self._member_for_existing_observed_session(db, session, info)
            if member is None:
                member = await self._member_for_advertised_slot(db, info)
            if member is None:
                member = await self._member_for_observed_session(db, info)
            if session is None:
                session = MailAgentSession(
                    member_id=member.id,
                    source="observed",
                    session_key=session_key,
                )
                db.add(session)
            elif session.member_id != member.id:
                affected_member_ids.add(session.member_id)
            session.member_id = member.id
            session.provider = info.get("provider", "unknown")
            session.cwd = cwd
            session.tmux_target = info.get("tmux_target")
            session.pane_id = pane_id
            try:
                session.pid = int(info.get("pid") or 0) or None
            except (TypeError, ValueError):
                session.pid = None
            session.team_preset_id = member.team_preset_id
            session.team_slot_id = member.team_slot_id
            session.wake_enabled = False
            session.mailbox_status = "observed"
            session.last_seen_at = datetime.utcnow()
        await self._remove_stale_observed_sessions(db, active_observed_keys)
        for member_id in affected_member_ids:
            await self._remove_empty_observed_member(db, member_id)
        await db.commit()

    async def _member_for_advertised_slot(
        self,
        db: AsyncSession,
        info: dict,
    ) -> MailTeamMember | None:
        """Bind a pane to the slot its own tmux environment advertises."""
        slot_id = info.get("team_slot_id")
        if not isinstance(slot_id, int):
            return None
        slot = await db.get(AgentTeamSlot, slot_id)
        if slot is None or slot.provider != str(info.get("provider") or "unknown"):
            return None
        preset_id = info.get("team_preset_id")
        if isinstance(preset_id, int) and preset_id != slot.preset_id:
            return None
        cwd = str(info.get("cwd") or "")
        if not cwd:
            return None
        try:
            if derive_repo_identity(cwd)["repo_id"] != slot.repo_id:
                return None
        except Exception:
            return None
        return await self.get_or_create_slot_member(db, slot)

    async def _member_for_observed_session(
        self,
        db: AsyncSession,
        info: dict,
    ) -> MailTeamMember:
        cwd = str(info.get("cwd") or "")
        provider = str(info.get("provider") or "unknown")
        pid = None
        try:
            pid = int(info.get("pid") or 0) or None
        except (TypeError, ValueError):
            pid = None

        if pid is not None:
            now = datetime.utcnow()
            result = await db.execute(
                select(MailAgentSession)
                .where(
                    MailAgentSession.source != "observed",
                    MailAgentSession.provider == provider,
                    MailAgentSession.pid.is_not(None),
                    MailAgentSession.last_seen_at >= now - timedelta(seconds=HEARTBEAT_TTL_SECONDS),
                )
                .order_by(MailAgentSession.last_seen_at.desc())
            )
            for registered_session in result.scalars().all():
                if not registered_session.pid or not self._pids_related(pid, int(registered_session.pid)):
                    continue
                if registered_session is not None and self._registered_session_matches_observed(
                    registered_session,
                    info,
                    now,
                ):
                    member = await db.get(MailTeamMember, registered_session.member_id)
                    if member is not None:
                        return member

        return await self._get_or_create_repo_member(db, cwd)

    def _pids_related(self, left_pid: int, right_pid: int) -> bool:
        return (
            left_pid == right_pid
            or self._pid_is_descendant(left_pid, right_pid)
            or self._pid_is_descendant(right_pid, left_pid)
        )

    def _pid_is_descendant(self, child_pid: int, ancestor_pid: int) -> bool:
        current = child_pid
        visited: set[int] = set()
        for _ in range(8):
            if current == ancestor_pid:
                return True
            if current in visited:
                return False
            visited.add(current)
            try:
                result = subprocess.run(
                    ["ps", "-o", "ppid=", "-p", str(current)],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            except (OSError, subprocess.SubprocessError):
                return False
            if result.returncode != 0:
                return False
            try:
                current = int(result.stdout.strip() or "0")
            except ValueError:
                return False
            if current <= 1:
                return False
        return False

    async def _member_for_existing_observed_session(
        self,
        db: AsyncSession,
        session: MailAgentSession | None,
        info: dict,
    ) -> MailTeamMember | None:
        if session is None or session.source != "observed" or session.team_slot_id is None:
            return None
        if session.provider != str(info.get("provider") or "unknown"):
            return None
        if session.pane_id and session.pane_id != info.get("pane_id"):
            return None
        if session.tmux_target and session.tmux_target != info.get("tmux_target"):
            return None
        try:
            discovered_pid = int(info.get("pid") or 0) or None
        except (TypeError, ValueError):
            discovered_pid = None
        if session.pid is not None and discovered_pid is not None and session.pid != discovered_pid:
            return None
        cwd = str(info.get("cwd") or "")
        if not session.cwd or not cwd:
            return None
        try:
            if derive_repo_identity(session.cwd)["repo_id"] != derive_repo_identity(cwd)["repo_id"]:
                return None
        except Exception:
            if os.path.realpath(session.cwd) != os.path.realpath(cwd):
                return None
        slot = await db.get(AgentTeamSlot, session.team_slot_id)
        if slot is None or slot.provider != session.provider:
            return None
        member = await db.get(MailTeamMember, session.member_id)
        if member is None or member.team_slot_id != slot.id:
            return None
        return member

    def _registered_session_matches_observed(
        self,
        session: MailAgentSession,
        info: dict,
        now: datetime,
    ) -> bool:
        cwd = str(info.get("cwd") or "")
        if not session.cwd or not cwd:
            return False
        try:
            if derive_repo_identity(session.cwd)["repo_id"] != derive_repo_identity(cwd)["repo_id"]:
                return False
        except Exception:
            if os.path.realpath(session.cwd) != os.path.realpath(cwd):
                return False
        if session.last_seen_at < now - timedelta(seconds=HEARTBEAT_TTL_SECONDS):
            return False
        return self._effective_status(session, now) != "offline"

    async def _remove_stale_observed_sessions(
        self, db: AsyncSession, active_observed_keys: set[str]
    ) -> None:
        """Drop Agent Bridge-only sessions that are no longer discoverable."""
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.source == "observed")
        )
        affected_member_ids: set[int] = set()
        for session in result.scalars().all():
            if session.session_key in active_observed_keys:
                continue
            # Absence from one discovery pass is not evidence of death.
            if self._pid_is_running(session.pid):
                continue
            affected_member_ids.add(session.member_id)
            await db.delete(session)

        if not affected_member_ids:
            return

        await db.flush()
        for member_id in affected_member_ids:
            await self._remove_empty_observed_member(db, member_id)

    async def _remove_empty_observed_member(self, db: AsyncSession, member_id: int) -> None:
        """Remove auto-observed members only when they have no durable user/mail state."""
        member = await db.get(MailTeamMember, member_id)
        if member is None:
            return
        if member.participant_kind != "repo":
            return
        if member.role or member.charter or member.display_name != member.repo_name:
            return

        session_count = (
            await db.execute(
                select(func.count())
                .select_from(MailAgentSession)
                .where(MailAgentSession.member_id == member_id)
            )
        ).scalar_one()
        if session_count:
            return

        message_count = (
            await db.execute(
                select(func.count())
                .select_from(MailMessage)
                .where(
                    or_(
                        MailMessage.sender_member_id == member_id,
                        MailMessage.recipient_member_id == member_id,
                    )
                )
            )
        ).scalar_one()
        receipt_count = (
            await db.execute(
                select(func.count())
                .select_from(MailReceipt)
                .where(MailReceipt.member_id == member_id)
            )
        ).scalar_one()
        if message_count or receipt_count:
            return

        await db.delete(member)

    def _pid_is_running(self, pid: Optional[int]) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False

    def _effective_status(self, session: MailAgentSession, now: datetime) -> str:
        if session.closed_at is not None:
            return "offline"
        if session.source == "mcp" and session.pid:
            if not self._pid_is_running(session.pid):
                return "offline"
            if session.mailbox_status == "offline":
                return "connected"
        if session.mailbox_status == "offline":
            return "offline"
        if session.source == "observed":
            ttl = OBSERVED_TTL_SECONDS
        elif session.source == "mcp":
            ttl = MCP_HEARTBEAT_TTL_SECONDS
        else:
            ttl = HEARTBEAT_TTL_SECONDS
        if session.last_seen_at < now - timedelta(seconds=ttl):
            # Observed rows carry a pid too. Return their own status so a live
            # observed pane remains nudgeable; explicit offline returned above.
            if session.source == "observed" and session.pid:
                if self._pid_is_running(session.pid):
                    return session.mailbox_status
            if session.source == "mcp" and session.pid:
                return "connected"
            return "offline"
        return session.mailbox_status

    def _session_response(
        self,
        session: MailAgentSession,
        now: datetime,
        team_context: dict[int, dict[str, str | int | None]] | None = None,
    ) -> MailSessionResponse:
        context = (team_context or {}).get(session.id, {})
        return MailSessionResponse(
            id=session.id,
            provider=session.provider,
            source=session.source,
            session_key=session.session_key,
            cwd=session.cwd,
            tmux_target=session.tmux_target,
            team_preset_id=session.team_preset_id,
            team_preset_name=context.get("team_preset_name"),
            team_slot_id=session.team_slot_id,
            team_slot_name=context.get("team_slot_name"),
            mailbox_status=self._effective_status(session, now),
            activity=session.activity,
            last_seen_at=session.last_seen_at,
        )

    async def _team_context_by_session(
        self,
        db: AsyncSession,
        sessions: list[MailAgentSession],
    ) -> dict[int, dict[str, str | int | None]]:
        slot_ids = {session.team_slot_id for session in sessions if session.team_slot_id is not None}
        preset_ids = {
            session.team_preset_id for session in sessions if session.team_preset_id is not None
        }
        slots: dict[int, AgentTeamSlot] = {}
        if slot_ids:
            slots = {
                slot.id: slot
                for slot in (
                    await db.execute(select(AgentTeamSlot).where(AgentTeamSlot.id.in_(slot_ids)))
                ).scalars().all()
            }
            preset_ids.update(slot.preset_id for slot in slots.values())
        presets: dict[int, AgentTeamPreset] = {}
        if preset_ids:
            presets = {
                preset.id: preset
                for preset in (
                    await db.execute(select(AgentTeamPreset).where(AgentTeamPreset.id.in_(preset_ids)))
                ).scalars().all()
            }
        context: dict[int, dict[str, str | int | None]] = {}
        for session in sessions:
            slot = slots.get(session.team_slot_id) if session.team_slot_id is not None else None
            preset_id = slot.preset_id if slot is not None else session.team_preset_id
            preset = presets.get(preset_id) if preset_id is not None else None
            context[session.id] = {
                "team_preset_name": preset.name if preset is not None else None,
                "team_slot_name": slot.display_name if slot is not None else None,
            }
        return context

    async def _team_context_by_member(
        self,
        db: AsyncSession,
        members: list[MailTeamMember],
    ) -> dict[int, dict[str, str | int | None]]:
        slot_ids = {member.team_slot_id for member in members if member.team_slot_id is not None}
        preset_ids = {
            member.team_preset_id for member in members if member.team_preset_id is not None
        }
        slots: dict[int, AgentTeamSlot] = {}
        if slot_ids:
            slots = {
                slot.id: slot
                for slot in (
                    await db.execute(select(AgentTeamSlot).where(AgentTeamSlot.id.in_(slot_ids)))
                ).scalars().all()
            }
            preset_ids.update(slot.preset_id for slot in slots.values())
        presets: dict[int, AgentTeamPreset] = {}
        if preset_ids:
            presets = {
                preset.id: preset
                for preset in (
                    await db.execute(select(AgentTeamPreset).where(AgentTeamPreset.id.in_(preset_ids)))
                ).scalars().all()
            }
        context: dict[int, dict[str, str | int | None]] = {}
        for member in members:
            slot = slots.get(member.team_slot_id) if member.team_slot_id is not None else None
            preset_id = slot.preset_id if slot is not None else member.team_preset_id
            preset = presets.get(preset_id) if preset_id is not None else None
            context[member.id] = {
                "team_preset_name": preset.name if preset is not None else None,
                "team_slot_name": slot.display_name if slot is not None else None,
            }
        return context

    async def list_team(self, db: AsyncSession) -> List[MailMemberResponse]:
        now = datetime.utcnow()
        members = (await db.execute(select(MailTeamMember))).scalars().all()
        sessions = (await db.execute(select(MailAgentSession))).scalars().all()
        team_context = await self._team_context_by_session(db, sessions)
        member_team_context = await self._team_context_by_member(db, members)
        by_member: dict[int, list[MailAgentSession]] = {}
        for session in sessions:
            by_member.setdefault(session.member_id, []).append(session)

        responses: List[MailMemberResponse] = []
        for member in members:
            member_context = member_team_context.get(member.id, {})
            session_responses = [
                self._session_response(session, now, team_context)
                for session in by_member.get(member.id, [])
            ]
            statuses = {session.mailbox_status for session in session_responses}
            if "connected" in statuses:
                status = "connected"
            elif "observed" in statuses:
                status = "observed"
            else:
                status = "offline"
            unread, pending, unseen_pending, stale_pending = await self.delivery_counts_for_member(
                db,
                member.id,
            )
            wake_methods = []
            try:
                await self._nudge_session_for_member(db, member.id, now)
            except MailWakeError:
                pass
            else:
                wake_methods.append("tmux")
            if status == "offline":
                wake_state = "offline"
            elif wake_methods:
                wake_state = "wakeable"
            else:
                wake_state = "delivered_waiting"
            responses.append(
                MailMemberResponse(
                    id=member.id,
                    identity_key=member.identity_key,
                    repo_id=member.repo_id,
                    repo_path=member.repo_path,
                    repo_name=member.repo_name,
                    display_name=member.display_name,
                    participant_kind=member.participant_kind,
                    team_preset_id=member.team_preset_id,
                    team_preset_name=member_context.get("team_preset_name"),
                    team_slot_id=member.team_slot_id,
                    team_slot_name=member_context.get("team_slot_name"),
                    role=member.role,
                    charter=member.charter,
                    status=status,
                    unread_count=unread,
                    pending_count=pending,
                    unseen_pending_count=unseen_pending,
                    stale_pending_count=stale_pending,
                    can_nudge=bool(wake_methods),
                    wake_methods=wake_methods,
                    wake_state=wake_state,
                    last_inbox_checked_at=member.last_inbox_checked_at,
                    sessions=session_responses,
                )
            )
        responses.sort(key=lambda member: (member.status != "connected", member.display_name.lower()))
        return responses

    async def send_message(
        self,
        db: AsyncSession,
        request: MailMessageCreate,
        *,
        auto_nudge: bool = True,
        bypass_nudge_cooldown: bool = False,
        nudge_prompt: str = INBOX_CHECK_PROMPT,
        sender_actor_id: Optional[int] = None,
        authenticated_sender_member_id: Optional[int] = None,
        delivery_key: Optional[str] = None,
        operator_authorized: bool = False,
        commit: bool = True,
    ) -> MailMessageResponse:
        if request.decision is not None:
            raise MailAuthorityError("use_decisions_route", status_code=409)
        return await self._send_message(
            db,
            request,
            auto_nudge=auto_nudge,
            bypass_nudge_cooldown=bypass_nudge_cooldown,
            nudge_prompt=nudge_prompt,
            sender_actor_id=sender_actor_id,
            authenticated_sender_member_id=authenticated_sender_member_id,
            delivery_key=delivery_key,
            operator_authorized=operator_authorized,
            commit=commit,
        )

    async def send_authoritative_decision(
        self,
        db: AsyncSession,
        request: MailMessageCreate,
        *,
        authenticated_sender_member_id: int,
        approval_round: int,
        delivery_key: str,
        auto_nudge: bool = False,
    ) -> MailMessageResponse:
        if request.decision not in {"approved", "rejected"}:
            raise MailAuthorityError("decision_required", status_code=400)
        if request.sender_member_id != authenticated_sender_member_id:
            raise MailAuthorityError("conflicting_sender_member_id", status_code=403)
        return await self._send_message(
            db,
            request,
            auto_nudge=auto_nudge,
            sender_actor_id=None,
            authenticated_sender_member_id=authenticated_sender_member_id,
            delivery_key=delivery_key,
            authoritative_approval_round=approval_round,
            commit=True,
        )

    async def _send_message(
        self,
        db: AsyncSession,
        request: MailMessageCreate,
        *,
        auto_nudge: bool = True,
        bypass_nudge_cooldown: bool = False,
        nudge_prompt: str = INBOX_CHECK_PROMPT,
        sender_actor_id: Optional[int] = None,
        authenticated_sender_member_id: Optional[int] = None,
        delivery_key: Optional[str] = None,
        authoritative_approval_round: int | None = None,
        operator_authorized: bool = False,
        commit: bool = True,
    ) -> MailMessageResponse:
        if delivery_key is not None and request.kind == "broadcast":
            existing = (
                await db.execute(
                    select(MailMessage).where(MailMessage.delivery_key == delivery_key)
                )
            ).scalar_one_or_none()
            if existing is not None:
                if not await self._same_delivery(
                    db,
                    existing,
                    request,
                    sender_actor_id=sender_actor_id,
                    operator_authorized=operator_authorized,
                ):
                    raise MailDeliveryIntegrityError(
                        f"delivery key {delivery_key!r} conflicts with different mail"
                    )
                return await self._message_response(db, existing, for_member_id=None)
        created = True
        if delivery_key is None:
            message, recipients = await self._create_message_row(
                db,
                request,
                sender_actor_id=sender_actor_id,
                authenticated_sender_member_id=authenticated_sender_member_id,
                authoritative_approval_round=authoritative_approval_round,
                operator_authorized=operator_authorized,
            )
        else:
            try:
                async with db.begin_nested():
                    message, recipients = await self._create_message_row(
                        db,
                        request,
                        sender_actor_id=sender_actor_id,
                        authenticated_sender_member_id=authenticated_sender_member_id,
                        delivery_key=delivery_key,
                        authoritative_approval_round=authoritative_approval_round,
                        operator_authorized=operator_authorized,
                    )
            except IntegrityError:
                created = False
                message = (
                    await db.execute(
                        select(MailMessage).where(
                            MailMessage.delivery_key == delivery_key
                        )
                    )
                ).scalar_one_or_none()
                if message is None or not await self._same_delivery(
                    db,
                    message,
                    request,
                    sender_actor_id=sender_actor_id,
                    operator_authorized=operator_authorized,
                ):
                    raise MailDeliveryIntegrityError(
                        f"delivery key {delivery_key!r} conflicts with different mail"
                    )
                recipients = await self.recipient_ids_for_message(db, message.id)
        if commit:
            if created:
                await db.commit()
                await db.refresh(message)
            if created and auto_nudge:
                await self.auto_nudge_members(
                    db,
                    recipients,
                    bypass_cooldown=bypass_nudge_cooldown,
                    nudge_prompt=nudge_prompt,
                )
        return await self._message_response(db, message, for_member_id=None)

    @staticmethod
    def _canonical_delivery_bytes(payload: dict) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    async def _same_delivery(
        self,
        db: AsyncSession,
        message: MailMessage,
        request: MailMessageCreate,
        *,
        sender_actor_id: int | None,
        operator_authorized: bool,
    ) -> bool:
        if request.recipient_member_id is not None or request.thread_root_id is not None:
            audience_type, audience_id = await self._message_audience(db, request)
        else:
            audience_type = getattr(request, "audience_type", None)
            audience_id = getattr(request, "audience_id", None)
            if audience_type is None or audience_id is None:
                return False
            audience_id = str(audience_id)
            if audience_type == "operator_global" and (
                audience_id != "global" or not operator_authorized
            ):
                return False
        expected = {
            "body_markdown": request.body_markdown,
            "decision": request.decision,
            "kind": request.kind,
            "payload": request.payload or None,
            "recipient_member_id": request.recipient_member_id,
            "sender_actor_id": sender_actor_id,
            "sender_member_id": request.sender_member_id,
            "subject": request.subject,
            "thread_root_id": request.thread_root_id,
            "audience_type": audience_type,
            "audience_id": audience_id,
        }
        actual = {
            "body_markdown": message.body_markdown,
            "decision": message.decision,
            "kind": message.kind,
            "payload": message.payload or None,
            "recipient_member_id": message.recipient_member_id,
            "sender_actor_id": message.sender_actor_id,
            "sender_member_id": message.sender_member_id,
            "subject": message.subject,
            "thread_root_id": message.thread_root_id,
            "audience_type": message.audience_type,
            "audience_id": message.audience_id,
        }
        if (
            message.audience_type is None
            and message.audience_id is None
            and (message.recipient_member_id is not None or message.thread_root_id is not None)
        ):
            actual["audience_type"] = audience_type
            actual["audience_id"] = audience_id
        return self._canonical_delivery_bytes(actual) == self._canonical_delivery_bytes(
            expected
        )

    async def _message_audience(
        self,
        db: AsyncSession,
        request: MailMessageCreate,
        *,
        operator_authorized: bool = False,
    ) -> tuple[str, str]:
        audience_type = getattr(request, "audience_type", None)
        audience_id = getattr(request, "audience_id", None)
        if request.recipient_member_id is not None or request.thread_root_id is not None:
            if audience_type is not None or audience_id is not None:
                if audience_type != "member" or audience_id is None:
                    raise ValueError("direct and threaded messages use member audience")
            if request.recipient_member_id is not None:
                member_id = request.recipient_member_id
                resolved_audience_id = str(member_id)
                if await db.get(MailTeamMember, member_id) is None:
                    raise ValueError("recipient_member_id must reference an existing member")
            else:
                root = await db.get(MailMessage, request.thread_root_id)
                if root is None:
                    raise ValueError("thread_root_id must reference an existing message")
                participants = {
                    member_id
                    for member_id in (root.sender_member_id, root.recipient_member_id)
                    if member_id is not None and member_id != request.sender_member_id
                }
                resolved_audience_id = (
                    str(next(iter(participants)))
                    if len(participants) == 1
                    else f"thread:{root.id}"
                )
            if audience_type == "member" and audience_id != resolved_audience_id:
                raise ValueError("member audience_id must match the direct recipient or thread")
            return "member", resolved_audience_id

        if audience_type is None or audience_id is None or not str(audience_id).strip():
            raise ValueError("messages without a recipient or thread require an explicit audience")
        audience_id = str(audience_id)
        if audience_type == "member":
            raise ValueError("member audience requires a direct recipient or thread")
        elif audience_type == "team_preset":
            preset_id = self._positive_audience_integer(audience_id)
            if await db.get(AgentTeamPreset, preset_id) is None:
                raise ValueError("team_preset audience does not exist")
        elif audience_type == "repository":
            if not (await db.execute(
                select(MailTeamMember.id).where(MailTeamMember.repo_id == audience_id).limit(1)
            )).scalar_one_or_none():
                raise ValueError("repository audience does not exist")
        elif audience_type == "work_item":
            item_id = self._positive_audience_integer(audience_id)
            if await db.get(GithubWorkItem, item_id) is None:
                raise ValueError("work_item audience does not exist")
        elif audience_type == "operator_global":
            if audience_id != "global":
                raise ValueError("operator_global audience_id must be 'global'")
            if not operator_authorized:
                raise MailAuthorityError("operator_authorization_required")
        else:
            raise ValueError("invalid audience_type")
        return audience_type, audience_id

    @staticmethod
    def _positive_audience_integer(value: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError("audience_id must be a positive integer") from None
        if number <= 0 or str(number) != value:
            raise ValueError("audience_id must be a positive integer")
        return number

    async def _broadcast_recipient_ids(
        self,
        db: AsyncSession,
        audience_type: str,
        audience_id: str,
        sender_member_id: int | None,
    ) -> set[int]:
        if audience_type == "member":
            recipients = {int(audience_id)}
        elif audience_type == "team_preset":
            result = await db.execute(
                select(MailTeamMember.id).where(
                    MailTeamMember.team_preset_id == int(audience_id)
                )
            )
            recipients = set(result.scalars().all())
        elif audience_type == "repository":
            result = await db.execute(
                select(MailTeamMember.id).where(MailTeamMember.repo_id == audience_id)
            )
            recipients = set(result.scalars().all())
        elif audience_type == "work_item":
            item = await db.get(GithubWorkItem, int(audience_id))
            scope = await db.get(TeamGithubScope, item.scope_id) if item else None
            if scope is None:
                raise ValueError("work_item audience has no valid GitHub scope")
            configured_repo_ids = set(
                (
                    await db.execute(
                        select(AgentTeamSlot.repo_id).where(
                            AgentTeamSlot.preset_id == scope.preset_id,
                            AgentTeamSlot.repo_path == scope.repo_path,
                        )
                    )
                ).scalars().all()
            )
            if not configured_repo_ids:
                return set()
            if len(configured_repo_ids) != 1:
                raise ValueError("work_item audience has no unambiguous configured repository")
            result = await db.execute(
                select(MailTeamMember.id).where(
                    MailTeamMember.team_preset_id == scope.preset_id,
                    MailTeamMember.repo_id == configured_repo_ids.pop(),
                )
            )
            recipients = set(result.scalars().all())
        else:
            recipients = {
                member.id
                for member in (await db.execute(select(MailTeamMember))).scalars().all()
            }
        if sender_member_id is not None:
            recipients.discard(sender_member_id)
        return recipients

    async def _create_message_row(
        self,
        db: AsyncSession,
        request: MailMessageCreate,
        *,
        sender_actor_id: Optional[int] = None,
        authenticated_sender_member_id: Optional[int] = None,
        delivery_key: Optional[str] = None,
        authoritative_approval_round: int | None = None,
        operator_authorized: bool = False,
    ) -> tuple[MailMessage, set[int]]:
        if request.kind not in MAIL_MESSAGE_KINDS:
            raise ValueError(f"Invalid message kind: {request.kind}")
        if request.sender_member_id is not None and sender_actor_id is not None:
            raise ValueError("messages cannot have both sender_member_id and sender_actor_id")
        audience_type, audience_id = await self._message_audience(
            db, request, operator_authorized=operator_authorized
        )
        is_broadcast = request.recipient_member_id is None and request.thread_root_id is None
        if request.kind == "broadcast" and not is_broadcast:
            raise ValueError("broadcast messages cannot have a recipient or thread")
        if is_broadcast and request.kind != "broadcast":
            raise ValueError("messages without a recipient or thread must be broadcasts")
        recipients = (
            await self._broadcast_recipient_ids(
                db, audience_type, audience_id, request.sender_member_id
            )
            if is_broadcast
            else set()
        )
        if request.kind == "answer" and request.thread_root_id is None:
            raise ValueError("answer messages require thread_root_id")
        if request.kind == "answer":
            root = await db.get(MailMessage, request.thread_root_id)
            if root is None:
                raise ValueError("answer messages require an existing thread root")
            if root.kind != "context_request":
                raise ValueError("answer messages can only resolve context requests")
            if root.recipient_member_id != request.sender_member_id:
                raise ValueError("only the context request recipient can answer it")
            if root.request_status == "superseded":
                raise ValueError("superseded context requests cannot be answered")
        else:
            root = None
        if request.kind in MAIL_REQUEST_KINDS and request.recipient_member_id is None:
            raise ValueError(f"{request.kind} requires recipient_member_id")

        payload = dict(request.payload or {})
        linked_item = None
        if request.kind == "context_request" and "work_item_id" in payload:
            linked_item = await self._validate_linked_context_request(
                db,
                request,
                payload,
                authenticated_sender_member_id=authenticated_sender_member_id,
            )
            payload["approval_round"] = linked_item.approval_round_count
        if request.decision is not None:
            if authoritative_approval_round is None:
                linked_item = await self._validate_decision_message(
                    db,
                    request,
                    root,
                    authenticated_sender_member_id=authenticated_sender_member_id,
                )

        message = MailMessage(
            thread_root_id=request.thread_root_id,
            kind=request.kind,
            sender_member_id=request.sender_member_id,
            sender_actor_id=sender_actor_id,
            recipient_member_id=request.recipient_member_id,
            subject=request.subject,
            body_markdown=request.body_markdown,
            payload=payload or None,
            request_status="pending" if request.kind in MAIL_REQUEST_KINDS else None,
            approval_round=(
                authoritative_approval_round
                if authoritative_approval_round is not None
                else linked_item.approval_round_count
                if linked_item is not None
                else None
            ),
            decision=request.decision,
            delivery_key=delivery_key,
            audience_type=audience_type,
            audience_id=audience_id,
        )
        db.add(message)
        await db.flush()

        if request.recipient_member_id is not None:
            recipients.add(request.recipient_member_id)
        elif request.thread_root_id is not None:
            root = await db.get(MailMessage, request.thread_root_id)
            if root is not None:
                for member_id in (root.sender_member_id, root.recipient_member_id):
                    if member_id is not None and member_id != request.sender_member_id:
                        recipients.add(member_id)

        for member_id in recipients:
            db.add(MailReceipt(message_id=message.id, member_id=member_id))

        if request.kind == "answer":
            root = await db.get(MailMessage, request.thread_root_id)
            if root is not None and root.request_status == "pending":
                root.request_status = "answered"

        return message, recipients

    async def _slot_member(
        self, db: AsyncSession, slot_id: int | None
    ) -> MailTeamMember | None:
        if slot_id is None:
            return None
        return (
            await db.execute(
                select(MailTeamMember)
                .where(MailTeamMember.team_slot_id == slot_id)
                .order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _dispatch_participants(
        self, db: AsyncSession, item: GithubWorkItem
    ) -> tuple[MailTeamMember | None, MailTeamMember | None]:
        scope = await db.get(TeamGithubScope, item.scope_id)
        if scope is None:
            return None, None
        leader_slot = (
            await db.execute(
                select(AgentTeamSlot)
                .where(
                    AgentTeamSlot.preset_id == scope.preset_id,
                    AgentTeamSlot.enabled.is_(True),
                )
                .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        return (
            await self._slot_member(db, item.owner_slot_id),
            await self._slot_member(db, leader_slot.id if leader_slot is not None else None),
        )

    async def _validate_linked_context_request(
        self,
        db: AsyncSession,
        request: MailMessageCreate,
        payload: dict,
        *,
        authenticated_sender_member_id: int | None,
    ) -> GithubWorkItem:
        if authenticated_sender_member_id is None:
            raise MailAuthorityError("session_token_required", status_code=401)
        if request.sender_member_id != authenticated_sender_member_id:
            raise MailAuthorityError("sender_not_token_holder")
        item = await db.get(GithubWorkItem, payload.get("work_item_id"))
        if item is None:
            raise MailAuthorityError("work_item_not_found", status_code=404)
        owner, leader = await self._dispatch_participants(db, item)
        if owner is None or owner.id != authenticated_sender_member_id:
            raise MailAuthorityError("not_item_owner")
        if leader is None or request.recipient_member_id != leader.id:
            raise MailAuthorityError("not_designated_leader")
        if item.dispatch_nonce is None or payload.get("dispatch_nonce") != item.dispatch_nonce:
            raise MailAuthorityError("stale_nonce", status_code=409)
        supplied_round = payload.get("approval_round")
        if supplied_round is not None and supplied_round != item.approval_round_count:
            raise MailAuthorityError("approval_round_mismatch")
        if item.approval_round_count < 1:
            raise MailAuthorityError("approval_round_not_open", status_code=409)
        return item

    async def _validate_decision_message(
        self,
        db: AsyncSession,
        request: MailMessageCreate,
        root: MailMessage | None,
        *,
        authenticated_sender_member_id: int | None,
    ) -> GithubWorkItem:
        if request.kind != "answer" or root is None:
            raise MailAuthorityError("decision_requires_answer", status_code=400)
        if authenticated_sender_member_id is None:
            raise MailAuthorityError("session_token_required", status_code=401)
        if request.sender_member_id != authenticated_sender_member_id:
            raise MailAuthorityError("sender_not_token_holder")
        payload = root.payload or {}
        item = await db.get(GithubWorkItem, payload.get("work_item_id"))
        if item is None:
            raise MailAuthorityError("no_current_approval_request", status_code=404)
        owner, leader = await self._dispatch_participants(db, item)
        if leader is None or leader.id != authenticated_sender_member_id:
            raise MailAuthorityError("not_designated_leader")
        if owner is None or root.sender_member_id != owner.id:
            raise MailAuthorityError("stale_approval_owner", status_code=409)
        if root.recipient_member_id != leader.id:
            raise MailAuthorityError("stale_approval_recipient", status_code=409)
        if payload.get("dispatch_nonce") != item.dispatch_nonce:
            raise MailAuthorityError("stale_nonce", status_code=409)
        if payload.get("approval_round") != item.approval_round_count:
            raise MailAuthorityError("approval_round_mismatch", status_code=409)
        return item

    async def send_broadcast(
        self,
        db: AsyncSession,
        *,
        subject: str | None,
        body_markdown: str,
        audience_type: str,
        audience_id: str,
        payload: dict | None = None,
        auto_nudge: bool = True,
        sender_actor_id: int | None = None,
        delivery_key: str | None = None,
        operator_authorized: bool = False,
    ) -> MailMessageResponse:
        return await self.send_message(
            db,
            MailMessageCreate(
                kind="broadcast",
                subject=subject,
                body_markdown=body_markdown,
                payload=payload,
                audience_type=audience_type,
                audience_id=audience_id,
            ),
            auto_nudge=auto_nudge,
            sender_actor_id=sender_actor_id,
            delivery_key=delivery_key,
            operator_authorized=operator_authorized,
        )

    async def send_direct_message(
        self,
        db: AsyncSession,
        *,
        recipient_member_id: int,
        subject: str | None,
        body_markdown: str,
        payload: dict | None = None,
        auto_nudge: bool = True,
        bypass_nudge_cooldown: bool = False,
        nudge_prompt: str = INBOX_CHECK_PROMPT,
        sender_actor_id: int | None = None,
        delivery_key: str | None = None,
    ) -> MailMessageResponse:
        return await self.send_message(
            db,
            MailMessageCreate(
                kind="message",
                recipient_member_id=recipient_member_id,
                subject=subject,
                body_markdown=body_markdown,
                payload=payload,
            ),
            auto_nudge=auto_nudge,
            bypass_nudge_cooldown=bypass_nudge_cooldown,
            nudge_prompt=nudge_prompt,
            sender_actor_id=sender_actor_id,
            delivery_key=delivery_key,
        )

    async def _sender_identity(
        self,
        db: AsyncSession,
        sender_member_id: Optional[int],
        sender_actor_id: Optional[int],
    ) -> tuple[str, str, str | None]:
        if sender_actor_id is not None:
            actor = await db.get(MailExternalActor, sender_actor_id)
            if actor is not None:
                return actor.display_name, "external_actor", actor.kind
            return "unknown external actor", "external_actor", None
        if sender_member_id is None:
            return "Director", "director", None
        member = await db.get(MailTeamMember, sender_member_id)
        return (member.display_name if member else "unknown", "member", None)

    async def _message_response(
        self, db: AsyncSession, message: MailMessage, for_member_id: Optional[int]
    ) -> MailMessageResponse:
        read_at = acked_at = None
        if for_member_id is not None:
            result = await db.execute(
                select(MailReceipt).where(
                    MailReceipt.message_id == message.id,
                    MailReceipt.member_id == for_member_id,
                )
            )
            receipt = result.scalar_one_or_none()
            if receipt is not None:
                read_at, acked_at = receipt.read_at, receipt.acked_at
        is_stale = (
            message.kind in MAIL_REQUEST_KINDS
            and message.request_status == "pending"
            and message.created_at < datetime.utcnow() - timedelta(minutes=STALE_REQUEST_MINUTES)
        )
        sender_name, sender_type, sender_actor_kind = await self._sender_identity(
            db,
            message.sender_member_id,
            message.sender_actor_id,
        )
        return MailMessageResponse(
            id=message.id,
            thread_root_id=message.thread_root_id,
            kind=message.kind,
            sender_member_id=message.sender_member_id,
            sender_actor_id=message.sender_actor_id,
            sender_type=sender_type,
            sender_actor_kind=sender_actor_kind,
            approval_round=message.approval_round,
            decision=message.decision,
            audience_type=message.audience_type,
            audience_id=message.audience_id,
            sender_name=sender_name,
            recipient_member_id=message.recipient_member_id,
            subject=message.subject,
            body_markdown=message.body_markdown,
            payload=message.payload,
            request_status=message.request_status,
            is_stale=is_stale,
            read_at=read_at,
            acked_at=acked_at,
            created_at=message.created_at,
        )

    async def counts_for_member(self, db: AsyncSession, member_id: int) -> tuple[int, int]:
        unread = (
            await db.execute(
                select(func.count())
                .select_from(MailReceipt)
                .where(MailReceipt.member_id == member_id, MailReceipt.read_at.is_(None))
            )
        ).scalar_one()
        pending = (
            await db.execute(
                select(func.count())
                .select_from(MailMessage)
                .where(
                    MailMessage.recipient_member_id == member_id,
                    MailMessage.kind.in_(MAIL_REQUEST_KINDS),
                    MailMessage.request_status == "pending",
                )
            )
        ).scalar_one()
        return unread, pending

    async def _has_pending_continuation_ack(
        self, db: AsyncSession, member_id: int, now: datetime
    ) -> bool:
        revision_id = (
            await db.execute(
                select(GithubAttemptScopeRevision.id)
                .join(
                    GithubWorkItem,
                    GithubWorkItem.id == GithubAttemptScopeRevision.work_item_id,
                )
                .join(
                    GithubApprovalRequest,
                    GithubApprovalRequest.id == GithubAttemptScopeRevision.approval_request_id,
                )
                .join(
                    MailMessage,
                    MailMessage.id == GithubAttemptScopeRevision.delivery_message_id,
                )
                .where(
                    GithubAttemptScopeRevision.owner_member_id == member_id,
                    GithubAttemptScopeRevision.status == "approved",
                    GithubAttemptScopeRevision.acknowledged_at.is_(None),
                    or_(
                        GithubAttemptScopeRevision.recovery_checkpoint_stage.is_(None),
                        GithubAttemptScopeRevision.recovery_checkpoint_stage == "ack_open",
                    ),
                    or_(
                        GithubAttemptScopeRevision.expires_at.is_(None),
                        GithubAttemptScopeRevision.expires_at > now,
                    ),
                    GithubApprovalRequest.status == "approved",
                    GithubApprovalRequest.request_kind == "continuation",
                    GithubApprovalRequest.scope_revision_id == GithubAttemptScopeRevision.id,
                    GithubWorkItem.owner_slot_id == GithubAttemptScopeRevision.owner_slot_id,
                    GithubWorkItem.dispatch_nonce == GithubAttemptScopeRevision.dispatch_nonce,
                    GithubWorkItem.dispatch_status == "escalated",
                    MailMessage.recipient_member_id == member_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return revision_id is not None

    async def delivery_counts_for_member(
        self,
        db: AsyncSession,
        member_id: int,
    ) -> tuple[int, int, int, int]:
        unread, pending = await self.counts_for_member(db, member_id)
        unseen_pending = (
            await db.execute(
                select(func.count())
                .select_from(MailMessage)
                .join(MailReceipt, MailReceipt.message_id == MailMessage.id)
                .where(
                    MailReceipt.member_id == member_id,
                    MailReceipt.read_at.is_(None),
                    MailMessage.kind.in_(MAIL_REQUEST_KINDS),
                    MailMessage.request_status == "pending",
                )
            )
        ).scalar_one()
        stale_cutoff = datetime.utcnow() - timedelta(minutes=STALE_REQUEST_MINUTES)
        stale_pending = (
            await db.execute(
                select(func.count())
                .select_from(MailMessage)
                .where(
                    MailMessage.recipient_member_id == member_id,
                    MailMessage.kind.in_(MAIL_REQUEST_KINDS),
                    MailMessage.request_status == "pending",
                    MailMessage.created_at < stale_cutoff,
                )
            )
        ).scalar_one()
        return unread, pending, unseen_pending, stale_pending

    async def get_inbox(
        self,
        db: AsyncSession,
        member_id: int,
        unread_only: bool = False,
        mark_read: bool = False,
        limit: int = 50,
        refresh_mcp_session: bool = False,
    ) -> MailInboxResponse:
        if refresh_mcp_session:
            await self.heartbeat_member_mcp_session(db, member_id)
        query = (
            select(MailMessage, MailReceipt)
            .join(MailReceipt, MailReceipt.message_id == MailMessage.id)
            .where(MailReceipt.member_id == member_id)
            .order_by(MailMessage.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            query = query.where(MailReceipt.read_at.is_(None))
        rows = (await db.execute(query)).all()
        messages = []
        now = datetime.utcnow()
        if mark_read:
            member = await db.get(MailTeamMember, member_id)
            if member is not None:
                member.last_inbox_checked_at = now
        for message, receipt in rows:
            if mark_read and receipt.read_at is None:
                receipt.read_at = now
            messages.append(await self._message_response(db, message, for_member_id=member_id))
        if mark_read:
            await db.commit()
        unread, pending = await self.counts_for_member(db, member_id)
        return MailInboxResponse(
            member_id=member_id,
            unread_count=unread,
            pending_count=pending,
            messages=messages,
        )

    async def _nudge_session_for_member(
        self,
        db: AsyncSession,
        member_id: int,
        now: datetime,
    ) -> MailAgentSession:
        observed = (
            await db.execute(
                select(MailAgentSession)
                .where(
                    MailAgentSession.member_id == member_id,
                    MailAgentSession.source == "observed",
                    MailAgentSession.provider.in_(sorted(TMUX_WAKE_PROVIDERS)),
                    MailAgentSession.tmux_target.is_not(None),
                )
            )
        ).scalars().all()
        registered = (
            await db.execute(
                select(MailAgentSession).where(
                    MailAgentSession.member_id == member_id,
                    MailAgentSession.source == "mcp",
                    MailAgentSession.mailbox_status == "connected",
                    MailAgentSession.closed_at.is_(None),
                    MailAgentSession.capability_token_hash.is_not(None),
                    MailAgentSession.last_seen_at
                    >= now - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS),
                    MailAgentSession.bound_pane_pid.is_not(None),
                    MailAgentSession.bound_pane_proc_start.is_not(None),
                )
            )
        ).scalars().all()
        member = await db.get(MailTeamMember, member_id)
        if member is None:
            raise MailWakeError("wake_target_unbound")

        def matching_bindings(pane: MailAgentSession) -> list[MailAgentSession]:
            if (
                pane.mailbox_status != "observed"
                or pane.pid is None
                or not pane.pane_id
                or pane.last_seen_at < now - timedelta(seconds=OBSERVED_TTL_SECONDS)
            ):
                return []
            matches = []
            for binding in registered:
                if binding.provider != pane.provider:
                    continue
                is_team_binding = (
                    binding.team_slot_id is not None
                    and binding.team_preset_id is not None
                    and member.participant_kind == "team_slot"
                    and member.team_slot_id == binding.team_slot_id
                    and member.team_preset_id == binding.team_preset_id
                    and pane.team_slot_id == binding.team_slot_id
                    and pane.team_preset_id == binding.team_preset_id
                )
                is_repo_binding = (
                    binding.team_slot_id is None
                    and binding.team_preset_id is None
                    and member.participant_kind == "repo"
                    and pane.team_slot_id is None
                    and pane.team_preset_id is None
                    and pane.member_id == member_id
                    and self._same_repo(binding.cwd, pane.cwd, member.repo_id)
                )
                if not (is_team_binding or is_repo_binding):
                    continue
                if binding.bound_pane_pid != pane.pid:
                    continue
                if peer_process.pane_is_alive(
                    binding.bound_pane_pid, binding.bound_pane_proc_start
                ) is True:
                    matches.append(binding)
            return matches

        matched = [(pane, matching_bindings(pane)) for pane in observed]
        if any(len(bindings) > 1 for _, bindings in matched):
            raise MailWakeError("wake_target_ambiguous")
        candidates = [pane for pane, bindings in matched if bindings and bindings[0].wake_enabled]
        if len(candidates) != 1:
            if not candidates and any(bindings for _, bindings in matched):
                raise MailWakeError("wake_opted_out")
            raise MailWakeError(
                "wake_target_ambiguous" if candidates else "wake_target_unbound"
            )
        return candidates[0]

    async def set_wake_enabled(
        self,
        db: AsyncSession,
        session_id: int,
        enabled: bool,
        *,
        actor_type: str,
        reason_code: str,
    ) -> MailAgentSession:
        session = await db.get(MailAgentSession, session_id)
        if session is None:
            raise MailWakeError("wake_target_unbound")
        if enabled:
            now = datetime.utcnow()
            if (
                session.source != "mcp"
                or session.closed_at is not None
                or session.mailbox_status != "connected"
                or session.capability_token_hash is None
                or session.bound_pane_pid is None
                or not session.bound_pane_proc_start
                or session.last_seen_at < now - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS)
                or peer_process.pane_is_alive(
                    session.bound_pane_pid, session.bound_pane_proc_start
                ) is not True
            ):
                raise MailWakeError("wake_target_unbound")
            observations = (
                await db.execute(
                    select(MailAgentSession).where(
                        MailAgentSession.source == "observed",
                        MailAgentSession.provider == session.provider,
                        MailAgentSession.pid == session.bound_pane_pid,
                        MailAgentSession.mailbox_status == "observed",
                        MailAgentSession.last_seen_at
                        >= now - timedelta(seconds=OBSERVED_TTL_SECONDS),
                    )
                )
            ).scalars().all()
            member = await db.get(MailTeamMember, session.member_id)
            if member is None:
                raise MailWakeError("wake_target_unbound")
            exact = [
                pane for pane in observations
                if pane.pane_id and pane.tmux_target and (
                    (session.team_slot_id is not None
                     and member.participant_kind == "team_slot"
                     and member.team_slot_id == session.team_slot_id
                     and member.team_preset_id == session.team_preset_id
                     and pane.member_id == session.member_id
                     and pane.team_slot_id == session.team_slot_id
                     and pane.team_preset_id == session.team_preset_id)
                    or (session.team_slot_id is None
                        and session.team_preset_id is None
                        and pane.team_slot_id is None
                        and pane.team_preset_id is None
                        and pane.member_id == session.member_id
                        and member.participant_kind == "repo"
                        and self._same_repo(session.cwd, pane.cwd, member.repo_id))
                )
            ]
            if len(exact) != 1:
                raise MailWakeError(
                    "wake_target_ambiguous" if exact else "wake_target_unbound"
                )
        previous_enabled = session.wake_enabled
        session.wake_enabled = enabled
        if enabled:
            try:
                target = await self._nudge_session_for_member(db, session.member_id, now)
                if target.id != exact[0].id:
                    raise MailWakeError("wake_target_ambiguous")
            except MailWakeError:
                session.wake_enabled = previous_enabled
                raise
        db.add(MailWakeAttempt(
            member_id=session.member_id,
            actor_type=actor_type,
            actor_session_id=None,
            source="participation_change",
            reason_code=reason_code,
            correlation_id=uuid4().hex,
            target_session_id=session.id,
            result="enabled" if enabled else "disabled",
        ))
        await db.commit()
        await db.refresh(session)
        return session

    async def nudgeable_sessions_for_slot(
        self, db: AsyncSession, slot_id: int
    ) -> list[MailAgentSession]:
        """Return only observed panes with a fresh authenticated binding."""
        now = datetime.utcnow()
        sessions = await self.observed_sessions_for_slot(db, slot_id)
        matched: list[MailAgentSession] = []
        for member_id in {session.member_id for session in sessions}:
            try:
                session = await self._nudge_session_for_member(db, member_id, now)
            except MailWakeError:
                continue
            if session.team_slot_id == slot_id:
                matched.append(session)
        return matched

    async def observed_sessions_for_slot(
        self, db: AsyncSession, slot_id: int
    ) -> list[MailAgentSession]:
        """Count physical panes for dispatch occupancy, not terminal delivery."""
        now = datetime.utcnow()
        sessions = (
            await db.execute(
                select(MailAgentSession).where(
                    MailAgentSession.team_slot_id == slot_id,
                    MailAgentSession.source == "observed",
                    MailAgentSession.provider.in_(sorted(TMUX_WAKE_PROVIDERS)),
                    MailAgentSession.tmux_target.is_not(None),
                )
            )
        ).scalars().all()
        return [
            session for session in sessions
            if self._effective_status(session, now) == "observed"
        ]

    async def has_fresh_authenticated_mcp_session(
        self,
        db: AsyncSession,
        *,
        member_id: int,
        preset_id: int,
        slot_id: int,
    ) -> bool:
        """Return whether a slot member has recent authenticated MCP presence."""
        cutoff = datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS)
        session_id = await db.scalar(
            select(MailAgentSession.id)
            .where(
                MailAgentSession.member_id == member_id,
                MailAgentSession.team_preset_id == preset_id,
                MailAgentSession.team_slot_id == slot_id,
                MailAgentSession.source == "mcp",
                MailAgentSession.mailbox_status == "connected",
                MailAgentSession.closed_at.is_(None),
                MailAgentSession.capability_token_hash.is_not(None),
                MailAgentSession.last_seen_at >= cutoff,
            )
            .limit(1)
        )
        return session_id is not None

    def _send_tmux_inbox_check(
        self,
        session: MailAgentSession,
        nudge_prompt: str = INBOX_CHECK_PROMPT,
    ) -> dict[str, str]:
        if not session.tmux_target or not session.pane_id or session.pid is None:
            raise MailWakeError("wake_target_unbound")
        try:
            current = subprocess.run(
                ["tmux", "display-message", "-p", "-t", session.pane_id,
                 "#{pane_id}|#{pane_pid}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            if current.stdout.strip() != f"{session.pane_id}|{session.pid}":
                raise MailWakeError("wake_target_stale")
            subprocess.run(
                ["tmux", "send-keys", "-t", session.pane_id, "-l", nudge_prompt],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            time.sleep(TMUX_ENTER_DELAY_SECONDS)
            subprocess.run(
                ["tmux", "send-keys", "-t", session.pane_id, "Enter"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise MailWakeError("wake_transport_failed") from exc
        return {"target": session.tmux_target, "prompt": nudge_prompt}

    async def record_wake_denial(
        self,
        db: AsyncSession,
        member_id: int,
        *,
        actor_type: str,
        actor_session_id: int | None,
        source: str,
        reason_code: str | None,
        failure_code: str,
    ) -> None:
        db.add(MailWakeAttempt(
            member_id=member_id,
            actor_type=actor_type,
            actor_session_id=actor_session_id,
            source=source,
            reason_code=reason_code or source,
            correlation_id=uuid4().hex,
            result="refused",
            failure_code=failure_code,
        ))
        await db.commit()

    async def _wake_member(
        self,
        db: AsyncSession,
        member_id: int,
        now: datetime,
        nudge_prompt: str = INBOX_CHECK_PROMPT,
        *,
        actor_type: str = "server",
        actor_session_id: int | None = None,
        source: str = "auto_nudge",
        reason_code: str | None = None,
        force: bool = False,
    ) -> dict[str, str]:
        unread, pending = await self.counts_for_member(db, member_id)
        audit = MailWakeAttempt(
            member_id=member_id,
            actor_type=actor_type,
            actor_session_id=actor_session_id,
            source=source,
            reason_code=reason_code or source,
            correlation_id=uuid4().hex,
            unread_count=unread,
            pending_count=pending,
            result="refused",
        )
        try:
            if not force and not (unread or pending):
                if await self._has_pending_continuation_ack(db, member_id, now):
                    audit.reason_code = "continuation_owner_ack"
                else:
                    raise MailWakeError("inbox_empty")
            session = await self._nudge_session_for_member(db, member_id, now)
            if actor_type == "session":
                caller = await db.get(MailAgentSession, actor_session_id)
                if (
                    caller is None
                    or caller.member_id != member_id
                    or caller.source != "mcp"
                    or caller.bound_pane_pid != session.pid
                    or not caller.bound_pane_proc_start
                    or peer_process.pane_is_alive(
                        caller.bound_pane_pid, caller.bound_pane_proc_start
                    ) is not True
                ):
                    raise MailWakeError("wake_session_mismatch", status_code=403)
            audit.target_session_id = session.id
            audit.target_pane_id = session.pane_id
            result = self._send_tmux_inbox_check(session, nudge_prompt)
            audit.result = "delivered"
            return {"method": "tmux", **result}
        except MailWakeError as exc:
            audit.failure_code = exc.code
            raise
        finally:
            db.add(audit)
            await db.commit()

    async def auto_nudge_members(
        self,
        db: AsyncSession,
        member_ids: set[int],
        *,
        bypass_cooldown: bool = False,
        nudge_prompt: str = INBOX_CHECK_PROMPT,
    ) -> list[dict[str, str | int]]:
        """Best-effort delivery wakeup for exactly bound team recipients."""
        if not member_ids:
            return []
        await self.sync_observed_sessions(db)
        now = datetime.utcnow()
        nudged: list[dict[str, str | int]] = []
        cooldown_cutoff = now - timedelta(seconds=AUTO_NUDGE_COOLDOWN_SECONDS)
        for member_id in sorted(member_ids):
            last_nudge_at = self._last_auto_nudge_at.get(member_id)
            if (
                not bypass_cooldown
                and last_nudge_at is not None
                and last_nudge_at > cooldown_cutoff
            ):
                continue
            try:
                result = await self._wake_member(
                    db,
                    member_id,
                    now,
                    nudge_prompt,
                )
            except MailWakeError as exc:
                logger.debug("agent mail auto-nudge failed for member %s: %s", member_id, exc.code)
                continue
            self._last_auto_nudge_at[member_id] = now
            nudged.append({"member_id": member_id, **result})
        return nudged

    async def recipient_ids_for_message(self, db: AsyncSession, message_id: int) -> set[int]:
        rows = (
            await db.execute(select(MailReceipt.member_id).where(MailReceipt.message_id == message_id))
        ).scalars().all()
        return set(rows)

    async def wake_members_with_results(
        self,
        db: AsyncSession,
        member_ids: set[int],
    ) -> dict[int, dict[str, str | bool]]:
        if not member_ids:
            return {}
        await self.sync_observed_sessions(db)
        now = datetime.utcnow()
        results: dict[int, dict[str, str | bool]] = {}
        for member_id in sorted(member_ids):
            try:
                result = await self._wake_member(db, member_id, now, source="external_delivery")
            except MailWakeError as exc:
                results[member_id] = {
                    "wake_attempted": exc.code not in {"wake_target_unbound", "inbox_empty"},
                    "wake_succeeded": False,
                    "wake_error": exc.code,
                }
                continue
            results[member_id] = {
                "wake_attempted": True,
                "wake_succeeded": True,
                "wake_method": str(result.get("method") or ""),
            }
        return results

    async def queue_inbox_check(
        self,
        db: AsyncSession,
        member_id: int,
        *,
        actor_type: str,
        actor_session_id: int | None = None,
        force: bool = False,
        reason_code: str | None = None,
    ) -> dict[str, str]:
        await self.sync_observed_sessions(db)
        return await self._wake_member(
            db, member_id, datetime.utcnow(),
            actor_type=actor_type,
            actor_session_id=actor_session_id,
            source="manual_operator" if actor_type == "operator" else "manual_session",
            force=force,
            reason_code=reason_code,
        )

    async def mark_read(self, db: AsyncSession, message_id: int, member_id: int) -> None:
        result = await db.execute(
            select(MailReceipt).where(
                MailReceipt.message_id == message_id,
                MailReceipt.member_id == member_id,
            )
        )
        receipt = result.scalar_one_or_none()
        if receipt is not None and receipt.read_at is None:
            receipt.read_at = datetime.utcnow()
            await db.commit()

    async def ack_message(self, db: AsyncSession, message_id: int, member_id: int) -> None:
        """Ack a message and close request lifecycle state when appropriate."""
        result = await db.execute(
            select(MailReceipt).where(
                MailReceipt.message_id == message_id,
                MailReceipt.member_id == member_id,
            )
        )
        receipt = result.scalar_one_or_none()
        if receipt is None:
            return
        now = datetime.utcnow()
        receipt.read_at = receipt.read_at or now
        receipt.acked_at = receipt.acked_at or now

        message = await db.get(MailMessage, message_id)
        if (
            message is not None
            and message.kind == "handoff"
            and message.thread_root_id is None
            and message.recipient_member_id == member_id
            and message.request_status == "pending"
        ):
            message.request_status = "acknowledged"
        if message is not None and message.kind == "answer" and message.thread_root_id:
            root = await db.get(MailMessage, message.thread_root_id)
            if (
                root is not None
                and root.sender_member_id == member_id
                and root.request_status == "answered"
            ):
                root.request_status = "acknowledged"
        await db.commit()

    async def get_thread(
        self, db: AsyncSession, root_id: int, for_member_id: Optional[int] = None
    ) -> MailThreadResponse:
        root = await db.get(MailMessage, root_id)
        if root is None:
            raise ValueError(f"Message {root_id} not found")
        replies = (
            (
                await db.execute(
                    select(MailMessage)
                    .where(MailMessage.thread_root_id == root_id)
                    .order_by(MailMessage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return MailThreadResponse(
            root=await self._message_response(db, root, for_member_id),
            replies=[await self._message_response(db, reply, for_member_id) for reply in replies],
        )

    async def list_root_messages(
        self, db: AsyncSession, limit: int = 100
    ) -> List[MailMessageResponse]:
        roots = (
            (
                await db.execute(
                    select(MailMessage)
                    .where(MailMessage.thread_root_id.is_(None))
                    .order_by(MailMessage.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [await self._message_response(db, root, for_member_id=None) for root in roots]

    async def _session_team_context(
        self,
        db: AsyncSession,
        member_id: int,
        session_key: str | None = None,
    ) -> tuple[AgentTeamPreset | None, AgentTeamSlot | None]:
        session: MailAgentSession | None = None
        if session_key is not None:
            session = (
                await db.execute(
                    select(MailAgentSession).where(MailAgentSession.session_key == session_key)
                )
            ).scalar_one_or_none()
        if session is None:
            session = (
                await db.execute(
                    select(MailAgentSession)
                    .where(
                        MailAgentSession.member_id == member_id,
                        MailAgentSession.team_preset_id.is_not(None),
                    )
                    .order_by(MailAgentSession.last_seen_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if session is None:
            return None, None

        slot = await db.get(AgentTeamSlot, session.team_slot_id) if session.team_slot_id else None
        preset_id = slot.preset_id if slot is not None else session.team_preset_id
        preset = await db.get(AgentTeamPreset, preset_id) if preset_id else None
        return preset, slot

    async def build_session_start_context(
        self,
        db: AsyncSession,
        member_id: int,
        session_key: str | None = None,
    ) -> str:
        member = await db.get(MailTeamMember, member_id)
        if member is None:
            return ""
        preset, slot = await self._session_team_context(db, member_id, session_key)
        team = await self.list_team(db)
        me = next((candidate for candidate in team if candidate.id == member_id), None)
        others = [candidate for candidate in team if candidate.id != member_id]

        lines = ["[Claude Deck Agent Mail]"]
        effective_role = slot.role if slot and slot.role else member.role
        role = f" ({effective_role})" if effective_role else ""
        lines.append(f'You are "{member.display_name}"{role} - repo: {member.repo_name}.')
        if preset is not None:
            if slot is not None:
                lines.append(f'Agent Team: "{preset.name}" / slot "{slot.display_name}".')
            else:
                lines.append(f'Agent Team: "{preset.name}".')
        if member.charter:
            lines.append(f"Charter: {member.charter}")
        if slot is not None and slot.charter:
            lines.append(f"Team slot charter: {slot.charter}")
        if others:
            roster = " | ".join(
                f"{candidate.display_name} ({candidate.role or candidate.repo_name}, {candidate.status})"
                for candidate in others[:8]
            )
            lines.append(f"Team: {roster}")
        if me is not None and (me.unread_count or me.pending_count):
            lines.append(
                f"Inbox: {me.unread_count} unread, "
                f"{me.pending_count} pending request(s) awaiting your answer."
            )
        lines.append(
            "Coordinate via MCP tools: deck_check_inbox, deck_request_context, "
            "deck_send_message, deck_create_handoff."
        )
        return "\n".join(lines)

    async def build_prompt_submit_context(
        self, db: AsyncSession, member_id: int
    ) -> Optional[str]:
        unread, pending = await self.counts_for_member(db, member_id)
        if not unread and not pending:
            return None
        parts = []
        if unread:
            parts.append(f"{unread} unread message(s)")
        if pending:
            parts.append(f"{pending} pending request(s)")
        return (
            f"[Agent Mail] You have {' and '.join(parts)}. "
            "Call deck_check_inbox when convenient."
        )


agent_mail_service = AgentMailService()
