"""Service for managing Claude Code status line configuration."""
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from app.models.schemas import (
    StatusLineConfig,
    StatusLinePreset,
    StatusLineUpdate,
    PowerlinePreset,
)
from app.utils.path_utils import get_claude_user_settings_file


# Mock data for status line preview
MOCK_PREVIEW_DATA = {
    "model": {"display_name": "claude-sonnet-4-20250514"},
    "workspace": {"current_dir": "/home/user/my-project"},
    "context_window": {"used": 45000, "max": 200000},
}


# Preset status line scripts
STATUSLINE_PRESETS: List[StatusLinePreset] = [
    StatusLinePreset(
        id="simple",
        name="Simple",
        description="Shows model name and current directory",
        script='''#!/bin/bash
input=$(cat)
MODEL_DISPLAY=$(echo "$input" | jq -r '.model.display_name')
CURRENT_DIR=$(echo "$input" | jq -r '.workspace.current_dir')
echo "[$MODEL_DISPLAY] 📁 ${CURRENT_DIR##*/}"
''',
    ),
    StatusLinePreset(
        id="git-aware",
        name="Git Aware",
        description="Shows model, directory, and git branch",
        script='''#!/bin/bash
input=$(cat)
MODEL_DISPLAY=$(echo "$input" | jq -r '.model.display_name')
CURRENT_DIR=$(echo "$input" | jq -r '.workspace.current_dir')
GIT_BRANCH=""
if git rev-parse --git-dir > /dev/null 2>&1; then
    BRANCH=$(git branch --show-current 2>/dev/null)
    if [ -n "$BRANCH" ]; then
        GIT_BRANCH=" | 🌿 $BRANCH"
    fi
fi
echo "[$MODEL_DISPLAY] 📁 ${CURRENT_DIR##*/}$GIT_BRANCH"
''',
    ),
    StatusLinePreset(
        id="minimal",
        name="Minimal",
        description="Just the model name",
        script='''#!/bin/bash
input=$(cat)
MODEL_DISPLAY=$(echo "$input" | jq -r '.model.display_name')
echo "$MODEL_DISPLAY"
''',
    ),
    StatusLinePreset(
        id="full-context",
        name="Full Context",
        description="Model, directory, git branch, and context usage",
        script='''#!/bin/bash
input=$(cat)
MODEL_DISPLAY=$(echo "$input" | jq -r '.model.display_name')
CURRENT_DIR=$(echo "$input" | jq -r '.workspace.current_dir')
CONTEXT_USED=$(echo "$input" | jq -r '.context_window.used // 0')
CONTEXT_MAX=$(echo "$input" | jq -r '.context_window.max // 200000')

# Calculate percentage
if [ "$CONTEXT_MAX" -gt 0 ]; then
    PERCENT=$((CONTEXT_USED * 100 / CONTEXT_MAX))
else
    PERCENT=0
fi

# Git branch
GIT_BRANCH=""
if git rev-parse --git-dir > /dev/null 2>&1; then
    BRANCH=$(git branch --show-current 2>/dev/null)
    if [ -n "$BRANCH" ]; then
        GIT_BRANCH=" 🌿 $BRANCH"
    fi
fi

echo "[$MODEL_DISPLAY] 📁 ${CURRENT_DIR##*/}$GIT_BRANCH | 📊 ${PERCENT}%"
''',
    ),
]


# Powerline presets (uses npx command, requires Node.js)
POWERLINE_PRESETS: List[PowerlinePreset] = [
    PowerlinePreset(
        id="powerline-dark",
        name="Dark Powerline",
        description="Classic dark theme with powerline separators",
        theme="dark",
        style="powerline",
        command="npx -y @owloops/claude-powerline@latest --theme=dark --style=powerline",
    ),
    PowerlinePreset(
        id="powerline-light",
        name="Light Powerline",
        description="Clean light theme with powerline separators",
        theme="light",
        style="powerline",
        command="npx -y @owloops/claude-powerline@latest --theme=light --style=powerline",
    ),
    PowerlinePreset(
        id="powerline-nord",
        name="Nord Minimal",
        description="Popular Nord color scheme with minimal style",
        theme="nord",
        style="minimal",
        command="npx -y @owloops/claude-powerline@latest --theme=nord --style=minimal",
    ),
    PowerlinePreset(
        id="powerline-tokyo",
        name="Tokyo Night",
        description="Tokyo Night theme with powerline separators",
        theme="tokyo-night",
        style="powerline",
        command="npx -y @owloops/claude-powerline@latest --theme=tokyo-night --style=powerline",
    ),
    PowerlinePreset(
        id="powerline-rose",
        name="Rose Pine Capsule",
        description="Rose Pine theme with capsule-style segments",
        theme="rose-pine",
        style="capsule",
        command="npx -y @owloops/claude-powerline@latest --theme=rose-pine --style=capsule",
    ),
    PowerlinePreset(
        id="powerline-gruvbox",
        name="Gruvbox Minimal",
        description="Retro Gruvbox theme with minimal style",
        theme="gruvbox",
        style="minimal",
        command="npx -y @owloops/claude-powerline@latest --theme=gruvbox --style=minimal",
    ),
]


class StatusLineService:
    """Service for managing status line configuration."""

    def __init__(self):
        """Initialize the status line service."""
        self.default_script_path = Path.home() / ".claude" / "statusline.sh"

    def get_config(self) -> StatusLineConfig:
        """
        Get the current status line configuration.

        Returns:
            StatusLineConfig object
        """
        settings_file = get_claude_user_settings_file()
        config = StatusLineConfig(enabled=False)

        if settings_file.exists():
            try:
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                    status_line = settings.get("statusLine", {})

                    if status_line:
                        config.enabled = True
                        config.type = status_line.get("type", "command")
                        config.command = status_line.get("command")
                        config.padding = status_line.get("padding")
            except (json.JSONDecodeError, IOError):
                pass

        # Read script content if command is set
        if config.command:
            script_path = Path(config.command).expanduser()
            if script_path.exists():
                try:
                    with open(script_path, "r") as f:
                        config.script_content = f.read()
                except IOError:
                    pass

        return config

    def update_config(self, update: StatusLineUpdate) -> StatusLineConfig:
        """
        Update the status line configuration.

        Args:
            update: StatusLineUpdate with fields to update

        Returns:
            Updated StatusLineConfig
        """
        settings_file = get_claude_user_settings_file()

        # Ensure parent directory exists
        settings_file.parent.mkdir(parents=True, exist_ok=True)

        # Read existing settings or create new
        if settings_file.exists():
            with open(settings_file, "r") as f:
                settings = json.load(f)
        else:
            settings = {}

        # Handle enabled/disabled
        if update.enabled is False:
            # Remove statusLine from settings to disable
            if "statusLine" in settings:
                del settings["statusLine"]
        else:
            # Ensure statusLine section exists
            if "statusLine" not in settings:
                settings["statusLine"] = {
                    "type": "command",
                    "command": str(self.default_script_path),
                }

            # Update fields
            if update.type is not None:
                settings["statusLine"]["type"] = update.type
            if update.command is not None:
                settings["statusLine"]["command"] = update.command
            if update.padding is not None:
                settings["statusLine"]["padding"] = update.padding

        # Write settings back
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)

        return self.get_config()

    def get_presets(self) -> List[StatusLinePreset]:
        """
        Get available status line presets.

        Returns:
            List of StatusLinePreset objects
        """
        return STATUSLINE_PRESETS

    def apply_preset(self, preset_id: str) -> StatusLineConfig:
        """
        Apply a preset status line configuration.

        Args:
            preset_id: ID of the preset to apply

        Returns:
            Updated StatusLineConfig

        Raises:
            ValueError: If preset_id is not found
        """
        # Find the preset
        preset = None
        for p in STATUSLINE_PRESETS:
            if p.id == preset_id:
                preset = p
                break

        if not preset:
            raise ValueError(f"Preset not found: {preset_id}")

        # Write the script file
        self.write_script(preset.script)

        # Update the configuration
        return self.update_config(
            StatusLineUpdate(
                type="command",
                command=str(self.default_script_path),
                enabled=True,
            )
        )

    def write_script(self, content: str) -> str:
        """
        Write a status line script to the default location.

        Args:
            content: Script content

        Returns:
            Path to the script file
        """
        # Ensure parent directory exists
        self.default_script_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the script
        with open(self.default_script_path, "w") as f:
            f.write(content)

        # Make it executable
        os.chmod(
            self.default_script_path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )

        return str(self.default_script_path)

    def get_script_content(self) -> Optional[str]:
        """
        Get the current script content.

        Returns:
            Script content or None if not found
        """
        config = self.get_config()
        if config.command:
            script_path = Path(config.command).expanduser()
            if script_path.exists():
                try:
                    with open(script_path, "r") as f:
                        return f.read()
                except IOError:
                    pass
        return None

    def preview_script(
        self, script_content: str, timeout: int = 5
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Execute a status line script with mock data and return the output.

        Args:
            script_content: The bash script to execute
            timeout: Maximum execution time in seconds (default: 5)

        Returns:
            Tuple of (success, output, error_message)
        """
        # Create a temporary script file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write(script_content)
            script_path = f.name

        try:
            # Make script executable
            os.chmod(script_path, stat.S_IRWXU)

            # Prepare mock JSON input
            mock_input = json.dumps(MOCK_PREVIEW_DATA)

            # Execute script with mock data piped to stdin
            result = subprocess.run(
                [script_path],
                input=mock_input,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd="/tmp",  # Safe working directory
            )

            if result.returncode == 0:
                return (True, result.stdout.strip(), None)
            else:
                error_msg = result.stderr.strip() if result.stderr else "Script failed"
                return (False, result.stdout.strip(), error_msg)

        except subprocess.TimeoutExpired:
            return (False, "", f"Script execution timed out after {timeout} seconds")
        except Exception as e:
            return (False, "", str(e))
        finally:
            # Clean up temporary file
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def get_powerline_presets(self) -> List[PowerlinePreset]:
        """
        Get available powerline presets.

        Returns:
            List of PowerlinePreset objects
        """
        return POWERLINE_PRESETS

    def check_nodejs(self) -> Tuple[bool, Optional[str]]:
        """
        Check if Node.js is available on the system.

        Returns:
            Tuple of (available, version_string)
        """
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                return (True, version)
            return (False, None)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return (False, None)

    def apply_powerline_preset(self, preset_id: str) -> StatusLineConfig:
        """
        Apply a powerline preset status line configuration.

        Args:
            preset_id: ID of the powerline preset to apply

        Returns:
            Updated StatusLineConfig

        Raises:
            ValueError: If preset_id is not found
            RuntimeError: If Node.js is not available
        """
        # Find the preset
        preset = None
        for p in POWERLINE_PRESETS:
            if p.id == preset_id:
                preset = p
                break

        if not preset:
            raise ValueError(f"Powerline preset not found: {preset_id}")

        # Update the configuration with the npx command
        return self.update_config(
            StatusLineUpdate(
                type="command",
                command=preset.command,
                enabled=True,
            )
        )
