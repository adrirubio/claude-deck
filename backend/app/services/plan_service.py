"""Service for browsing Claude Code plan files."""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.config_service import ConfigService
from app.utils.path_utils import get_claude_plans_dir, get_claude_projects_dir, get_project_display_name


class PlanService:
    """Service for reading and searching Claude Code plan files."""

    @classmethod
    def resolve_plans_dir(cls, project_path: Optional[str] = None) -> Path:
        """Resolve the plans directory from settings or use default.

        The plansDirectory setting can be:
        - Absolute path (starts with / or ~)
        - Relative path (resolved against project_path)
        - Not set (defaults to ~/.claude/plans/)
        """
        config = ConfigService()
        merged = config.get_merged_config(project_path)
        plans_dir_setting = merged.get("settings", {}).get("plansDirectory")

        if plans_dir_setting:
            plans_path = Path(plans_dir_setting).expanduser()
            if not plans_path.is_absolute():
                # Relative to project root
                base = Path(project_path) if project_path else Path.cwd()
                plans_path = (base / plans_path).resolve()
            return plans_path

        return get_claude_plans_dir()

    @classmethod
    def _extract_title(cls, content: str) -> str:
        """Extract title from first # Plan: ... heading."""
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                # Remove "Plan: " prefix if present
                if title.lower().startswith("plan:"):
                    title = title[5:].strip()
                elif title.lower().startswith("plan —"):
                    title = title[6:].strip()
                return title
        return "(untitled)"

    @classmethod
    def _extract_excerpt(cls, content: str, max_len: int = 200) -> str:
        """Extract excerpt from content, skipping the title line."""
        lines = content.split("\n")
        body_lines = []
        past_title = False
        for line in lines:
            stripped = line.strip()
            if not past_title:
                if stripped.startswith("# "):
                    past_title = True
                    continue
                if not stripped:
                    continue
                # No title found, just use content
                past_title = True
            if stripped and not stripped.startswith("---"):
                body_lines.append(stripped)
                if len(" ".join(body_lines)) >= max_len:
                    break

        excerpt = " ".join(body_lines)
        if len(excerpt) > max_len:
            excerpt = excerpt[:max_len - 3] + "..."
        return excerpt

    @classmethod
    def _extract_headings(cls, content: str) -> List[str]:
        """Extract h2/h3 headings for table of contents."""
        headings = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                headings.append(stripped.lstrip("#").strip())
        return headings

    @classmethod
    def _count_code_blocks(cls, content: str) -> int:
        """Count fenced code blocks."""
        return len(re.findall(r"^```", content, re.MULTILINE)) // 2

    @classmethod
    def _count_tables(cls, content: str) -> int:
        """Count markdown tables (lines with | separators after a header row)."""
        count = 0
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "|" in line and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if re.match(r"^\|[\s:|-]+\|$", next_line):
                    count += 1
        return count

    @classmethod
    def list_plans(cls, plans_dir: Path) -> List[Dict[str, Any]]:
        """List all plan files sorted by modification time (newest first)."""
        plans = []

        if not plans_dir.exists():
            return plans

        for plan_file in plans_dir.glob("*.md"):
            try:
                stat = plan_file.stat()
                content = plan_file.read_text(encoding="utf-8")
                title = cls._extract_title(content)
                excerpt = cls._extract_excerpt(content)

                plans.append({
                    "filename": plan_file.name,
                    "slug": plan_file.stem,
                    "title": title,
                    "excerpt": excerpt,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "size_bytes": stat.st_size,
                })
            except Exception:
                continue

        plans.sort(key=lambda p: p["modified_at"], reverse=True)
        return plans

    @classmethod
    def get_plan(cls, plans_dir: Path, filename: str) -> Optional[Dict[str, Any]]:
        """Get full plan content and metadata."""
        plan_file = plans_dir / filename
        if not plan_file.exists() or not plan_file.suffix == ".md":
            return None

        try:
            stat = plan_file.stat()
            content = plan_file.read_text(encoding="utf-8")

            return {
                "filename": plan_file.name,
                "slug": plan_file.stem,
                "title": cls._extract_title(content),
                "content": content,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size_bytes": stat.st_size,
                "headings": cls._extract_headings(content),
                "code_block_count": cls._count_code_blocks(content),
                "table_count": cls._count_tables(content),
            }
        except Exception:
            return None

    @classmethod
    def search_plans(cls, plans_dir: Path, query: str) -> List[Dict[str, Any]]:
        """Search plans by title and content (case-insensitive)."""
        results = []
        query_lower = query.lower()

        if not plans_dir.exists():
            return results

        for plan_file in plans_dir.glob("*.md"):
            try:
                content = plan_file.read_text(encoding="utf-8")
                content_lower = content.lower()

                if query_lower not in content_lower:
                    continue

                title = cls._extract_title(content)
                stat = plan_file.stat()

                # Extract match context snippets
                matches = []
                for i, line in enumerate(content.split("\n")):
                    if query_lower in line.lower():
                        snippet = line.strip()
                        if len(snippet) > 120:
                            idx = line.lower().index(query_lower)
                            start = max(0, idx - 40)
                            end = min(len(snippet), idx + len(query) + 40)
                            snippet = ("..." if start > 0 else "") + snippet[start:end] + ("..." if end < len(line.strip()) else "")
                        matches.append(snippet)
                        if len(matches) >= 3:
                            break

                results.append({
                    "filename": plan_file.name,
                    "slug": plan_file.stem,
                    "title": title,
                    "matches": matches,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except Exception:
                continue

        results.sort(key=lambda r: r["modified_at"], reverse=True)
        return results

    @classmethod
    def _empty_stats(cls) -> Dict[str, Any]:
        return {
            "total_plans": 0,
            "oldest_date": None,
            "newest_date": None,
            "total_size_bytes": 0,
        }

    @classmethod
    def get_plan_stats(cls, plans_dir: Path) -> Dict[str, Any]:
        """Get plan statistics."""
        if not plans_dir.exists():
            return cls._empty_stats()

        plan_files = list(plans_dir.glob("*.md"))
        if not plan_files:
            return cls._empty_stats()

        stats = [f.stat() for f in plan_files]
        mtimes = [s.st_mtime for s in stats]
        sizes = [s.st_size for s in stats]

        return {
            "total_plans": len(plan_files),
            "oldest_date": datetime.fromtimestamp(min(mtimes)).isoformat(),
            "newest_date": datetime.fromtimestamp(max(mtimes)).isoformat(),
            "total_size_bytes": sum(sizes),
        }

    @classmethod
    def get_plan_sessions(cls, slug: str) -> List[Dict[str, Any]]:
        """Find sessions linked to a plan via the slug field in JSONL files."""
        sessions = []
        projects_dir = get_claude_projects_dir()

        if not projects_dir.exists():
            return sessions

        for project_folder in projects_dir.iterdir():
            if not project_folder.is_dir():
                continue

            for jsonl_file in project_folder.glob("*.jsonl"):
                try:
                    session_info = cls._scan_jsonl_for_slug(jsonl_file, slug, project_folder.name)
                    if session_info:
                        sessions.append(session_info)
                except Exception:
                    continue

        # Sort by last_seen descending
        sessions.sort(key=lambda s: s.get("last_seen", ""), reverse=True)
        return sessions

    @classmethod
    def _scan_jsonl_for_slug(
        cls, filepath: Path, slug: str, project_folder: str
    ) -> Optional[Dict[str, Any]]:
        """Scan a JSONL file for entries matching the given slug.

        Reads all entries to get accurate first_seen/last_seen timestamps.
        """
        session_id = filepath.stem
        first_seen = None
        last_seen = None
        git_branch = None

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("slug") != slug:
                    continue

                timestamp = obj.get("timestamp")
                if timestamp:
                    if first_seen is None:
                        first_seen = timestamp
                    last_seen = timestamp
                if not git_branch:
                    git_branch = obj.get("gitBranch")

        if first_seen is None:
            return None

        return {
            "session_id": session_id,
            "project_folder": project_folder,
            "project_name": get_project_display_name(project_folder),
            "git_branch": git_branch,
            "first_seen": first_seen,
            "last_seen": last_seen,
        }
