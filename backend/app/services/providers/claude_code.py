"""Claude Code provider implementation."""
from __future__ import annotations

from pathlib import Path

from app.services.cc_bridge.spawn import _resolve_project_directory
from app.services.providers.base import (
    AgentProvider,
    SpawnCommandOptions,
    argv0_name,
    has_binary_descendant,
)
from app.utils.path_utils import ClaudePathUtils


class ClaudeCodeProvider(AgentProvider):
    id = "claude-code"
    display_name = "Claude Code"
    binary_name = "claude"

    def get_capabilities(self) -> dict[str, bool]:
        return {
            "sessions": True,
            "spawn": True,
            "resume": True,
            "fork": False,
            "mcp": True,
            "plugins": True,
            "commands": True,
            "agents": True,
            "skills": True,
            "hooks": True,
            "memory": True,
            "usage": True,
            "context": True,
            "doctor": False,
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
            worktree_name = options.worktree_name or Path(options.directory).name
            command += ["--worktree", worktree_name]
        elif options.mode == "resume":
            if not options.session_id:
                raise ValueError("session_id is required for Claude Code resume mode")
            command += ["--resume", options.session_id]
        else:
            raise ValueError(f"Unsupported Claude Code mode: {options.mode}")

        if options.skip_permissions:
            command.append("--dangerously-skip-permissions")
        if options.prompt:
            command.append(options.prompt)
        return command

    def resolve_directory(self, options: SpawnCommandOptions) -> str:
        if options.mode == "resume" and not options.directory.strip() and options.project_folder:
            return _resolve_project_directory(options.project_folder)
        return options.directory

    def get_allowed_cli_commands(self) -> list[str]:
        return ["mcp", "config", "plugin"]
