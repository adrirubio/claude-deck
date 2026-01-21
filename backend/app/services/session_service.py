"""Service for managing Claude Code session transcripts.

Session parsing logic adapted from claude-code-transcripts by Simon Willison
https://github.com/simonw/claude-code-transcripts
Licensed under Apache 2.0
"""
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import aiofiles

from app.models.database import SessionCache
from app.models.schemas import (
    SessionSummary, SessionDetail, SessionProject,
    SessionConversation, SessionMessage, ContentBlock,
    SessionStatsResponse, SessionListResponse, SessionProjectListResponse,
    SessionDetailResponse
)
from app.utils.path_utils import get_claude_projects_dir, get_project_display_name


class SessionService:
    """Service for session transcript management."""

    CACHE_TTL_MINUTES = 5
    PROMPTS_PER_PAGE = 5

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.projects_dir = get_claude_projects_dir()

    # === Cache Management ===

    async def get_file_hash(self, filepath: Path) -> str:
        """Calculate file hash for cache invalidation."""
        stat = filepath.stat()
        return hashlib.md5(f"{stat.st_size}:{stat.st_mtime}".encode()).hexdigest()

    async def get_cached_summary(self, session_id: str, project_folder: str) -> Optional[SessionSummary]:
        """Get session summary from cache if valid."""
        if not self.db:
            return None

        result = await self.db.execute(
            select(SessionCache).where(
                SessionCache.session_id == session_id,
                SessionCache.project_folder == project_folder
            )
        )
        cache_entry = result.scalar_one_or_none()

        if not cache_entry:
            return None

        # Check if cache is stale
        if datetime.utcnow() - cache_entry.cached_at > timedelta(minutes=self.CACHE_TTL_MINUTES):
            return None

        # Check if file changed
        filepath = self.projects_dir / project_folder / f"{session_id}.jsonl"
        if not filepath.exists():
            return None

        file_hash = await self.get_file_hash(filepath)
        if file_hash != cache_entry.file_hash:
            return None

        return SessionSummary(
            id=cache_entry.session_id,
            project_folder=cache_entry.project_folder,
            project_name=cache_entry.project_name,
            summary=cache_entry.summary,
            modified_at=cache_entry.modified_at.isoformat(),
            size_bytes=cache_entry.size_bytes,
            total_messages=cache_entry.total_messages,
            total_tool_calls=cache_entry.total_tool_calls,
        )

    async def save_to_cache(self, summary: SessionSummary, filepath: Path):
        """Save session summary to cache."""
        if not self.db:
            return

        file_hash = await self.get_file_hash(filepath)

        # Upsert cache entry
        result = await self.db.execute(
            select(SessionCache).where(
                SessionCache.session_id == summary.id,
                SessionCache.project_folder == summary.project_folder
            )
        )
        cache_entry = result.scalar_one_or_none()

        if cache_entry:
            cache_entry.summary = summary.summary
            cache_entry.modified_at = datetime.fromisoformat(summary.modified_at)
            cache_entry.size_bytes = summary.size_bytes
            cache_entry.total_messages = summary.total_messages
            cache_entry.total_tool_calls = summary.total_tool_calls
            cache_entry.cached_at = datetime.utcnow()
            cache_entry.file_hash = file_hash
        else:
            cache_entry = SessionCache(
                session_id=summary.id,
                project_folder=summary.project_folder,
                project_name=summary.project_name,
                summary=summary.summary,
                modified_at=datetime.fromisoformat(summary.modified_at),
                size_bytes=summary.size_bytes,
                total_messages=summary.total_messages,
                total_tool_calls=summary.total_tool_calls,
                file_hash=file_hash,
            )
            self.db.add(cache_entry)

        await self.db.commit()

    # === JSONL Parsing ===

    def extract_text_from_content(self, content: Any) -> str:
        """Extract text from content (string or array of blocks)."""
        if isinstance(content, str):
            return content.strip()
        elif isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        texts.append(text)
            return " ".join(texts).strip()
        return ""

    async def parse_jsonl_file(self, filepath: Path) -> List[Dict[str, Any]]:
        """Parse JSONL file into list of entry objects."""
        entries = []
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    entries.append(obj)
                except json.JSONDecodeError:
                    continue
        return entries

    async def get_session_summary_text(self, entries: List[Dict]) -> str:
        """Extract summary from parsed JSONL entries."""
        # First pass: look for summary type
        for obj in entries:
            if obj.get("type") == "summary" and obj.get("summary"):
                summary = obj["summary"]
                if len(summary) > 200:
                    return summary[:197] + "..."
                return summary

        # Second pass: first user message
        for obj in entries:
            if (obj.get("type") == "user" and
                not obj.get("isMeta") and
                obj.get("message", {}).get("content")):
                content = obj["message"]["content"]
                text = self.extract_text_from_content(content)
                if text and not text.startswith("<"):
                    if len(text) > 200:
                        return text[:197] + "..."
                    return text

        return "(no summary)"

    async def parse_session_to_conversations(self, entries: List[Dict]) -> List[SessionConversation]:
        """Convert JSONL entries to conversation objects."""
        conversations = []
        current_convo = None

        for obj in entries:
            obj_type = obj.get("type")

            if obj_type == "user" and not obj.get("isMeta"):
                # Start new conversation
                if current_convo:
                    conversations.append(current_convo)

                message_data = obj.get("message", {})
                content = message_data.get("content", "")
                user_text = self.extract_text_from_content(content)

                current_convo = {
                    "user_text": user_text[:100] + "..." if len(user_text) > 100 else user_text,
                    "timestamp": obj.get("timestamp", ""),
                    "messages": [self._build_session_message(obj)],
                    "is_continuation": False,
                }

            elif obj_type == "assistant" and current_convo:
                # Add assistant response to current conversation
                current_convo["messages"].append(self._build_session_message(obj))

        if current_convo:
            conversations.append(current_convo)

        return [SessionConversation(**c) for c in conversations]

    def _build_session_message(self, obj: Dict) -> SessionMessage:
        """Build SessionMessage from JSONL entry."""
        message_data = obj.get("message", {})
        content = message_data.get("content", [])

        # Normalize content to list of blocks
        content_blocks = []
        if isinstance(content, str):
            content_blocks = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            content_blocks = content

        # Parse content blocks
        parsed_blocks = []
        for block in content_blocks:
            if isinstance(block, dict):
                parsed_blocks.append(ContentBlock(**block))

        return SessionMessage(
            type=obj.get("type", "user"),
            timestamp=obj.get("timestamp", ""),
            content=parsed_blocks,
            model=message_data.get("model"),
            usage=message_data.get("usage"),
        )

    # === Public API Methods ===

    async def list_projects(self) -> SessionProjectListResponse:
        """List all projects with session counts."""
        projects_map = {}
        total_sessions = 0

        if not self.projects_dir.exists():
            return SessionProjectListResponse(projects=[], total_sessions=0)

        for project_folder in self.projects_dir.iterdir():
            if not project_folder.is_dir():
                continue

            jsonl_files = list(project_folder.glob("*.jsonl"))
            if not jsonl_files:
                continue

            session_count = len(jsonl_files)
            most_recent = max(f.stat().st_mtime for f in jsonl_files)

            projects_map[project_folder.name] = SessionProject(
                folder=project_folder.name,
                name=get_project_display_name(project_folder.name),
                session_count=session_count,
                most_recent=datetime.fromtimestamp(most_recent).isoformat(),
            )
            total_sessions += session_count

        projects = sorted(projects_map.values(), key=lambda p: p.most_recent, reverse=True)
        return SessionProjectListResponse(projects=projects, total_sessions=total_sessions)

    async def list_sessions(
        self,
        project_folder: Optional[str] = None,
        limit: int = 50,
        sort_by: str = "date",
        sort_order: str = "desc",
    ) -> SessionListResponse:
        """List session summaries with optional project filter."""
        sessions = []

        if not self.projects_dir.exists():
            return SessionListResponse(sessions=[], total=0)

        # Determine which project folders to scan
        if project_folder:
            folders = [self.projects_dir / project_folder]
        else:
            folders = [f for f in self.projects_dir.iterdir() if f.is_dir()]

        for folder in folders:
            if not folder.exists():
                continue

            for jsonl_file in folder.glob("*.jsonl"):
                session_id = jsonl_file.stem

                # Try cache first
                cached = await self.get_cached_summary(session_id, folder.name)
                if cached:
                    sessions.append(cached)
                    continue

                # Parse file for summary
                stat = jsonl_file.stat()
                entries = await self.parse_jsonl_file(jsonl_file)
                summary_text = await self.get_session_summary_text(entries)

                # Count messages and tool calls
                total_messages = sum(1 for e in entries if e.get("type") in ("user", "assistant"))
                total_tool_calls = sum(
                    1 for e in entries
                    if e.get("type") == "assistant"
                    for block in e.get("message", {}).get("content", [])
                    if isinstance(block, dict) and block.get("type") == "tool_use"
                )

                summary = SessionSummary(
                    id=session_id,
                    project_folder=folder.name,
                    project_name=get_project_display_name(folder.name),
                    summary=summary_text,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    size_bytes=stat.st_size,
                    total_messages=total_messages,
                    total_tool_calls=total_tool_calls,
                )

                sessions.append(summary)
                await self.save_to_cache(summary, jsonl_file)

        # Sort
        reverse = (sort_order == "desc")
        if sort_by == "date":
            sessions.sort(key=lambda s: s.modified_at, reverse=reverse)
        elif sort_by == "size":
            sessions.sort(key=lambda s: s.size_bytes, reverse=reverse)

        # Limit
        total = len(sessions)
        sessions = sessions[:limit]

        return SessionListResponse(sessions=sessions, total=total)

    async def get_session_detail(
        self,
        session_id: str,
        project_folder: str,
        page: int = 1,
    ) -> SessionDetailResponse:
        """Get full session detail with pagination."""
        filepath = self.projects_dir / project_folder / f"{session_id}.jsonl"

        if not filepath.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        entries = await self.parse_jsonl_file(filepath)
        conversations = await self.parse_session_to_conversations(entries)

        # Pagination
        total_pages = (len(conversations) + self.PROMPTS_PER_PAGE - 1) // self.PROMPTS_PER_PAGE
        start_idx = (page - 1) * self.PROMPTS_PER_PAGE
        end_idx = start_idx + self.PROMPTS_PER_PAGE
        paginated_conversations = conversations[start_idx:end_idx]

        # Calculate stats
        total_messages = sum(1 for e in entries if e.get("type") in ("user", "assistant"))
        total_tool_calls = sum(
            1 for e in entries
            if e.get("type") == "assistant"
            for block in e.get("message", {}).get("content", [])
            if isinstance(block, dict) and block.get("type") == "tool_use"
        )

        # Extract models used
        models_used = list(set(
            e.get("message", {}).get("model")
            for e in entries
            if e.get("type") == "assistant" and e.get("message", {}).get("model")
        ))

        detail = SessionDetail(
            id=session_id,
            project_folder=project_folder,
            project_name=get_project_display_name(project_folder),
            conversations=paginated_conversations,
            total_messages=total_messages,
            total_tool_calls=total_tool_calls,
            models_used=models_used,
        )

        return SessionDetailResponse(
            session=detail,
            current_page=page,
            total_pages=total_pages,
            prompts_per_page=self.PROMPTS_PER_PAGE,
        )

    async def get_dashboard_stats(self) -> SessionStatsResponse:
        """Get session statistics for dashboard."""
        all_sessions = await self.list_sessions(limit=10000)

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        sessions_today = sum(
            1 for s in all_sessions.sessions
            if datetime.fromisoformat(s.modified_at) >= today_start
        )

        sessions_this_week = sum(
            1 for s in all_sessions.sessions
            if datetime.fromisoformat(s.modified_at) >= week_start
        )

        # Most active project
        project_counts = {}
        for s in all_sessions.sessions:
            project_counts[s.project_name] = project_counts.get(s.project_name, 0) + 1

        most_active = max(project_counts.items(), key=lambda x: x[1])[0] if project_counts else None

        total_messages = sum(s.total_messages for s in all_sessions.sessions)

        return SessionStatsResponse(
            total_sessions=all_sessions.total,
            sessions_today=sessions_today,
            sessions_this_week=sessions_this_week,
            most_active_project=most_active,
            total_messages=total_messages,
        )
