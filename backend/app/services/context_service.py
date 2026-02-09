"""Service for context window analysis of Claude Code sessions."""
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Any, List, Optional

import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import (
    ActiveSessionContext,
    ActiveSessionsResponse,
    CacheEfficiency,
    ContentCategory,
    ContextAnalysis,
    ContextAnalysisResponse,
    ContextCategoryItem,
    ContextComposition,
    ContextCompositionCategory,
    ContextSnapshot,
    FileConsumption,
)
from app.utils.path_utils import get_claude_projects_dir, get_project_display_name


# Model context window limits (input tokens)
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    # Older models
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
}
DEFAULT_CONTEXT_LIMIT = 200_000
ACTIVE_SESSION_THRESHOLD_SECONDS = 600  # 10 minutes
CHARS_PER_TOKEN_ESTIMATE = 4


def get_context_limit(model: str) -> int:
    """Get context window limit for a model."""
    # Try exact match first
    if model in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model]
    # Try prefix match
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return limit
    return DEFAULT_CONTEXT_LIMIT


def get_context_zone(percentage: float) -> str:
    """Get context zone label from percentage."""
    if percentage >= 95:
        return "red"
    elif percentage >= 80:
        return "orange"
    elif percentage >= 50:
        return "yellow"
    return "green"


class ContextService:
    """Service for context window analysis."""

    def __init__(self):
        self.projects_dir = get_claude_projects_dir()

    async def _parse_jsonl_file(self, filepath: Path) -> List[dict[str, Any]]:
        """Parse JSONL file into list of entries."""
        entries = []
        try:
            async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return entries

    def _extract_usage(self, entry: dict) -> Optional[dict]:
        """Extract usage dict from an assistant entry."""
        if entry.get("type") != "assistant":
            return None
        message = entry.get("message", {})
        usage = message.get("usage", {})
        if not usage:
            return None
        return usage

    def _get_total_input_context(self, usage: dict) -> int:
        """Calculate total context tokens from usage.

        Each assistant message's usage represents the full prompt size:
        cache_read + cache_creation + input_tokens = total context for that call.
        """
        return (
            usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("input_tokens", 0)
        )

    async def get_active_sessions(self) -> ActiveSessionsResponse:
        """Get context info for all recently active sessions."""
        sessions: List[ActiveSessionContext] = []

        if not self.projects_dir.exists():
            return ActiveSessionsResponse(sessions=[])

        now = time.time()

        for project_folder in self.projects_dir.iterdir():
            if not project_folder.is_dir():
                continue

            for jsonl_file in project_folder.glob("*.jsonl"):
                try:
                    mtime = jsonl_file.stat().st_mtime
                except OSError:
                    continue

                age_seconds = now - mtime
                is_active = age_seconds <= ACTIVE_SESSION_THRESHOLD_SECONDS

                # Only include sessions modified within the last hour for the list
                if age_seconds > 3600:
                    continue

                # Quick scan: read last few KB to find the last assistant message
                usage_data = await self._get_last_assistant_usage(jsonl_file)
                if not usage_data:
                    continue

                usage = usage_data["usage"]
                model = usage_data["model"]
                timestamp = usage_data["timestamp"]

                total_context = self._get_total_input_context(usage)
                max_context = get_context_limit(model)
                percentage = min(100.0, (total_context / max_context) * 100) if max_context > 0 else 0

                sessions.append(
                    ActiveSessionContext(
                        session_id=jsonl_file.stem,
                        project_folder=project_folder.name,
                        project_name=get_project_display_name(project_folder.name),
                        model=model,
                        context_percentage=round(percentage, 1),
                        current_context_tokens=total_context,
                        max_context_tokens=max_context,
                        is_active=is_active,
                        last_activity=timestamp,
                    )
                )

        # Sort: active first, then by context percentage descending
        sessions.sort(key=lambda s: (not s.is_active, -s.context_percentage))
        return ActiveSessionsResponse(sessions=sessions)

    async def _get_last_assistant_usage(self, filepath: Path) -> Optional[dict]:
        """Read last assistant usage from a JSONL file efficiently.

        Reads the last 32KB of the file to find the most recent assistant message.
        """
        try:
            file_size = filepath.stat().st_size
            read_size = min(file_size, 32 * 1024)

            async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                if file_size > read_size:
                    await f.seek(file_size - read_size)
                    # Skip partial first line
                    await f.readline()
                content = await f.read()

            # Parse lines in reverse to find last assistant message with usage
            lines = content.strip().split("\n")
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "assistant":
                    continue

                message = obj.get("message", {})
                usage = message.get("usage")
                if not usage:
                    continue

                return {
                    "usage": usage,
                    "model": message.get("model", "unknown"),
                    "timestamp": obj.get("timestamp", ""),
                }
        except Exception:
            pass
        return None

    async def get_context_composition(
        self,
        project_folder: str,
        session_id: str,
        model: str,
        current_context_tokens: int,
        db: Optional[AsyncSession] = None,
        message_chars: int = 0,
    ) -> Optional[ContextComposition]:
        """Estimate context composition breakdown like /context CLI.

        Uses local estimation (chars // 4) from existing services.
        Messages are estimated from actual JSONL content; System & Tools
        is derived as the residual.
        """
        from app.services.mcp_service import MCPService
        from app.services.agent_service import AgentService
        from app.services.memory_service import MemoryService

        context_limit = get_context_limit(model)

        # Derive project_path from folder name
        # Folder names are like '-home-user-project' → '/home/user/project'
        project_path: Optional[str] = None
        if project_folder and project_folder.startswith("-"):
            project_path = project_folder.replace("-", "/", 1)
            # Remaining dashes are path separators
            project_path = "/" + project_folder[1:].replace("-", "/")

        autocompact_buffer = int(context_limit * 0.165)

        # --- MCP Tools ---
        mcp_items: List[ContextCategoryItem] = []
        mcp_total = 0
        try:
            mcp_service = MCPService()
            servers = await mcp_service.list_servers(project_path, db)
            for server in servers:
                if server.disabled:
                    continue
                if server.tools:
                    for tool in server.tools:
                        tool_json = json.dumps({
                            "name": tool.name,
                            "description": tool.description or "",
                            "inputSchema": tool.inputSchema or {},
                        })
                        tokens = len(tool_json) // CHARS_PER_TOKEN_ESTIMATE
                        mcp_items.append(ContextCategoryItem(name=f"{server.name}:{tool.name}", estimated_tokens=tokens))
                        mcp_total += tokens
                elif server.tool_count and server.tool_count > 0:
                    # No cached tool details but we know count — rough estimate
                    est = server.tool_count * 150  # ~150 tokens per tool
                    mcp_items.append(ContextCategoryItem(name=server.name, estimated_tokens=est))
                    mcp_total += est
        except Exception:
            pass

        # --- Custom Agents ---
        agent_items: List[ContextCategoryItem] = []
        agent_total = 0
        try:
            agents = AgentService.list_agents(project_path)
            for agent in agents:
                tokens = len(agent.prompt) // CHARS_PER_TOKEN_ESTIMATE
                agent_items.append(ContextCategoryItem(name=agent.name, estimated_tokens=tokens))
                agent_total += tokens
        except Exception:
            pass

        # --- Memory Files ---
        memory_items: List[ContextCategoryItem] = []
        memory_total = 0
        try:
            hierarchy = MemoryService.get_memory_hierarchy(project_path)
            for mem_file in hierarchy:
                if not mem_file.get("exists"):
                    continue
                file_data = MemoryService.get_memory_file(mem_file["path"])
                content = file_data.get("content")
                if content:
                    tokens = len(content) // CHARS_PER_TOKEN_ESTIMATE
                    # Use a short display name
                    display = mem_file.get("scope", "file")
                    if mem_file.get("type") == "rule":
                        display = f"rule:{mem_file.get('name', 'unknown')}"
                    else:
                        display = f"{mem_file['scope']}:CLAUDE.md"
                    memory_items.append(ContextCategoryItem(name=display, estimated_tokens=tokens))
                    memory_total += tokens
        except Exception:
            pass

        # --- Skills ---
        skill_items: List[ContextCategoryItem] = []
        skill_total = 0
        try:
            skills = AgentService.list_skills(project_path)
            for skill in skills:
                detail = AgentService.get_skill(skill.name, skill.location, project_path)
                if detail and detail.content:
                    tokens = len(detail.content) // CHARS_PER_TOKEN_ESTIMATE
                    skill_items.append(ContextCategoryItem(name=skill.name, estimated_tokens=tokens))
                    skill_total += tokens
        except Exception:
            pass

        # --- Messages (estimated from JSONL content) ---
        messages_tokens = message_chars // CHARS_PER_TOKEN_ESTIMATE

        # --- System & Tools (derived as residual) ---
        system_and_tools_tokens = max(
            0,
            current_context_tokens - messages_tokens - mcp_total - agent_total - memory_total - skill_total,
        )

        # --- Free Space ---
        free_space = max(0, context_limit - current_context_tokens - autocompact_buffer)

        # Build categories
        categories: List[ContextCompositionCategory] = []

        def _add(name: str, tokens: int, color: str, items: Optional[List[ContextCategoryItem]] = None):
            pct = (tokens / context_limit * 100) if context_limit > 0 else 0
            if tokens > 0 or name in ("Free Space",):
                categories.append(ContextCompositionCategory(
                    category=name,
                    estimated_tokens=tokens,
                    percentage=round(pct, 1),
                    color=color,
                    items=items if items else None,
                ))

        _add("System & Tools", system_and_tools_tokens, "#888888")
        _add("MCP Tools", mcp_total, "#0891b2", mcp_items)
        _add("Custom Agents", agent_total, "#b1b9f9", agent_items)
        _add("Memory Files", memory_total, "#d77757", memory_items)
        _add("Skills", skill_total, "#ffc107", skill_items)
        _add("Messages", messages_tokens, "#9333ea")
        _add("Autocompact Buffer", autocompact_buffer, "#555555")
        _add("Free Space", free_space, "#333333")

        total_tokens = sum(c.estimated_tokens for c in categories)

        return ContextComposition(
            categories=categories,
            total_tokens=total_tokens,
            context_limit=context_limit,
            model=model,
        )

    async def analyze_session(
        self, project_folder: str, session_id: str, db: Optional[AsyncSession] = None
    ) -> ContextAnalysisResponse:
        """Full context analysis for a session."""
        filepath = self.projects_dir / project_folder / f"{session_id}.jsonl"

        if not filepath.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        entries = await self._parse_jsonl_file(filepath)

        # Build timeline snapshots
        snapshots: List[ContextSnapshot] = []
        turn_number = 0
        model = "unknown"
        last_usage: Optional[dict] = None

        # Content categorization
        user_chars = 0
        assistant_chars = 0
        tool_result_chars = 0
        tool_call_chars = 0
        thinking_chars = 0

        # File tracking
        file_reads: dict[str, dict] = {}  # path -> {count, chars}

        # Cache totals
        total_cache_read = 0
        total_cache_creation = 0
        total_uncached = 0

        for entry in entries:
            entry_type = entry.get("type")
            message = entry.get("message", {})
            content = message.get("content", [])

            if isinstance(content, str):
                content = [{"type": "text", "text": content}]

            if entry_type == "user":
                # Count user message content
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type", "")
                    if block_type == "text":
                        user_chars += len(block.get("text", ""))
                    elif block_type == "tool_result":
                        result_content = block.get("content", "")
                        if isinstance(result_content, str):
                            tool_result_chars += len(result_content)
                        elif isinstance(result_content, list):
                            for rc in result_content:
                                if isinstance(rc, dict) and rc.get("type") == "text":
                                    tool_result_chars += len(rc.get("text", ""))

            elif entry_type == "assistant":
                usage = message.get("usage")
                entry_model = message.get("model", model)
                timestamp = entry.get("timestamp", "")

                # Count assistant content
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type", "")
                    if block_type == "text":
                        assistant_chars += len(block.get("text", ""))
                    elif block_type == "thinking":
                        thinking_chars += len(block.get("thinking", ""))
                    elif block_type == "tool_use":
                        # Track tool call input size
                        tool_input = block.get("input", {})
                        tool_call_chars += len(json.dumps(tool_input))

                        # Track file reads
                        tool_name = block.get("name", "")
                        if tool_name == "Read":
                            file_path = tool_input.get("file_path", "")
                            if file_path:
                                if file_path not in file_reads:
                                    file_reads[file_path] = {"count": 0, "chars": 0}
                                file_reads[file_path]["count"] += 1

                if usage:
                    turn_number += 1
                    model = entry_model
                    last_usage = usage

                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_creation = usage.get("cache_creation_input_tokens", 0)
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    total_context = cache_read + cache_creation + input_tokens

                    total_cache_read += cache_read
                    total_cache_creation += cache_creation
                    total_uncached += input_tokens

                    max_context = get_context_limit(entry_model)
                    percentage = min(100.0, (total_context / max_context) * 100) if max_context > 0 else 0

                    snapshots.append(
                        ContextSnapshot(
                            turn_number=turn_number,
                            timestamp=timestamp,
                            total_context_tokens=total_context,
                            input_tokens=input_tokens,
                            cache_creation_tokens=cache_creation,
                            cache_read_tokens=cache_read,
                            output_tokens=output_tokens,
                            model=entry_model,
                            context_percentage=round(percentage, 1),
                        )
                    )

        # Estimate file read chars from tool_result content
        # Match tool_use Read blocks with subsequent tool_result blocks
        pending_read_path: Optional[str] = None
        for entry in entries:
            entry_type = entry.get("type")
            message = entry.get("message", {})
            content = message.get("content", [])
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]

            if entry_type == "assistant":
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and block.get("name") == "Read":
                        pending_read_path = block.get("input", {}).get("file_path")

            elif entry_type == "user" and pending_read_path:
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        result_content = block.get("content", "")
                        char_count = 0
                        if isinstance(result_content, str):
                            char_count = len(result_content)
                        elif isinstance(result_content, list):
                            for rc in result_content:
                                if isinstance(rc, dict) and rc.get("type") == "text":
                                    char_count += len(rc.get("text", ""))
                        if pending_read_path in file_reads:
                            file_reads[pending_read_path]["chars"] += char_count
                        pending_read_path = None
                        break

        # Build content categories
        total_chars = user_chars + assistant_chars + tool_result_chars + tool_call_chars + thinking_chars
        categories: List[ContentCategory] = []
        for name, chars in [
            ("User Messages", user_chars),
            ("Assistant Messages", assistant_chars),
            ("Tool Results", tool_result_chars),
            ("Tool Calls", tool_call_chars),
            ("Thinking", thinking_chars),
        ]:
            if chars > 0:
                est_tokens = chars // CHARS_PER_TOKEN_ESTIMATE
                pct = (chars / total_chars * 100) if total_chars > 0 else 0
                categories.append(
                    ContentCategory(
                        category=name,
                        estimated_chars=chars,
                        estimated_tokens=est_tokens,
                        percentage=round(pct, 1),
                    )
                )

        # Sort categories by tokens descending
        categories.sort(key=lambda c: c.estimated_tokens, reverse=True)

        # Build file consumption list
        file_consumptions: List[FileConsumption] = []
        for fpath, data in file_reads.items():
            file_consumptions.append(
                FileConsumption(
                    file_path=fpath,
                    read_count=data["count"],
                    total_chars=data["chars"],
                    estimated_tokens=data["chars"] // CHARS_PER_TOKEN_ESTIMATE,
                )
            )
        file_consumptions.sort(key=lambda f: f.estimated_tokens, reverse=True)
        file_consumptions = file_consumptions[:50]  # Top 50

        # Cache efficiency
        total_input_all = total_cache_read + total_cache_creation + total_uncached
        hit_ratio = total_cache_read / total_input_all if total_input_all > 0 else 0
        cache_efficiency = CacheEfficiency(
            total_cache_read=total_cache_read,
            total_cache_creation=total_cache_creation,
            total_uncached=total_uncached,
            hit_ratio=round(hit_ratio, 3),
        )

        # Current state from last snapshot
        max_context = get_context_limit(model)
        current_context = 0
        context_percentage = 0.0
        if snapshots:
            current_context = snapshots[-1].total_context_tokens
            context_percentage = snapshots[-1].context_percentage

        # Projections
        avg_tokens_per_turn = 0
        estimated_turns_remaining = 0
        if len(snapshots) >= 2:
            # Use token growth between turns
            growths = []
            for i in range(1, len(snapshots)):
                growth = snapshots[i].total_context_tokens - snapshots[i - 1].total_context_tokens
                if growth > 0:
                    growths.append(growth)
            if growths:
                avg_tokens_per_turn = sum(growths) // len(growths)
                remaining_tokens = max_context - current_context
                if avg_tokens_per_turn > 0:
                    estimated_turns_remaining = max(0, remaining_tokens // avg_tokens_per_turn)
        elif len(snapshots) == 1:
            avg_tokens_per_turn = current_context
            remaining_tokens = max_context - current_context
            if avg_tokens_per_turn > 0:
                estimated_turns_remaining = max(0, remaining_tokens // avg_tokens_per_turn)

        # Get context composition breakdown
        # Exclude thinking_chars — thinking is output, not carried in input context
        conversation_chars = user_chars + assistant_chars + tool_result_chars + tool_call_chars
        composition = None
        try:
            composition = await self.get_context_composition(
                project_folder=project_folder,
                session_id=session_id,
                model=model,
                current_context_tokens=current_context,
                db=db,
                message_chars=conversation_chars,
            )
        except Exception:
            pass  # Composition is best-effort

        analysis = ContextAnalysis(
            session_id=session_id,
            project_folder=project_folder,
            project_name=get_project_display_name(project_folder),
            model=model,
            current_context_tokens=current_context,
            max_context_tokens=max_context,
            context_percentage=round(context_percentage, 1),
            snapshots=snapshots,
            content_categories=categories,
            file_consumptions=file_consumptions,
            cache_efficiency=cache_efficiency,
            avg_tokens_per_turn=avg_tokens_per_turn,
            estimated_turns_remaining=estimated_turns_remaining,
            context_zone=get_context_zone(context_percentage),
            total_turns=turn_number,
            composition=composition,
        )

        return ContextAnalysisResponse(analysis=analysis)
