"""Read bounded Claude Code turn evidence for an explicitly identified process."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat

from app.utils.path_utils import convert_path_to_folder_name

_TAIL_BYTES = 1_048_576
_PROC = Path("/proc")


def _home(pid: int) -> Path:
    process = _PROC / str(pid)
    try:
        env = dict(entry.split(b"=", 1) for entry in
                   (process / "environ").read_bytes().split(b"\0") if b"=" in entry)
        configured = env.get(b"CLAUDE_CONFIG_DIR")
        home = configured or env.get(b"HOME")
        if home:
            value = Path(os.fsdecode(home))
            if not value.is_absolute():
                raise ValueError("Relative native configuration directory")
            return value if configured else value / ".claude"
    except PermissionError:
        pass
    return Path(pwd.getpwuid(process.stat().st_uid).pw_dir) / ".claude"


def _identity(pid: int, session_id: str) -> bool:
    argv = (_PROC / str(pid) / "cmdline").read_bytes().split(b"\0")
    if not argv or Path(os.fsdecode(argv[0])).name != "claude":
        return False
    values = []
    for index, arg in enumerate(argv):
        if arg == b"--":
            break
        if arg in {b"--resume", b"--session-id"}:
            if index + 1 >= len(argv):
                return False
            values.append(os.fsdecode(argv[index + 1]))
        elif arg.startswith((b"--resume=", b"--session-id=")):
            values.append(os.fsdecode(arg.split(b"=", 1)[1]))
    return values == [session_id]


def _state(path: Path, uid: int, session_id: str, cwd: str, now: datetime,
           started_at: datetime, provenance: dict | None) -> tuple[str, str, datetime | None]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid
                or before.st_mode & stat.S_IWOTH):
            raise ValueError("Unsafe native observation file")
        offset = max(0, before.st_size - _TAIL_BYTES)
        stream.seek(offset)
        data = stream.read(_TAIL_BYTES)
        after = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    binding = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if binding(before) != binding(after) or binding(after) != binding(current):
        return "unknown", "binding_changed", None
    if not data.endswith(b"\n"):
        return "unknown", "observation_incomplete", None
    lines = data.splitlines()
    if offset:
        lines = lines[1:]
    state, reason, observed_at = "unknown", "no_native_event", None
    terminal = None
    cursor = None
    for line in lines:
        row = json.loads(line)
        kind = row.get("type")
        if kind not in {"user", "assistant", "system"}:
            continue
        if row.get("isSidechain") is True or row.get("isReplay") is True:
            continue
        timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > now + timedelta(seconds=5):
            return "unknown", "observation_invalid", None
        if timestamp < started_at:
            continue
        if (row.get("sessionId") != session_id or not isinstance(row.get("cwd"), str)
                or not Path(row["cwd"]).is_absolute()
                or not Path(row["cwd"]).resolve().is_relative_to(Path(cwd).resolve())):
            return "unknown", "session_mismatch", None
        if observed_at and timestamp < observed_at:
            return "unknown", "observation_invalid", None
        if kind == "system" and row.get("subtype") != "turn_duration":
            state, reason, terminal = "unknown", "native_event_unsupported", None
            observed_at = timestamp
            cursor = None
            continue
        message = row.get("message")
        if kind == "user":
            if not isinstance(message, dict) or message.get("role") != "user":
                return "unknown", "observation_invalid", None
            content = message.get("content")
            tool_result = (isinstance(content, list) and bool(content)
                           and all(isinstance(part, dict) and part.get("type") == "tool_result"
                                   for part in content))
            if isinstance(content, str) and content in {
                "[Request interrupted by user]", "[Request interrupted by user for tool use]",
            }:
                state, reason = "idle", "native_turn_interrupted"
            elif tool_result:
                if state != "working":
                    state, reason = "unknown", "native_progress_without_start"
            else:
                state, reason = "working", "native_turn_started"
            terminal = None
        elif kind == "assistant":
            if not isinstance(message, dict) or message.get("role") != "assistant":
                return "unknown", "observation_invalid", None
            if state != "working":
                state, reason = "unknown", "native_progress_without_start"
                terminal = None
            elif message.get("stop_reason") == "end_turn":
                if not isinstance(row.get("uuid"), str) or not row["uuid"]:
                    return "unknown", "observation_invalid", None
                state, reason = "idle", "native_turn_completed"
                terminal = row["uuid"]
            elif message.get("stop_reason") in {"max_tokens", "refusal"}:
                state, reason = "idle", "native_turn_interrupted"
                terminal = None
            else:
                reason = "native_progress"
        else:
            # Duration is a second record for the same end_turn, not a new settlement.
            if state != "idle" or terminal is None or row.get("parentUuid") != terminal:
                state, reason, terminal = "unknown", "completion_unconfirmed", None
                observed_at = timestamp
            continue
        observed_at = timestamp
        cursor = hashlib.sha256(f"{session_id}:{row.get('uuid')}:{kind}".encode()).hexdigest()
    if provenance is not None:
        provenance.update(session_id=session_id, event_id=cursor)
        if terminal and state == "idle" and reason == "native_turn_completed":
            provenance.update(event_source="claude_end_turn", event_id=hashlib.sha256(
                f"{session_id}:{terminal}:claude_end_turn".encode()).hexdigest())
    if state == "working" and observed_at and (now - observed_at).total_seconds() > 180:
        return "unknown", "native_event_stale", observed_at
    return state, reason, observed_at


def observe_claude(pid: int, session_id: str, cwd: str, now: datetime,
                   started_at: datetime, *, provenance: dict | None = None):
    if not _identity(pid, session_id):
        return "unknown", "session_mismatch", None
    home = _home(pid)
    path = home / "projects" / convert_path_to_folder_name(str(Path(cwd).resolve())) / (session_id + ".jsonl")
    return _state(path, (_PROC / str(pid)).stat().st_uid, session_id, cwd, now, started_at, provenance)
