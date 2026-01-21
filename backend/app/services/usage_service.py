"""Service for usage data loading and aggregation.

Usage tracking algorithms adapted from ccusage by ryoppippi
https://github.com/ryoppippi/ccusage
Licensed under MIT
"""
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import UsageCache
from app.models.schemas import (
    DailyUsage,
    DailyUsageListResponse,
    ModelBreakdown,
    MonthlyUsage,
    MonthlyUsageListResponse,
    SessionBlock,
    SessionUsage,
    SessionUsageListResponse,
    BlockUsageListResponse,
    TokenCounts,
    UsageSummary,
    UsageSummaryResponse,
)
from app.services.pricing_service import PricingService
from app.utils.path_utils import get_claude_projects_dir, get_project_display_name


@dataclass
class LoadedUsageEntry:
    """A single usage entry from JSONL files."""

    timestamp: datetime
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: Optional[float]
    model: str
    session_id: Optional[str]
    version: Optional[str]
    project_path: str


class UsageService:
    """Service for usage data loading and aggregation."""

    CACHE_TTL_MINUTES = 5
    SESSION_DURATION_HOURS = 5  # Claude billing block duration
    DEFAULT_RECENT_DAYS = 3

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.pricing = PricingService()
        self.projects_dir = get_claude_projects_dir()

    # === Cache Management ===

    async def get_cache_key(
        self,
        cache_type: str,
        project_path: Optional[str] = None,
        **params: Any,
    ) -> str:
        """Generate cache key for query."""
        key_parts = [cache_type]
        if project_path:
            key_parts.append(f"project:{project_path}")
        for k, v in sorted(params.items()):
            if v is not None:
                key_parts.append(f"{k}:{v}")
        return ":".join(key_parts)

    async def get_from_cache(self, cache_key: str) -> Optional[dict]:
        """Get data from cache if valid."""
        if not self.db:
            return None

        result = await self.db.execute(
            select(UsageCache).where(UsageCache.cache_key == cache_key)
        )
        cache_entry = result.scalar_one_or_none()

        if not cache_entry:
            return None

        # Check if cache is stale
        if datetime.now(timezone.utc) - cache_entry.cached_at.replace(tzinfo=timezone.utc) > timedelta(
            minutes=self.CACHE_TTL_MINUTES
        ):
            return None

        return cache_entry.data

    async def save_to_cache(
        self,
        cache_key: str,
        cache_type: str,
        data: dict,
        project_path: Optional[str] = None,
    ):
        """Save data to cache."""
        if not self.db:
            return

        # Upsert cache entry
        result = await self.db.execute(
            select(UsageCache).where(UsageCache.cache_key == cache_key)
        )
        cache_entry = result.scalar_one_or_none()

        if cache_entry:
            cache_entry.data = data
            cache_entry.cached_at = datetime.now(timezone.utc)
        else:
            cache_entry = UsageCache(
                cache_key=cache_key,
                cache_type=cache_type,
                project_path=project_path,
                data=data,
            )
            self.db.add(cache_entry)

        await self.db.commit()

    async def invalidate_cache(
        self,
        cache_type: Optional[str] = None,
        project_path: Optional[str] = None,
    ):
        """Invalidate cache entries."""
        if not self.db:
            return

        query = delete(UsageCache)
        if cache_type:
            query = query.where(UsageCache.cache_type == cache_type)
        if project_path:
            query = query.where(UsageCache.project_path == project_path)

        await self.db.execute(query)
        await self.db.commit()

    # === JSONL Parsing ===

    async def discover_jsonl_files(
        self, project_path: Optional[str] = None
    ) -> list[Path]:
        """Discover all JSONL files in projects directory."""
        files = []

        if not self.projects_dir.exists():
            return files

        if project_path:
            # Scan specific project folder
            project_folder = self.projects_dir / project_path
            if project_folder.exists():
                files.extend(project_folder.glob("*.jsonl"))
        else:
            # Scan all project folders
            for project_folder in self.projects_dir.iterdir():
                if project_folder.is_dir():
                    files.extend(project_folder.glob("*.jsonl"))

        return files

    async def parse_usage_from_jsonl(self, filepath: Path) -> list[LoadedUsageEntry]:
        """Parse usage entries from a JSONL file.

        Extracts usage data from assistant messages in the JSONL file.
        """
        entries = []
        project_folder = filepath.parent.name

        try:
            async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Only process assistant messages with usage data
                    if obj.get("type") != "assistant":
                        continue

                    message = obj.get("message", {})
                    usage = message.get("usage", {})

                    if not usage:
                        continue

                    # Extract token counts
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cache_creation = usage.get("cache_creation_input_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)

                    # Skip entries with no tokens
                    if (
                        input_tokens == 0
                        and output_tokens == 0
                        and cache_creation == 0
                        and cache_read == 0
                    ):
                        continue

                    # Parse timestamp
                    timestamp_str = obj.get("timestamp", "")
                    try:
                        timestamp = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        continue

                    # Get model name
                    model = message.get("model", "unknown")

                    # Get cost if available
                    cost_usd = obj.get("costUSD")

                    # Get session info
                    session_id = obj.get("sessionId")
                    version = obj.get("version")

                    entries.append(
                        LoadedUsageEntry(
                            timestamp=timestamp,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cache_creation_tokens=cache_creation,
                            cache_read_tokens=cache_read,
                            cost_usd=cost_usd,
                            model=model,
                            session_id=session_id or filepath.stem,
                            version=version,
                            project_path=project_folder,
                        )
                    )
        except Exception:
            pass  # Skip files that can't be read

        return entries

    async def get_all_usage_entries(
        self, project_path: Optional[str] = None
    ) -> list[LoadedUsageEntry]:
        """Load all usage entries from JSONL files."""
        files = await self.discover_jsonl_files(project_path)
        all_entries = []

        for filepath in files:
            entries = await self.parse_usage_from_jsonl(filepath)
            all_entries.extend(entries)

        # Sort by timestamp
        all_entries.sort(key=lambda e: e.timestamp)
        return all_entries

    # === Aggregation Methods ===

    def _calculate_entry_cost(self, entry: LoadedUsageEntry) -> float:
        """Calculate cost for a single entry."""
        if entry.cost_usd is not None:
            return entry.cost_usd
        return self.pricing.calculate_cost(
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            cache_creation_tokens=entry.cache_creation_tokens,
            cache_read_tokens=entry.cache_read_tokens,
            model=entry.model,
        )

    def _aggregate_model_breakdowns(
        self, entries: list[LoadedUsageEntry]
    ) -> list[ModelBreakdown]:
        """Aggregate entries into model breakdowns."""
        model_data: dict[str, dict] = defaultdict(
            lambda: {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "cost": 0.0,
            }
        )

        for entry in entries:
            data = model_data[entry.model]
            data["input_tokens"] += entry.input_tokens
            data["output_tokens"] += entry.output_tokens
            data["cache_creation_tokens"] += entry.cache_creation_tokens
            data["cache_read_tokens"] += entry.cache_read_tokens
            data["cost"] += self._calculate_entry_cost(entry)

        return [
            ModelBreakdown(model=model, **data) for model, data in model_data.items()
        ]

    async def aggregate_by_daily(
        self, entries: list[LoadedUsageEntry]
    ) -> list[DailyUsage]:
        """Aggregate entries by date (YYYY-MM-DD)."""
        daily_data: dict[str, list[LoadedUsageEntry]] = defaultdict(list)

        for entry in entries:
            date_key = entry.timestamp.strftime("%Y-%m-%d")
            daily_data[date_key].append(entry)

        daily_usage = []
        for date, day_entries in sorted(daily_data.items(), reverse=True):
            input_tokens = sum(e.input_tokens for e in day_entries)
            output_tokens = sum(e.output_tokens for e in day_entries)
            cache_creation = sum(e.cache_creation_tokens for e in day_entries)
            cache_read = sum(e.cache_read_tokens for e in day_entries)
            total_cost = sum(self._calculate_entry_cost(e) for e in day_entries)
            models_used = list(set(e.model for e in day_entries))
            model_breakdowns = self._aggregate_model_breakdowns(day_entries)

            daily_usage.append(
                DailyUsage(
                    date=date,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                    total_cost=total_cost,
                    models_used=models_used,
                    model_breakdowns=model_breakdowns,
                )
            )

        return daily_usage

    async def aggregate_by_session(
        self, entries: list[LoadedUsageEntry]
    ) -> list[SessionUsage]:
        """Aggregate entries by session."""
        session_data: dict[str, list[LoadedUsageEntry]] = defaultdict(list)

        for entry in entries:
            session_key = f"{entry.project_path}:{entry.session_id}"
            session_data[session_key].append(entry)

        session_usage = []
        for session_key, session_entries in session_data.items():
            project_path, session_id = session_key.split(":", 1)

            input_tokens = sum(e.input_tokens for e in session_entries)
            output_tokens = sum(e.output_tokens for e in session_entries)
            cache_creation = sum(e.cache_creation_tokens for e in session_entries)
            cache_read = sum(e.cache_read_tokens for e in session_entries)
            total_cost = sum(self._calculate_entry_cost(e) for e in session_entries)

            # Get last activity and versions
            last_entry = max(session_entries, key=lambda e: e.timestamp)
            versions = list(
                set(e.version for e in session_entries if e.version is not None)
            )
            models_used = list(set(e.model for e in session_entries))
            model_breakdowns = self._aggregate_model_breakdowns(session_entries)

            session_usage.append(
                SessionUsage(
                    session_id=session_id,
                    project_path=project_path,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                    total_cost=total_cost,
                    last_activity=last_entry.timestamp.strftime("%Y-%m-%d"),
                    versions=versions,
                    models_used=models_used,
                    model_breakdowns=model_breakdowns,
                )
            )

        # Sort by last activity descending
        session_usage.sort(key=lambda s: s.last_activity, reverse=True)
        return session_usage

    async def aggregate_by_monthly(
        self, entries: list[LoadedUsageEntry]
    ) -> list[MonthlyUsage]:
        """Aggregate entries by month (YYYY-MM)."""
        monthly_data: dict[str, list[LoadedUsageEntry]] = defaultdict(list)

        for entry in entries:
            month_key = entry.timestamp.strftime("%Y-%m")
            monthly_data[month_key].append(entry)

        monthly_usage = []
        for month, month_entries in sorted(monthly_data.items(), reverse=True):
            input_tokens = sum(e.input_tokens for e in month_entries)
            output_tokens = sum(e.output_tokens for e in month_entries)
            cache_creation = sum(e.cache_creation_tokens for e in month_entries)
            cache_read = sum(e.cache_read_tokens for e in month_entries)
            total_cost = sum(self._calculate_entry_cost(e) for e in month_entries)
            models_used = list(set(e.model for e in month_entries))
            model_breakdowns = self._aggregate_model_breakdowns(month_entries)

            monthly_usage.append(
                MonthlyUsage(
                    month=month,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                    total_cost=total_cost,
                    models_used=models_used,
                    model_breakdowns=model_breakdowns,
                )
            )

        return monthly_usage

    # === Session Blocks (5-hour billing periods) ===

    def _floor_to_hour(self, dt: datetime) -> datetime:
        """Floor datetime to beginning of hour."""
        return dt.replace(minute=0, second=0, microsecond=0)

    async def identify_session_blocks(
        self, entries: list[LoadedUsageEntry]
    ) -> list[SessionBlock]:
        """Identify 5-hour session blocks from entries.

        Groups entries into time-based blocks (5-hour periods) with gap detection.
        """
        if not entries:
            return []

        session_duration_ms = self.SESSION_DURATION_HOURS * 60 * 60 * 1000
        blocks = []
        sorted_entries = sorted(entries, key=lambda e: e.timestamp)

        current_block_start: Optional[datetime] = None
        current_block_entries: list[LoadedUsageEntry] = []
        now = datetime.now(timezone.utc)

        for entry in sorted_entries:
            entry_time = entry.timestamp

            if current_block_start is None:
                # First entry - start new block
                current_block_start = self._floor_to_hour(entry_time)
                current_block_entries = [entry]
            else:
                time_since_start = (
                    entry_time - current_block_start
                ).total_seconds() * 1000
                last_entry = current_block_entries[-1] if current_block_entries else None
                time_since_last = (
                    (entry_time - last_entry.timestamp).total_seconds() * 1000
                    if last_entry
                    else 0
                )

                if (
                    time_since_start > session_duration_ms
                    or time_since_last > session_duration_ms
                ):
                    # Close current block
                    block = self._create_block(
                        current_block_start, current_block_entries, now
                    )
                    blocks.append(block)

                    # Add gap block if there's a significant gap
                    if last_entry and time_since_last > session_duration_ms:
                        gap_block = self._create_gap_block(
                            last_entry.timestamp, entry_time
                        )
                        if gap_block:
                            blocks.append(gap_block)

                    # Start new block
                    current_block_start = self._floor_to_hour(entry_time)
                    current_block_entries = [entry]
                else:
                    # Add to current block
                    current_block_entries.append(entry)

        # Close last block
        if current_block_start and current_block_entries:
            block = self._create_block(current_block_start, current_block_entries, now)
            blocks.append(block)

        return blocks

    def _create_block(
        self,
        start_time: datetime,
        entries: list[LoadedUsageEntry],
        now: datetime,
    ) -> SessionBlock:
        """Create a session block from entries."""
        session_duration = timedelta(hours=self.SESSION_DURATION_HOURS)
        end_time = start_time + session_duration

        last_entry = entries[-1] if entries else None
        actual_end_time = last_entry.timestamp if last_entry else start_time

        # Determine if block is active
        is_active = (
            (now - actual_end_time) < session_duration and now < end_time
        )

        # Aggregate tokens
        input_tokens = sum(e.input_tokens for e in entries)
        output_tokens = sum(e.output_tokens for e in entries)
        cache_creation = sum(e.cache_creation_tokens for e in entries)
        cache_read = sum(e.cache_read_tokens for e in entries)
        cost_usd = sum(self._calculate_entry_cost(e) for e in entries)
        models = list(set(e.model for e in entries))

        # Calculate burn rate and projections for active blocks
        burn_rate_tokens: Optional[float] = None
        burn_rate_cost: Optional[float] = None
        projected_tokens: Optional[int] = None
        projected_cost: Optional[float] = None
        remaining_minutes: Optional[int] = None

        if is_active and len(entries) > 1:
            first_entry = entries[0]
            duration_minutes = (
                last_entry.timestamp - first_entry.timestamp
            ).total_seconds() / 60

            if duration_minutes > 0:
                total_tokens = (
                    input_tokens + output_tokens + cache_creation + cache_read
                )
                burn_rate_tokens = total_tokens / duration_minutes
                burn_rate_cost = (cost_usd / duration_minutes) * 60  # Per hour

                # Project remaining usage
                remaining_ms = (end_time - now).total_seconds() * 1000
                remaining_minutes = max(0, int(remaining_ms / (1000 * 60)))

                projected_additional_tokens = burn_rate_tokens * remaining_minutes
                projected_tokens = int(total_tokens + projected_additional_tokens)

                projected_additional_cost = (burn_rate_cost / 60) * remaining_minutes
                projected_cost = round(cost_usd + projected_additional_cost, 2)

        return SessionBlock(
            id=start_time.isoformat(),
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            actual_end_time=actual_end_time.isoformat() if actual_end_time else None,
            is_active=is_active,
            is_gap=False,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            cost_usd=cost_usd,
            models=models,
            burn_rate_tokens_per_minute=burn_rate_tokens,
            burn_rate_cost_per_hour=burn_rate_cost,
            projected_total_tokens=projected_tokens,
            projected_total_cost=projected_cost,
            remaining_minutes=remaining_minutes,
        )

    def _create_gap_block(
        self, last_activity: datetime, next_activity: datetime
    ) -> Optional[SessionBlock]:
        """Create a gap block for periods with no activity."""
        session_duration = timedelta(hours=self.SESSION_DURATION_HOURS)
        gap_duration = next_activity - last_activity

        if gap_duration <= session_duration:
            return None

        gap_start = last_activity + session_duration
        gap_end = next_activity

        return SessionBlock(
            id=f"gap-{gap_start.isoformat()}",
            start_time=gap_start.isoformat(),
            end_time=gap_end.isoformat(),
            is_active=False,
            is_gap=True,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            models=[],
        )

    def _filter_recent_blocks(
        self, blocks: list[SessionBlock], days: int = DEFAULT_RECENT_DAYS
    ) -> list[SessionBlock]:
        """Filter blocks to recent ones and active blocks."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        return [
            block
            for block in blocks
            if datetime.fromisoformat(block.start_time) >= cutoff or block.is_active
        ]

    # === Public API Methods ===

    async def get_usage_summary(
        self, project_path: Optional[str] = None
    ) -> UsageSummaryResponse:
        """Get overall usage statistics."""
        cache_key = await self.get_cache_key("summary", project_path)
        cached = await self.get_from_cache(cache_key)

        if cached:
            return UsageSummaryResponse(summary=UsageSummary(**cached))

        entries = await self.get_all_usage_entries(project_path)

        if not entries:
            summary = UsageSummary(
                total_cost=0.0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_cache_creation_tokens=0,
                total_cache_read_tokens=0,
                total_tokens=0,
                project_count=0,
                session_count=0,
                models_used=[],
            )
            return UsageSummaryResponse(summary=summary)

        # Calculate totals
        total_cost = sum(self._calculate_entry_cost(e) for e in entries)
        total_input = sum(e.input_tokens for e in entries)
        total_output = sum(e.output_tokens for e in entries)
        total_cache_creation = sum(e.cache_creation_tokens for e in entries)
        total_cache_read = sum(e.cache_read_tokens for e in entries)
        total_tokens = total_input + total_output + total_cache_creation + total_cache_read

        projects = set(e.project_path for e in entries)
        sessions = set(f"{e.project_path}:{e.session_id}" for e in entries)
        models = list(set(e.model for e in entries))

        # Date range
        dates = [e.timestamp for e in entries]
        date_range_start = min(dates).strftime("%Y-%m-%d") if dates else None
        date_range_end = max(dates).strftime("%Y-%m-%d") if dates else None

        summary = UsageSummary(
            total_cost=total_cost,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_creation_tokens=total_cache_creation,
            total_cache_read_tokens=total_cache_read,
            total_tokens=total_tokens,
            project_count=len(projects),
            session_count=len(sessions),
            models_used=models,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
        )

        # Cache the result
        await self.save_to_cache(cache_key, "summary", summary.model_dump(), project_path)

        return UsageSummaryResponse(summary=summary)

    async def get_daily_usage(
        self,
        project_path: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> DailyUsageListResponse:
        """Get daily usage breakdown."""
        cache_key = await self.get_cache_key(
            "daily", project_path, start=start_date, end=end_date
        )
        cached = await self.get_from_cache(cache_key)

        if cached:
            return DailyUsageListResponse(**cached)

        entries = await self.get_all_usage_entries(project_path)

        # Filter by date range
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            entries = [e for e in entries if e.timestamp >= start_dt]
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            entries = [e for e in entries if e.timestamp < end_dt]

        daily_data = await self.aggregate_by_daily(entries)

        # Calculate totals
        totals = TokenCounts(
            input_tokens=sum(d.input_tokens for d in daily_data),
            output_tokens=sum(d.output_tokens for d in daily_data),
            cache_creation_tokens=sum(d.cache_creation_tokens for d in daily_data),
            cache_read_tokens=sum(d.cache_read_tokens for d in daily_data),
        )
        total_cost = sum(d.total_cost for d in daily_data)

        response = DailyUsageListResponse(
            data=daily_data,
            totals=totals,
            total_cost=total_cost,
        )

        # Cache the result
        await self.save_to_cache(cache_key, "daily", response.model_dump(), project_path)

        return response

    async def get_session_usage(
        self,
        project_path: Optional[str] = None,
        limit: int = 50,
    ) -> SessionUsageListResponse:
        """Get session-based usage breakdown."""
        cache_key = await self.get_cache_key("session", project_path, limit=limit)
        cached = await self.get_from_cache(cache_key)

        if cached:
            return SessionUsageListResponse(**cached)

        entries = await self.get_all_usage_entries(project_path)
        session_data = await self.aggregate_by_session(entries)

        total = len(session_data)
        session_data = session_data[:limit]

        # Calculate totals
        totals = TokenCounts(
            input_tokens=sum(s.input_tokens for s in session_data),
            output_tokens=sum(s.output_tokens for s in session_data),
            cache_creation_tokens=sum(s.cache_creation_tokens for s in session_data),
            cache_read_tokens=sum(s.cache_read_tokens for s in session_data),
        )
        total_cost = sum(s.total_cost for s in session_data)

        response = SessionUsageListResponse(
            data=session_data,
            totals=totals,
            total_cost=total_cost,
            total=total,
        )

        # Cache the result
        await self.save_to_cache(
            cache_key, "session", response.model_dump(), project_path
        )

        return response

    async def get_monthly_usage(
        self,
        project_path: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None,
    ) -> MonthlyUsageListResponse:
        """Get monthly usage breakdown."""
        cache_key = await self.get_cache_key(
            "monthly", project_path, start=start_month, end=end_month
        )
        cached = await self.get_from_cache(cache_key)

        if cached:
            return MonthlyUsageListResponse(**cached)

        entries = await self.get_all_usage_entries(project_path)

        # Filter by month range
        if start_month:
            start_dt = datetime.strptime(f"{start_month}-01", "%Y-%m-%d")
            entries = [e for e in entries if e.timestamp >= start_dt]
        if end_month:
            # End of month
            end_dt = datetime.strptime(f"{end_month}-01", "%Y-%m-%d")
            # Move to next month start
            if end_dt.month == 12:
                end_dt = end_dt.replace(year=end_dt.year + 1, month=1)
            else:
                end_dt = end_dt.replace(month=end_dt.month + 1)
            entries = [e for e in entries if e.timestamp < end_dt]

        monthly_data = await self.aggregate_by_monthly(entries)

        # Calculate totals
        totals = TokenCounts(
            input_tokens=sum(m.input_tokens for m in monthly_data),
            output_tokens=sum(m.output_tokens for m in monthly_data),
            cache_creation_tokens=sum(m.cache_creation_tokens for m in monthly_data),
            cache_read_tokens=sum(m.cache_read_tokens for m in monthly_data),
        )
        total_cost = sum(m.total_cost for m in monthly_data)

        response = MonthlyUsageListResponse(
            data=monthly_data,
            totals=totals,
            total_cost=total_cost,
        )

        # Cache the result
        await self.save_to_cache(
            cache_key, "monthly", response.model_dump(), project_path
        )

        return response

    async def get_block_usage(
        self,
        project_path: Optional[str] = None,
        recent: bool = True,
        active: bool = False,
    ) -> BlockUsageListResponse:
        """Get 5-hour billing block usage."""
        cache_key = await self.get_cache_key(
            "block", project_path, recent=recent, active=active
        )
        cached = await self.get_from_cache(cache_key)

        if cached:
            return BlockUsageListResponse(**cached)

        entries = await self.get_all_usage_entries(project_path)
        blocks = await self.identify_session_blocks(entries)

        # Filter
        if recent:
            blocks = self._filter_recent_blocks(blocks)
        if active:
            blocks = [b for b in blocks if b.is_active]

        # Find active block
        active_block = next((b for b in blocks if b.is_active), None)

        # Filter out gap blocks for totals calculation
        non_gap_blocks = [b for b in blocks if not b.is_gap]

        # Calculate totals
        totals = TokenCounts(
            input_tokens=sum(b.input_tokens for b in non_gap_blocks),
            output_tokens=sum(b.output_tokens for b in non_gap_blocks),
            cache_creation_tokens=sum(b.cache_creation_tokens for b in non_gap_blocks),
            cache_read_tokens=sum(b.cache_read_tokens for b in non_gap_blocks),
        )
        total_cost = sum(b.cost_usd for b in non_gap_blocks)

        # Sort by start time descending
        blocks.sort(key=lambda b: b.start_time, reverse=True)

        response = BlockUsageListResponse(
            data=blocks,
            active_block=active_block,
            totals=totals,
            total_cost=total_cost,
        )

        # Cache the result (shorter TTL for block data due to active blocks)
        await self.save_to_cache(cache_key, "block", response.model_dump(), project_path)

        return response
