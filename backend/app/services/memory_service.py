"""Service for managing Claude Code memory files (CLAUDE.md, rules, etc.)."""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.utils.path_utils import (
    get_claude_user_config_dir,
    get_project_claude_dir,
)


class MemoryService:
    """Service for managing Claude Code memory files."""

    # Memory file types and their locations
    MEMORY_TYPES = {
        "managed": "/etc/claude-code/CLAUDE.md",  # Organization-wide (read-only)
        "user": "~/.claude/CLAUDE.md",  # Personal preferences (all projects)
        "project": "./CLAUDE.md",  # Team-shared project instructions
        "project_alt": "./.claude/CLAUDE.md",  # Alternative location
        "local": "./CLAUDE.local.md",  # Personal project-specific
    }

    @staticmethod
    def _get_user_claude_md() -> Path:
        """Get user-level CLAUDE.md path."""
        return get_claude_user_config_dir() / "CLAUDE.md"

    @staticmethod
    def _get_managed_claude_md() -> Path:
        """Get managed/org-level CLAUDE.md path."""
        return Path("/etc/claude-code/CLAUDE.md")

    @staticmethod
    def _get_project_claude_md(project_path: Optional[str]) -> Path:
        """Get project-level CLAUDE.md path."""
        if project_path:
            return Path(project_path) / "CLAUDE.md"
        return Path.cwd() / "CLAUDE.md"

    @staticmethod
    def _get_project_alt_claude_md(project_path: Optional[str]) -> Path:
        """Get alternative project-level CLAUDE.md path (.claude/CLAUDE.md)."""
        return get_project_claude_dir(project_path) / "CLAUDE.md"

    @staticmethod
    def _get_local_claude_md(project_path: Optional[str]) -> Path:
        """Get local (personal project-specific) CLAUDE.md path."""
        if project_path:
            return Path(project_path) / "CLAUDE.local.md"
        return Path.cwd() / "CLAUDE.local.md"

    @staticmethod
    def _get_rules_dir(project_path: Optional[str]) -> Path:
        """Get the .claude/rules/ directory path."""
        return get_project_claude_dir(project_path) / "rules"

    @staticmethod
    def _parse_rule_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
        """Parse YAML frontmatter from a rule file.

        Returns:
            Tuple of (frontmatter dict, remaining content)
        """
        if not content.startswith("---"):
            return {}, content

        try:
            end_match = re.search(r"\n---\s*\n", content[3:])
            if not end_match:
                return {}, content

            frontmatter_str = content[3 : end_match.start() + 3]
            remaining = content[end_match.end() + 3 :]

            frontmatter = yaml.safe_load(frontmatter_str) or {}
            return frontmatter, remaining
        except yaml.YAMLError:
            return {}, content

    @staticmethod
    def _extract_imports(content: str) -> List[str]:
        """Extract @import references from content.

        Supports:
        - @path/to/file
        - @./relative/path
        - @~/user/path
        """
        # Match @path patterns (not inside code blocks)
        # Simple pattern: @followed by path characters
        pattern = r"@([~./]?[\w./-]+)"
        matches = re.findall(pattern, content)
        return list(set(matches))

    @classmethod
    def get_memory_hierarchy(
        cls, project_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get the full memory file hierarchy.

        Args:
            project_path: Optional project directory path

        Returns:
            List of memory file info dicts with path, scope, exists, imports
        """
        files = []

        # Managed (organization-wide)
        managed_path = cls._get_managed_claude_md()
        files.append(
            {
                "path": str(managed_path),
                "scope": "managed",
                "type": "claude_md",
                "exists": managed_path.exists(),
                "readonly": True,
                "description": "Organization-wide instructions (managed policy)",
            }
        )

        # User-level
        user_path = cls._get_user_claude_md()
        files.append(
            {
                "path": str(user_path),
                "scope": "user",
                "type": "claude_md",
                "exists": user_path.exists(),
                "readonly": False,
                "description": "Personal preferences (all projects)",
            }
        )

        # Project-level
        project_path_obj = cls._get_project_claude_md(project_path)
        project_alt_path = cls._get_project_alt_claude_md(project_path)

        # Check which project path exists (prefer root CLAUDE.md)
        if project_path_obj.exists():
            files.append(
                {
                    "path": str(project_path_obj),
                    "scope": "project",
                    "type": "claude_md",
                    "exists": True,
                    "readonly": False,
                    "description": "Team-shared project instructions",
                }
            )
        elif project_alt_path.exists():
            files.append(
                {
                    "path": str(project_alt_path),
                    "scope": "project",
                    "type": "claude_md",
                    "exists": True,
                    "readonly": False,
                    "description": "Team-shared project instructions",
                }
            )
        else:
            # Show the preferred location even if it doesn't exist
            files.append(
                {
                    "path": str(project_path_obj),
                    "scope": "project",
                    "type": "claude_md",
                    "exists": False,
                    "readonly": False,
                    "description": "Team-shared project instructions",
                }
            )

        # Local (personal project-specific)
        local_path = cls._get_local_claude_md(project_path)
        files.append(
            {
                "path": str(local_path),
                "scope": "local",
                "type": "claude_md",
                "exists": local_path.exists(),
                "readonly": False,
                "description": "Personal project-specific preferences (gitignored)",
            }
        )

        # Rules directory
        rules_dir = cls._get_rules_dir(project_path)
        if rules_dir.exists():
            for rule_file in sorted(rules_dir.rglob("*.md")):
                rel_path = rule_file.relative_to(rules_dir)
                files.append(
                    {
                        "path": str(rule_file),
                        "scope": "rules",
                        "type": "rule",
                        "name": rel_path.stem,
                        "relative_path": str(rel_path),
                        "exists": True,
                        "readonly": False,
                        "description": f"Rule: {rel_path.stem}",
                    }
                )

        return files

    @classmethod
    def get_memory_file(
        cls, file_path: str, include_imports: bool = True
    ) -> Dict[str, Any]:
        """Get a specific memory file with its content and metadata.

        Args:
            file_path: Absolute path to the memory file
            include_imports: Whether to extract and return import references

        Returns:
            Dict with path, content, exists, imports, frontmatter
        """
        path = Path(file_path).expanduser()

        result = {
            "path": str(path),
            "exists": path.exists(),
            "content": None,
            "imports": [],
            "frontmatter": {},
        }

        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                result["content"] = content

                if include_imports:
                    result["imports"] = cls._extract_imports(content)

                # Parse frontmatter if it's a rule file
                if ".claude/rules/" in str(path) or "/rules/" in str(path):
                    frontmatter, _ = cls._parse_rule_frontmatter(content)
                    result["frontmatter"] = frontmatter

            except Exception as e:
                result["error"] = str(e)

        return result

    @classmethod
    def save_memory_file(
        cls, file_path: str, content: str, create_parents: bool = True
    ) -> Dict[str, Any]:
        """Save content to a memory file.

        Args:
            file_path: Absolute path to the memory file
            content: Content to write
            create_parents: Whether to create parent directories

        Returns:
            Dict with success status and path
        """
        path = Path(file_path).expanduser()

        # Don't allow writing to managed path
        if str(path) == str(cls._get_managed_claude_md()):
            return {
                "success": False,
                "error": "Cannot modify managed policy file",
                "path": str(path),
            }

        try:
            if create_parents:
                path.parent.mkdir(parents=True, exist_ok=True)

            path.write_text(content, encoding="utf-8")

            return {
                "success": True,
                "path": str(path),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": str(path),
            }

    @classmethod
    def delete_memory_file(cls, file_path: str) -> Dict[str, Any]:
        """Delete a memory file.

        Args:
            file_path: Absolute path to the memory file

        Returns:
            Dict with success status
        """
        path = Path(file_path).expanduser()

        # Don't allow deleting managed path
        if str(path) == str(cls._get_managed_claude_md()):
            return {
                "success": False,
                "error": "Cannot delete managed policy file",
                "path": str(path),
            }

        try:
            if path.exists():
                path.unlink()
                return {
                    "success": True,
                    "path": str(path),
                }
            else:
                return {
                    "success": False,
                    "error": "File does not exist",
                    "path": str(path),
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": str(path),
            }

    @classmethod
    def list_rules(cls, project_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all rules in the .claude/rules/ directory.

        Args:
            project_path: Optional project directory path

        Returns:
            List of rule info dicts
        """
        rules_dir = cls._get_rules_dir(project_path)
        rules = []

        if not rules_dir.exists():
            return rules

        for rule_file in sorted(rules_dir.rglob("*.md")):
            rel_path = rule_file.relative_to(rules_dir)
            content = rule_file.read_text(encoding="utf-8")
            frontmatter, body = cls._parse_rule_frontmatter(content)

            # Get paths from frontmatter (for path-scoped rules)
            paths = frontmatter.get("paths", [])
            if isinstance(paths, str):
                paths = [paths]

            rules.append(
                {
                    "name": rel_path.stem,
                    "path": str(rule_file),
                    "relative_path": str(rel_path),
                    "frontmatter": frontmatter,
                    "scoped_paths": paths,
                    "description": frontmatter.get("description", ""),
                    "content_preview": body[:200] if body else "",
                }
            )

        return rules

    @classmethod
    def create_rule(
        cls,
        project_path: Optional[str],
        name: str,
        content: str,
        paths: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new rule file.

        Args:
            project_path: Project directory path
            name: Rule name (without .md extension)
            content: Rule content (markdown)
            paths: Optional list of paths this rule applies to
            description: Optional description for frontmatter

        Returns:
            Dict with success status and path
        """
        rules_dir = cls._get_rules_dir(project_path)
        rules_dir.mkdir(parents=True, exist_ok=True)

        rule_path = rules_dir / f"{name}.md"

        # Build frontmatter if we have metadata
        frontmatter_parts = []
        if description:
            frontmatter_parts.append(f"description: {description}")
        if paths:
            frontmatter_parts.append("paths:")
            for p in paths:
                frontmatter_parts.append(f"  - {p}")

        if frontmatter_parts:
            full_content = "---\n" + "\n".join(frontmatter_parts) + "\n---\n\n" + content
        else:
            full_content = content

        return cls.save_memory_file(str(rule_path), full_content)

    @classmethod
    def resolve_imports(
        cls, file_path: str, visited: Optional[set] = None
    ) -> Dict[str, Any]:
        """Resolve the import tree for a memory file.

        Args:
            file_path: Path to the memory file
            visited: Set of already-visited paths (for cycle detection)

        Returns:
            Dict with import tree structure
        """
        if visited is None:
            visited = set()

        path = Path(file_path).expanduser()
        path_str = str(path.resolve())

        if path_str in visited:
            return {
                "path": str(path),
                "exists": path.exists(),
                "cycle": True,
                "imports": [],
            }

        visited.add(path_str)

        result = {
            "path": str(path),
            "exists": path.exists(),
            "cycle": False,
            "imports": [],
        }

        if not path.exists():
            return result

        try:
            content = path.read_text(encoding="utf-8")
            imports = cls._extract_imports(content)

            for imp in imports:
                # Resolve import path
                if imp.startswith("~/"):
                    imp_path = Path(imp).expanduser()
                elif imp.startswith("./") or imp.startswith("../"):
                    imp_path = (path.parent / imp).resolve()
                else:
                    imp_path = Path(imp)

                # Recursively resolve
                imp_tree = cls.resolve_imports(str(imp_path), visited.copy())
                result["imports"].append(imp_tree)

        except Exception as e:
            result["error"] = str(e)

        return result
