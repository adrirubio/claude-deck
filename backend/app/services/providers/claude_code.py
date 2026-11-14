"""Claude Code provider implementation."""
from __future__ import annotations

import re
from pathlib import Path

from app.services.cc_bridge.spawn import _resolve_project_directory
from app.services.providers.base import (
    AgentProvider,
    ProviderLaunchError,
    SpawnCommandOptions,
    argv0_name,
    has_binary_descendant,
)
from app.services.providers.launch_contract import CLAUDE_REASONING_EFFORTS
from app.services.providers.platform_env import PLATFORM_BEDROCK
from app.utils.path_utils import ClaudePathUtils

# A concrete model id, as the team service validates it. A leading dash would be read as a flag.
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_CONCRETE_MODEL_MARKERS = (".", "/", ":")


class ClaudeCodeProvider(AgentProvider):
    id = "claude-code"
    display_name = "Claude Code"
    binary_name = "claude"

    def get_backup_policy(self) -> dict:
        return {
            "provider": self.id,
            "export_supported": True,
            "automatic_restore_supported": True,
            "restore_mode": "automatic",
        }

    def get_config_paths(self, project_path: str | None = None) -> dict:
        paths = ClaudePathUtils()
        result = {
            "root": str(Path.home() / ".claude"),
            "user_settings": str(paths.get_user_settings_json()),
            "user_settings_local": str(paths.get_user_settings_local_json()),
            "user_claude": str(paths.get_user_claude_json()),
        }
        if project_path:
            project = Path(project_path)
            result.update({
                "project_settings": str(project / ".claude" / "settings.json"),
                "project_settings_local": str(project / ".claude" / "settings.local.json"),
                "project_mcp": str(project / ".mcp.json"),
                "project_memory": str(project / "CLAUDE.md"),
            })
        return result

    def is_process_match(self, command: str, pid: str) -> bool:
        name = argv0_name(command)
        if name == "claude":
            return True
        if name == "node":
            return has_binary_descendant(pid, {"claude"})
        return False

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        command = ["claude"]

        if options.mode == "plain":
            pass
        elif options.mode == "worktree":
            if not options.worktree_name:
                raise ValueError("worktree_name is required for Claude Code worktree mode")
            command += ["--worktree", options.worktree_name]
        elif options.mode == "resume":
            if not options.session_id:
                raise ValueError("session_id is required for Claude Code resume mode")
            command += ["--resume", options.session_id]
        else:
            raise ValueError(f"Unsupported Claude Code mode: {options.mode}")

        if options.mode != "resume" and options.session_id:
            command += ["--session-id", options.session_id]

        if options.platform == PLATFORM_BEDROCK and options.model and options.bedrock_model:
            raise ProviderLaunchError(
                "Set either model or bedrock_model on a Bedrock Claude Code member, not both",
                "bedrock_model_conflict",
            )
        if options.model is not None:
            model = options.model.strip()
            if (
                not _MODEL_ID_PATTERN.fullmatch(model)
                or not (any(char.isdigit() for char in model) or any(marker in model for marker in _CONCRETE_MODEL_MARKERS))
            ):
                raise ProviderLaunchError("Claude Code model must be a concrete model ID", "invalid_model")
            command += ["--model", model]
        if options.reasoning_effort:
            if options.reasoning_effort not in CLAUDE_REASONING_EFFORTS:
                raise ProviderLaunchError(
                    f"Unsupported Claude Code reasoning_effort: {options.reasoning_effort}. "
                    f"Expected one of: {', '.join(CLAUDE_REASONING_EFFORTS)}",
                    "invalid_reasoning_effort",
                )
            command += ["--effort", options.reasoning_effort]

        if options.skip_permissions:
            command.append("--dangerously-skip-permissions")
        if options.prompt:
            command.append(options.prompt)
        return command

    def resolve_directory(self, options: SpawnCommandOptions) -> str:
        if options.mode == "resume" and not options.directory.strip() and options.project_folder:
            return _resolve_project_directory(options.project_folder, options.session_id)
        return options.directory

    def get_allowed_cli_commands(self) -> list[str]:
        return ["mcp", "config", "plugin"]
