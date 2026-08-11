"""External local orchestration surface for Agent Mail."""
import asyncio
import hashlib
import hmac
import re
import secrets
from collections import deque
from datetime import datetime, timedelta
from typing import Deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import MailExternalActor, MailMessage, MailTeamMember
from app.models.schemas import (
    ExternalAgentMailContextRequest,
    ExternalAgentMailDeliveryRecipient,
    ExternalAgentMailHandoffRequest,
    ExternalAgentMailMessageRequest,
    ExternalAgentMailRequestStatus,
    ExternalAgentMailSendResponse,
    MailExternalActorCreate,
    MailExternalActorCreateResponse,
    MailExternalActorResponse,
    MailMessageCreate,
    MailThreadResponse,
    TeamListResponse,
)
from app.services.agent_mail_service import agent_mail_service

ACTOR_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{2,80}$")
EXTERNAL_RATE_LIMIT_MAX_MESSAGES = 30
EXTERNAL_RATE_LIMIT_WINDOW_SECONDS = 60
EXTERNAL_WAIT_MAX_SECONDS = 30
EXTERNAL_WAIT_POLL_SECONDS = 0.5
_REQUEST_RECIPIENT = object()


class ExternalAgentMailAuthError(ValueError):
    """Raised when a bearer token cannot be mapped to an external actor."""


class ExternalAgentMailRateLimitError(ValueError):
    """Raised when an external actor exceeds the local message rate limit."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("External Agent Mail rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class ExternalAgentMailService:
    """Token-bound external actor helpers for Agent Mail orchestration."""

    def __init__(self) -> None:
        self._send_windows: dict[int, Deque[datetime]] = {}

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def actor_response(self, actor: MailExternalActor) -> MailExternalActorResponse:
        return MailExternalActorResponse(
            id=actor.id,
            actor_key=actor.actor_key,
            display_name=actor.display_name,
            kind=actor.kind,
            description=actor.description,
            created_at=actor.created_at,
            last_used_at=actor.last_used_at,
        )

    async def create_actor(
        self,
        db: AsyncSession,
        request: MailExternalActorCreate,
    ) -> MailExternalActorCreateResponse:
        actor_key = request.actor_key.strip()
        display_name = request.display_name.strip()
        kind = request.kind.strip() or "external_tool"
        description = request.description.strip() if request.description else None
        if not ACTOR_KEY_PATTERN.match(actor_key):
            raise ValueError("actor_key must be 2-80 chars using letters, numbers, _, ., :, or -")
        if not display_name:
            raise ValueError("display_name is required")
        if len(kind) > 80:
            raise ValueError("kind must be 80 chars or less")

        token = secrets.token_urlsafe(32)
        result = await db.execute(
            select(MailExternalActor).where(MailExternalActor.actor_key == actor_key)
        )
        actor = result.scalar_one_or_none()
        if actor is None:
            actor = MailExternalActor(
                actor_key=actor_key,
                display_name=display_name,
                kind=kind,
                description=description,
                token_hash=self._hash_token(token),
            )
            db.add(actor)
        else:
            actor.display_name = display_name
            actor.kind = kind
            actor.description = description
            actor.token_hash = self._hash_token(token)
        await db.commit()
        await db.refresh(actor)
        return MailExternalActorCreateResponse(actor=self.actor_response(actor), token=token)

    async def authenticate_actor(self, db: AsyncSession, token: str | None) -> MailExternalActor:
        if not token:
            raise ExternalAgentMailAuthError("Missing bearer token")
        hashed = self._hash_token(token)
        result = await db.execute(select(MailExternalActor))
        for actor in result.scalars().all():
            if hmac.compare_digest(actor.token_hash, hashed):
                actor.last_used_at = datetime.utcnow()
                await db.commit()
                await db.refresh(actor)
                return actor
        raise ExternalAgentMailAuthError("Invalid bearer token")

    def check_send_rate_limit(self, actor_id: int) -> None:
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=EXTERNAL_RATE_LIMIT_WINDOW_SECONDS)
        window = self._send_windows.setdefault(actor_id, deque())
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= EXTERNAL_RATE_LIMIT_MAX_MESSAGES:
            retry_after = max(
                1,
                int((window[0] + timedelta(seconds=EXTERNAL_RATE_LIMIT_WINDOW_SECONDS) - now).total_seconds()),
            )
            raise ExternalAgentMailRateLimitError(retry_after)
        window.append(now)

    async def list_members(self, db: AsyncSession) -> TeamListResponse:
        await agent_mail_service.sync_observed_sessions(db)
        return TeamListResponse(members=await agent_mail_service.list_team(db))

    async def send_message(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        request: ExternalAgentMailMessageRequest,
        *,
        kind: str = "message",
        recipient_member_id: int | None | object = _REQUEST_RECIPIENT,
        thread_root_id: int | None = None,
        subject: str | None = None,
        body_markdown: str | None = None,
        payload: dict | None = None,
    ) -> ExternalAgentMailSendResponse:
        self.check_send_rate_limit(actor.id)
        resolved_recipient_id = (
            request.recipient_member_id
            if recipient_member_id is _REQUEST_RECIPIENT
            else recipient_member_id
        )
        if resolved_recipient_id is not None:
            await self._require_member(db, int(resolved_recipient_id))
        message_request = MailMessageCreate(
            kind=kind,
            recipient_member_id=resolved_recipient_id,
            thread_root_id=thread_root_id,
            subject=subject if subject is not None else request.subject,
            body_markdown=body_markdown if body_markdown is not None else request.body_markdown,
            payload=payload if payload is not None else request.payload,
        )
        message = await agent_mail_service.send_message(
            db,
            message_request,
            auto_nudge=False,
            sender_actor_id=actor.id,
        )
        recipient_ids = await agent_mail_service.recipient_ids_for_message(db, message.id)
        wake_results = await agent_mail_service.wake_members_with_results(db, recipient_ids)
        recipients = await self._delivery_recipients(db, recipient_ids, wake_results)
        return ExternalAgentMailSendResponse(
            actor=self.actor_response(actor),
            message=message,
            delivery_state=self._delivery_state(recipients),
            recipients=recipients,
        )

    async def send_direct_message(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        request: ExternalAgentMailMessageRequest,
    ) -> ExternalAgentMailSendResponse:
        if request.recipient_member_id is None:
            raise ValueError("recipient_member_id is required")
        return await self.send_message(db, actor, request, kind="message")

    async def send_broadcast(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        request: ExternalAgentMailMessageRequest,
    ) -> ExternalAgentMailSendResponse:
        return await self.send_message(db, actor, request, kind="broadcast", recipient_member_id=None)

    async def send_context_request(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        request: ExternalAgentMailContextRequest,
    ) -> ExternalAgentMailSendResponse:
        payload = {
            "why_needed": request.why_needed,
            "files_or_symbols": request.files_or_symbols,
        }
        return await self.send_message(
            db,
            actor,
            ExternalAgentMailMessageRequest(
                recipient_member_id=request.recipient_member_id,
                subject=request.subject,
                body_markdown=request.body_markdown,
            ),
            kind="context_request",
            payload=payload,
        )

    async def send_handoff(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        request: ExternalAgentMailHandoffRequest,
    ) -> ExternalAgentMailSendResponse:
        payload = {
            "files": request.files,
            "next_steps": request.next_steps,
        }
        return await self.send_message(
            db,
            actor,
            ExternalAgentMailMessageRequest(
                recipient_member_id=request.recipient_member_id,
                subject=request.subject,
                body_markdown=request.body_markdown,
            ),
            kind="handoff",
            payload=payload,
        )

    async def reply_in_thread(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        root_id: int,
        request: ExternalAgentMailMessageRequest,
    ) -> ExternalAgentMailSendResponse:
        root = await db.get(MailMessage, root_id)
        if root is None:
            raise ValueError("Thread root not found")
        if root.sender_actor_id is not None and root.sender_actor_id != actor.id:
            raise ValueError("External actors can only reply in threads they created")
        return await self.send_message(
            db,
            actor,
            request,
            kind="message",
            recipient_member_id=None,
            thread_root_id=root_id,
            subject=request.subject,
            body_markdown=request.body_markdown,
            payload=request.payload,
        )

    async def thread(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        message_id: int,
    ) -> MailThreadResponse:
        thread = await agent_mail_service.get_thread(db, message_id)
        self._require_actor_owns_thread(thread, actor)
        return thread

    async def request_status(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        message_id: int,
    ) -> ExternalAgentMailRequestStatus:
        thread = await self.thread(db, actor, message_id)
        root = thread.root
        if root.kind not in {"context_request", "handoff"}:
            raise ValueError("Message is not a request")
        answered = root.request_status in {"answered", "acknowledged"} or any(
            reply.kind == "answer" for reply in thread.replies
        )
        acknowledged = root.request_status == "acknowledged"
        return ExternalAgentMailRequestStatus(
            message_id=root.id,
            kind=root.kind,
            request_status=root.request_status,
            is_stale=root.is_stale,
            answered=answered,
            acknowledged=acknowledged,
            root=root,
            replies=thread.replies,
        )

    async def wait_for_request_status(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        message_id: int,
        timeout_seconds: int,
    ) -> ExternalAgentMailRequestStatus:
        timeout = max(0, min(timeout_seconds, EXTERNAL_WAIT_MAX_SECONDS))
        deadline = datetime.utcnow() + timedelta(seconds=timeout)
        status = await self.request_status(db, actor, message_id)
        while (
            status.request_status == "pending"
            and not status.answered
            and not status.is_stale
            and datetime.utcnow() < deadline
        ):
            # Do not pin a DB transaction/connection while long-polling.
            await db.rollback()
            db.expire_all()
            await asyncio.sleep(EXTERNAL_WAIT_POLL_SECONDS)
            status = await self.request_status(db, actor, message_id)
        return status

    async def acknowledge_external_request(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        message_id: int,
    ) -> ExternalAgentMailRequestStatus:
        root = await db.get(MailMessage, message_id)
        if root is None:
            raise ValueError("Message not found")
        if root.sender_actor_id != actor.id:
            raise ValueError("External actors can only acknowledge requests they created")
        if root.kind not in {"context_request", "handoff"}:
            raise ValueError("Message is not a request")
        if root.request_status == "answered":
            root.request_status = "acknowledged"
            await db.commit()
        return await self.request_status(db, actor, message_id)

    async def acknowledge_actor_request(
        self,
        db: AsyncSession,
        actor: MailExternalActor,
        message_id: int,
    ) -> ExternalAgentMailRequestStatus:
        """Acknowledge a request as an external actor without member evidence."""
        root = await db.get(MailMessage, message_id)
        if root is None:
            raise ValueError("Message not found")
        if root.sender_actor_id is not None and root.sender_actor_id != actor.id:
            raise ValueError("External actors can only acknowledge requests they created")
        if root.kind not in {"context_request", "handoff"}:
            raise ValueError("Message is not a request")
        if root.request_status in {"pending", "answered"}:
            root.request_status = "acknowledged"
            await db.commit()
        return await self._actor_request_status(db, root.id)

    async def _actor_request_status(
        self,
        db: AsyncSession,
        message_id: int,
    ) -> ExternalAgentMailRequestStatus:
        """Project request status without applying the actor thread-read gate."""
        thread = await agent_mail_service.get_thread(db, message_id)
        root = thread.root
        answered = root.request_status in {"answered", "acknowledged"} or any(
            reply.kind == "answer" for reply in thread.replies
        )
        return ExternalAgentMailRequestStatus(
            message_id=root.id,
            kind=root.kind,
            request_status=root.request_status,
            is_stale=root.is_stale,
            answered=answered,
            acknowledged=root.request_status == "acknowledged",
            root=root,
            replies=thread.replies,
        )

    async def _delivery_recipients(
        self,
        db: AsyncSession,
        recipient_ids: set[int],
        wake_results: dict[int, dict[str, str | bool]],
    ) -> list[ExternalAgentMailDeliveryRecipient]:
        members = {member.id: member for member in (await agent_mail_service.list_team(db))}
        recipients: list[ExternalAgentMailDeliveryRecipient] = []
        for member_id in sorted(recipient_ids):
            member = members.get(member_id)
            if member is None:
                db_member = await db.get(MailTeamMember, member_id)
                member_name = db_member.display_name if db_member is not None else f"Member {member_id}"
                wake_state = "offline"
            else:
                member_name = member.display_name
                wake_state = member.wake_state
            wake = wake_results.get(member_id, {})
            wake_attempted = bool(wake.get("wake_attempted", False))
            wake_succeeded = bool(wake.get("wake_succeeded", False))
            if wake_succeeded:
                status = "wake_succeeded"
            elif wake_attempted:
                status = "wake_failed"
            elif wake_state == "offline":
                status = "stored_offline"
            elif wake_state == "delivered_waiting":
                status = "delivered_waiting"
            else:
                status = "stored"
            recipients.append(
                ExternalAgentMailDeliveryRecipient(
                    member_id=member_id,
                    member_name=member_name,
                    status=status,
                    wake_state=wake_state,
                    wake_attempted=wake_attempted,
                    wake_succeeded=wake_succeeded,
                    wake_method=str(wake["wake_method"]) if "wake_method" in wake else None,
                    wake_error=str(wake["wake_error"]) if "wake_error" in wake else None,
                )
            )
        return recipients

    async def _require_member(self, db: AsyncSession, member_id: int) -> None:
        if await db.get(MailTeamMember, member_id) is None:
            raise ValueError(f"Recipient member {member_id} not found")

    def _require_actor_owns_thread(
        self,
        thread: MailThreadResponse,
        actor: MailExternalActor,
    ) -> None:
        if thread.root.sender_actor_id != actor.id:
            raise PermissionError("External actors can only read threads they created")

    def _delivery_state(self, recipients: list[ExternalAgentMailDeliveryRecipient]) -> str:
        if not recipients:
            return "stored_no_recipients"
        statuses = {recipient.status for recipient in recipients}
        if "wake_succeeded" in statuses:
            return "wake_succeeded"
        if "wake_failed" in statuses:
            return "wake_failed"
        if "delivered_waiting" in statuses:
            return "delivered_waiting"
        if "stored_offline" in statuses:
            return "stored_offline"
        return "stored"


external_agent_mail_service = ExternalAgentMailService()
