"""Discover Claude Code sessions running in tmux."""
import logging
import subprocess
from pathlib import Path

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


_MAX_TREE_DEPTH = 4


def _has_claude_descendant(pid: str, *, _depth: int = 0, _visited: set | None = None) -> bool:
    """Check if any descendant process of `pid` is the Claude Code binary.

    This handles wrappers (e.g. node-based launchers) that spawn `claude`
    as a child process. Uses pgrep to walk the descendant tree with depth
    and cycle guards to prevent unbounded recursion.
    """
    if _depth > _MAX_TREE_DEPTH:
        return False
    if _visited is None:
        _visited = set()
    if pid in _visited:
        return False
    _visited.add(pid)

    try:
        result = subprocess.run(
            ["pgrep", "-a", "-P", pid],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            # pgrep -a output: "<pid> <cmdline>"
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            child_pid, cmdline = parts
            # Check if this process IS claude
            argv0 = cmdline.split()[0] if cmdline else ""
            if Path(argv0).name == "claude":
                return True
            # Recurse into this child's descendants
            if _has_claude_descendant(child_pid, _depth=_depth + 1, _visited=_visited):
                return True
    except (subprocess.SubprocessError, OSError):
        pass
    return False


def _is_claude_code(command: str, pid: str) -> bool:
    """Check if a tmux pane is running Claude Code.

    Matches when the pane command is 'claude' directly, or when
    a node-based wrapper has spawned `claude` as a descendant process.
    """
    if command.strip().lower() == "claude":
        return True

    # When launched via a node wrapper (shebang), pane_current_command
    # is 'node'. Walk the descendant tree for the real claude binary.
    if command.strip().lower() == "node":
        if not pid.isdigit():
            return False
        return _has_claude_descendant(pid)

    return False


def discover_cc_sessions() -> list[dict]:
    """Find all tmux panes running Claude Code."""
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

    results = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 6)
        if len(parts) != 7:
            continue
        target, session_name, window_name, pane_id, cwd, pid, command = parts
        if _is_claude_code(command, pid):
            results.append({
                "tmux_target": target,
                "session_name": session_name,
                "window_name": window_name,
                "pane_id": pane_id,
                "cwd": cwd,
                "pid": pid,
                "status": "active",
            })
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
