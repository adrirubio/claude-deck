"""GitHub Copilot CLI provider implementation."""
from __future__ import annotations

import os
from pathlib import Path

from app.services.providers.base import (
    AgentProvider,
    SpawnCommandOptions,
    argv0_name,
    has_binary_descendant,
)


def get_copilot_home() -> Path:
    """Return COPILOT_HOME, defaulting to ~/.copilot."""
    return Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot")).expanduser()


class CopilotCliProvider(AgentProvider):
    id = "copilot-cli"
    display_name = "GitHub Copilot CLI"
    binary_name = "copilot"
    version_args = ("--version",)

    def get_config_paths(self, project_path: str | None = None) -> dict:
        home = get_copilot_home()
        paths = {
            "root": str(home),
            "user_config": str(home / "config.json"),
            "mcp_config": str(home / "mcp-config.json"),
            "hooks": str(home / "hooks"),
            "agents": str(home / "agents"),
            "skills": str(home / "skills"),
            "session_store": str(home / "session-store.db"),
            "logs": str(home / "logs"),
        }
        if project_path:
            project = Path(project_path)
            paths["workspace_mcp"] = str(project / ".mcp.json")
            paths["github_mcp"] = str(project / ".github" / "mcp.json")
        return paths

    def is_process_match(self, command: str, pid: str) -> bool:
        name = argv0_name(command)
        if name == "copilot":
            return True
        if name in {"copilot-language-server"}:
            return False
        if name == "node":
            return has_binary_descendant(
                pid,
                {"copilot"},
                excluded_names={"copilot-language-server"},
            )
        return False

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        if options.mode not in {"plain", "resume"}:
            raise ValueError(f"Unsupported GitHub Copilot CLI mode: {options.mode}")

        command = ["copilot", "-C", options.directory]
        if options.model:
            command += ["--model", options.model]
        if options.agent:
            command += ["--agent", options.agent]
        if options.context_tier:
            command += ["--context", options.context_tier]
        if options.reasoning_effort:
            command += ["--effort", options.reasoning_effort]
        if options.plan:
            command.append("--plan")
        if options.remote is True:
            command.append("--remote")
        elif options.remote is False:
            command.append("--no-remote")
        if options.allow_all or options.skip_permissions or options.dangerously_bypass_approvals_and_sandbox:
            command.append("--allow-all")
        if options.no_ask_user:
            command.append("--no-ask-user")

        if options.mode == "resume":
            if options.use_last:
                command.append("--continue")
            elif options.session_id:
                command.append(f"--resume={options.session_id}")
            else:
                raise ValueError("session_id or use_last is required for GitHub Copilot CLI resume mode")

        if options.prompt:
            command += ["-i", options.prompt]
        return command

    def get_allowed_cli_commands(self) -> list[str]:
        return ["config", "mcp", "plugin"]
