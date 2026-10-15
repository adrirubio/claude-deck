"""Muse Code CLI provider (Meta)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.services.providers.base import AgentProvider, ProviderLaunchError, SpawnCommandOptions, argv0_name
from app.services.providers.launch_contract import MUSE_REASONING_EFFORTS

_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_BINARY = re.compile(r"muse-bin-[0-9][0-9A-Za-z.\-]*")


def muse_data_dir() -> Path:
    return Path(os.environ.get("MUSE_DATA_DIR", "~/.local/share/muse")).expanduser()


def muse_config_dir() -> Path:
    return Path(os.environ.get("MUSE_CONFIG_DIR", "~/.config/muse")).expanduser()


def is_muse_command(command: str) -> bool:
    name = argv0_name(command)
    return name == "muse" or bool(_BINARY.fullmatch(name))


class MuseCliProvider(AgentProvider):
    id = "muse-cli"
    display_name = "Muse Code"
    binary_name = "muse"

    def get_config_paths(self, project_path: str | None = None) -> dict:
        return {"root": str(muse_config_dir()), "user_config": str(muse_config_dir() / "settings.json"),
                "sessions": str(muse_data_dir() / "sessions")}

    def is_process_match(self, command: str, pid: str) -> bool:
        return is_muse_command(command)

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        if options.mode not in {"plain", "resume"}:
            raise ProviderLaunchError("Muse Code supports plain and resume only", "unsupported_launch_mode")
        if options.platform.strip() not in {"", "anthropic", "meta"}:
            raise ProviderLaunchError("Muse Code runs only on Meta", "muse_platform_unsupported")
        unsupported = (
            "worktree_name", "project_folder", "profile", "profile_v2", "sandbox", "approval_policy",
            "search", "no_alt_screen", "dangerously_bypass_approvals_and_sandbox", "aws_region",
            "aws_profile", "bedrock_model", "agent", "context_tier", "plan", "remote", "allow_all",
            "no_ask_user", "use_last",
        )
        if any(getattr(options, field) not in (None, False, "") for field in unsupported):
            raise ProviderLaunchError("Unsupported Muse Code launch option", "muse_option_unsupported")
        command = ["muse", "--trust-workspace"]
        if options.model is not None:
            model = options.model.strip()
            if not model or any(character in model for character in "\n\r\x00 "):
                raise ProviderLaunchError("Invalid Muse model", "invalid_model")
            command += ["--model", model]
        if options.reasoning_effort:
            if options.reasoning_effort not in MUSE_REASONING_EFFORTS:
                raise ProviderLaunchError("Invalid Muse reasoning effort", "invalid_reasoning_effort")
            command += ["--reasoning-effort", options.reasoning_effort]
        if options.skip_permissions:
            command.append("--yolo")
        if options.mode == "resume":
            if not options.session_id or not _UUID.fullmatch(options.session_id):
                raise ProviderLaunchError("Muse resume requires an exact session UUID", "muse_session_invalid")
            if options.prompt:
                raise ProviderLaunchError("Muse resume does not take a prompt", "muse_option_unsupported")
            return command + ["resume", options.session_id]
        if options.session_id:
            raise ProviderLaunchError("A session id requires resume mode", "muse_session_invalid")
        if options.prompt:
            if options.prompt.startswith("-"):
                raise ProviderLaunchError("A Muse prompt cannot start with -", "muse_literal_prompt_required")
            command.append(options.prompt)
        return command

    def get_allowed_cli_commands(self) -> list[str]:
        return []
