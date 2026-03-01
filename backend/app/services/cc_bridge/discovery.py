"""Discover Claude Code sessions running in tmux."""
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _is_claude_code(command: str) -> bool:
    """Check if a tmux pane command looks like Claude Code."""
    return command.strip().lower() == "claude"


def _build_session_info(pane: Any, window: Any, session: Any) -> dict:
    """Build a session info dict from libtmux objects."""
    return {
        "tmux_target": f"{session.session_name}:{window.window_index}.{pane.pane_index}",
        "session_name": session.session_name,
        "window_name": window.window_name,
        "pane_id": pane.pane_id,
        "cwd": pane.pane_current_path,
        "pid": pane.pane_pid,
        "status": "active",
    }


def discover_cc_sessions() -> list[dict]:
    """Find all tmux panes running Claude Code."""
    try:
        import libtmux
        server = libtmux.Server()
    except Exception:
        logger.debug("Could not connect to tmux server")
        return []

    results = []
    try:
        for session in server.sessions:
            for window in session.windows:
                for pane in window.panes:
                    cmd = pane.pane_current_command or ""
                    if _is_claude_code(cmd):
                        results.append(_build_session_info(pane, window, session))
    except Exception as e:
        logger.warning(f"Error discovering tmux sessions: {e}")

    return results


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
