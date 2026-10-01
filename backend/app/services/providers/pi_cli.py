from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from app.services.providers.base import AgentProvider, ProviderLaunchError, SpawnCommandOptions

PI_THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


def pi_home() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")).expanduser()


def pi_session_directory(directory: str) -> Path:
    resolved = str(Path(directory).expanduser().resolve())
    configured = os.environ.get("PI_CODING_AGENT_SESSION_DIR")
    if not configured:
        settings = {}
        for location in (pi_home() / "settings.json", Path(resolved) / ".pi/settings.json"):
            try:
                with location.open() as stream:
                    data = stream.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise ValueError("settings too large")
                values = json.loads(data)
                if not isinstance(values, dict):
                    raise ValueError("settings must be an object")
                settings.update(values)
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                raise ProviderLaunchError("Pi session settings cannot be resolved", "pi_session_settings_invalid") from None
        configured = settings.get("sessionDir")
    if configured:
        if not isinstance(configured, str):
            raise ProviderLaunchError("Invalid Pi session directory", "pi_session_settings_invalid")
        selected = Path(configured).expanduser()
        return (selected if selected.is_absolute() else Path(resolved) / selected).resolve()
    encoded = "--" + re.sub(r"[/\\:]", "-", resolved.lstrip("/\\")) + "--"
    return pi_home() / "sessions" / encoded


def resolve_pi_session(directory: str, selector: str) -> str:
    session_dir = pi_session_directory(directory).resolve()
    by_id = bool(re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", selector))
    if by_id:
        matches = list(session_dir.glob(f"*_{selector}.jsonl"))
        if len(matches) != 1:
            raise ProviderLaunchError("Exact project-local Pi session not found", "pi_session_invalid")
        selected = matches[0].resolve()
    else:
        selected = Path(selector).expanduser()
        if not selected.is_absolute():
            raise ProviderLaunchError("Pi resume requires an exact session path or full ID", "pi_session_invalid")
        selected = selected.resolve()
    if selected.parent != session_dir or selected.suffix != ".jsonl" or not selected.is_file():
        raise ProviderLaunchError("Pi session must belong to this project", "pi_session_invalid")
    try:
        with selected.open() as stream:
            header_line = stream.readline(16385)
        if len(header_line) > 16384:
            raise ValueError("header too large")
        header = json.loads(header_line)
        if (
            not isinstance(header, dict) or header.get("type") != "session"
            or not isinstance(header.get("cwd"), str)
            or Path(header["cwd"]).expanduser().resolve() != Path(directory).expanduser().resolve()
            or (by_id and header.get("id") != selector)
        ):
            raise ValueError("foreign session")
    except (OSError, ValueError):
        raise ProviderLaunchError("Pi session header does not match this project and selector", "pi_session_invalid") from None
    return str(selected)


def _pi_command(command: str) -> bool:
    parts = command.split()
    if not parts:
        return False
    name = Path(parts[0]).name
    if name == "pi":
        return True
    return name == "node" and len(parts) > 1 and bool(
        re.search(r"/@earendil-works/pi-coding-agent/dist/bundle/cli\.js$", parts[1])
    )


def _pi_descendant(pid: str, depth: int = 0, visited: set[str] | None = None) -> bool:
    if depth > 4 or not pid.isdigit():
        return False
    visited = visited if visited is not None else set()
    if pid in visited:
        return False
    visited.add(pid)
    try:
        result = subprocess.run(["pgrep", "-a", "-P", pid], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    for line in result.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and (_pi_command(parts[1]) or _pi_descendant(parts[0], depth + 1, visited)):
            return True
    return False


class PiCliProvider(AgentProvider):
    id = "pi-cli"
    display_name = "Pi"
    binary_name = "pi"

    def get_config_paths(self, project_path: str | None = None) -> dict:
        return {"root": str(pi_home()), "sessions": str(pi_home() / "sessions")}

    def is_process_match(self, command: str, pid: str) -> bool:
        return _pi_command(command) or _pi_descendant(pid)

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        if options.mode not in {"plain", "resume"}:
            raise ProviderLaunchError("Pi supports plain and resume only", "unsupported_launch_mode")
        if options.platform.strip() != "openrouter":
            raise ProviderLaunchError("Pi requires platform=openrouter", "pi_platform_unsupported")
        unsupported = (
            "worktree_name", "project_folder", "skip_permissions", "profile", "profile_v2", "sandbox",
            "approval_policy", "search", "no_alt_screen", "dangerously_bypass_approvals_and_sandbox",
            "aws_region", "aws_profile", "bedrock_model", "agent", "context_tier", "plan", "remote",
            "allow_all", "no_ask_user",
        )
        if any(getattr(options, field) not in (None, False, "") for field in unsupported):
            raise ProviderLaunchError("Unsupported Pi launch option", "pi_option_unsupported")
        model = (options.model or "moonshotai/kimi-k3").strip().removeprefix("openrouter/")
        if not model or any(character in model for character in "\n\r\x00"):
            raise ProviderLaunchError("Invalid Pi model", "invalid_model")
        command = ["pi", "--provider", "openrouter", "--model", model]
        if options.reasoning_effort:
            if options.reasoning_effort not in PI_THINKING_LEVELS:
                raise ProviderLaunchError("Invalid Pi thinking level", "invalid_reasoning_effort")
            command += ["--thinking", options.reasoning_effort]
        if options.mode == "resume":
            if bool(options.session_id) == options.use_last:
                raise ProviderLaunchError("Select exactly one Pi resume source", "pi_session_invalid")
            command += ["--continue"] if options.use_last else [
                "--session", resolve_pi_session(options.directory, options.session_id or "")
            ]
        elif options.session_id or options.use_last:
            raise ProviderLaunchError("Resume options require resume mode", "pi_session_invalid")
        if options.prompt:
            if options.prompt.startswith("@"):
                raise ProviderLaunchError("Pi prompts beginning with @ are not literal text", "pi_literal_prompt_required")
            command += ["--", options.prompt]
        command[5:5] = ["--session-dir", str(pi_session_directory(options.directory).resolve())]
        return command

    def get_allowed_cli_commands(self) -> list[str]:
        return []
