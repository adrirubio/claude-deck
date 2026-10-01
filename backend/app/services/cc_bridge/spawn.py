"""Spawn and kill Claude Code sessions in tmux."""
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

def _resolve_project_directory(project_folder: str, session_id: str | None = None) -> str:
    """Resolve a Claude project folder name to the actual project directory.

    Use the selected transcript's recorded cwd. Claude's folder name cannot
    reconstruct the directory reliably because slashes and hyphens collide.
    """
    folder_path = Path(project_folder)
    if not project_folder or folder_path.name != project_folder or ".." in folder_path.parts:
        raise ValueError(f"Invalid project folder: '{project_folder}'")
    projects_root = (Path.home() / ".claude" / "projects").resolve()
    try:
        project_dir = (projects_root / project_folder).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Invalid project folder: '{project_folder}'") from exc
    if project_dir.parent != projects_root:
        raise ValueError(f"Invalid project folder: '{project_folder}'")

    if session_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
            raise ValueError("Invalid Claude session ID")
        try:
            transcript = (project_dir / f"{session_id}.jsonl").resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError("Invalid Claude transcript path") from exc
        if transcript.parent != project_dir:
            raise ValueError("Invalid Claude transcript path")
        if transcript.is_file():
            try:
                with transcript.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            cwd = json.loads(line).get("cwd")
                        except json.JSONDecodeError:
                            continue
                        if not cwd:
                            continue
                        resolved = Path(cwd).resolve()
                        if resolved.is_absolute() and ".." not in Path(cwd).parts and resolved.is_dir():
                            return str(resolved)
            except OSError:
                logger.warning("Could not read Claude transcript for directory resolution: %s", transcript)

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
    """Spawn Claude Code through the provider-aware bridge."""
    from app.services.agent_bridge.spawn import spawn_session as spawn_provider_session
    from app.services.providers.base import SpawnCommandOptions

    result = spawn_provider_session(
        "claude-code",
        SpawnCommandOptions(
            directory=directory,
            mode=mode,
            worktree_name=worktree_name,
            session_id=session_id,
            project_folder=project_folder,
            skip_permissions=skip_permissions,
        ),
    )
    return {"tmux_target": result["tmux_target"], "session_name": result["session_name"]}


def kill_session(session_name: str, cleanup_worktree: bool = False) -> dict:
    """Kill a Claude Code session through the provider-aware bridge."""
    from app.services.agent_bridge.spawn import kill_session as kill_provider_session

    return kill_provider_session(session_name, cleanup_worktree=cleanup_worktree)


def get_spawned_sessions() -> dict[str, dict]:
    """Return all sessions spawned by Deck."""
    from app.services.agent_bridge.spawn import get_spawned_sessions as get_provider_sessions

    return get_provider_sessions()
