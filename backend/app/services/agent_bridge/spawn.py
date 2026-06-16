"""Spawn and kill agent provider sessions in tmux."""
from __future__ import annotations

import logging
import re
import shlex
import subprocess
import uuid
from pathlib import Path

from app.services.providers import get_provider
from app.services.providers.base import SpawnCommandOptions
from app.services.providers.claude_code import ClaudeCodeProvider
from app.services.providers.platform_env import build_platform_env

logger = logging.getLogger(__name__)

_spawned_sessions: dict[str, dict] = {}


def _validate_directory(directory: str) -> str:
    dir_path = Path(directory).resolve()
    if not dir_path.is_absolute():
        raise ValueError(f"Directory must be an absolute path: {directory}")
    if ".." in Path(directory).parts:
        raise ValueError(f"Directory must not contain path traversal: {directory}")
    if not dir_path.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")
    return str(dir_path)


def _session_name_for(directory: str) -> str:
    basename = Path(directory).name or "project"
    safe_basename = re.sub(r"[^a-zA-Z0-9_-]", "-", basename)[:20]
    return f"{safe_basename}-{uuid.uuid4().hex[:4]}"


def _env_flags(env: dict[str, str]) -> list[str]:
    flags: list[str] = []
    for key, value in env.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            raise ValueError(f"Invalid environment variable name: {key}")
        flags += ["-e", f"{key}={value}"]
    return flags


def spawn_session(
    provider_id: str,
    options: SpawnCommandOptions,
    *,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """Spawn a new provider CLI session inside tmux."""
    provider = get_provider(provider_id)
    if isinstance(provider, ClaudeCodeProvider):
        directory = provider.resolve_directory(options)
        options = SpawnCommandOptions(**{**options.__dict__, "directory": directory})

    directory = _validate_directory(options.directory)
    options = SpawnCommandOptions(**{**options.__dict__, "directory": directory})
    name = _session_name_for(directory)
    if provider.id == "claude-code" and options.mode == "worktree" and not options.worktree_name:
        options = SpawnCommandOptions(**{**options.__dict__, "worktree_name": name})
    command = provider.build_spawn_command(options)
    shell_command = " ".join(shlex.quote(part) for part in command)

    platform_env = build_platform_env(
        options.platform,
        region=options.aws_region,
        aws_profile=options.aws_profile,
        model=options.bedrock_model,
    )
    env_flags = _env_flags(platform_env)
    if extra_env:
        env_flags += _env_flags(extra_env)

    try:
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", name, "-c", directory, *env_flags, shell_command],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise ValueError(f"tmux new-session failed: {result.stderr.strip()}")
    except FileNotFoundError:
        raise ValueError("tmux is not installed or not in PATH")
    except subprocess.TimeoutExpired:
        raise ValueError("tmux new-session timed out")

    _spawned_sessions[name] = {
        "provider": provider.id,
        "mode": options.mode,
        "directory": directory,
        "worktree_name": options.worktree_name or (name if options.mode == "worktree" else None),
        "platform": options.platform,
    }

    logger.info("Spawned %s session %s in %s (mode=%s)", provider.id, name, directory, options.mode)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "tmux_target": f"{name}:0.0",
        "session_name": name,
    }


def kill_session(session_name: str, cleanup_worktree: bool = False) -> dict:
    """Kill a tmux session and optionally clean up a Claude Code worktree."""
    metadata = _spawned_sessions.get(session_name)
    try:
        result = subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"killed": False, "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"killed": False, "error": "tmux is not installed or not in PATH"}
    except subprocess.TimeoutExpired:
        return {"killed": False, "error": "tmux kill-session timed out"}

    if cleanup_worktree and metadata and metadata.get("provider") == "claude-code" and metadata["mode"] == "worktree":
        worktree_name = metadata.get("worktree_name")
        directory = metadata["directory"]
        if worktree_name:
            try:
                subprocess.run(
                    ["git", "-C", directory, "worktree", "remove", worktree_name, "--force"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:
                logger.warning("Failed to remove worktree %s in %s", worktree_name, directory)

    _spawned_sessions.pop(session_name, None)
    logger.info("Killed session %s", session_name)
    return {"killed": True}


def get_spawned_sessions() -> dict[str, dict]:
    return _spawned_sessions
