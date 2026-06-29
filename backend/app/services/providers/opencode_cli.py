"""OpenCode CLI provider implementation."""
from __future__ import annotations

import os
from pathlib import Path

from app.services.providers.base import (
    AgentProvider,
    ProviderLaunchError,
    SpawnCommandOptions,
    argv0_name,
    has_binary_descendant,
)


def get_opencode_home() -> Path:
    """Return OPENCODE_CONFIG_DIR, defaulting to ~/.config/opencode."""
    explicit = os.environ.get("OPENCODE_CONFIG_DIR")
    if explicit:
        return Path(explicit).expanduser()
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return (Path(xdg_config_home).expanduser() / "opencode")
    return Path.home() / ".config" / "opencode"


class OpenCodeCliProvider(AgentProvider):
    id = "opencode-cli"
    display_name = "OpenCode CLI"
    binary_name = "opencode"
    version_args = ("--version",)

    def get_config_paths(self, project_path: str | None = None) -> dict:
        home = get_opencode_home()
        paths = {
            "root": str(home),
            "user_config": str(home / "opencode.json"),
            "plugins": str(home / "plugins"),
            "agent_mail_plugin": str(home / "plugins" / "claude-deck-agent-mail.js"),
            "session_store": str(Path.home() / ".local" / "share" / "opencode" / "opencode.db"),
            "logs": str(Path.home() / ".local" / "share" / "opencode" / "log"),
        }
        if project_path:
            project = Path(project_path)
            paths["project_config"] = str(project / "opencode.json")
            paths["project_config_jsonc"] = str(project / "opencode.jsonc")
        return paths

    def is_process_match(self, command: str, pid: str) -> bool:
        name = argv0_name(command)
        if name == "opencode":
            return True
        if name in {"opencode-server"}:
            return False
        if name in {"node", "bun"}:
            return has_binary_descendant(
                pid,
                {"opencode"},
                excluded_names={"opencode-server"},
            )
        return False

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        if options.mode not in {"plain", "resume"}:
            raise ValueError(f"Unsupported OpenCode CLI mode: {options.mode}")

        if options.reasoning_effort:
            raise ProviderLaunchError(
                "OpenCode TUI launch does not support reasoning_effort",
                "reasoning_effort_unsupported",
            )
        if options.dangerously_bypass_approvals_and_sandbox or options.skip_permissions:
            raise ValueError("OpenCode TUI launch does not support permission bypass flags")

        command = ["opencode", options.directory]
        if options.model:
            command += ["--model", options.model]
        if options.agent:
            command += ["--agent", options.agent]
        if options.dangerously_bypass_approvals_and_sandbox or options.skip_permissions:
            command.append("--dangerously-skip-permissions")

        if options.mode == "resume":
            if options.use_last:
                command.append("--continue")
            elif options.session_id:
                command += ["--session", options.session_id]
            else:
                raise ValueError("session_id or use_last is required for OpenCode CLI resume mode")

        if options.prompt:
            command += ["--prompt", options.prompt]
        return command

    def get_allowed_cli_commands(self) -> list[str]:
        return ["agent", "mcp", "models", "plugin", "providers", "stats"]
