"""Service for Presence Dashboard — event processing and session aggregation."""
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Union

from fastapi import WebSocket
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.constants import SessionStatus
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

IDLE_TIMEOUT_MINUTES = 15
BUCKET_COUNT = 30
FILE_EDIT_TOOLS = {"Write", "Edit", "MultiEdit"}
EVENT_RETENTION_DAYS = 7
IDLE_CHECK_INTERVAL_SECONDS = 30  # throttle idle checks


class PresenceService:
    """Processes webhook events and maintains aggregated session state."""

    _last_idle_check: float = 0.0
    _last_prune: float = 0.0

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
                status=SessionStatus.ACTIVE,
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
            base_label = self._derive_label(cwd)
            session.label = await self._assign_unique_label(base_label, session_id, db)

        # Update based on event type
        if event_type == "Notification":
            msg = payload.get("message")
            if msg:
                # Skip generic "waiting" notifications — redundant with Stop event
                waiting_phrases = ("waiting for your input", "waiting for input")
                if not any(p in msg.lower() for p in waiting_phrases):
                    session.last_narrative = msg
                    session.last_narrative_at = now
                    session.status_text = msg.replace("\n", " ").strip()[:120]

        elif event_type == "PostToolUse":
            tool_name = payload.get("tool_name", "")
            tool_input = payload.get("tool_input") or {}
            tool_result = payload.get("tool_result") or {}

            if tool_name in FILE_EDIT_TOOLS:
                file_path = tool_input.get("file_path") or tool_input.get("path")
                if file_path:
                    # Write can also overwrite existing files, but we label it "created" for simplicity
                    op = "created" if tool_name == "Write" else "modified"
                    files = list(session.modified_files or [])
                    files = [f for f in files if self._get_file_path(f) != file_path]
                    files.append({"path": file_path, "op": op})
                    session.modified_files = files[-10:]
                    basename = os.path.basename(file_path)
                    session.status_text = f"Edited {basename}"
                else:
                    session.status_text = f"Used tool: {tool_name}"
            elif tool_name == "Bash":
                cmd = tool_input.get("command", "")
                session.last_command = cmd[:500] if cmd else None
                exit_code = self._extract_exit_code(tool_result)
                session.last_command_exit = exit_code
                if exit_code and exit_code != 0:
                    session.error_count = (session.error_count or 0) + 1
                    session.status = SessionStatus.ERROR
                session.status_text = "Ran command"
            else:
                session.status_text = f"Used tool: {tool_name}"

        elif event_type == "PreToolUse":
            tool_name = payload.get("tool_name", "unknown")
            session.status_text = f"Running tool: {tool_name}..."

        elif event_type == "UserPromptSubmit":
            msg = payload.get("user_prompt") or payload.get("message")
            if msg:
                session.last_user_prompt = msg.strip()[:500]
            session.status_text = "Processing user message..."

        elif event_type == "SubagentStart":
            session.status_text = "Started subagent"

        elif event_type == "SubagentStop":
            session.status_text = "Subagent completed"

        elif event_type == "Stop":
            session.status = SessionStatus.STOPPED
            session.status_text = "Waiting for input"

        elif event_type == "SessionEnd":
            session.status = SessionStatus.STOPPED
            session.ended_at = now
            session.status_text = "Session ended"

        elif event_type == "SessionStart":
            session.status = SessionStatus.ACTIVE
            session.ended_at = None
            session.started_at = now
            session.total_events = 0
            session.error_count = 0
            session.modified_files = []
            session.last_narrative = None
            session.last_user_prompt = None
            session.last_command = None
            session.last_command_exit = None
            session.activity_buckets = [0] * BUCKET_COUNT
            session.bucket_start = now
            session.status_text = "Session started"

        # Common updates for all events
        session.last_event_at = now
        session.total_events = (session.total_events or 0) + 1

        # Reactivate if we get an event for a stopped/idle session (except passive events)
        if event_type not in ("Stop", "SessionEnd", "Notification", "SubagentStop") and session.status in (SessionStatus.IDLE, SessionStatus.STOPPED):
            session.status = SessionStatus.ACTIVE
            session.ended_at = None

        # Update activity buckets
        self._update_activity_buckets(session, now)

        await db.flush()

        # Throttled maintenance: idle check + event pruning (not on every event)
        await self._maybe_run_maintenance(db, now)

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

    async def _maybe_run_maintenance(self, db: AsyncSession, now: datetime):
        """Run idle check and event pruning, throttled to avoid per-event overhead."""
        current = time.monotonic()

        if current - PresenceService._last_idle_check >= IDLE_CHECK_INTERVAL_SECONDS:
            PresenceService._last_idle_check = current
            await self._mark_idle_sessions(db, now)

        # Prune old events once per hour
        if current - PresenceService._last_prune >= 3600:
            PresenceService._last_prune = current
            await self._prune_old_events(db, now)

    async def _mark_idle_sessions(self, db: AsyncSession, now: datetime):
        cutoff = now - timedelta(minutes=IDLE_TIMEOUT_MINUTES)
        result = await db.execute(
            select(PresenceSession).where(
                PresenceSession.status == SessionStatus.ACTIVE,
                PresenceSession.last_event_at < cutoff,
            )
        )
        for session in result.scalars().all():
            session.status = SessionStatus.IDLE
            session.status_text = None

    async def _prune_old_events(self, db: AsyncSession, now: datetime):
        """Delete presence events older than retention period."""
        cutoff = now - timedelta(days=EVENT_RETENTION_DAYS)
        await db.execute(
            delete(PresenceEvent).where(PresenceEvent.timestamp < cutoff)
        )
        await db.flush()

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

    async def _assign_unique_label(self, base_label: str, session_id: str, db: AsyncSession) -> str:
        """Append a short session_id suffix if another session already uses this label."""
        result = await db.execute(
            select(PresenceSession).where(
                PresenceSession.label == base_label,
                PresenceSession.session_id != session_id,
            )
        )
        existing = result.scalars().all()
        if existing:
            for s in existing:
                s.label = f"{base_label} ({s.session_id[:6]})"
            return f"{base_label} ({session_id[:6]})"
        return base_label

    def _get_file_path(self, entry: Union[str, dict]) -> str:
        """Extract path from either a string (legacy) or dict (new format)."""
        if isinstance(entry, str):
            return entry
        return entry.get("path", "")

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
            status_text=session.status_text,
            last_narrative=session.last_narrative,
            last_narrative_at=session.last_narrative_at.isoformat() if session.last_narrative_at else None,
            modified_files=session.modified_files,
            last_user_prompt=session.last_user_prompt,
            last_command=session.last_command,
            last_command_exit=session.last_command_exit,
            activity_buckets=session.activity_buckets,
            total_events=session.total_events or 0,
            error_count=session.error_count or 0,
            started_at=session.started_at.isoformat() if session.started_at else datetime.now(timezone.utc).isoformat(),
            last_event_at=session.last_event_at.isoformat() if session.last_event_at else datetime.now(timezone.utc).isoformat(),
            ended_at=session.ended_at.isoformat() if session.ended_at else None,
        )
