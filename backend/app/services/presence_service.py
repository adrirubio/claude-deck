"""Service for Presence Dashboard — event processing and session aggregation."""
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import PresenceEvent, PresenceSession
from app.models.schemas import PresenceSessionResponse


class ConnectionManager:
    """Manages WebSocket connections for live presence updates."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def broadcast(self, message: str):
        disconnected = []
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


manager = ConnectionManager()

IDLE_TIMEOUT_MINUTES = 5
BUCKET_COUNT = 30
FILE_EDIT_TOOLS = {"Write", "Edit", "MultiEdit"}


class PresenceService:
    """Processes webhook events and maintains aggregated session state."""

    async def process_event(self, payload: dict, db: AsyncSession) -> PresenceSessionResponse:
        now = datetime.now(timezone.utc)
        session_id = payload["session_id"]
        event_type = payload.get("hook_event_name", "Unknown")

        # Store raw event
        raw_event = PresenceEvent(
            session_id=session_id,
            event_type=event_type,
            tool_name=payload.get("tool_name"),
            tool_input=payload.get("tool_input"),
            tool_result=payload.get("tool_result"),
            message=payload.get("message"),
            cwd=payload.get("cwd"),
            timestamp=now,
            received_at=now,
        )
        db.add(raw_event)

        # Upsert presence session
        result = await db.execute(
            select(PresenceSession).where(PresenceSession.session_id == session_id)
        )
        session = result.scalar_one_or_none()

        if session is None:
            session = PresenceSession(
                session_id=session_id,
                status="active",
                started_at=now,
                last_event_at=now,
                total_events=0,
                error_count=0,
                activity_buckets=[0] * BUCKET_COUNT,
                bucket_start=now,
                modified_files=[],
            )
            db.add(session)

        # Derive project_path / label from cwd
        cwd = payload.get("cwd")
        if cwd and not session.project_path:
            session.project_path = cwd
        if cwd and not session.label:
            session.label = self._derive_label(cwd)

        # Update based on event type
        if event_type == "Notification":
            msg = payload.get("message")
            if msg:
                session.last_narrative = msg
                session.last_narrative_at = now

        elif event_type == "PostToolUse":
            tool_name = payload.get("tool_name", "")
            tool_input = payload.get("tool_input") or {}
            tool_result = payload.get("tool_result") or {}

            if tool_name in FILE_EDIT_TOOLS:
                file_path = tool_input.get("file_path") or tool_input.get("path")
                if file_path:
                    files = list(session.modified_files or [])
                    if file_path in files:
                        files.remove(file_path)
                    files.append(file_path)
                    session.modified_files = files[-10:]

            if tool_name == "Bash":
                cmd = tool_input.get("command", "")
                session.last_command = cmd[:500] if cmd else None
                # Extract exit code from tool_result
                exit_code = self._extract_exit_code(tool_result)
                session.last_command_exit = exit_code
                if exit_code and exit_code != 0:
                    session.error_count = (session.error_count or 0) + 1
                    session.status = "error"

        elif event_type in ("Stop", "SessionEnd"):
            session.status = "stopped"
            session.ended_at = now

        elif event_type == "SessionStart":
            # Reset session if restarted
            session.status = "active"
            session.ended_at = None
            session.started_at = now
            session.total_events = 0
            session.error_count = 0
            session.modified_files = []
            session.last_narrative = None
            session.last_command = None
            session.last_command_exit = None
            session.activity_buckets = [0] * BUCKET_COUNT
            session.bucket_start = now

        # Common updates for all events
        session.last_event_at = now
        session.total_events = (session.total_events or 0) + 1

        # Reactivate if we get an event for a stopped/idle session (except Stop/SessionEnd)
        if event_type not in ("Stop", "SessionEnd") and session.status in ("idle", "stopped"):
            session.status = "active"
            session.ended_at = None

        # Update activity buckets
        self._update_activity_buckets(session, now)

        await db.flush()

        # Mark idle sessions while we're here
        await self._mark_idle_sessions(db, now)

        return self._to_response(session)

    async def get_all_sessions(self, db: AsyncSession) -> List[PresenceSessionResponse]:
        now = datetime.now(timezone.utc)
        await self._mark_idle_sessions(db, now)

        result = await db.execute(
            select(PresenceSession).order_by(PresenceSession.last_event_at.desc())
        )
        sessions = result.scalars().all()
        return [self._to_response(s) for s in sessions]

    async def update_label(self, session_id: str, label: str, db: AsyncSession) -> Optional[PresenceSessionResponse]:
        result = await db.execute(
            select(PresenceSession).where(PresenceSession.session_id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return None
        session.label = label
        await db.flush()
        return self._to_response(session)

    async def remove_session(self, session_id: str, db: AsyncSession) -> bool:
        result = await db.execute(
            select(PresenceSession).where(PresenceSession.session_id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return False
        await db.delete(session)
        await db.flush()
        return True

    async def clear_all_sessions(self, db: AsyncSession) -> int:
        result = await db.execute(select(PresenceSession))
        sessions = result.scalars().all()
        count = len(sessions)
        for s in sessions:
            await db.delete(s)
        await db.flush()
        return count

    async def _mark_idle_sessions(self, db: AsyncSession, now: datetime):
        cutoff = now - timedelta(minutes=IDLE_TIMEOUT_MINUTES)
        result = await db.execute(
            select(PresenceSession).where(
                PresenceSession.status == "active",
                PresenceSession.last_event_at < cutoff,
            )
        )
        for session in result.scalars().all():
            session.status = "idle"

    def _update_activity_buckets(self, session: PresenceSession, now: datetime):
        buckets = list(session.activity_buckets or [0] * BUCKET_COUNT)
        bucket_start = session.bucket_start

        if not bucket_start:
            session.bucket_start = now
            session.activity_buckets = [0] * (BUCKET_COUNT - 1) + [1]
            return

        # Make bucket_start timezone-aware if it isn't
        if bucket_start.tzinfo is None:
            bucket_start = bucket_start.replace(tzinfo=timezone.utc)

        offset = int((now - bucket_start).total_seconds() / 60)

        if offset >= BUCKET_COUNT:
            shift = offset - BUCKET_COUNT + 1
            buckets = buckets[shift:] + [0] * shift
            session.bucket_start = bucket_start + timedelta(minutes=shift)
            offset = BUCKET_COUNT - 1

        if 0 <= offset < len(buckets):
            buckets[offset] = buckets[offset] + 1

        session.activity_buckets = buckets

    def _derive_label(self, cwd: str) -> str:
        return os.path.basename(cwd.rstrip("/"))

    def _extract_exit_code(self, tool_result: dict) -> Optional[int]:
        # tool_result may have various structures
        if not tool_result:
            return None
        # Check direct exit_code field
        if "exit_code" in tool_result:
            return tool_result["exit_code"]
        # Check content string for exit code pattern
        content = tool_result.get("content", "")
        if isinstance(content, str) and "exit code" in content.lower():
            # Try to parse "exit code N" from the string
            import re
            match = re.search(r'exit code[:\s]+(\d+)', content, re.IGNORECASE)
            if match:
                return int(match.group(1))
        # Check for stderr / error indicators
        if tool_result.get("is_error"):
            return 1
        return 0

    def _to_response(self, session: PresenceSession) -> PresenceSessionResponse:
        return PresenceSessionResponse(
            session_id=session.session_id,
            label=session.label,
            project_path=session.project_path,
            status=session.status,
            last_narrative=session.last_narrative,
            last_narrative_at=session.last_narrative_at.isoformat() if session.last_narrative_at else None,
            modified_files=session.modified_files,
            last_command=session.last_command,
            last_command_exit=session.last_command_exit,
            activity_buckets=session.activity_buckets,
            total_events=session.total_events or 0,
            error_count=session.error_count or 0,
            started_at=session.started_at.isoformat() if session.started_at else datetime.now(timezone.utc).isoformat(),
            last_event_at=session.last_event_at.isoformat() if session.last_event_at else datetime.now(timezone.utc).isoformat(),
            ended_at=session.ended_at.isoformat() if session.ended_at else None,
        )
