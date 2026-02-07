"""Service for managing slash commands."""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from app.models.schemas import SlashCommand, SlashCommandCreate, SlashCommandUpdate
from app.utils.path_utils import (
    ensure_directory_exists,
    get_project_commands_dir,
    get_claude_user_commands_dir,
    get_claude_user_plugins_dir,
)
from app.utils.file_utils import read_json_file


class CommandService:
    """Service for managing slash commands."""

    @staticmethod
    def _parse_frontmatter(content: str) -> Tuple[Dict, str]:
        """
        Parse YAML frontmatter from markdown content.

        Returns:
            Tuple of (metadata dict, content without frontmatter)
        """
        # Match frontmatter pattern: ---\n...\n---
        frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if match:
            yaml_content = match.group(1)
            markdown_content = match.group(2).strip()

            try:
                metadata = yaml.safe_load(yaml_content) or {}
            except yaml.YAMLError:
                metadata = {}

            return metadata, markdown_content
        else:
            return {}, content.strip()

    @staticmethod
    def _build_frontmatter(metadata: Dict) -> str:
        """
        Build YAML frontmatter string from metadata dict.

        Args:
            metadata: Dictionary of frontmatter metadata

        Returns:
            Formatted frontmatter string with delimiters
        """
        if not metadata:
            return ""

        yaml_content = yaml.dump(metadata, default_flow_style=False, allow_unicode=True)
        return f"---\n{yaml_content}---\n\n"

    @staticmethod
    def _path_to_name(file_path: Path, base_dir: Path) -> str:
        """
        Convert file path to command name with namespace.

        Example: commands/tools/analyze.md -> tools:analyze
        """
        relative_path = file_path.relative_to(base_dir)
        parts = list(relative_path.parts)

        # Remove .md extension from last part
        if parts:
            parts[-1] = parts[-1].replace(".md", "")

        # Join with colon for namespacing
        return ":".join(parts)

    @staticmethod
    def _name_to_path(name: str, base_dir: Path) -> Path:
        """
        Convert command name with namespace to file path.

        Example: tools:analyze -> commands/tools/analyze.md
        """
        parts = name.split(":")
        parts[-1] = f"{parts[-1]}.md"
        return base_dir / Path(*parts)

    @staticmethod
    def list_commands(project_path: Optional[str] = None) -> List[SlashCommand]:
        """
        List all commands from user, project, and plugin scopes.

        Args:
            project_path: Optional project path for project-scoped commands

        Returns:
            List of SlashCommand objects
        """
        commands = []

        # User commands
        user_commands_dir = get_claude_user_commands_dir()
        if user_commands_dir.exists():
            commands.extend(
                CommandService._scan_commands_dir(user_commands_dir, "user")
            )

        # Project commands
        if project_path:
            project_commands_dir = get_project_commands_dir(project_path)
            if project_commands_dir.exists():
                commands.extend(
                    CommandService._scan_commands_dir(
                        project_commands_dir, "project"
                    )
                )

        # Plugin commands - scan installed plugins from installed_plugins.json
        commands.extend(CommandService._scan_plugin_commands())

        return commands

    @staticmethod
    def _scan_plugin_commands() -> List[SlashCommand]:
        """
        Scan installed plugin directories for commands.

        Returns:
            List of SlashCommand objects from plugins
        """
        commands = []

        installed_file = get_claude_user_plugins_dir() / "installed_plugins.json"
        if not installed_file.exists():
            return commands

        installed_data = read_json_file(installed_file)
        if not installed_data or "plugins" not in installed_data:
            return commands

        # Get enabled plugins from settings
        from app.utils.path_utils import get_claude_user_settings_file
        settings_file = get_claude_user_settings_file()
        settings_data = read_json_file(settings_file) or {}
        enabled_plugins = settings_data.get("enabledPlugins", {})

        for plugin_key, install_list in installed_data.get("plugins", {}).items():
            # Check if plugin is enabled
            if not enabled_plugins.get(plugin_key, False):
                continue

            if not install_list or len(install_list) == 0:
                continue

            install_path = install_list[0].get("installPath")
            if not install_path:
                continue

            plugin_dir = Path(install_path)
            commands_dir = plugin_dir / "commands"

            if commands_dir.exists():
                # Extract plugin name for scope
                plugin_name = plugin_key.split("@")[0] if "@" in plugin_key else plugin_key
                scope = f"plugin:{plugin_name}"

                for md_file in commands_dir.glob("*.md"):
                    try:
                        content = md_file.read_text(encoding="utf-8")
                        metadata, markdown_content = CommandService._parse_frontmatter(content)

                        command_name = md_file.stem  # filename without .md

                        # Handle allowed-tools which can be string or list
                        allowed_tools = metadata.get("allowed-tools")
                        if isinstance(allowed_tools, str):
                            # Split comma-separated string into list
                            allowed_tools = [t.strip() for t in allowed_tools.split(",")]

                        commands.append(
                            SlashCommand(
                                name=command_name,
                                path=str(md_file.relative_to(plugin_dir)),
                                scope=scope,
                                description=metadata.get("description"),
                                allowed_tools=allowed_tools,
                                content=markdown_content,
                            )
                        )
                    except Exception as e:
                        print(f"Error reading plugin command {md_file}: {e}")
                        continue

        return commands

    @staticmethod
    def _scan_commands_dir(base_dir: Path, scope: str) -> List[SlashCommand]:
        """
        Scan a commands directory for .md files.

        Args:
            base_dir: Base commands directory
            scope: "user" or "project"

        Returns:
            List of SlashCommand objects
        """
        commands = []

        # Recursively find all .md files
        for md_file in base_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                metadata, markdown_content = CommandService._parse_frontmatter(
                    content
                )

                command_name = CommandService._path_to_name(md_file, base_dir)
                relative_path = str(md_file.relative_to(base_dir))

                commands.append(
                    SlashCommand(
                        name=command_name,
                        path=relative_path,
                        scope=scope,
                        description=metadata.get("description"),
                        allowed_tools=metadata.get("allowed-tools"),
                        content=markdown_content,
                    )
                )
            except Exception as e:
                # Skip files that can't be read
                print(f"Error reading command file {md_file}: {e}")
                continue

        return commands

    @staticmethod
    def get_command(scope: str, path: str, project_path: Optional[str] = None) -> Optional[SlashCommand]:
        """
        Get a specific command by scope and path.

        Args:
            scope: "user", "project", or "plugin:name"
            path: Relative path to command file
            project_path: Optional project path for project-scoped commands

        Returns:
            SlashCommand object or None if not found
        """
        if scope == "user":
            base_dir = get_claude_user_commands_dir()
            file_path = base_dir / path
        elif scope == "project":
            base_dir = get_project_commands_dir(project_path)
            file_path = base_dir / path
        elif scope.startswith("plugin:"):
            # Handle plugin commands
            plugin_name = scope.replace("plugin:", "")
            return CommandService._get_plugin_command(plugin_name, path)
        else:
            return None

        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            metadata, markdown_content = CommandService._parse_frontmatter(content)

            command_name = CommandService._path_to_name(file_path, base_dir)

            # Handle allowed-tools which can be string or list
            allowed_tools = metadata.get("allowed-tools")
            if isinstance(allowed_tools, str):
                allowed_tools = [t.strip() for t in allowed_tools.split(",")]

            return SlashCommand(
                name=command_name,
                path=path,
                scope=scope,
                description=metadata.get("description"),
                allowed_tools=allowed_tools,
                content=markdown_content,
            )
        except Exception as e:
            print(f"Error reading command file {file_path}: {e}")
            return None

    @staticmethod
    def _get_plugin_command(plugin_name: str, path: str) -> Optional[SlashCommand]:
        """
        Get a command from a plugin directory.

        Args:
            plugin_name: Plugin name (e.g., "posthog")
            path: Relative path to command file (e.g., "commands/docs.md")

        Returns:
            SlashCommand object or None if not found
        """
        installed_file = get_claude_user_plugins_dir() / "installed_plugins.json"
        if not installed_file.exists():
            return None

        installed_data = read_json_file(installed_file)
        if not installed_data or "plugins" not in installed_data:
            return None

        # Find matching plugin
        for plugin_key, install_list in installed_data.get("plugins", {}).items():
            key_plugin_name = plugin_key.split("@")[0] if "@" in plugin_key else plugin_key
            if key_plugin_name != plugin_name:
                continue

            if not install_list or len(install_list) == 0:
                continue

            install_path = install_list[0].get("installPath")
            if not install_path:
                continue

            plugin_dir = Path(install_path)
            file_path = plugin_dir / path

            if not file_path.exists():
                return None

            try:
                content = file_path.read_text(encoding="utf-8")
                metadata, markdown_content = CommandService._parse_frontmatter(content)

                command_name = file_path.stem

                # Handle allowed-tools which can be string or list
                allowed_tools = metadata.get("allowed-tools")
                if isinstance(allowed_tools, str):
                    allowed_tools = [t.strip() for t in allowed_tools.split(",")]

                return SlashCommand(
                    name=command_name,
                    path=path,
                    scope=f"plugin:{plugin_name}",
                    description=metadata.get("description"),
                    allowed_tools=allowed_tools,
                    content=markdown_content,
                )
            except Exception as e:
                print(f"Error reading plugin command {file_path}: {e}")
                return None

        return None

    @staticmethod
    def create_command(
        command: SlashCommandCreate, project_path: Optional[str] = None
    ) -> SlashCommand:
        """
        Create a new command file.

        Args:
            command: SlashCommandCreate object with command data
            project_path: Optional project path for project-scoped commands

        Returns:
            Created SlashCommand object

        Raises:
            ValueError: If command already exists or invalid scope
        """
        if command.scope == "user":
            base_dir = get_user_commands_dir()
        elif command.scope == "project":
            base_dir = get_project_commands_dir(project_path)
        else:
            raise ValueError(f"Invalid scope: {command.scope}")

        # Convert name to file path
        file_path = CommandService._name_to_path(command.name, base_dir)

        # Check if file already exists
        if file_path.exists():
            raise ValueError(f"Command already exists: {command.name}")

        # Ensure parent directory exists
        ensure_directory_exists(file_path.parent)

        # Build frontmatter
        metadata = {}
        if command.description:
            metadata["description"] = command.description
        if command.allowed_tools:
            metadata["allowed-tools"] = command.allowed_tools

        frontmatter = CommandService._build_frontmatter(metadata)
        full_content = frontmatter + command.content

        # Write file
        file_path.write_text(full_content, encoding="utf-8")

        relative_path = str(file_path.relative_to(base_dir))

        return SlashCommand(
            name=command.name,
            path=relative_path,
            scope=command.scope,
            description=command.description,
            allowed_tools=command.allowed_tools,
            content=command.content,
        )

    @staticmethod
    def update_command(
        scope: str,
        path: str,
        command: SlashCommandUpdate,
        project_path: Optional[str] = None,
    ) -> Optional[SlashCommand]:
        """
        Update an existing command file.

        Args:
            scope: "user" or "project"
            path: Relative path to command file
            command: SlashCommandUpdate object with updated data
            project_path: Optional project path for project-scoped commands

        Returns:
            Updated SlashCommand object or None if not found
        """
        if scope == "user":
            base_dir = get_claude_user_commands_dir()
        else:
            base_dir = get_project_commands_dir(project_path)

        file_path = base_dir / path
        if not file_path.exists():
            return None

        try:
            # Read existing content
            existing_content = file_path.read_text(encoding="utf-8")
            metadata, markdown_content = CommandService._parse_frontmatter(
                existing_content
            )

            # Update metadata
            if command.description is not None:
                metadata["description"] = command.description
            if command.allowed_tools is not None:
                metadata["allowed-tools"] = command.allowed_tools

            # Update content
            if command.content is not None:
                markdown_content = command.content

            # Build new content
            frontmatter = CommandService._build_frontmatter(metadata)
            full_content = frontmatter + markdown_content

            # Write file
            file_path.write_text(full_content, encoding="utf-8")

            command_name = CommandService._path_to_name(file_path, base_dir)

            return SlashCommand(
                name=command_name,
                path=path,
                scope=scope,
                description=metadata.get("description"),
                allowed_tools=metadata.get("allowed-tools"),
                content=markdown_content,
            )
        except Exception as e:
            print(f"Error updating command file {file_path}: {e}")
            return None

    @staticmethod
    def delete_command(
        scope: str, path: str, project_path: Optional[str] = None
    ) -> bool:
        """
        Delete a command file.

        Args:
            scope: "user" or "project"
            path: Relative path to command file
            project_path: Optional project path for project-scoped commands

        Returns:
            True if deleted, False if not found
        """
        if scope == "user":
            base_dir = get_claude_user_commands_dir()
        else:
            base_dir = get_project_commands_dir(project_path)

        file_path = base_dir / path
        if not file_path.exists():
            return False

        try:
            file_path.unlink()
            return True
        except Exception as e:
            print(f"Error deleting command file {file_path}: {e}")
            return False
