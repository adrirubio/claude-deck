"""Image attachment handling for Agent Bridge tmux sessions."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import BridgeSessionAttachment
from app.models.schemas import (
    BridgeAttachmentDeleteResponse,
    BridgeAttachmentPasteRequest,
    BridgeAttachmentPasteResponse,
    BridgeAttachmentResponse,
)
from app.services.agent_bridge.discovery import discover_agent_sessions
from app.services.agent_mail_service import TMUX_ENTER_DELAY_SECONDS

_SAFE_SEGMENT_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_PROMPT_TEMPLATES = {
    "claude-code": "Please inspect this image: {path}",
    "codex-cli": "Please inspect this image: {path}",
    "opencode-cli": "Please inspect this image: {path}",
    "copilot-cli": "Please inspect this image: {path}",
    "unknown": "Please inspect this image: {path}",
}
_MAX_PROMPT_LENGTH = 4000


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AgentBridgeAttachmentService:
    """Stores images where the tmux agent can read them and injects references."""

    async def create_attachment(
        self,
        db: AsyncSession,
        *,
        target: str,
        content: bytes,
        original_filename: str | None = None,
        prompt: str | None = None,
        template: str | None = None,
        created_by: str | None = None,
    ) -> BridgeAttachmentResponse:
        session = self._require_live_session(target)
        mime_type, extension = self._detect_image(content)
        sha256 = hashlib.sha256(content).hexdigest()
        await self._enforce_daily_limit(db, target)

        now = _utcnow()
        storage_path = self._storage_path(
            session=session,
            created_at=now,
            sha256=sha256,
            extension=extension,
        )
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = storage_path.with_suffix(storage_path.suffix + ".tmp")
        temp_path.write_bytes(content)
        os.replace(temp_path, storage_path)

        agent_path = self._agent_path(storage_path)
        prompt_text = self._build_prompt(
            provider=str(session.get("provider") or "unknown"),
            agent_path=agent_path,
            prompt=prompt,
            template=template,
        )
        attachment = BridgeSessionAttachment(
            target=target,
            session_name=self._clean_optional(session.get("session_name")),
            provider=self._clean_optional(session.get("provider")),
            original_filename=self._clean_optional(original_filename),
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=sha256,
            storage_path=str(storage_path),
            agent_path=agent_path,
            prompt_text=prompt_text,
            created_by=self._clean_optional(created_by),
            created_at=now,
            expires_at=now + timedelta(days=max(settings.bridge_attachment_retention_days, 1)),
        )
        db.add(attachment)
        await db.commit()
        await db.refresh(attachment)
        return self._response(attachment)

    async def list_attachments(
        self,
        db: AsyncSession,
        *,
        target: str,
    ) -> list[BridgeAttachmentResponse]:
        statement = (
            select(BridgeSessionAttachment)
            .where(BridgeSessionAttachment.target == target)
            .order_by(BridgeSessionAttachment.created_at.desc())
        )
        attachments = (await db.execute(statement)).scalars().all()
        return [self._response(attachment) for attachment in attachments]

    async def paste_attachment(
        self,
        db: AsyncSession,
        *,
        target: str,
        attachment_id: int,
        request: BridgeAttachmentPasteRequest,
    ) -> BridgeAttachmentPasteResponse:
        self._require_live_session(target)
        attachment = await self._require_attachment(db, target, attachment_id)
        prompt_text = self._clean_prompt_text(
            f"{request.prefix or ''}{attachment.prompt_text}{request.suffix or ''}"
        )
        self._send_tmux_prompt(target, prompt_text, submit=request.submit)
        return BridgeAttachmentPasteResponse(
            pasted=True,
            submitted=request.submit,
            target=target,
        )

    async def delete_attachment(
        self,
        db: AsyncSession,
        *,
        target: str,
        attachment_id: int,
    ) -> BridgeAttachmentDeleteResponse:
        attachment = await self._require_attachment(db, target, attachment_id)
        self._unlink_attachment_file(attachment.storage_path)
        await db.delete(attachment)
        await db.commit()
        return BridgeAttachmentDeleteResponse(
            deleted=True,
            target=target,
            attachment_id=attachment_id,
        )

    async def cleanup_expired(self, db: AsyncSession, *, now: datetime | None = None) -> int:
        current = now or _utcnow()
        statement = select(BridgeSessionAttachment).where(
            BridgeSessionAttachment.expires_at.is_not(None),
            BridgeSessionAttachment.expires_at <= current,
        )
        attachments = (await db.execute(statement)).scalars().all()
        for attachment in attachments:
            self._unlink_attachment_file(attachment.storage_path)
        if attachments:
            await db.execute(
                delete(BridgeSessionAttachment).where(
                    BridgeSessionAttachment.id.in_([attachment.id for attachment in attachments])
                )
            )
            await db.commit()
        return len(attachments)

    def _require_live_session(self, target: str) -> dict[str, Any]:
        for session in discover_agent_sessions():
            if session.get("tmux_target") == target:
                return session
        raise ValueError("Agent Bridge session target not found")

    async def _require_attachment(
        self,
        db: AsyncSession,
        target: str,
        attachment_id: int,
    ) -> BridgeSessionAttachment:
        attachment = await db.get(BridgeSessionAttachment, attachment_id)
        if attachment is None or attachment.target != target:
            raise ValueError("Attachment not found for target")
        return attachment

    async def _enforce_daily_limit(self, db: AsyncSession, target: str) -> None:
        limit = settings.bridge_attachment_max_per_session_per_day
        if limit <= 0:
            return
        today = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        count = (
            await db.execute(
                select(func.count(BridgeSessionAttachment.id)).where(
                    BridgeSessionAttachment.target == target,
                    BridgeSessionAttachment.created_at >= today,
                )
            )
        ).scalar_one()
        if count >= limit:
            raise ValueError("Daily attachment limit reached for this session")

    def _detect_image(self, content: bytes) -> tuple[str, str]:
        max_bytes = settings.bridge_attachment_max_bytes
        if not content:
            raise ValueError("Attachment file is empty")
        if len(content) > max_bytes:
            raise ValueError(f"Attachment exceeds maximum size of {max_bytes} bytes")
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif", "gif"
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp", "webp"
        raise ValueError("Unsupported image type")

    def _storage_path(
        self,
        *,
        session: dict[str, Any],
        created_at: datetime,
        sha256: str,
        extension: str,
    ) -> Path:
        root = self._storage_root()
        segment = self._safe_segment(
            self._clean_optional(session.get("session_name"))
            or self._clean_optional(session.get("tmux_target"))
            or sha256[:12]
        )
        date_segment = created_at.strftime("%Y-%m-%d")
        filename = f"{created_at.strftime('%H%M%S')}-{sha256[:12]}.{extension}"
        return root / segment / date_segment / filename

    def _storage_root(self) -> Path:
        return Path(settings.bridge_attachment_dir).expanduser().resolve()

    def _agent_path(self, storage_path: Path) -> str:
        storage_root = self._storage_root()
        relative_path = storage_path.resolve().relative_to(storage_root)
        configured_agent_root = self._clean_optional(settings.bridge_attachment_agent_root)
        if not configured_agent_root:
            return str(storage_path)
        return str(Path(configured_agent_root).expanduser() / relative_path)

    def _build_prompt(
        self,
        *,
        provider: str,
        agent_path: str,
        prompt: str | None = None,
        template: str | None = None,
    ) -> str:
        template_text = prompt or _PROMPT_TEMPLATES.get(template or provider) or _PROMPT_TEMPLATES["unknown"]
        if "{path}" not in template_text:
            raise ValueError("Attachment prompt must include {path}")
        return self._clean_prompt_text(template_text.replace("{path}", agent_path))

    def _clean_prompt_text(self, value: str) -> str:
        text = value.replace("\x00", "")
        text = re.sub(r"[\r\n]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            raise ValueError("Attachment prompt is empty")
        if len(text) > _MAX_PROMPT_LENGTH:
            raise ValueError("Attachment prompt is too long")
        return text

    def _send_tmux_prompt(self, target: str, prompt_text: str, *, submit: bool) -> None:
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "-l", prompt_text],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            if submit:
                time.sleep(TMUX_ENTER_DELAY_SECONDS)
                subprocess.run(
                    ["tmux", "send-keys", "-t", target, "Enter"],
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

    def _unlink_attachment_file(self, storage_path: str) -> None:
        try:
            root = self._storage_root()
            path = Path(storage_path).resolve()
            path.relative_to(root)
            if path.is_file():
                path.unlink()
        except (OSError, ValueError):
            return

    def _safe_segment(self, value: str) -> str:
        segment = _SAFE_SEGMENT_PATTERN.sub("-", value.strip()).strip(".-")
        return segment[:80] or hashlib.sha256(value.encode()).hexdigest()[:12]

    def _clean_optional(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _response(self, attachment: BridgeSessionAttachment) -> BridgeAttachmentResponse:
        return BridgeAttachmentResponse(
            id=attachment.id,
            target=attachment.target,
            session_name=attachment.session_name,
            provider=attachment.provider,
            original_filename=attachment.original_filename,
            mime_type=attachment.mime_type,
            size_bytes=attachment.size_bytes,
            sha256=attachment.sha256,
            agent_path=attachment.agent_path,
            prompt_text=attachment.prompt_text,
            created_by=attachment.created_by,
            created_at=attachment.created_at,
            expires_at=attachment.expires_at,
        )


agent_bridge_attachment_service = AgentBridgeAttachmentService()
