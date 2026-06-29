"""Discover agent provider sessions running in tmux."""
from __future__ import annotations

import logging
import subprocess
from typing import Any

from app.models.constants import SessionStatus
from app.services.providers import get_provider, get_providers
from app.services.providers.base import AgentProvider

logger = logging.getLogger(__name__)

_PANE_FORMAT = (
    "#{session_name}:#{window_index}.#{pane_index}"
    "|#{session_name}"
    "|#{window_name}"
    "|#{pane_id}"
    "|#{pane_current_path}"
    "|#{pane_pid}"
    "|#{pane_current_command}"
)

_TEAM_ENV_KEYS = {
    "CLAUDE_DECK_TEAM_PRESET_ID": "team_preset_id",
    "CLAUDE_DECK_TEAM_PRESET_NAME": "team_preset_name",
    "CLAUDE_DECK_TEAM_SLOT_ID": "team_slot_id",
    "CLAUDE_DECK_TEAM_SLOT_NAME": "team_slot_name",
    "CLAUDE_DECK_TEAM_SLOT_ROLE": "team_slot_role",
}


def _clean_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_tmux_environment(stdout: str) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for line in stdout.splitlines():
        if not line or line.startswith("-") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        target = _TEAM_ENV_KEYS.get(key)
        if target is None:
            continue
        context[target] = _clean_int(value) if target.endswith("_id") else value
    return context


def _team_context_for_session(session_name: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if session_name in cache:
        return cache[session_name]
    try:
        result = subprocess.run(
            ["tmux", "show-environment", "-t", session_name],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        cache[session_name] = {}
        return cache[session_name]
    cache[session_name] = _parse_tmux_environment(result.stdout) if result.returncode == 0 else {}
    return cache[session_name]


def _build_session_info_from_parts(
    *,
    target: str,
    session_name: str,
    window_name: str,
    pane_id: str,
    cwd: str,
    pid: str,
    provider: AgentProvider,
    team_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "tmux_target": target,
        "session_name": session_name,
        "window_name": window_name,
        "pane_id": pane_id,
        "cwd": cwd,
        "pid": pid,
        "status": SessionStatus.ACTIVE,
        **(team_context or {}),
    }


def discover_agent_sessions(provider_id: str | None = None) -> list[dict[str, Any]]:
    """Find all tmux panes running supported agent providers."""
    providers = [get_provider(provider_id)] if provider_id else get_providers()
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", _PANE_FORMAT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.debug("tmux list-panes failed: %s", result.stderr.strip())
            return []
    except FileNotFoundError:
        logger.debug("tmux not found")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("tmux list-panes timed out")
        return []

    sessions: list[dict[str, Any]] = []
    team_context_cache: dict[str, dict[str, Any]] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 6)
        if len(parts) != 7:
            continue
        target, session_name, window_name, pane_id, cwd, pid, command = parts
        for provider in providers:
            if provider.is_process_match(command, pid):
                team_context = _team_context_for_session(session_name, team_context_cache)
                sessions.append(
                    _build_session_info_from_parts(
                        target=target,
                        session_name=session_name,
                        window_name=window_name,
                        pane_id=pane_id,
                        cwd=cwd,
                        pid=pid,
                        provider=provider,
                        team_context=team_context,
                    )
                )
                break
    return sessions


def capture_pane_preview(target: str) -> str:
    """Capture the current visible content of a tmux pane."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-e"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""
