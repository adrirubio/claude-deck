"""Bounded, read-only Pi observations from the opted-in native extension.

Pi replaces its argv with its process title and closes session file descriptors
between writes. The extension therefore records its current session and native
event state next to that session. Never select a file by recency or PID alone.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.services.providers.pi_cli import pi_session_directory

_METADATA_BYTES = 16_384
_PROC = Path("/proc")
_FRESHNESS_SECONDS = 180
_STOPPED_STATES = {"T", "t", "Z", "X", "x"}
_REASONS = {
    "working": {"native_turn_started", "native_progress"},
    "idle": {"native_turn_completed", "native_turn_interrupted", "native_input_requested"},
    "unknown": {"no_native_event", "native_session_ended"},
}


def _read(path: Path, uid: int, *, header: bool = False) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != uid
                or metadata.st_mode & stat.S_IWOTH):
            raise ValueError("Unsafe native observation file")
        value = stream.readline(_METADATA_BYTES + 1) if header else stream.read(_METADATA_BYTES + 1)
    if len(value) > _METADATA_BYTES or (header and not value.endswith(b"\n")):
        raise ValueError("Incomplete or excessive native metadata")
    return value


def _process(pid: int) -> tuple[str, int, str]:
    fields = (_PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
    return fields[0], int(fields[1]), fields[19]


def _native_process(pid: int, start: str, pane_pid: int, pane_start: str, cwd: str) -> tuple[str, int]:
    state, parent, current_start = _process(pid)
    if current_start != start:
        raise ValueError("Native process was replaced")
    ancestor = pid
    for _ in range(32):
        if ancestor == pane_pid:
            if _process(ancestor)[2] != pane_start:
                raise ValueError("Pane was replaced")
            break
        if parent <= 0 or parent == ancestor:
            raise ValueError("Native process is outside its pane")
        ancestor = parent
        _, parent, _ = _process(ancestor)
    else:
        raise ValueError("Native ancestry exceeds its bound")
    proc = _PROC / str(pid)
    uid = proc.stat().st_uid
    if state in _STOPPED_STATES:
        return state, uid
    argv = (proc / "cmdline").read_bytes().split(b"\0")
    executable = Path(os.fsdecode(argv[0])).name
    if not (executable == "pi" or (
        executable == "node" and len(argv) > 1 and os.fsdecode(argv[1]).endswith(
            "/@earendil-works/pi-coding-agent/dist/bundle/cli.js"))):
        raise ValueError("Native executable does not match Pi")
    try:
        native_cwd = (proc / "cwd").resolve(strict=True)
    except PermissionError:
        # Cross-user controllers can read stat/cmdline but not this symlink.
        # Authenticated Mail cwd and the exact SDK/file headers still have to
        # match below. Do not change process or profile permissions to read it.
        native_cwd = None
    if native_cwd is not None and native_cwd != Path(cwd).resolve():
        raise ValueError("Native process project does not match")
    return state, uid


def observe_pi(pane_pid: int, pane_start: str, cwd: str, now: datetime, started_at: datetime,
               expected_native_pid: int, expected_native_start: str, *, provenance: dict | None = None,
               ) -> tuple[str, str, datetime | None]:
    directory = pi_session_directory(cwd).resolve()
    marker = directory / f".deck-native-{pane_pid}-{pane_start}.json"
    # The marker is owned by the native process user, which also owns its pane.
    uid = (_PROC / str(pane_pid)).stat().st_uid
    raw = _read(marker, uid)
    value = json.loads(raw)
    if (type(value.get("version")) is not int or value.get("version") != 1
            or value.get("pane") != {"pid": pane_pid, "start": pane_start}
            or not isinstance(value.get("cwd"), str)
            or Path(value["cwd"]).resolve() != Path(cwd).resolve()):
        return "unknown", "session_mismatch", None
    native = value["native"]
    pid, start = native["pid"], native["start"]
    if (type(pid) is not int or pid <= 0 or not isinstance(start, str)
            or not start.isdecimal() or int(start) < int(pane_start)):
        raise ValueError("Invalid native identity")
    if pid != expected_native_pid or start != expected_native_start:
        return "unknown", "native_identity_mismatch", None
    process_state, native_uid = _native_process(pid, start, pane_pid, pane_start, cwd)
    if native_uid != uid:
        raise ValueError("Native process owner differs from its pane")
    if process_state in _STOPPED_STATES:
        return "stopped", "process_stopped", None
    session_id = value["session_id"]
    if not isinstance(session_id, str) or str(UUID(session_id)) != session_id:
        raise ValueError("Invalid native session identity")
    path = Path(value["session_file"])
    if (not path.is_absolute() or path.parent != directory or path.suffix != ".jsonl"
            or path.is_symlink()):
        return "unknown", "session_mismatch", None
    # Pi does not flush a new session until its first assistant reply. The SDK
    # header in the exact native event supplies identity during that first turn.
    header = value["session_header"]
    if (header.get("type") != "session" or header.get("id") != session_id
            or header.get("version") != 3 or not isinstance(header.get("cwd"), str)
            or Path(header["cwd"]).resolve() != Path(cwd).resolve()):
        return "unknown", "session_mismatch", None
    if type(value.get("session_persisted")) is not bool:
        raise ValueError("Invalid native persistence observation")
    try:
        persisted_header = json.loads(_read(path, uid, header=True))
    except FileNotFoundError:
        if value["session_persisted"]:
            raise
    else:
        if any(persisted_header.get(key) != header.get(key) for key in ("type", "version", "id", "cwd")):
            return "unknown", "session_mismatch", None
    state, reason = value["state"], value["reason"]
    if state not in _REASONS or reason not in _REASONS[state]:
        raise ValueError("Invalid native activity")
    observed_at = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
    if observed_at.tzinfo is None or observed_at > now + timedelta(seconds=5):
        return "unknown", "observation_invalid", None
    native_started_at = started_at + timedelta(
        seconds=(int(start) - int(pane_start)) / os.sysconf("SC_CLK_TCK"))
    if observed_at < native_started_at:
        return "unknown", "native_event_before_process", None
    # Reject a concurrent session switch, state update or native PID reuse.
    if _read(marker, uid) != raw:
        return "unknown", "binding_changed", None
    current_state, current_uid = _native_process(pid, start, pane_pid, pane_start, cwd)
    if current_uid != uid:
        return "unknown", "binding_changed", None
    if current_state in _STOPPED_STATES:
        return "stopped", "process_stopped", None
    attested_idle = False
    if (value.get("attestation_source") == "sdk_idle" and state == "idle"
            and value.get("event_source") == "agent_settled"):
        attested_at = datetime.fromisoformat(value["attested_at"].replace("Z", "+00:00"))
        if (attested_at.tzinfo is None or attested_at < observed_at
                or attested_at > now + timedelta(seconds=5)):
            return "unknown", "observation_invalid", None
        attested_idle = 0 <= (now - attested_at).total_seconds() <= 30
    if provenance is not None:
        # Identity survives expired activity only after native and file checks.
        # A stale record cannot supply settlement or current idle proof.
        provenance.update(session_id=session_id, native_pid=pid, native_start=start)
        event_id, source = value.get("event_id"), value.get("event_source")
        if (isinstance(event_id, str) and str(UUID(event_id)) == event_id
                and source in {"agent_start", "agent_settled", "native_progress",
                               "ui_prompt_start", "ui_prompt_end", "session_reset"}):
            provenance.update(event_id=event_id, event_source=source)
            if (state == "idle" and reason == "native_turn_completed" and source == "agent_settled"
                    and (attested_idle or (now - observed_at).total_seconds() <= _FRESHNESS_SECONDS)):
                provenance["current_settlement_id"] = event_id
    if not attested_idle and (now - observed_at).total_seconds() > _FRESHNESS_SECONDS:
        return "unknown", "native_event_stale", observed_at
    return state, reason, observed_at
