"""Codex CLI provider implementation."""
from __future__ import annotations

import os
from pathlib import Path

from app.services.providers.base import (
    AgentProvider,
    SpawnCommandOptions,
    argv0_name,
    has_binary_descendant,
)


def get_codex_home() -> Path:
    """Return CODEX_HOME, defaulting to ~/.codex."""
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


class CodexCliProvider(AgentProvider):
    id = "codex-cli"
    display_name = "Codex"
    binary_name = "codex"
    version_args = ("--version",)

    def get_capabilities(self) -> dict[str, bool]:
        return {
            "sessions": True,
            "spawn": True,
            "resume": True,
            "fork": True,
            "mcp": True,
            "plugins": True,
            "commands": False,
            "agents": False,
            "skills": False,
            "hooks": False,
            "memory": False,
            "usage": False,
            "context": False,
            "doctor": True,
        }

    def get_capability_details(self) -> dict[str, dict[str, str]]:
        details = super().get_capability_details()
        details.update({
            "sessions": {"state": "write_capable", "label": "tmux sessions"},
            "spawn": {"state": "write_capable", "label": "new sessions"},
            "resume": {"state": "write_capable", "label": "resume session"},
            "fork": {"state": "write_capable", "label": "fork session"},
            "mcp": {"state": "write_capable", "label": "MCP servers"},
            "plugins": {"state": "read_only", "label": "plugin inventory"},
            "commands": {"state": "unsupported", "reason": "Codex command files are not modeled yet"},
            "agents": {"state": "unsupported", "reason": "Codex agent files are not modeled yet"},
            "skills": {"state": "unsupported", "reason": "Codex skills are not modeled yet"},
            "hooks": {"state": "unsupported", "reason": "Codex hooks are not modeled yet"},
            "memory": {"state": "unsupported", "reason": "Codex memory is not modeled yet"},
            "usage": {"state": "unsupported", "reason": "Codex usage data is not available yet"},
            "context": {"state": "unsupported", "reason": "Codex context metrics are not available yet"},
            "doctor": {"state": "read_only", "label": "doctor diagnostics"},
        })
        return details

    def get_config_paths(self, project_path: str | None = None) -> dict:
        home = get_codex_home()
        return {
            "root": str(home),
            "user_config": str(home / "config.toml"),
            "auth": str(home / "auth.json"),
            "history": str(home / "history.jsonl"),
            "models_cache": str(home / "models_cache.json"),
            "rules": str(home / "rules"),
        }

    def is_process_match(self, command: str, pid: str) -> bool:
        name = argv0_name(command)
        if name == "codex":
            return True
        if name in {"codex-exec-server", "codex-cli"}:
            return False
        if name == "node":
            return has_binary_descendant(
                pid,
                {"codex"},
                excluded_names={"codex-exec-server"},
            )
        return False

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        if options.mode not in {"plain", "resume", "fork"}:
            raise ValueError(f"Unsupported Codex mode: {options.mode}")

        command = ["codex", "--cd", options.directory]
        if options.model:
            command += ["--model", options.model]
        if options.profile:
            command += ["--profile", options.profile]
        if options.profile_v2:
            command += ["--profile-v2", options.profile_v2]
        if options.sandbox:
            command += ["--sandbox", options.sandbox]
        if options.approval_policy:
            command += ["--ask-for-approval", options.approval_policy]
        if options.search:
            command.append("--search")
        if options.no_alt_screen:
            command.append("--no-alt-screen")
        if options.dangerously_bypass_approvals_and_sandbox:
            command.append("--dangerously-bypass-approvals-and-sandbox")

        if options.mode in {"resume", "fork"}:
            command.append(options.mode)
            if options.use_last:
                command.append("--last")
            elif options.session_id:
                command.append(options.session_id)
            else:
                raise ValueError(f"session_id or use_last is required for Codex {options.mode} mode")

        if options.prompt:
            command.append(options.prompt)
        return command

    def get_allowed_cli_commands(self) -> list[str]:
        return ["doctor", "mcp", "plugin", "features"]
