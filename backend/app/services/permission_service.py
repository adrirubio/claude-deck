"""Permission management service."""
import re
import uuid
from pathlib import Path
from typing import List, Optional

from app.models.schemas import (
    PermissionListResponse,
    PermissionRule,
    PermissionRuleCreate,
    PermissionRuleUpdate,
    PermissionSettings,
    PermissionSettingsUpdate,
    VALID_PERMISSION_MODES,
)
from app.utils.file_utils import read_json_file, write_json_file
from app.utils.path_utils import (
    get_claude_user_settings_file,
    get_project_settings_file,
)


class PermissionService:
    """Service for managing permission rules."""

    @staticmethod
    def list_permissions(project_path: Optional[str] = None) -> PermissionListResponse:
        """
        List all permission rules from user and project scopes.

        Args:
            project_path: Optional path to project directory

        Returns:
            PermissionListResponse with all rules and settings
        """
        rules: List[PermissionRule] = []
        settings = PermissionSettings()

        # Read user-level permissions
        user_settings_path = get_claude_user_settings_file()
        user_settings = read_json_file(user_settings_path)
        if user_settings and "permissions" in user_settings:
            permissions = user_settings["permissions"]

            # Parse settings
            if "defaultMode" in permissions:
                settings.defaultMode = permissions["defaultMode"]
            if "additionalDirectories" in permissions:
                settings.additionalDirectories = permissions["additionalDirectories"]
            if "disableBypassPermissionsMode" in permissions:
                settings.disableBypassPermissionsMode = permissions["disableBypassPermissionsMode"]

            # Parse allow rules
            if "allow" in permissions:
                for pattern in permissions["allow"]:
                    rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user-allow-{pattern}"))
                    rules.append(
                        PermissionRule(
                            id=rule_id,
                            type="allow",
                            pattern=pattern,
                            scope="user",
                        )
                    )

            # Parse ask rules
            if "ask" in permissions:
                for pattern in permissions["ask"]:
                    rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user-ask-{pattern}"))
                    rules.append(
                        PermissionRule(
                            id=rule_id,
                            type="ask",
                            pattern=pattern,
                            scope="user",
                        )
                    )

            # Parse deny rules
            if "deny" in permissions:
                for pattern in permissions["deny"]:
                    rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user-deny-{pattern}"))
                    rules.append(
                        PermissionRule(
                            id=rule_id,
                            type="deny",
                            pattern=pattern,
                            scope="user",
                        )
                    )

        # Read project-level permissions if project_path is provided
        if project_path:
            project_settings_path = get_project_settings_file(project_path)
            project_settings = read_json_file(project_settings_path)
            if project_settings and "permissions" in project_settings:
                permissions = project_settings["permissions"]

                # Project settings can override user settings
                if "defaultMode" in permissions:
                    settings.defaultMode = permissions["defaultMode"]
                if "additionalDirectories" in permissions:
                    # Merge with user directories
                    project_dirs = permissions["additionalDirectories"]
                    if settings.additionalDirectories:
                        settings.additionalDirectories = list(
                            set(settings.additionalDirectories + project_dirs)
                        )
                    else:
                        settings.additionalDirectories = project_dirs
                if "disableBypassPermissionsMode" in permissions:
                    settings.disableBypassPermissionsMode = permissions["disableBypassPermissionsMode"]

                # Parse allow rules
                if "allow" in permissions:
                    for pattern in permissions["allow"]:
                        rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"project-allow-{pattern}"))
                        rules.append(
                            PermissionRule(
                                id=rule_id,
                                type="allow",
                                pattern=pattern,
                                scope="project",
                            )
                        )

                # Parse ask rules
                if "ask" in permissions:
                    for pattern in permissions["ask"]:
                        rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"project-ask-{pattern}"))
                        rules.append(
                            PermissionRule(
                                id=rule_id,
                                type="ask",
                                pattern=pattern,
                                scope="project",
                            )
                        )

                # Parse deny rules
                if "deny" in permissions:
                    for pattern in permissions["deny"]:
                        rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"project-deny-{pattern}"))
                        rules.append(
                            PermissionRule(
                                id=rule_id,
                                type="deny",
                                pattern=pattern,
                                scope="project",
                            )
                        )

        return PermissionListResponse(rules=rules, settings=settings)

    @staticmethod
    async def add_permission(
        rule: PermissionRuleCreate, project_path: Optional[str] = None
    ) -> PermissionRule:
        """
        Add a new permission rule to the appropriate settings file.

        Args:
            rule: Permission rule to add
            project_path: Optional path to project directory

        Returns:
            Created PermissionRule with generated ID
        """
        # Validate type
        if rule.type not in ["allow", "ask", "deny"]:
            raise ValueError(f"Invalid rule type: {rule.type}. Must be 'allow', 'ask', or 'deny'")

        # Validate pattern
        if not PermissionService.validate_pattern(rule.pattern):
            raise ValueError(f"Invalid pattern format: {rule.pattern}")

        # Determine settings file path
        if rule.scope == "user":
            settings_path = get_claude_user_settings_file()
        else:  # project
            if not project_path:
                raise ValueError("project_path is required for project scope")
            settings_path = get_project_settings_file(project_path)

        # Read existing settings
        settings = read_json_file(settings_path) or {}

        # Ensure permissions structure exists
        if "permissions" not in settings:
            settings["permissions"] = {"allow": [], "ask": [], "deny": []}
        if "allow" not in settings["permissions"]:
            settings["permissions"]["allow"] = []
        if "ask" not in settings["permissions"]:
            settings["permissions"]["ask"] = []
        if "deny" not in settings["permissions"]:
            settings["permissions"]["deny"] = []

        # Check if pattern already exists
        if rule.pattern in settings["permissions"][rule.type]:
            raise ValueError(f"Pattern already exists in {rule.type} list: {rule.pattern}")

        # Add pattern to appropriate list
        settings["permissions"][rule.type].append(rule.pattern)

        # Write back to settings file
        success = await write_json_file(settings_path, settings)
        if not success:
            raise IOError(f"Failed to write settings file: {settings_path}")

        # Generate deterministic ID
        rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{rule.scope}-{rule.type}-{rule.pattern}"))

        return PermissionRule(
            id=rule_id,
            type=rule.type,
            pattern=rule.pattern,
            scope=rule.scope,
        )

    @staticmethod
    async def update_permission(
        rule_id: str,
        rule_update: PermissionRuleUpdate,
        scope: str,
        project_path: Optional[str] = None,
    ) -> PermissionRule:
        """
        Update an existing permission rule.

        Args:
            rule_id: ID of the rule to update
            rule_update: Updated rule data
            scope: Scope of the rule (user or project)
            project_path: Optional path to project directory

        Returns:
            Updated PermissionRule
        """
        # Validate type if provided
        if rule_update.type and rule_update.type not in ["allow", "ask", "deny"]:
            raise ValueError(f"Invalid rule type: {rule_update.type}. Must be 'allow', 'ask', or 'deny'")

        # Find existing rule
        all_rules = PermissionService.list_permissions(project_path)
        existing_rule = None
        for rule in all_rules.rules:
            if rule.id == rule_id and rule.scope == scope:
                existing_rule = rule
                break

        if not existing_rule:
            raise ValueError(f"Permission rule not found: {rule_id}")

        # Remove old rule
        await PermissionService.remove_permission(rule_id, scope, project_path)

        # Create updated rule
        new_rule = PermissionRuleCreate(
            type=rule_update.type or existing_rule.type,
            pattern=rule_update.pattern or existing_rule.pattern,
            scope=scope,
        )

        # Add updated rule
        return await PermissionService.add_permission(new_rule, project_path)

    @staticmethod
    async def remove_permission(
        rule_id: str, scope: str, project_path: Optional[str] = None
    ) -> None:
        """
        Remove a permission rule from settings.

        Args:
            rule_id: ID of the rule to remove
            scope: Scope of the rule (user or project)
            project_path: Optional path to project directory
        """
        # Find existing rule
        all_rules = PermissionService.list_permissions(project_path)
        existing_rule = None
        for rule in all_rules.rules:
            if rule.id == rule_id and rule.scope == scope:
                existing_rule = rule
                break

        if not existing_rule:
            raise ValueError(f"Permission rule not found: {rule_id}")

        # Determine settings file path
        if scope == "user":
            settings_path = get_claude_user_settings_file()
        else:  # project
            if not project_path:
                raise ValueError("project_path is required for project scope")
            settings_path = get_project_settings_file(project_path)

        # Read existing settings
        settings = read_json_file(settings_path) or {}

        if "permissions" not in settings or existing_rule.type not in settings["permissions"]:
            raise ValueError(f"Permissions not found in settings")

        # Remove pattern from appropriate list
        if existing_rule.pattern in settings["permissions"][existing_rule.type]:
            settings["permissions"][existing_rule.type].remove(existing_rule.pattern)

        # Write back to settings file
        success = await write_json_file(settings_path, settings)
        if not success:
            raise IOError(f"Failed to write settings file: {settings_path}")

    @staticmethod
    async def update_settings(
        settings_update: PermissionSettingsUpdate,
        scope: str,
        project_path: Optional[str] = None,
    ) -> PermissionSettings:
        """
        Update permission settings (mode, directories, etc.).

        Args:
            settings_update: Settings to update
            scope: Scope to update (user or project)
            project_path: Optional path to project directory

        Returns:
            Updated PermissionSettings
        """
        # Validate mode if provided
        if settings_update.defaultMode and settings_update.defaultMode not in VALID_PERMISSION_MODES:
            raise ValueError(
                f"Invalid permission mode: {settings_update.defaultMode}. "
                f"Must be one of: {', '.join(VALID_PERMISSION_MODES)}"
            )

        # Determine settings file path
        if scope == "user":
            settings_path = get_claude_user_settings_file()
        else:  # project
            if not project_path:
                raise ValueError("project_path is required for project scope")
            settings_path = get_project_settings_file(project_path)

        # Read existing settings
        settings = read_json_file(settings_path) or {}

        # Ensure permissions structure exists
        if "permissions" not in settings:
            settings["permissions"] = {}

        # Update settings
        if settings_update.defaultMode is not None:
            settings["permissions"]["defaultMode"] = settings_update.defaultMode
        if settings_update.additionalDirectories is not None:
            settings["permissions"]["additionalDirectories"] = settings_update.additionalDirectories
        if settings_update.disableBypassPermissionsMode is not None:
            settings["permissions"]["disableBypassPermissionsMode"] = settings_update.disableBypassPermissionsMode

        # Write back to settings file
        success = await write_json_file(settings_path, settings)
        if not success:
            raise IOError(f"Failed to write settings file: {settings_path}")

        # Return current settings
        result = PermissionService.list_permissions(project_path)
        return result.settings or PermissionSettings()

    @staticmethod
    def validate_pattern(pattern: str) -> bool:
        """
        Validate permission pattern format.

        Pattern format examples:
        - Tool(pattern): Bash(npm run *), Read(~/.zshrc), Write(*.py)
        - Tool:subcommand: Task:explore
        - Tool:*: Bash:* (prefix matching at tool level)
        - WebFetch(domain:example.com)
        - MCP(server:tool) or MCP(server:*)
        - Task(*) or Task(explore)
        - Skill(skill-name)
        - mcp__server__tool (MCP tool names)

        Args:
            pattern: Pattern to validate

        Returns:
            True if valid, False otherwise
        """
        from app.utils.pattern_utils import validate_permission_pattern
        is_valid, _ = validate_permission_pattern(pattern)
        return is_valid

    @staticmethod
    def evaluate_permission(
        tool: str,
        argument: Optional[str],
        project_path: Optional[str] = None,
    ) -> str:
        """
        Evaluate permission for a tool/argument combination.

        Evaluation order: deny first → ask → allow

        Args:
            tool: Tool name (e.g., "Bash", "Read")
            argument: Tool argument (e.g., "npm install")
            project_path: Optional project path for project-level rules

        Returns:
            "allow", "ask", or "deny"
        """
        rules_response = PermissionService.list_permissions(project_path)
        rules = rules_response.rules

        # Build the full pattern to match against
        if argument:
            full_pattern = f"{tool}({argument})"
        else:
            full_pattern = tool

        # Check deny rules first (highest priority)
        for rule in rules:
            if rule.type == "deny" and PermissionService._matches_pattern(rule.pattern, tool, argument):
                return "deny"

        # Check ask rules next
        for rule in rules:
            if rule.type == "ask" and PermissionService._matches_pattern(rule.pattern, tool, argument):
                return "ask"

        # Check allow rules
        for rule in rules:
            if rule.type == "allow" and PermissionService._matches_pattern(rule.pattern, tool, argument):
                return "allow"

        # Default based on settings
        settings = rules_response.settings
        if settings and settings.defaultMode == "dontAsk":
            return "allow"
        return "ask"  # Default is to ask

    @staticmethod
    def _matches_pattern(rule_pattern: str, tool: str, argument: Optional[str]) -> bool:
        """
        Check if a rule pattern matches the given tool and argument.

        Args:
            rule_pattern: The permission rule pattern
            tool: Tool name
            argument: Tool argument (optional)

        Returns:
            True if matches, False otherwise
        """
        import fnmatch

        # Parse the rule pattern
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\((.+)\)$", rule_pattern)
        if match:
            pattern_tool = match.group(1)
            pattern_arg = match.group(2)

            # Tool must match
            if pattern_tool != tool and pattern_tool != "*":
                return False

            # If no argument provided, only match if pattern is wildcard
            if argument is None:
                return pattern_arg == "*"

            # Use fnmatch for glob-style matching
            return fnmatch.fnmatch(argument, pattern_arg)

        # Check for Tool:subcommand format
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):([A-Za-z0-9_\-\*]+)$", rule_pattern)
        if match:
            pattern_tool = match.group(1)
            pattern_subcommand = match.group(2)

            if pattern_tool != tool:
                return False

            if argument is None:
                return pattern_subcommand == "*"

            # Extract subcommand from argument (first word before space or colon)
            arg_parts = re.split(r"[\s:]", argument, maxsplit=1)
            arg_subcommand = arg_parts[0] if arg_parts else ""

            return fnmatch.fnmatch(arg_subcommand, pattern_subcommand)

        # Simple tool name match
        return rule_pattern == tool or rule_pattern == "*"
