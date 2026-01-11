"""Service for managing Claude Code hooks."""
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from app.models.schemas import Hook, HookCreate, HookUpdate
from app.utils.path_utils import (
    get_claude_user_settings_file,
    get_project_settings_file,
)


class HookService:
    """Service for managing hook configurations."""

    def __init__(self):
        """Initialize the hook service."""
        pass

    def list_hooks(self, project_path: Optional[str] = None) -> List[Hook]:
        """
        List all hooks from user and project settings files.

        Args:
            project_path: Optional path to project directory

        Returns:
            List of Hook objects
        """
        hooks = []

        # Read user-level hooks
        user_settings_file = get_claude_user_settings_file()
        if user_settings_file.exists():
            try:
                with open(user_settings_file, "r") as f:
                    user_settings = json.load(f)
                    user_hooks = user_settings.get("hooks", {})

                    # Hooks are organized by event type in settings.json
                    for event, event_hooks in user_hooks.items():
                        if isinstance(event_hooks, list):
                            for hook_data in event_hooks:
                                hook_id = hook_data.get("id", str(uuid.uuid4()))
                                hooks.append(Hook(
                                    id=hook_id,
                                    event=event,
                                    matcher=hook_data.get("matcher"),
                                    type=hook_data.get("type", "command"),
                                    command=hook_data.get("command"),
                                    prompt=hook_data.get("prompt"),
                                    timeout=hook_data.get("timeout"),
                                    scope="user"
                                ))
            except (json.JSONDecodeError, IOError):
                pass

        # Read project-level hooks
        if project_path:
            project_settings_file = get_project_settings_file(project_path)
            if project_settings_file.exists():
                try:
                    with open(project_settings_file, "r") as f:
                        project_settings = json.load(f)
                        project_hooks = project_settings.get("hooks", {})

                        for event, event_hooks in project_hooks.items():
                            if isinstance(event_hooks, list):
                                for hook_data in event_hooks:
                                    hook_id = hook_data.get("id", str(uuid.uuid4()))
                                    hooks.append(Hook(
                                        id=hook_id,
                                        event=event,
                                        matcher=hook_data.get("matcher"),
                                        type=hook_data.get("type", "command"),
                                        command=hook_data.get("command"),
                                        prompt=hook_data.get("prompt"),
                                        timeout=hook_data.get("timeout"),
                                        scope="project"
                                    ))
                except (json.JSONDecodeError, IOError):
                    pass

        return hooks

    def get_hooks_by_event(
        self, event: str, project_path: Optional[str] = None
    ) -> List[Hook]:
        """
        Get hooks filtered by event type.

        Args:
            event: Event type to filter by
            project_path: Optional path to project directory

        Returns:
            List of Hook objects for the specified event
        """
        all_hooks = self.list_hooks(project_path)
        return [hook for hook in all_hooks if hook.event == event]

    def add_hook(
        self, hook: HookCreate, project_path: Optional[str] = None
    ) -> Hook:
        """
        Add a new hook to the appropriate settings file.

        Args:
            hook: Hook creation data
            project_path: Optional path to project directory

        Returns:
            Created Hook object
        """
        # Generate unique ID
        hook_id = str(uuid.uuid4())

        # Determine settings file path
        if hook.scope == "user":
            settings_file = get_claude_user_settings_file()
        else:
            settings_file = get_project_settings_file(project_path)

        # Ensure parent directory exists
        settings_file.parent.mkdir(parents=True, exist_ok=True)

        # Read existing settings or create new
        if settings_file.exists():
            with open(settings_file, "r") as f:
                settings = json.load(f)
        else:
            settings = {}

        # Ensure hooks section exists
        if "hooks" not in settings:
            settings["hooks"] = {}

        # Ensure event array exists
        if hook.event not in settings["hooks"]:
            settings["hooks"][hook.event] = []

        # Create hook data
        hook_data = {
            "id": hook_id,
            "type": hook.type,
        }

        if hook.matcher:
            hook_data["matcher"] = hook.matcher
        if hook.command:
            hook_data["command"] = hook.command
        if hook.prompt:
            hook_data["prompt"] = hook.prompt
        if hook.timeout:
            hook_data["timeout"] = hook.timeout

        # Add hook to settings
        settings["hooks"][hook.event].append(hook_data)

        # Write settings back
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)

        return Hook(
            id=hook_id,
            event=hook.event,
            matcher=hook.matcher,
            type=hook.type,
            command=hook.command,
            prompt=hook.prompt,
            timeout=hook.timeout,
            scope=hook.scope
        )

    def update_hook(
        self,
        hook_id: str,
        hook_update: HookUpdate,
        scope: str,
        project_path: Optional[str] = None
    ) -> Optional[Hook]:
        """
        Update an existing hook.

        Args:
            hook_id: ID of the hook to update
            hook_update: Hook update data
            scope: "user" or "project"
            project_path: Optional path to project directory

        Returns:
            Updated Hook object or None if not found
        """
        # Determine settings file path
        if scope == "user":
            settings_file = get_claude_user_settings_file()
        else:
            settings_file = get_project_settings_file(project_path)

        if not settings_file.exists():
            return None

        # Read settings
        with open(settings_file, "r") as f:
            settings = json.load(f)

        hooks_section = settings.get("hooks", {})

        # Find and update hook
        updated_hook = None
        for event, event_hooks in hooks_section.items():
            if isinstance(event_hooks, list):
                for i, hook_data in enumerate(event_hooks):
                    if hook_data.get("id") == hook_id:
                        # Update fields
                        if hook_update.event:
                            # Move to different event if needed
                            if hook_update.event != event:
                                # Remove from current event
                                event_hooks.pop(i)
                                # Add to new event
                                if hook_update.event not in hooks_section:
                                    hooks_section[hook_update.event] = []
                                hooks_section[hook_update.event].append(hook_data)
                                event = hook_update.event

                        if hook_update.matcher is not None:
                            hook_data["matcher"] = hook_update.matcher
                        if hook_update.type is not None:
                            hook_data["type"] = hook_update.type
                        if hook_update.command is not None:
                            hook_data["command"] = hook_update.command
                        if hook_update.prompt is not None:
                            hook_data["prompt"] = hook_update.prompt
                        if hook_update.timeout is not None:
                            hook_data["timeout"] = hook_update.timeout

                        updated_hook = Hook(
                            id=hook_id,
                            event=event,
                            matcher=hook_data.get("matcher"),
                            type=hook_data.get("type", "command"),
                            command=hook_data.get("command"),
                            prompt=hook_data.get("prompt"),
                            timeout=hook_data.get("timeout"),
                            scope=scope
                        )
                        break
            if updated_hook:
                break

        if not updated_hook:
            return None

        # Write settings back
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)

        return updated_hook

    def remove_hook(
        self, hook_id: str, scope: str, project_path: Optional[str] = None
    ) -> bool:
        """
        Remove a hook from settings.

        Args:
            hook_id: ID of the hook to remove
            scope: "user" or "project"
            project_path: Optional path to project directory

        Returns:
            True if removed, False if not found
        """
        # Determine settings file path
        if scope == "user":
            settings_file = get_claude_user_settings_file()
        else:
            settings_file = get_project_settings_file(project_path)

        if not settings_file.exists():
            return False

        # Read settings
        with open(settings_file, "r") as f:
            settings = json.load(f)

        hooks_section = settings.get("hooks", {})

        # Find and remove hook
        removed = False
        for event, event_hooks in hooks_section.items():
            if isinstance(event_hooks, list):
                for i, hook_data in enumerate(event_hooks):
                    if hook_data.get("id") == hook_id:
                        event_hooks.pop(i)
                        removed = True
                        break
            if removed:
                break

        if not removed:
            return False

        # Write settings back
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)

        return True
