"""Configuration service for reading and merging Claude Code configurations."""
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from ..utils.path_utils import (
    ClaudePathUtils,
    get_claude_user_settings_file,
    get_claude_user_settings_local_file,
    get_project_settings_file,
    get_project_settings_local_file,
    get_managed_settings_file,
    ensure_directory_exists,
)
from ..utils.file_utils import read_json_file
from ..utils.pattern_utils import sanitize_permission_rules


# Settings scope priority (highest to lowest)
SCOPE_PRIORITY = ["managed", "local", "project", "user"]
ScopeType = Literal["managed", "local", "project", "user"]


class ConfigService:
    """Service for managing Claude Code configuration files."""

    def __init__(self):
        self.path_utils = ClaudePathUtils()

    def get_all_config_files(self, project_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all configuration file paths with their status.

        Args:
            project_path: Optional project directory path

        Returns:
            List of config file information
        """
        files = []

        # User-level config files
        user_files = [
            (self.path_utils.get_user_claude_json(), "user"),
            (self.path_utils.get_user_settings_json(), "user"),
            (self.path_utils.get_user_settings_local_json(), "user"),
        ]

        for file_path, scope in user_files:
            if file_path:
                files.append({
                    "path": str(file_path),
                    "scope": scope,
                    "exists": file_path.exists(),
                    "content": None
                })

        # Add user commands directory
        commands_dir = self.path_utils.get_user_commands_dir()
        if commands_dir and commands_dir.exists():
            for cmd_file in commands_dir.rglob("*.md"):
                files.append({
                    "path": str(cmd_file),
                    "scope": "user",
                    "exists": True,
                    "content": None
                })

        # Project-level config files
        if project_path:
            proj_path = Path(project_path)
            project_files = [
                (proj_path / ".claude" / "settings.json", "project"),
                (proj_path / ".claude" / "settings.local.json", "project"),
                (proj_path / ".mcp.json", "project"),
                (proj_path / "CLAUDE.md", "project"),
            ]

            for file_path, scope in project_files:
                files.append({
                    "path": str(file_path),
                    "scope": scope,
                    "exists": file_path.exists(),
                    "content": None
                })

            # Add project commands directory
            proj_commands_dir = proj_path / ".claude" / "commands"
            if proj_commands_dir.exists():
                for cmd_file in proj_commands_dir.rglob("*.md"):
                    files.append({
                        "path": str(cmd_file),
                        "scope": "project",
                        "exists": True,
                        "content": None
                    })

        return files

    def get_merged_config(self, project_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Get merged configuration from all scopes.

        Args:
            project_path: Optional project directory path

        Returns:
            Merged configuration dictionary
        """
        merged = {
            "settings": {},
            "mcp_servers": {},
            "hooks": {},
            "permissions": {"allow": [], "deny": []},
            "commands": [],
            "agents": []
        }

        # Load user config
        user_claude = self.path_utils.get_user_claude_json()
        if user_claude and user_claude.exists():
            user_data = read_json_file(user_claude)
            if user_data:
                # Extract top-level MCP servers from user config
                if "mcpServers" in user_data:
                    merged["mcp_servers"].update(user_data["mcpServers"])

                # Extract MCP servers from all projects in user config
                projects = user_data.get("projects", {})
                for path, project_config in projects.items():
                    if isinstance(project_config, dict):
                        project_servers = project_config.get("mcpServers", {})
                        if project_servers:
                            merged["mcp_servers"].update(project_servers)

        # Load user settings
        user_settings = self.path_utils.get_user_settings_json()
        if user_settings and user_settings.exists():
            settings_data = read_json_file(user_settings)
            if settings_data:
                merged["settings"].update(settings_data)
                if "hooks" in settings_data:
                    merged["hooks"] = settings_data["hooks"]
                if "permissions" in settings_data:
                    merged["permissions"].update(settings_data["permissions"])

        # Load user local settings (overrides)
        user_settings_local = self.path_utils.get_user_settings_local_json()
        if user_settings_local and user_settings_local.exists():
            local_data = read_json_file(user_settings_local)
            if local_data:
                merged["settings"].update(local_data)

        # Load project config if provided
        if project_path:
            proj_path = Path(project_path)

            # Project MCP servers
            mcp_json = proj_path / ".mcp.json"
            if mcp_json.exists():
                mcp_data = read_json_file(mcp_json)
                if mcp_data and "mcpServers" in mcp_data:
                    merged["mcp_servers"].update(mcp_data["mcpServers"])

            # Project settings
            proj_settings = proj_path / ".claude" / "settings.json"
            if proj_settings.exists():
                proj_settings_data = read_json_file(proj_settings)
                if proj_settings_data:
                    merged["settings"].update(proj_settings_data)
                    if "hooks" in proj_settings_data:
                        for key, hooks in proj_settings_data["hooks"].items():
                            if key not in merged["hooks"]:
                                merged["hooks"][key] = []
                            merged["hooks"][key].extend(hooks)

            # Project local settings
            proj_settings_local = proj_path / ".claude" / "settings.local.json"
            if proj_settings_local.exists():
                proj_local_data = read_json_file(proj_settings_local)
                if proj_local_data:
                    merged["settings"].update(proj_local_data)

        # List commands
        commands_dir = self.path_utils.get_user_commands_dir()
        if commands_dir and commands_dir.exists():
            for cmd_file in commands_dir.rglob("*.md"):
                merged["commands"].append(str(cmd_file.relative_to(commands_dir)))

        if project_path:
            proj_commands_dir = Path(project_path) / ".claude" / "commands"
            if proj_commands_dir.exists():
                for cmd_file in proj_commands_dir.rglob("*.md"):
                    merged["commands"].append(f"project:{cmd_file.relative_to(proj_commands_dir)}")

        # List agents
        agents_dir = self.path_utils.get_user_agents_dir()
        if agents_dir and agents_dir.exists():
            for agent_file in agents_dir.glob("*.md"):
                merged["agents"].append(agent_file.stem)

        if project_path:
            proj_agents_dir = Path(project_path) / ".claude" / "agents"
            if proj_agents_dir.exists():
                for agent_file in proj_agents_dir.glob("*.md"):
                    merged["agents"].append(f"project:{agent_file.stem}")

        return merged

    def get_file_content(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get raw file content.

        Args:
            file_path: Path to file

        Returns:
            File content dictionary or None if file doesn't exist
        """
        path = Path(file_path)

        if not path.exists():
            return {
                "path": file_path,
                "content": "",
                "exists": False
            }

        try:
            if path.suffix == ".json":
                content = read_json_file(path)
                content_str = json.dumps(content, indent=2) if content else ""
            else:
                with open(path, 'r', encoding='utf-8') as f:
                    content_str = f.read()

            return {
                "path": file_path,
                "content": content_str,
                "exists": True
            }
        except Exception as e:
            return {
                "path": file_path,
                "content": f"Error reading file: {str(e)}",
                "exists": True
            }

    def mask_sensitive_values(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mask sensitive values in configuration data.

        Args:
            data: Configuration dictionary

        Returns:
            Dictionary with masked sensitive values
        """
        if not isinstance(data, dict):
            return data

        masked = {}
        sensitive_keys = ["key", "token", "secret", "password", "api_key", "apikey"]

        for key, value in data.items():
            lower_key = key.lower()
            if any(sensitive in lower_key for sensitive in sensitive_keys):
                if isinstance(value, str) and len(value) > 4:
                    masked[key] = f"{value[:4]}{'*' * (len(value) - 4)}"
                else:
                    masked[key] = "****"
            elif isinstance(value, dict):
                masked[key] = self.mask_sensitive_values(value)
            elif isinstance(value, list):
                masked[key] = [
                    self.mask_sensitive_values(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                masked[key] = value

        return masked

    def update_settings(
        self, scope: str, settings: Dict[str, Any], project_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update settings for a given scope.

        Args:
            scope: "user", "project", or "local"
            settings: Settings dictionary to write
            project_path: Required for project/local scope

        Returns:
            Dict with success status, message, and path

        Raises:
            ValueError: If scope is invalid or project_path is missing for project scopes
        """
        # Determine which file to write to
        if scope == "user":
            file_path = get_claude_user_settings_file()
        elif scope == "user_local":
            file_path = get_claude_user_settings_local_file()
        elif scope == "project":
            if not project_path:
                raise ValueError("project_path is required for project scope")
            file_path = get_project_settings_file(project_path)
        elif scope == "local":
            if not project_path:
                raise ValueError("project_path is required for local scope")
            file_path = get_project_settings_local_file(project_path)
        else:
            raise ValueError(f"Invalid scope: {scope}. Must be user, user_local, project, or local")

        # Ensure parent directory exists
        ensure_directory_exists(file_path.parent)

        # Load existing settings if file exists
        existing_settings = {}
        if file_path.exists():
            existing_settings = read_json_file(file_path) or {}

        # Deep merge settings (new settings override existing)
        merged_settings = self._deep_merge(existing_settings, settings)

        # Sanitize permission patterns before writing
        sanitize_result = sanitize_permission_rules(merged_settings)
        merged_settings = sanitize_result["sanitized_settings"]

        # Write the merged settings
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(merged_settings, f, indent=2)

            message = "Settings updated successfully"
            if sanitize_result["migrated"]:
                count = len(sanitize_result["migrated"])
                message += f" ({count} pattern(s) auto-migrated)"
            if sanitize_result["removed"]:
                count = len(sanitize_result["removed"])
                message += f" ({count} invalid pattern(s) removed)"

            return {
                "success": True,
                "message": message,
                "path": str(file_path),
                "migrated_patterns": sanitize_result["migrated"],
                "removed_patterns": sanitize_result["removed"],
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to write settings: {str(e)}",
                "path": str(file_path)
            }

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries.

        Args:
            base: Base dictionary
            override: Override dictionary (takes precedence)

        Returns:
            Merged dictionary
        """
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def get_settings_by_scope(self, scope: str, project_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Get settings for a specific scope (not merged).

        Args:
            scope: "user", "user_local", "project", "local", or "managed"
            project_path: Required for project/local scope

        Returns:
            Settings dictionary for the specified scope
        """
        if scope == "managed":
            file_path = get_managed_settings_file()
        elif scope == "user":
            file_path = get_claude_user_settings_file()
        elif scope == "user_local":
            file_path = get_claude_user_settings_local_file()
        elif scope == "project":
            if not project_path:
                return {}
            file_path = get_project_settings_file(project_path)
        elif scope == "local":
            if not project_path:
                return {}
            file_path = get_project_settings_local_file(project_path)
        else:
            return {}

        if file_path.exists():
            return read_json_file(file_path) or {}
        return {}

    def get_all_scoped_settings(self, project_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Get settings from all scopes separately.

        Args:
            project_path: Optional project directory path

        Returns:
            Dictionary with settings from each scope
        """
        result = {
            "managed": {},
            "user": {},
            "project": {},
            "local": {}
        }

        # Load managed settings (read-only, admin-enforced)
        managed_path = get_managed_settings_file()
        if managed_path.exists():
            result["managed"] = read_json_file(managed_path) or {}

        # Load user settings
        user_settings = self.path_utils.get_user_settings_json()
        if user_settings and user_settings.exists():
            result["user"] = read_json_file(user_settings) or {}

        # Load project settings
        if project_path:
            proj_settings = get_project_settings_file(project_path)
            if proj_settings.exists():
                result["project"] = read_json_file(proj_settings) or {}

            # Load local settings (project-level local overrides)
            proj_local_settings = get_project_settings_local_file(project_path)
            if proj_local_settings.exists():
                result["local"] = read_json_file(proj_local_settings) or {}

        return result

    def get_resolved_config(self, project_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Get resolved configuration showing effective values and their source scopes.
        
        Merge priority (highest to lowest): Managed → Local → Project → User

        Args:
            project_path: Optional project directory path

        Returns:
            Dictionary with resolved settings, showing effective value and source scope for each key
        """
        scoped_settings = self.get_all_scoped_settings(project_path)
        
        # Build resolved config with source tracking
        resolved = {}
        
        # Collect all unique keys from all scopes
        all_keys = set()
        for scope_settings in scoped_settings.values():
            all_keys.update(self._flatten_keys(scope_settings))
        
        # For each key, find the effective value and its source
        for key in all_keys:
            effective_value, source_scope, all_values = self._resolve_key(key, scoped_settings)
            resolved[key] = {
                "effective_value": effective_value,
                "source_scope": source_scope,
                "values_by_scope": all_values
            }
        
        return {
            "resolved": resolved,
            "scopes": {
                "managed": {
                    "settings": scoped_settings["managed"],
                    "path": str(get_managed_settings_file()),
                    "exists": get_managed_settings_file().exists(),
                    "readonly": True
                },
                "user": {
                    "settings": scoped_settings["user"],
                    "path": str(get_claude_user_settings_file()),
                    "exists": get_claude_user_settings_file().exists(),
                    "readonly": False
                },
                "project": {
                    "settings": scoped_settings["project"],
                    "path": str(get_project_settings_file(project_path)) if project_path else None,
                    "exists": get_project_settings_file(project_path).exists() if project_path else False,
                    "readonly": False
                },
                "local": {
                    "settings": scoped_settings["local"],
                    "path": str(get_project_settings_local_file(project_path)) if project_path else None,
                    "exists": get_project_settings_local_file(project_path).exists() if project_path else False,
                    "readonly": False
                }
            }
        }

    def _flatten_keys(self, d: Dict[str, Any], parent_key: str = "") -> set:
        """Flatten nested dict keys using dot notation."""
        keys = set()
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, dict):
                keys.update(self._flatten_keys(v, new_key))
            else:
                keys.add(new_key)
        return keys

    def _get_nested_value(self, d: Dict[str, Any], key: str) -> Tuple[Any, bool]:
        """Get a nested value by dot-notation key. Returns (value, found)."""
        parts = key.split(".")
        current = d
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None, False
        return current, True

    def _resolve_key(self, key: str, scoped_settings: Dict[str, Dict[str, Any]]) -> Tuple[Any, str, Dict[str, Any]]:
        """
        Resolve a setting key across all scopes.
        
        Returns (effective_value, source_scope, values_by_scope)
        """
        values_by_scope = {}
        effective_value = None
        source_scope = None
        
        # Check each scope in priority order (managed first, then local, project, user)
        for scope in SCOPE_PRIORITY:
            value, found = self._get_nested_value(scoped_settings.get(scope, {}), key)
            if found:
                values_by_scope[scope] = value
                # First found value wins (due to priority order)
                if effective_value is None:
                    effective_value = value
                    source_scope = scope
        
        return effective_value, source_scope, values_by_scope
