"""Agent Mail: durable team members, ephemeral sessions, messages, delivery context."""
import logging
import os
import subprocess
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import MailAgentSession, MailMessage, MailReceipt, MailTeamMember
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
INBOX_CHECK_PROMPT = (
    "Claude Deck Agent Mail: please call `deck_check_inbox(unread_only=False)` now, "
    "then answer any pending context requests or handoffs before continuing."
)


class AgentMailService:
    """Registry, messaging, and delivery-context behavior for Agent Mail."""

    async def _get_or_create_member(self, db: AsyncSession, cwd: str) -> MailTeamMember:
        ident = derive_repo_identity(cwd)
        result = await db.execute(
            select(MailTeamMember).where(MailTeamMember.repo_id == ident["repo_id"])
        )
        member = result.scalar_one_or_none()
        if member is None:
            member = MailTeamMember(
                repo_id=ident["repo_id"],
                repo_path=ident["repo_root"],
                repo_name=ident["repo_name"],
                display_name=ident["repo_name"],
            )
            db.add(member)
            await db.flush()
        return member

    async def register_session(
        self, db: AsyncSession, request: MailAgentRegisterRequest
    ) -> tuple[MailTeamMember, MailAgentSession]:
        member = await self._get_or_create_member(db, request.cwd)
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == request.session_key)
        )
        session = result.scalar_one_or_none()
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
        session.mailbox_status = "connected"
        session.last_seen_at = datetime.utcnow()
        await db.commit()
        await db.refresh(member)
        await db.refresh(session)
        return member, session

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
        for info in discovered:
            pane_id = info.get("pane_id")
            cwd = info.get("cwd")
            if not pane_id or not cwd:
                continue
            member = await self._get_or_create_member(db, cwd)
            session_key = f"tmux:{pane_id}"
            active_observed_keys.add(session_key)
            result = await db.execute(
                select(MailAgentSession).where(MailAgentSession.session_key == session_key)
            )
            session = result.scalar_one_or_none()
            if session is None:
                session = MailAgentSession(
                    member_id=member.id,
                    source="observed",
                    session_key=session_key,
                )
                db.add(session)
            session.member_id = member.id
            session.provider = info.get("provider", "unknown")
            session.cwd = cwd
            session.tmux_target = info.get("tmux_target")
            session.pane_id = pane_id
            try:
                session.pid = int(info.get("pid") or 0) or None
            except (TypeError, ValueError):
                session.pid = None
            session.mailbox_status = "observed"
            session.last_seen_at = datetime.utcnow()
        await self._remove_stale_observed_sessions(db, active_observed_keys)
        await db.commit()

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
            and session.provider == "codex-cli"
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

    def _session_response(self, session: MailAgentSession, now: datetime) -> MailSessionResponse:
        return MailSessionResponse(
            id=session.id,
            provider=session.provider,
            source=session.source,
            session_key=session.session_key,
            cwd=session.cwd,
            tmux_target=session.tmux_target,
            mailbox_status=self._effective_status(session, now),
            activity=session.activity,
            last_seen_at=session.last_seen_at,
        )

    async def list_team(self, db: AsyncSession) -> List[MailMemberResponse]:
        now = datetime.utcnow()
        members = (await db.execute(select(MailTeamMember))).scalars().all()
        sessions = (await db.execute(select(MailAgentSession))).scalars().all()
        by_member: dict[int, list[MailAgentSession]] = {}
        for session in sessions:
            by_member.setdefault(session.member_id, []).append(session)

        responses: List[MailMemberResponse] = []
        for member in members:
            session_responses = [
                self._session_response(session, now) for session in by_member.get(member.id, [])
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
            responses.append(
                MailMemberResponse(
                    id=member.id,
                    repo_id=member.repo_id,
                    repo_path=member.repo_path,
                    repo_name=member.repo_name,
                    display_name=member.display_name,
                    role=member.role,
                    charter=member.charter,
                    status=status,
                    unread_count=unread,
                    pending_count=pending,
                    unseen_pending_count=unseen_pending,
                    stale_pending_count=stale_pending,
                    can_nudge=any(
                        self._session_can_nudge(session, now) for session in by_member.get(member.id, [])
                    ),
                    last_inbox_checked_at=member.last_inbox_checked_at,
                    sessions=session_responses,
                )
            )
        responses.sort(key=lambda member: (member.status != "connected", member.display_name.lower()))
        return responses

    async def send_message(
        self, db: AsyncSession, request: MailMessageCreate
    ) -> MailMessageResponse:
        if request.kind not in MAIL_MESSAGE_KINDS:
            raise ValueError(f"Invalid message kind: {request.kind}")
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
        return await self._message_response(db, message, for_member_id=None)

    async def _sender_name(self, db: AsyncSession, sender_member_id: Optional[int]) -> str:
        if sender_member_id is None:
            return "Director"
        member = await db.get(MailTeamMember, sender_member_id)
        return member.display_name if member else "unknown"

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
        return MailMessageResponse(
            id=message.id,
            thread_root_id=message.thread_root_id,
            kind=message.kind,
            sender_member_id=message.sender_member_id,
            sender_name=await self._sender_name(db, message.sender_member_id),
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

    async def queue_inbox_check(self, db: AsyncSession, member_id: int) -> dict[str, str]:
        await self.sync_observed_sessions(db)
        now = datetime.utcnow()
        result = await db.execute(
            select(MailAgentSession)
            .where(
                MailAgentSession.member_id == member_id,
                MailAgentSession.source == "observed",
                MailAgentSession.provider == "codex-cli",
                MailAgentSession.tmux_target.is_not(None),
            )
            .order_by(MailAgentSession.last_seen_at.desc())
        )
        session = next(
            (candidate for candidate in result.scalars().all() if self._session_can_nudge(candidate, now)),
            None,
        )
        if session is None or not session.tmux_target:
            raise ValueError("No live Codex tmux session is available for this member")
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", session.tmux_target, "-l", INBOX_CHECK_PROMPT],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
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

    async def build_session_start_context(self, db: AsyncSession, member_id: int) -> str:
        member = await db.get(MailTeamMember, member_id)
        if member is None:
            return ""
        team = await self.list_team(db)
        me = next((candidate for candidate in team if candidate.id == member_id), None)
        others = [candidate for candidate in team if candidate.id != member_id]

        lines = ["[Claude Deck Agent Mail]"]
        role = f" ({member.role})" if member.role else ""
        lines.append(f'You are "{member.display_name}"{role} - repo: {member.repo_name}.')
        if member.charter:
            lines.append(f"Charter: {member.charter}")
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
