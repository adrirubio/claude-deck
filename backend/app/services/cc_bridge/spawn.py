"""Spawn and kill Claude Code sessions in tmux."""
import logging
import shlex
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_spawned_sessions: dict[str, dict] = {}


def _resolve_project_directory(project_folder: str) -> str:
    """Resolve a Claude project folder name to the actual project directory.

    Reconstructs the path from the folder name encoding (slashes → dashes).
    This is inherently ambiguous for paths with actual hyphens, but works
    for the common case.
    """
    decoded = "/" + project_folder.lstrip("-").replace("-", "/")
    if Path(decoded).is_dir():
        return decoded

    raise ValueError(
        f"Could not resolve project directory for '{project_folder}'. "
        f"Please provide the directory path explicitly."
    )


def spawn_session(
    directory: str,
    mode: str = "plain",
    worktree_name: str | None = None,
    session_id: str | None = None,
    project_folder: str | None = None,
    skip_permissions: bool = False,
) -> dict:
    """Spawn a new Claude Code session inside a tmux session.

    Args:
        directory: Absolute path to the working directory.
        mode: One of "plain", "worktree", or "resume".
        worktree_name: Name for the worktree (mode="worktree" only).
        session_id: Claude session ID to resume (mode="resume" only).
        project_folder: Claude project folder name (for resume mode directory resolution).
        skip_permissions: Append --dangerously-skip-permissions flag.

    Returns:
        Dict with tmux_target and session_name.

    Raises:
        ValueError: For invalid arguments.
    """
    # For resume mode, derive directory from project_folder if not provided
    if mode == "resume" and (not directory or not directory.strip()) and project_folder:
        directory = _resolve_project_directory(project_folder)

    # Validate directory
    dir_path = Path(directory)
    if not dir_path.is_absolute():
        raise ValueError(f"Directory must be an absolute path: {directory}")
    if not dir_path.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    # Generate tmux session name including project directory basename
    import re
    dir_basename = dir_path.name or "project"
    # Sanitize: tmux disallows dots and colons in session names
    safe_basename = re.sub(r"[^a-zA-Z0-9_-]", "-", dir_basename)[:20]
    name = f"{safe_basename}-{uuid.uuid4().hex[:4]}"

    # Build command
    command = ["claude"]

    if mode == "plain":
        pass
    elif mode == "worktree":
        wt_name = worktree_name or name
        command += ["--worktree", wt_name]
    elif mode == "resume":
        if not session_id:
            raise ValueError("session_id is required for resume mode")
        command += ["--resume", session_id]
    else:
        raise ValueError(f"Unknown mode: {mode}")

    if skip_permissions:
        command.append("--dangerously-skip-permissions")

    # Spawn tmux session — tmux passes shell_command to $SHELL -c, so quote args
    shell_command = " ".join(shlex.quote(part) for part in command)
    try:
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", name, "-c", directory, shell_command],
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

    # Store metadata
    _spawned_sessions[name] = {
        "mode": mode,
        "directory": directory,
        "worktree_name": worktree_name or (name if mode == "worktree" else None),
    }

    logger.info("Spawned session %s in %s (mode=%s)", name, directory, mode)
    return {"tmux_target": f"{name}:0.0", "session_name": name}


def kill_session(session_name: str, cleanup_worktree: bool = False) -> dict:
    """Kill a tmux session and optionally clean up its worktree.

    Args:
        session_name: The tmux session name to kill.
        cleanup_worktree: Remove the git worktree if applicable.

    Returns:
        Dict with killed status and optional error.
    """
    metadata = _spawned_sessions.get(session_name)

    # Kill the tmux session
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

    # Clean up worktree if requested
    if cleanup_worktree and metadata and metadata["mode"] == "worktree":
        wt_name = metadata.get("worktree_name")
        directory = metadata["directory"]
        if wt_name:
            try:
                subprocess.run(
                    ["git", "-C", directory, "worktree", "remove", wt_name, "--force"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                logger.info("Removed worktree %s in %s", wt_name, directory)
            except Exception:
                logger.warning(
                    "Failed to remove worktree %s in %s", wt_name, directory
                )

    # Remove from tracked sessions
    _spawned_sessions.pop(session_name, None)

    logger.info("Killed session %s", session_name)
    return {"killed": True}


def get_spawned_sessions() -> dict[str, dict]:
    """Return all sessions spawned by Deck."""
    return _spawned_sessions
