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
            PermissionListResponse with all rules
        """
        rules: List[PermissionRule] = []

        # Read user-level permissions
        user_settings_path = get_claude_user_settings_file()
        user_settings = read_json_file(user_settings_path)
        if user_settings and "permissions" in user_settings:
            permissions = user_settings["permissions"]

            # Parse allow rules
            if "allow" in permissions:
                for pattern in permissions["allow"]:
                    # Generate deterministic ID based on pattern and type
                    rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user-allow-{pattern}"))
                    rules.append(
                        PermissionRule(
                            id=rule_id,
                            type="allow",
                            pattern=pattern,
                            scope="user",
                        )
                    )

            # Parse deny rules
            if "deny" in permissions:
                for pattern in permissions["deny"]:
                    # Generate deterministic ID based on pattern and type
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

                # Parse allow rules
                if "allow" in permissions:
                    for pattern in permissions["allow"]:
                        # Generate deterministic ID based on pattern and type
                        rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"project-allow-{pattern}"))
                        rules.append(
                            PermissionRule(
                                id=rule_id,
                                type="allow",
                                pattern=pattern,
                                scope="project",
                            )
                        )

                # Parse deny rules
                if "deny" in permissions:
                    for pattern in permissions["deny"]:
                        # Generate deterministic ID based on pattern and type
                        rule_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"project-deny-{pattern}"))
                        rules.append(
                            PermissionRule(
                                id=rule_id,
                                type="deny",
                                pattern=pattern,
                                scope="project",
                            )
                        )

        return PermissionListResponse(rules=rules)

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
            settings["permissions"] = {"allow": [], "deny": []}
        if "allow" not in settings["permissions"]:
            settings["permissions"]["allow"] = []
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
    def validate_pattern(pattern: str) -> bool:
        """
        Validate permission pattern format.

        Pattern format examples:
        - Tool(pattern): Bash(npm*), Read(~/.zshrc), Write(*.py)
        - Tool:subcommand: Task:explore, Grep:regex

        Args:
            pattern: Pattern to validate

        Returns:
            True if valid, False otherwise
        """
        # Pattern must be non-empty
        if not pattern or not pattern.strip():
            return False

        # Check for Tool(pattern) format
        tool_pattern_regex = r"^[A-Za-z_][A-Za-z0-9_]*\(.*\)$"
        if re.match(tool_pattern_regex, pattern):
            return True

        # Check for Tool:subcommand format
        tool_subcommand_regex = r"^[A-Za-z_][A-Za-z0-9_]*:[A-Za-z0-9_\-]+$"
        if re.match(tool_subcommand_regex, pattern):
            return True

        # Check for simple tool name
        tool_name_regex = r"^[A-Za-z_][A-Za-z0-9_]*$"
        if re.match(tool_name_regex, pattern):
            return True

        return False
