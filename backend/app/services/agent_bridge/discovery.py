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


def _build_session_info_from_parts(
    *,
    target: str,
    session_name: str,
    window_name: str,
    pane_id: str,
    cwd: str,
    pid: str,
    provider: AgentProvider,
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
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 6)
        if len(parts) != 7:
            continue
        target, session_name, window_name, pane_id, cwd, pid, command = parts
        for provider in providers:
            if provider.is_process_match(command, pid):
                sessions.append(
                    _build_session_info_from_parts(
                        target=target,
                        session_name=session_name,
                        window_name=window_name,
                        pane_id=pane_id,
                        cwd=cwd,
                        pid=pid,
                        provider=provider,
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

