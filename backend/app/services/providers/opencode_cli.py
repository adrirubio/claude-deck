"""OpenCode CLI provider implementation."""
from __future__ import annotations

import os
from pathlib import Path

from app.services import opencode_process_identity
from app.services.providers.base import (
    AgentProvider,
    ProviderLaunchError,
    SpawnCommandOptions,
    argv0_name,
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
            "agent_mail_plugin": str(home / "plugins" / "albiex-synth-city-agent-mail.js"),
            "session_store": str(Path.home() / ".local" / "share" / "opencode" / "opencode.db"),
            "logs": str(Path.home() / ".local" / "share" / "opencode" / "log"),
        }
        if project_path:
            project = Path(project_path)
            paths["project_config"] = str(project / "opencode.json")
            paths["project_config_jsonc"] = str(project / "opencode.jsonc")
        return paths

    def is_process_match(self, command: str, pid: str) -> bool:
        """Positive evidence only: the readable argv of an ``opencode`` process that is
        not a server. OpenCode 2 is a compiled binary, so a node or bun wrapper is
        never a member, and an unreadable or oversized cmdline is no match."""
        if argv0_name(command) != "opencode" or not pid.isdigit():
            return False
        argv = opencode_process_identity.read_argv(int(pid))
        return bool(argv) and not opencode_process_identity.is_server_argv(argv)

    def _validate(self, options: SpawnCommandOptions) -> None:
        if options.mode not in {"plain", "resume"}:
            raise ValueError(f"Unsupported OpenCode CLI mode: {options.mode}")
        if options.reasoning_effort:
            raise ProviderLaunchError(
                "OpenCode TUI launch does not support reasoning_effort",
                "reasoning_effort_unsupported",
            )
        if options.use_last:
            raise ProviderLaunchError(
                "OpenCode members resume only an exact saved session; --continue is not supported",
                "opencode_continue_unsupported",
            )
        if options.dangerously_bypass_approvals_and_sandbox:
            raise ValueError("OpenCode TUI launch does not support permission bypass flags")
        if options.mode == "resume" and not options.session_id:
            raise ValueError("session_id is required for OpenCode CLI resume mode")
        if options.session_id is not None and not opencode_process_identity.is_session_id(options.session_id):
            raise ValueError("OpenCode session_id must start with ses")
        if options.model is not None and not opencode_process_identity.is_model(options.model):
            raise ValueError("OpenCode model must be provider/model, with an optional #variant")
        if options.agent is not None and not opencode_process_identity.is_agent(options.agent):
            raise ValueError("OpenCode agent must be a plain agent name")
        if options.platform == "bedrock" and not (options.model or "").startswith("amazon-bedrock/"):
            raise ValueError("OpenCode on Bedrock needs an amazon-bedrock/ model")

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        """``opencode <dir> --standalone --session <ses_id> [--auto] [--prompt P]`` (#729 spec).

        The v2 TUI has no --model or --agent; they reach the member through
        OPENCODE_CONFIG_CONTENT (see build_spawn_env). Without --standalone the
        shared service would mix up members.
        """
        self._validate(options)
        command = ["opencode", options.directory, "--standalone"]
        if options.session_id:
            command += ["--session", options.session_id]
        if options.skip_permissions:
            command.append("--auto")
        if options.prompt:
            command += ["--prompt", options.prompt]
        return command

    def build_spawn_env(self, options: SpawnCommandOptions) -> dict[str, str]:
        self._validate(options)
        return {
            "OPENCODE_CONFIG_CONTENT": opencode_process_identity.config_content(
                model=options.model, agent=options.agent,
            )
        }

    def get_allowed_cli_commands(self) -> list[str]:
        return ["agent", "mcp", "models", "plugin", "providers", "stats"]
