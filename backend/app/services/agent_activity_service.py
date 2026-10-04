"""Read bounded native activity observations; never infer work from a live PID.

Only authenticated, current pane bindings and explicit Codex resume UUIDs are
supported. Missing permissions, ambiguous bindings and other harnesses return
unknown. No transcripts, paths, session IDs or credentials leave this module.
"""
from __future__ import annotations

import asyncio
import json
import os
import pwd
import sqlite3
import stat
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentPaneBinding, AgentTeamSlot, MailAgentSession, MailPaneLifecycle, MailTeamMember,
)
from app.models.schemas import AgentActivityObservation, AgentTeamActivityResponse

_TAIL_BYTES = 1_048_576
_MAX_PROCESS_DESCRIPTORS = 256
_WORK_FRESHNESS_SECONDS = 180
_STOPPED_STATES = {"T", "t", "Z", "X", "x"}


def _canonical_session_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _process(pid: int) -> tuple[str, str]:
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return fields[0], fields[19]  # state and kernel process start, not PID alone


def _codex_home(pid: int) -> Path:
    proc = Path(f"/proc/{pid}")
    # Cross-user controllers may read stat/cmdline but not environ. In that
    # case use the process owner's default home; custom homes remain unknown.
    try:
        environment = dict(entry.split(b"=", 1) for entry in
                           (proc / "environ").read_bytes().split(b"\0") if b"=" in entry)
        configured = environment.get(b"CODEX_HOME")
        home = configured or environment.get(b"HOME")
        if home:
            result = Path(os.fsdecode(home))
            if not result.is_absolute():
                raise ValueError("Relative home")
            return result if configured else result / ".codex"
    except PermissionError:
        pass
    return Path(pwd.getpwuid(proc.stat().st_uid).pw_dir) / ".codex"


def _process_rollout_path(pid: int, home: Path, session_id: str) -> Path | None:
    """Find the native conversation actually opened by this exact process.

    This needs only read access. SQLite's live WAL index can require writable
    scratch files even for a mode=ro query from another controller user.
    """
    descriptors = Path(f"/proc/{pid}/fd")
    matches: set[Path] = set()
    try:
        with os.scandir(descriptors) as entries:
            for index, entry in enumerate(entries):
                if index >= _MAX_PROCESS_DESCRIPTORS:
                    raise ValueError("Process descriptor observation exceeds its bound")
                target = Path(os.readlink(entry.path))
                if not target.name.endswith(f"-{session_id}.jsonl") or not target.is_absolute():
                    continue
                target = target.resolve()
                if (target.is_relative_to((home / "sessions").resolve())
                        and stat.S_ISREG(target.stat().st_mode)):
                    matches.add(target)
    except OSError:
        return None
    if len(matches) > 1:
        raise ValueError("Native conversation has ambiguous process descriptors")
    return next(iter(matches), None)


def _rollout_path(home: Path, session_id: str, cwd: str) -> Path | None:
    # Indexed exact-ID lookup: do not recursively scan every user's history on
    # each roster poll. Bound both schema discovery and SQLite lock waiting.
    databases = [home / "state_5.sqlite"]
    databases.extend(sorted(home.glob("state_*.sqlite"), reverse=True)[:8])
    for database in dict.fromkeys(databases):
        if not database.is_file():
            continue
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True,
                                         timeout=0.1)) as connection:
                row = connection.execute(
                    "SELECT rollout_path, cwd FROM threads WHERE id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
        except sqlite3.Error:
            continue
        if row and row[0] and row[1] and Path(row[1]).resolve() == Path(cwd).resolve():
            result = Path(row[0]).resolve()
            if (result.is_relative_to((home / "sessions").resolve())
                    and stat.S_ISREG(result.stat().st_mode)):
                return result
    return None


def _process_started_at(start: str) -> datetime:
    # Sample boot clock first, wall clock second, and add a kernel tick. This
    # is a conservative upper boundary: inherited events must never start work
    # in a newly resumed process just because its conversation UUID is the same.
    boot_seconds = time.clock_gettime(time.CLOCK_BOOTTIME)
    wall = datetime.now(timezone.utc)
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    return wall - timedelta(seconds=boot_seconds - int(start) / ticks_per_second) + timedelta(
        seconds=1 / ticks_per_second)


def _native_state(path: Path, session_id: str, cwd: str, now: datetime, started_at: datetime
                  ) -> tuple[str, str, datetime | None]:
    with path.open("rb") as stream:
        metadata = json.loads(stream.readline(65_536))
        payload = metadata.get("payload", {})
        if (metadata.get("type") != "session_meta" or payload.get("id") != session_id
                or Path(payload.get("cwd", "")).resolve() != Path(cwd).resolve()):
            return "unknown", "session_mismatch", None
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        offset = max(0, size - _TAIL_BYTES)
        stream.seek(offset)
        tail = stream.read(_TAIL_BYTES)
    if not tail.endswith(b"\n"):
        return "unknown", "observation_incomplete", None
    lines = tail.splitlines()
    if offset:
        lines = lines[1:]  # first line can be a partial JSON record
    state, reason, observed_at = "unknown", "no_native_event", None
    for line in lines:
        record = json.loads(line)
        if record.get("type") != "event_msg":
            continue
        event = record.get("payload", {}).get("type")
        if event not in {"task_started", "task_complete", "turn_aborted", "error",
                         "token_count", "item_completed"}:
            continue
        timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > now + timedelta(seconds=5):
            return "unknown", "observation_invalid", None
        if observed_at is not None and timestamp < observed_at:
            return "unknown", "observation_invalid", None
        if timestamp < started_at:
            state, reason = "unknown", "native_event_before_process"
            continue
        if event == "task_started":
            state, reason = "working", "native_turn_started"
        elif event == "task_complete":
            state, reason = "idle", "native_turn_completed"
        elif event in {"turn_aborted", "error"}:
            state, reason = "idle", "native_turn_interrupted"
        elif state != "working":
            continue  # progress alone never starts an inferred turn
        observed_at = timestamp
    if state == "working" and observed_at and (
        now - observed_at
    ).total_seconds() > _WORK_FRESHNESS_SECONDS:
        return "unknown", "native_event_stale", observed_at
    return state, reason, observed_at


def _observe(slot_id: int, provider: str, session_id: str | None,
             candidates: list[tuple[int, str, str]], duplicate_identity: bool, now: datetime
             ) -> AgentActivityObservation:
    def result(state: str, reason: str, observed_at: datetime | None = None):
        return AgentActivityObservation(slot_id=slot_id, state=state, reason=reason,
                                        observed_at=observed_at)

    try:
        live = []
        for pid, start, cwd in candidates:
            try:
                process_state, current_start = _process(pid)
            except FileNotFoundError:
                continue
            if current_start == start:
                live.append((pid, start, cwd, process_state))
        if not live:
            return result("stopped" if candidates else "unknown",
                          "process_ended" if candidates else "no_current_binding")
        if len(live) != 1:
            return result("unknown", "ambiguous_binding")
        pid, start, cwd, process_state = live[0]
        if process_state in _STOPPED_STATES:
            return result("stopped", "process_stopped")
        if provider != "codex-cli":
            return result("unknown", "provider_unsupported")
        if duplicate_identity:
            return result("unknown", "duplicate_native_identity")
        if not session_id or _canonical_session_id(session_id) != session_id:
            return result("unknown", "session_identity_unavailable")
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        # The running executable must be Codex and explicitly resume this UUID.
        if (Path(os.fsdecode(argv[0])).name != "codex" or b"resume" not in argv
                or session_id.encode() not in argv):
            return result("unknown", "session_mismatch")
        home = _codex_home(pid)
        path = _process_rollout_path(pid, home, session_id) or _rollout_path(home, session_id, cwd)
        if path is None:
            return result("unknown", "native_log_unavailable")
        state, reason, observed_at = _native_state(path, session_id, cwd, now, _process_started_at(start))
        process_state, current_start = _process(pid)
        if current_start != start:
            return result("unknown", "binding_changed")
        if process_state in _STOPPED_STATES:
            return result("stopped", "process_stopped")
        return result(state, reason, observed_at)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, RuntimeError):
        return result("unknown", "observation_unavailable")


async def _team_inputs(db: AsyncSession, preset_id: int):
    slots = list((await db.scalars(select(AgentTeamSlot).where(
        AgentTeamSlot.preset_id == preset_id).execution_options(populate_existing=True))).all())
    # A rollout identifies a conversation, not its writer PID. Conservatively
    # reject UUID reuse anywhere in Deck, including other presets/disabled slots,
    # so another harness cannot supply a false Working event for this owner.
    native_identity_counts: dict[str, int] = {}
    for options in await db.scalars(select(AgentTeamSlot.launch_options).where(
            AgentTeamSlot.provider == "codex-cli")):
        session_id = _canonical_session_id((options or {}).get("session_id"))
        if session_id is not None:
            native_identity_counts[session_id] = native_identity_counts.get(session_id, 0) + 1
    members = list((await db.scalars(select(MailTeamMember).where(
        MailTeamMember.team_preset_id == preset_id).order_by(
            MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).execution_options(
                populate_existing=True))).all())
    current_member = {}
    for member in members:
        current_member.setdefault(member.team_slot_id, member.id)
    rows = (await db.execute(select(AgentPaneBinding, MailAgentSession).join(
        MailAgentSession,
        (MailAgentSession.bound_pane_pid == AgentPaneBinding.pane_pid)
        & (MailAgentSession.bound_pane_proc_start == AgentPaneBinding.pane_proc_start)
        & (MailAgentSession.team_slot_id == AgentPaneBinding.slot_id)
        & (MailAgentSession.team_preset_id == AgentPaneBinding.preset_id),
    ).outerjoin(MailPaneLifecycle,
        (MailPaneLifecycle.pane_pid == AgentPaneBinding.pane_pid)
        & (MailPaneLifecycle.pane_proc_start == AgentPaneBinding.pane_proc_start),
    ).where(AgentPaneBinding.preset_id == preset_id,
            MailAgentSession.source == "mcp", MailAgentSession.closed_at.is_(None),
            MailAgentSession.mailbox_status == "connected",
            MailAgentSession.capability_token_hash.is_not(None),
            MailPaneLifecycle.retired_at.is_(None)).execution_options(populate_existing=True))).all()
    bindings: dict[int, set[tuple[int, str, str, str]]] = {}
    for binding, session in rows:
        if session.member_id == current_member.get(binding.slot_id) and session.cwd:
            bindings.setdefault(binding.slot_id, set()).add((
                binding.pane_pid, binding.pane_proc_start, session.provider, session.cwd))
    return [(slot.id, slot.provider, (slot.launch_options or {}).get("session_id"),
               sorted((pid, start, cwd) for pid, start, provider, cwd in
                bindings.get(slot.id, set()) if provider == slot.provider),
               native_identity_counts.get(_canonical_session_id((slot.launch_options or {}).get("session_id")) or "", 0) > 1)
            for slot in slots]


async def observe_team(db: AsyncSession, preset_id: int) -> AgentTeamActivityResponse:
    inputs = await _team_inputs(db, preset_id)
    now = datetime.now(timezone.utc)
    observations = await asyncio.to_thread(
        lambda: [_observe(slot_id, provider, session_id, candidates, duplicate_identity, now)
                 for slot_id, provider, session_id, candidates, duplicate_identity in inputs])
    current = {entry[0]: entry for entry in await _team_inputs(db, preset_id)}
    for entry, observation in zip(inputs, observations):
        if current.get(entry[0]) != entry:
            observation.state = "unknown"
            observation.reason = "binding_changed"
            observation.observed_at = None
    return AgentTeamActivityResponse(preset_id=preset_id, checked_at=now,
                                    valid_until=now + timedelta(seconds=15), slots=observations)
