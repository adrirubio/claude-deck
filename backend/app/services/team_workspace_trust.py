"""Prepare trust for the selected team workspace before native launch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass

import tomlkit

_PROC = Path("/proc")
_CONFIG_KEYS = ("HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME")
_WRITE_LOCK = threading.Lock()
_ERROR = "Workspace trust could not be prepared. Check native configuration access."


@dataclass(frozen=True)
class NativeUser:
    home: Path
    uid: int
    environment: dict[str, str]


def native_user() -> NativeUser:
    """Read the owner and selected environment of the target tmux server."""
    result = subprocess.run(["tmux", "display-message", "-p", "#{pid}"],
                            capture_output=True, text=True, timeout=3)
    if result.returncode:
        # No server means new-session will start one as this process's user.
        if not any(reason in result.stderr.lower() for reason in (
                "no server running", "no such file or directory", "error connecting")):
            raise ValueError(_ERROR)
        environment = {key: os.environ[key] for key in _CONFIG_KEYS if key in os.environ}
        home = Path(environment.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)
        if not home.is_absolute():
            raise ValueError(_ERROR)
        return NativeUser(home, os.getuid(), environment)
    pid = int(result.stdout.strip())
    uid = (_PROC / str(pid)).stat().st_uid
    environment = {}
    for key in _CONFIG_KEYS:
        value = subprocess.run(["tmux", "show-environment", "-g", key],
                               capture_output=True, text=True, timeout=3)
        if value.returncode:
            if "unknown variable" in value.stderr.lower():
                continue
            raise ValueError(_ERROR)
        for line in value.stdout.splitlines():
            if line.startswith(key + "="):
                environment[key] = line[len(key) + 1:]
    home = Path(environment.get("HOME") or pwd.getpwuid(uid).pw_dir)
    if not home.is_absolute() or (_PROC / str(pid)).stat().st_uid != uid:
        raise ValueError(_ERROR)
    return NativeUser(home, uid, environment)


def _primary_checkout(directory: Path) -> Path:
    result = subprocess.run(["git", "-C", str(directory), "worktree", "list", "--porcelain", "-z"],
                            capture_output=True, text=True, timeout=3)
    if result.returncode:
        # Plain directories are valid team workspaces. Git errors are not.
        if "not a git repository" in result.stderr.lower():
            return directory
        raise ValueError(_ERROR)
    records = result.stdout.split("\0\0")
    if not records or "bare" in records[0].split("\0"):
        raise ValueError(_ERROR)
    primary = next((line.removeprefix("worktree ") for line in records[0].split("\0")
                    if line.startswith("worktree ")), None)
    if primary is None:
        raise ValueError(_ERROR)
    path = Path(primary)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(_ERROR)
    return path.resolve()


def _snapshot(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(_ERROR)
    return info.st_ino, info.st_mtime_ns, info.st_size, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)


def _atomic_write(path: Path, text: str, uid: int, before) -> None:
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.stat().st_uid != uid:
            os.chown(directory, uid, -1)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".deck-trust-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            mode = before[5] if before else 0o600
            owner, group = (before[3], before[4]) if before else (uid, -1)
            if owner != os.getuid() or (group != -1 and group != os.getgid()):
                os.fchown(stream.fileno(), owner, group)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        if _snapshot(path) != before:
            raise ValueError(_ERROR)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_workspace_trust(provider: str, directory: str) -> bool:
    """Return whether trust changed. Never expose native configuration values."""
    if provider not in {"claude-code", "codex-cli"}:
        return False
    try:
        user = native_user()
        workspace = Path(directory).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError(_ERROR)
        if provider == "claude-code":
            workspace = _primary_checkout(workspace)
            configured = user.environment.get("CLAUDE_CONFIG_DIR")
            path = Path(configured) / ".claude.json" if configured else user.home / ".claude.json"
        else:
            configured = user.environment.get("CODEX_HOME")
            path = (Path(configured) if configured else user.home / ".codex") / "config.toml"
        if not path.is_absolute():
            raise ValueError(_ERROR)
        with _WRITE_LOCK:
            before = _snapshot(path)
            if before and before[3] != user.uid:
                raise ValueError(_ERROR)
            content = path.read_text(encoding="utf-8") if before else ""
            if provider == "claude-code":
                document = json.loads(content) if before else {}
                if not isinstance(document, dict):
                    raise ValueError(_ERROR)
                projects = document.setdefault("projects", {})
                if not isinstance(projects, dict):
                    raise ValueError(_ERROR)
                project = projects.setdefault(str(workspace), {})
                if not isinstance(project, dict):
                    raise ValueError(_ERROR)
                if project.get("hasTrustDialogAccepted") is True:
                    return False
                project["hasTrustDialogAccepted"] = True
                updated = json.dumps(document, indent=2) + "\n"
            else:
                document = tomlkit.parse(content)
                projects = document.setdefault("projects", tomlkit.table())
                if not isinstance(projects, dict):
                    raise ValueError(_ERROR)
                project = projects.setdefault(str(workspace), tomlkit.table())
                if not isinstance(project, dict):
                    raise ValueError(_ERROR)
                if project.get("trust_level") == "trusted":
                    return False
                project["trust_level"] = "trusted"
                updated = tomlkit.dumps(document)
            _atomic_write(path, updated, user.uid, before)
            return True
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        raise ValueError(_ERROR) from None
