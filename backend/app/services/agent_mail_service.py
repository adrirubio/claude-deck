"""Agent Mail: durable team members, ephemeral sessions, messages, delivery context."""
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    MailAgentSession,
    MailExternalActor,
    MailMessage,
    MailReceipt,
    MailTeamMember,
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
from app.utils.repo_utils import derive_repo_identity

logger = logging.getLogger(__name__)

HEARTBEAT_TTL_SECONDS = 180
MCP_HEARTBEAT_TTL_SECONDS = 3600
OBSERVED_TTL_SECONDS = 300
STALE_REQUEST_MINUTES = 15
AUTO_NUDGE_COOLDOWN_SECONDS = 30
TMUX_ENTER_DELAY_SECONDS = 0.25
TMUX_WAKE_PROVIDERS = {"claude-code", "codex-cli", "copilot-cli"}
INBOX_CHECK_PROMPT = (
    "Claude Deck Agent Mail: please call `deck_check_inbox(unread_only=False)` now, "
    "then answer any pending context requests or handoffs before continuing."
)


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
        self, db: AsyncSession, request: MailAgentRegisterRequest
    ) -> tuple[MailTeamMember, MailAgentSession]:
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
        session.mailbox_status = "connected"
        session.last_seen_at = datetime.utcnow()
        await db.commit()
        await db.refresh(member)
        await db.refresh(session)
        return member, session

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

    async def heartbeat_session(
        self, db: AsyncSession, session_key: str, activity: Optional[str] = None
    ) -> Optional[MailAgentSession]:
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == session_key)
        )
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.last_seen_at = datetime.utcnow()
        session.mailbox_status = "connected" if session.source != "observed" else "observed"
        if activity:
            session.activity = activity[:200]
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
            )
            .order_by(MailAgentSession.last_seen_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session is None:
            return
        session.last_seen_at = datetime.utcnow()
        session.mailbox_status = "connected"
        await db.commit()

    async def sync_observed_sessions(self, db: AsyncSession) -> None:
        """Upsert Agent Bridge tmux discoveries as observed sessions."""
        try:
            discovered = discover_agent_sessions()
        except Exception as exc:
            logger.warning("agent bridge discovery failed: %s", exc)
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
            session.mailbox_status = "observed"
            session.last_seen_at = datetime.utcnow()
        await self._remove_stale_observed_sessions(db, active_observed_keys)
        for member_id in affected_member_ids:
            await self._remove_empty_observed_member(db, member_id)
        await db.commit()

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

    def _session_can_nudge(self, session: MailAgentSession, now: datetime) -> bool:
        return bool(
            session.source == "observed"
            and session.provider in TMUX_WAKE_PROVIDERS
            and session.tmux_target
            and self._effective_status(session, now) == "observed"
        )

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
            member_sessions = by_member.get(member.id, [])
            wake_methods = []
            if any(self._session_can_nudge(session, now) for session in member_sessions):
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
        sender_actor_id: Optional[int] = None,
    ) -> MailMessageResponse:
        if request.kind not in MAIL_MESSAGE_KINDS:
            raise ValueError(f"Invalid message kind: {request.kind}")
        if request.sender_member_id is not None and sender_actor_id is not None:
            raise ValueError("messages cannot have both sender_member_id and sender_actor_id")
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
        if request.kind in MAIL_REQUEST_KINDS and request.recipient_member_id is None:
            raise ValueError(f"{request.kind} requires recipient_member_id")

        message = MailMessage(
            thread_root_id=request.thread_root_id,
            kind=request.kind,
            sender_member_id=request.sender_member_id,
            sender_actor_id=sender_actor_id,
            recipient_member_id=request.recipient_member_id,
            subject=request.subject,
            body_markdown=request.body_markdown,
            payload=request.payload,
            request_status="pending" if request.kind in MAIL_REQUEST_KINDS else None,
        )
        db.add(message)
        await db.flush()

        recipients: set[int] = set()
        if request.recipient_member_id is not None:
            recipients.add(request.recipient_member_id)
        elif request.thread_root_id is not None:
            root = await db.get(MailMessage, request.thread_root_id)
            if root is not None:
                for member_id in (root.sender_member_id, root.recipient_member_id):
                    if member_id is not None and member_id != request.sender_member_id:
                        recipients.add(member_id)
        else:
            members = (await db.execute(select(MailTeamMember))).scalars().all()
            recipients = {member.id for member in members if member.id != request.sender_member_id}

        for member_id in recipients:
            db.add(MailReceipt(message_id=message.id, member_id=member_id))

        if request.kind == "answer":
            root = await db.get(MailMessage, request.thread_root_id)
            if root is not None and root.request_status == "pending":
                root.request_status = "answered"

        await db.commit()
        await db.refresh(message)
        if auto_nudge:
            await self.auto_nudge_members(db, recipients)
        return await self._message_response(db, message, for_member_id=None)

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
    ) -> MailAgentSession | None:
        result = await db.execute(
            select(MailAgentSession)
            .where(
                MailAgentSession.member_id == member_id,
                MailAgentSession.source == "observed",
                MailAgentSession.provider.in_(sorted(TMUX_WAKE_PROVIDERS)),
                MailAgentSession.tmux_target.is_not(None),
            )
            .order_by(MailAgentSession.last_seen_at.desc())
        )
        return next(
            (candidate for candidate in result.scalars().all() if self._session_can_nudge(candidate, now)),
            None,
        )

    def _send_tmux_inbox_check(self, session: MailAgentSession) -> dict[str, str]:
        if not session.tmux_target:
            raise ValueError("No live tmux session is available for this member")
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", session.tmux_target, "-l", INBOX_CHECK_PROMPT],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            time.sleep(TMUX_ENTER_DELAY_SECONDS)
            subprocess.run(
                ["tmux", "send-keys", "-t", session.tmux_target, "Enter"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except FileNotFoundError as exc:
            raise ValueError("tmux is not installed or not available") from exc
        except subprocess.CalledProcessError as exc:
            raise ValueError(f"tmux send-keys failed: {(exc.stderr or '')[:200]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("tmux send-keys timed out") from exc
        return {"target": session.tmux_target, "prompt": INBOX_CHECK_PROMPT}

    async def _wake_member(
        self,
        db: AsyncSession,
        member_id: int,
        now: datetime,
    ) -> dict[str, str] | None:
        session = await self._nudge_session_for_member(db, member_id, now)
        if session is not None:
            result = self._send_tmux_inbox_check(session)
            return {"method": "tmux", **result}
        return None

    async def auto_nudge_members(self, db: AsyncSession, member_ids: set[int]) -> list[dict[str, str | int]]:
        """Best-effort delivery wakeup for visible tmux-observed recipients."""
        if not member_ids:
            return []
        await self.sync_observed_sessions(db)
        now = datetime.utcnow()
        nudged: list[dict[str, str | int]] = []
        cooldown_cutoff = now - timedelta(seconds=AUTO_NUDGE_COOLDOWN_SECONDS)
        for member_id in sorted(member_ids):
            last_nudge_at = self._last_auto_nudge_at.get(member_id)
            if last_nudge_at is not None and last_nudge_at > cooldown_cutoff:
                continue
            try:
                result = await self._wake_member(db, member_id, now)
            except ValueError as exc:
                logger.debug("agent mail auto-nudge failed for member %s: %s", member_id, exc)
                continue
            if result is None:
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
                result = await self._wake_member(db, member_id, now)
            except ValueError as exc:
                results[member_id] = {
                    "wake_attempted": True,
                    "wake_succeeded": False,
                    "wake_error": str(exc),
                }
                continue
            if result is None:
                results[member_id] = {
                    "wake_attempted": False,
                    "wake_succeeded": False,
                }
                continue
            results[member_id] = {
                "wake_attempted": True,
                "wake_succeeded": True,
                "wake_method": str(result.get("method") or ""),
            }
        return results

    async def queue_inbox_check(self, db: AsyncSession, member_id: int) -> dict[str, str]:
        await self.sync_observed_sessions(db)
        now = datetime.utcnow()
        result = await self._wake_member(db, member_id, now)
        if result is None:
            raise ValueError("No Agent Mail wake path is available for this member")
        return result

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
