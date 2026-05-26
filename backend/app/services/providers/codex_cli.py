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
            "backup": True,
            "restore": False,
        }

    def get_backup_policy(self) -> dict:
        return {
            "provider": self.id,
            "export_supported": True,
            "automatic_restore_supported": False,
            "restore_mode": "manual_review",
            "included": [
                "config.toml with secret-like assignments redacted",
                "*.config.toml profile files with secret-like assignments redacted",
                "rules/*.rules files with secret-like assignments redacted",
                "redacted provider inventory metadata",
            ],
            "excluded": [
                "auth.json",
                "history.jsonl",
                "models_cache.json",
                "*.sqlite and related SQLite sidecar files",
                "raw cache payloads and prompt text",
            ],
            "restore_refusal_reasons": [
                "Codex auth, history, cache, and local state are intentionally excluded from exports.",
                "Automatic restore could overwrite active Codex state without a stable provider-owned restore API.",
            ],
        }

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
