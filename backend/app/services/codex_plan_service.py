"""Read-only Codex plan snapshots from update_plan events.

Codex session JSONL can contain prompt text, tool outputs, and instructions.
This service intentionally extracts only structured update_plan payloads plus
safe thread metadata needed for filtering and sorting.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from app.services.providers.codex_cli import get_codex_home


PLAN_SOURCE = "codex-cli"
PLAN_SOURCE_LABEL = "Codex plan snapshot"
ALLOWED_STATUSES = {"pending", "in_progress", "completed"}
MAX_THREAD_ROWS = 1_000
MAX_FILESYSTEM_FILES = 1_000
MAX_JSONL_LINES = 100_000
MAX_PLAN_UPDATES_PER_THREAD = 100
MAX_PLAN_ITEMS = 30
MAX_STEP_LENGTH = 240
MAX_EXPLANATION_LENGTH = 500
MAX_HISTORY_IN_DETAIL = 20


@dataclass(frozen=True)
class CodexThreadRef:
    thread_id: str
    rollout_path: Path
    cwd: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    git_branch: str | None = None
    git_sha: str | None = None


@dataclass(frozen=True)
class CodexPlanUpdate:
    timestamp: str
    explanation: str | None
    plan: list[dict[str, str]]


class CodexPlanService:
    """Surface Codex update_plan snapshots as plan-like records."""

    def __init__(self, codex_home: Path | None = None):
        self.codex_home = (codex_home or get_codex_home()).expanduser()

    def list_plans(self, project_path: str | None = None) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        for thread in self._iter_thread_refs(project_path):
            record = self._build_record(thread, include_content=False)
            if record:
                plans.append(record)

        plans.sort(key=lambda plan: plan.get("modified_at") or "", reverse=True)
        return plans

    def get_plan(self, filename: str, project_path: str | None = None) -> dict[str, Any] | None:
        for thread in self._iter_thread_refs(project_path):
            record = self._build_record(thread, include_content=True)
            if record and record["filename"] == filename:
                return record
        return None

    def search_plans(self, query: str, project_path: str | None = None) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for thread in self._iter_thread_refs(project_path):
            plan = self._build_record(thread, include_content=True)
            if not plan:
                continue
            fields = [
                plan.get("title", ""),
                plan.get("excerpt", ""),
                plan.get("slug", ""),
                plan.get("content", ""),
            ]
            if not any(query_lower in str(field).lower() for field in fields):
                continue
            matches = self._search_matches(plan, query_lower)
            results.append(
                {
                    "filename": plan["filename"],
                    "slug": plan["slug"],
                    "title": plan["title"],
                    "matches": matches,
                    "modified_at": plan["modified_at"],
                    "source": PLAN_SOURCE,
                    "source_label": PLAN_SOURCE_LABEL,
                }
            )

        results.sort(key=lambda result: result.get("modified_at") or "", reverse=True)
        return results

    def get_plan_stats(self, project_path: str | None = None) -> dict[str, Any]:
        plans = self.list_plans(project_path)
        if not plans:
            return {
                "total_plans": 0,
                "oldest_date": None,
                "newest_date": None,
                "total_size_bytes": 0,
                "source": PLAN_SOURCE,
                "source_label": PLAN_SOURCE_LABEL,
            }

        dates = [plan["modified_at"] for plan in plans if plan.get("modified_at")]
        return {
            "total_plans": len(plans),
            "oldest_date": min(dates) if dates else None,
            "newest_date": max(dates) if dates else None,
            "total_size_bytes": sum(int(plan.get("size_bytes") or 0) for plan in plans),
            "source": PLAN_SOURCE,
            "source_label": PLAN_SOURCE_LABEL,
        }

    def _iter_thread_refs(self, project_path: str | None) -> Iterable[CodexThreadRef]:
        seen_paths: set[Path] = set()
        refs = self._thread_refs_from_sqlite(project_path)
        if not refs:
            refs = self._thread_refs_from_filesystem(project_path)

        for ref in refs:
            try:
                rollout_path = ref.rollout_path.expanduser().resolve(strict=False)
            except OSError:
                rollout_path = ref.rollout_path.expanduser()
            if rollout_path in seen_paths:
                continue
            seen_paths.add(rollout_path)
            if rollout_path.exists() and rollout_path.is_file():
                yield ref

    def _thread_refs_from_sqlite(self, project_path: str | None) -> list[CodexThreadRef]:
        db_path = self._state_db_path()
        if not db_path:
            return []

        refs: list[CodexThreadRef] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT id, rollout_path, created_at, updated_at, cwd, git_branch, git_sha
                    FROM threads
                    WHERE rollout_path IS NOT NULL AND rollout_path <> ''
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (MAX_THREAD_ROWS,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []

        for row in rows:
            cwd = self._clean_optional_text(row["cwd"], max_len=1_000)
            if not self._matches_project(cwd, project_path):
                continue
            rollout_path = Path(str(row["rollout_path"])).expanduser()
            refs.append(
                CodexThreadRef(
                    thread_id=self._clean_optional_text(row["id"], max_len=128)
                    or rollout_path.stem,
                    rollout_path=rollout_path,
                    cwd=cwd,
                    created_at=self._sqlite_time_to_iso(row["created_at"]),
                    updated_at=self._sqlite_time_to_iso(row["updated_at"]),
                    git_branch=self._clean_optional_text(row["git_branch"], max_len=120),
                    git_sha=self._clean_optional_text(row["git_sha"], max_len=80),
                )
            )
        return refs

    def _thread_refs_from_filesystem(self, project_path: str | None) -> list[CodexThreadRef]:
        sessions_dir = self.codex_home / "sessions"
        if not sessions_dir.exists():
            return []

        files = sorted(
            sessions_dir.glob("**/*.jsonl"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )[:MAX_FILESYSTEM_FILES]

        refs: list[CodexThreadRef] = []
        for path in files:
            meta = self._read_session_meta(path)
            cwd = meta.get("cwd")
            if not self._matches_project(cwd, project_path):
                continue
            refs.append(
                CodexThreadRef(
                    thread_id=meta.get("id") or path.stem,
                    rollout_path=path,
                    cwd=cwd,
                    created_at=meta.get("timestamp"),
                    updated_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                    git_branch=meta.get("git_branch"),
                    git_sha=meta.get("git_sha"),
                )
            )
        return refs

    def _read_session_meta(self, path: Path) -> dict[str, str | None]:
        meta: dict[str, str | None] = {}
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for index, raw_line in enumerate(handle):
                    if index >= 100:
                        break
                    record = self._parse_json_line(raw_line)
                    if record.get("type") != "session_meta":
                        continue
                    payload = record.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
                    meta = {
                        "id": self._clean_optional_text(payload.get("id"), max_len=128),
                        "timestamp": self._clean_optional_text(payload.get("timestamp"), max_len=80),
                        "cwd": self._clean_optional_text(payload.get("cwd"), max_len=1_000),
                        "git_branch": self._clean_optional_text(git.get("branch"), max_len=120),
                        "git_sha": self._clean_optional_text(git.get("commit_hash"), max_len=80),
                    }
                    break
        except OSError:
            return {}
        return meta

    def _build_record(self, thread: CodexThreadRef, *, include_content: bool) -> dict[str, Any] | None:
        updates = self._read_plan_updates(thread.rollout_path)
        if not updates:
            return None

        latest = sorted(updates, key=lambda update: self._timestamp_key(update.timestamp))[-1]
        counts = self._plan_counts(latest.plan)
        filename = f"codex-{self._safe_slug(thread.thread_id or thread.rollout_path.stem)}.md"
        title = self._title_for(thread, latest)
        excerpt = self._excerpt_for(latest, counts)
        source_size = self._safe_size(thread.rollout_path)

        record: dict[str, Any] = {
            "filename": filename,
            "slug": filename.removesuffix(".md"),
            "title": title,
            "excerpt": excerpt,
            "modified_at": latest.timestamp or thread.updated_at or thread.created_at or "",
            "size_bytes": source_size,
            "source": PLAN_SOURCE,
            "source_label": PLAN_SOURCE_LABEL,
            "project_path": thread.cwd,
            "session_id": thread.thread_id,
            "git_branch": thread.git_branch,
            "git_sha": thread.git_sha,
            "step_count": counts["total"],
            "pending_count": counts["pending"],
            "in_progress_count": counts["in_progress"],
            "completed_count": counts["completed"],
            "history_count": len(updates),
        }
        if include_content:
            record.update(
                {
                    "content": self._render_markdown(thread, latest, updates),
                    "headings": ["Current Snapshot", "Update History"],
                    "code_block_count": 0,
                    "table_count": 0,
                    "linked_sessions": [],
                }
            )
        return record

    def _read_plan_updates(self, path: Path) -> list[CodexPlanUpdate]:
        updates: list[CodexPlanUpdate] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_index, raw_line in enumerate(handle):
                    if line_index >= MAX_JSONL_LINES:
                        break
                    record = self._parse_json_line(raw_line)
                    if not self._is_update_plan_call(record):
                        continue
                    update = self._parse_update_plan(record)
                    if update:
                        updates.append(update)
                    if len(updates) >= MAX_PLAN_UPDATES_PER_THREAD:
                        break
        except OSError:
            return []
        return updates

    def _parse_update_plan(self, record: dict[str, Any]) -> CodexPlanUpdate | None:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        args = payload.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        if not isinstance(args, dict):
            return None

        raw_plan = args.get("plan")
        if not isinstance(raw_plan, list):
            return None

        plan: list[dict[str, str]] = []
        for item in raw_plan[:MAX_PLAN_ITEMS]:
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            step = self._clean_optional_text(item.get("step"), max_len=MAX_STEP_LENGTH)
            if not step or status not in ALLOWED_STATUSES:
                continue
            plan.append({"step": step, "status": str(status)})

        if not plan:
            return None

        timestamp = self._clean_optional_text(record.get("timestamp"), max_len=80) or ""
        explanation = self._clean_optional_text(
            args.get("explanation"),
            max_len=MAX_EXPLANATION_LENGTH,
        )
        return CodexPlanUpdate(timestamp=timestamp, explanation=explanation, plan=plan)

    def _render_markdown(
        self,
        thread: CodexThreadRef,
        latest: CodexPlanUpdate,
        updates: list[CodexPlanUpdate],
    ) -> str:
        lines = [
            "# Codex Plan Snapshot",
            "",
            "## Current Snapshot",
            "",
        ]
        if latest.explanation:
            lines.extend([latest.explanation, ""])
        lines.extend(self._markdown_steps(latest.plan))

        lines.extend(["", "## Update History", ""])
        for update in sorted(updates, key=lambda item: self._timestamp_key(item.timestamp), reverse=True)[
            :MAX_HISTORY_IN_DETAIL
        ]:
            lines.extend([f"### {update.timestamp or 'Unknown time'}", ""])
            if update.explanation:
                lines.extend([update.explanation, ""])
            lines.extend(self._markdown_steps(update.plan))
            lines.append("")

        if thread.cwd or thread.git_branch or thread.thread_id:
            lines.extend(["## Source", ""])
            if thread.cwd:
                lines.append(f"- Repo: `{thread.cwd}`")
            if thread.thread_id:
                lines.append(f"- Codex thread: `{thread.thread_id}`")
            if thread.git_branch:
                lines.append(f"- Git branch: `{thread.git_branch}`")
            if thread.git_sha:
                lines.append(f"- Git SHA: `{thread.git_sha}`")
        return "\n".join(lines).strip() + "\n"

    def _markdown_steps(self, plan: list[dict[str, str]]) -> list[str]:
        rendered = []
        for item in plan:
            marker = "[x]" if item["status"] == "completed" else "[ ]"
            status = item["status"].replace("_", " ")
            rendered.append(f"- {marker} {item['step']} ({status})")
        return rendered

    def _search_matches(self, plan: dict[str, Any], query_lower: str) -> list[str]:
        matches: list[str] = []
        for value in (plan.get("title"), plan.get("excerpt"), plan.get("slug")):
            if isinstance(value, str) and query_lower in value.lower():
                matches.append(value)
        content = plan.get("content")
        if isinstance(content, str):
            for line in content.splitlines():
                stripped = line.strip()
                if stripped and query_lower in stripped.lower():
                    matches.append(stripped[:160])
                if len(matches) >= 3:
                    break
        return matches[:3]

    def _state_db_path(self) -> Path | None:
        preferred = self.codex_home / "state_5.sqlite"
        if preferred.exists():
            return preferred
        candidates = sorted(self.codex_home.glob("state_*.sqlite"))
        return candidates[-1] if candidates else None

    def _matches_project(self, cwd: str | None, project_path: str | None) -> bool:
        if not project_path:
            return True
        if not cwd:
            return False
        return self._normalized_path(cwd) == self._normalized_path(project_path)

    def _normalized_path(self, path: str) -> str:
        try:
            return str(Path(path).expanduser().resolve(strict=False))
        except OSError:
            return str(Path(path).expanduser())

    def _is_update_plan_call(self, record: dict[str, Any]) -> bool:
        payload = record.get("payload")
        return (
            record.get("type") == "response_item"
            and isinstance(payload, dict)
            and payload.get("type") == "function_call"
            and payload.get("name") == "update_plan"
        )

    def _parse_json_line(self, raw_line: str) -> dict[str, Any]:
        stripped = raw_line.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _title_for(self, thread: CodexThreadRef, latest: CodexPlanUpdate) -> str:
        repo_name = Path(thread.cwd).name if thread.cwd else "Codex session"
        active = next((item["step"] for item in latest.plan if item["status"] == "in_progress"), None)
        if active:
            return f"{repo_name} - {active}"
        return f"{repo_name} - Codex plan snapshot"

    def _excerpt_for(self, latest: CodexPlanUpdate, counts: dict[str, int]) -> str:
        active = next((item["step"] for item in latest.plan if item["status"] == "in_progress"), None)
        if active:
            return f"In progress: {active}"
        return (
            f"{counts['total']} steps: {counts['completed']} completed, "
            f"{counts['in_progress']} in progress, {counts['pending']} pending"
        )

    def _plan_counts(self, plan: list[dict[str, str]]) -> dict[str, int]:
        counts = {"total": len(plan), "pending": 0, "in_progress": 0, "completed": 0}
        for item in plan:
            status = item.get("status")
            if status in counts:
                counts[status] += 1
        return counts

    def _safe_slug(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
        return slug[:120] or "session"

    def _safe_size(self, path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _sqlite_time_to_iso(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            if value.isdigit():
                value = int(value)
            else:
                return self._clean_optional_text(value, max_len=80)
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            try:
                return datetime.fromtimestamp(timestamp).isoformat()
            except (OSError, OverflowError, ValueError):
                return None
        return None

    def _timestamp_key(self, value: str) -> float:
        if not value:
            return 0
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0

    def _clean_optional_text(self, value: Any, *, max_len: int) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            return None
        if len(cleaned) > max_len:
            return cleaned[: max_len - 3] + "..."
        return cleaned
