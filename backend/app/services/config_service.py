"""Configuration service for reading and merging Claude Code configurations."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..utils.path_utils import ClaudePathUtils
from ..utils.file_utils import read_json_file


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
