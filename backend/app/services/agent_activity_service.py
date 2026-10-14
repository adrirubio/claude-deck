"""Read bounded native activity observations; never infer work from a live PID.

Use authenticated current pane bindings, explicit Codex resume UUIDs, or Pi's
native extension observations. Missing permissions and ambiguous bindings return
unknown. No transcripts, paths, session IDs or credentials leave this module.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pwd
import re
import sqlite3
import stat
import subprocess
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import JSON, and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, MailAgentSession, MailMessage, MailReceipt, MailPaneLifecycle, MailTeamMember,
)
from app.models.schemas import (
    AgentActivityDisplayObservation, AgentActivityObservation, AgentTeamActivityResponse,
    NativeInputWait,
)
from app.services.pi_activity_service import observe_pi
from app.services.claude_activity_service import observe_claude
from app.services.muse_activity_service import discover_muse_session, observe_muse

_TAIL_BYTES = 1_048_576
_MAX_PROCESS_DESCRIPTORS = 256
_WORK_FRESHNESS_SECONDS = 180
_STOPPED_STATES = {"T", "t", "Z", "X", "x"}
_BOUNDED_PRIVATE_WORKERS = threading.BoundedSemaphore(1)
_PROC = Path("/proc")


def recognize_native_input_wait(provider: str, screen: str) -> str | None:
    """Recognize captured active prompts. None means the screen is unknown."""
    if provider not in {"claude-code", "codex-cli"} or len(screen) > 65536:
        return None
    plain = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", screen)
    plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", plain)
    lines = [line.strip() for line in plain.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    active = "\n".join(lines[-40:])
    footer = " ".join(lines[-3:])
    if provider == "claude-code":
        if (re.search(r"Enter to select\s*·\s*(?:↑/↓|Tab/Arrow keys) to navigate\s*·\s*Esc to\s+cancel$", footer)
                and re.search(r"(?m)^❯\s*\d+\.", active) and "☐" in active):
            return "question"
        if (footer.endswith("Enter to confirm · Esc to cancel") and "Accessing workspace:" in active
                and "Quick safety check:" in active and "Yes, I trust this folder" in active
                and re.search(r"(?m)^❯\s*(?:No,|Yes,)", active)):
            return "trust"
        if any(re.fullmatch(r"❯\s*", line) for line in lines[-4:]):
            return "clear"
    else:
        if (footer.endswith("Press enter to continue") and "Welcome to Codex" in active
                and "Sign in with ChatGPT" in active and "Provide your own API key" in active
                and re.search(r"(?m)^>\s*1\. Sign in with ChatGPT$", active)):
            return "sign_in"
        if any(re.fullmatch(r"›\s*Ask Codex to do anything", line) for line in lines[-4:]):
            return "clear"
    return None


@dataclass(frozen=True)
class ActivityBinding:
    pane_pid: int
    pane_start: str
    cwd: str
    native_pid: int | None = None
    registered_at: datetime | None = None
    tmux_target: str | None = None
    binding_id: int | None = None


def _capture_native_input_wait(provider: str, binding: ActivityBinding) -> str | None:
    """Read the visible pane after checking its exact process identity."""
    if not binding.tmux_target or provider not in {"claude-code", "codex-cli"}:
        return None
    def pane_identity(target):
        process = subprocess.run(["tmux", "display-message", "-p", "-t", target,
                                  "#{pane_pid}:#{pane_id}"], capture_output=True, text=True, timeout=0.5)
        if process.returncode != 0:
            return None
        match = re.fullmatch(r"(\d+):(%\d+)", process.stdout.strip())
        return (int(match[1]), match[2]) if match else None
    try:
        before = pane_identity(binding.tmux_target)
        if before is None or before[0] != binding.pane_pid:
            return None
        state, start = _process(binding.pane_pid)
        if start != binding.pane_start or state in _STOPPED_STATES:
            return None
        captured = subprocess.run(["tmux", "capture-pane", "-p", "-t", before[1]],
            capture_output=True, text=True, timeout=0.5)
        after = pane_identity(before[1])
        state, start = _process(binding.pane_pid)
        if captured.returncode != 0 or before != after or start != binding.pane_start or state in _STOPPED_STATES:
            return None
        return recognize_native_input_wait(provider, captured.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _canonical_session_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _process(pid: int) -> tuple[str, str]:
    fields = (_PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
    return fields[0], fields[19]  # state and kernel process start, not PID alone


def _codex_home(pid: int) -> Path:
    proc = _PROC / str(pid)
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
    descriptors = _PROC / str(pid) / "fd"
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


def _new_codex_rollout(pid: int, cwd: str, now: datetime, started_at: datetime) -> str | None:
    """Capture one current rollout from this exact process. This is not work evidence."""
    home = _codex_home(pid)
    uid = (_PROC / str(pid)).stat().st_uid
    matches = set()
    with os.scandir(_PROC / str(pid) / "fd") as entries:
        for index, entry in enumerate(entries):
            if index >= _MAX_PROCESS_DESCRIPTORS:
                raise ValueError("Process descriptor observation exceeds its bound")
            try:
                target = Path(os.readlink(entry.path))
                identity = _canonical_session_id(target.stem[-36:])
                if (identity is None or target.suffix != ".jsonl" or not target.is_absolute()
                        or not target.resolve().is_relative_to((home / "sessions").resolve())):
                    continue
                descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    opened = os.stat(entry.path)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                            or info.st_mode & stat.S_IWOTH
                            or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)):
                        continue
                    line = stream.readline(65537)
                    if len(line) > 65536 or not line.endswith(b"\n"):
                        continue
                    row = json.loads(line)
                    current = os.stat(entry.path)
                    if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                        continue
                payload = row.get("payload", {})
                if (row.get("type") != "session_meta" or payload.get("id") != identity
                        or Path(payload.get("cwd", "")).resolve() != Path(cwd).resolve()):
                    continue
                timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None or not started_at <= timestamp <= now + timedelta(seconds=5):
                    continue
                matches.add(identity)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
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


def _native_state(path: Path, session_id: str, cwd: str, now: datetime, started_at: datetime,
                  *, provenance: dict | None = None
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
    state, reason, observed_at, cursor = "unknown", "no_native_event", None, None
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
        cursor = hashlib.sha256(f"{session_id}:{timestamp.isoformat()}:{event}".encode()).hexdigest()
    if provenance is not None:
        # A validated native lifetime can remain current while activity expires.
        # This supplies identity, never a working or idle assertion.
        provenance.update(session_id=session_id, event_id=cursor)
        if state == "idle" and reason == "native_turn_completed" and observed_at:
            provenance.update(event_source="task_complete", event_id=hashlib.sha256(
                f"{session_id}:{observed_at.isoformat()}:task_complete".encode()).hexdigest())
    if state == "working" and observed_at and (
        now - observed_at
    ).total_seconds() > _WORK_FRESHNESS_SECONDS:
        return "unknown", "native_event_stale", observed_at
    return state, reason, observed_at


def _observe(slot_id: int, provider: str, session_id: str | None,
             candidates: list[ActivityBinding], duplicate_identity: bool, now: datetime,
             *, provenance: dict | None = None,
             ) -> AgentActivityObservation:
    waiting_input = None
    def result(state: str, reason: str, observed_at: datetime | None = None):
        if reason == "binding_changed" or state == "stopped":
            if provenance is not None:
                for key in ("input_wait_known", "input_wait_reason", "input_wait_binding_id"):
                    provenance.pop(key, None)
        wait = waiting_input if reason != "binding_changed" and state != "stopped" else None
        if wait is not None:
            state, reason, observed_at = "idle", "native_input_wait", now
        return AgentActivityObservation(slot_id=slot_id, state=state, reason=reason,
                                        observed_at=observed_at, waiting_input=wait)

    try:
        live = {}
        for binding in candidates:
            pid, start, cwd = binding.pane_pid, binding.pane_start, binding.cwd
            try:
                process_state, current_start = _process(pid)
            except FileNotFoundError:
                continue
            if current_start == start:
                native_pid, native_start = None, None
                if provider == "pi-cli":
                    if not binding.native_pid or binding.registered_at is None:
                        return result("unknown", "native_identity_unavailable")
                    try:
                        _, native_start = _process(binding.native_pid)
                    except FileNotFoundError:
                        continue  # a dead auxiliary shim is not another live owner
                    registered_at = binding.registered_at
                    if registered_at.tzinfo is None:
                        registered_at = registered_at.replace(tzinfo=timezone.utc)
                    if (_process_started_at(native_start) > registered_at
                            or registered_at > now + timedelta(seconds=5)):
                        continue  # this PID did not exist at its authenticated registration
                    native_pid = binding.native_pid
                # Repeated authenticated rows for one exact native process do
                # not create another worker. Different live identities do.
                live[(pid, start, cwd, native_pid, native_start)] = process_state
        if not live:
            return result("stopped" if candidates else "unknown",
                          "process_ended" if candidates else "no_current_binding")
        if len(live) != 1:
            return result("unknown", "ambiguous_binding")
        (pid, start, cwd, native_pid, native_start), process_state = next(iter(live.items()))
        if process_state in _STOPPED_STATES:
            return result("stopped", "process_stopped")
        if provider == "pi-cli":
            options = {"provenance": provenance} if provenance is not None else {}
            state, reason, observed_at = observe_pi(
                pid, start, cwd, now, _process_started_at(start), native_pid, native_start, **options)
            process_state, current_start = _process(pid)
            if current_start != start:
                return result("unknown", "binding_changed")
            if process_state in _STOPPED_STATES:
                return result("stopped", "process_stopped")
            if provenance is not None and provenance.get("session_id"):
                provenance.update(pane_pid=pid, pane_start=start, provider=provider)
            return result(state, reason, observed_at)
        if provider == "muse-cli":
            if not session_id:
                identity = discover_muse_session(pid, cwd)
                process_state, current_start = _process(pid)
                if current_start != start or process_state in _STOPPED_STATES:
                    return result("unknown", "binding_changed")
                if identity and provenance is not None:
                    provenance["discovered_session_id"] = identity
                return result("unknown", "restart_needed_for_observation" if identity
                              else "session_identity_unavailable")
            if _canonical_session_id(session_id) != session_id:
                return result("unknown", "session_identity_unavailable")
            options = {"provenance": provenance} if provenance is not None else {}
            state, reason, observed_at = observe_muse(
                pid, session_id, cwd, now, _process_started_at(start), **options)
            process_state, current_start = _process(pid)
            if current_start != start:
                return result("unknown", "binding_changed")
            if process_state in _STOPPED_STATES:
                return result("stopped", "process_stopped")
            # The event log gives the question state exactly; record it per binding
            # the same way the screen recogniser does for other harnesses.
            matching = [binding for binding in candidates if binding.pane_pid == pid and binding.pane_start == start]
            if len(matching) == 1 and state in {"waiting_input", "working", "idle"}:
                input_reason = "question" if state == "waiting_input" else "clear"
                if provenance is not None:
                    provenance.update(input_wait_known=True, input_wait_reason=input_reason,
                                      input_wait_binding_id=matching[0].binding_id)
                if input_reason == "question":
                    waiting_input = NativeInputWait(reason="question", observed_at=now)
            if state == "waiting_input":
                state = "working"
            if provenance is not None and provenance.get("session_id"):
                provenance.update(pane_pid=pid, pane_start=start, provider=provider)
            return result(state, reason, observed_at)
        if provider not in {"codex-cli", "claude-code"}:
            return result("unknown", "provider_unsupported")
        if duplicate_identity:
            return result("unknown", "duplicate_native_identity")
        matching = [binding for binding in candidates if binding.pane_pid == pid and binding.pane_start == start]
        targets = {binding.tmux_target for binding in matching if binding.tmux_target}
        if len(targets) == 1:
            selected_binding = next(binding for binding in matching if binding.tmux_target in targets)
            input_reason = _capture_native_input_wait(provider, selected_binding)
            if input_reason is not None:
                if provenance is not None:
                    provenance.update(input_wait_known=True, input_wait_reason=input_reason,
                                      input_wait_binding_id=selected_binding.binding_id)
                if input_reason != "clear":
                    waiting_input = NativeInputWait(reason=input_reason, observed_at=now)
        if provider == "codex-cli" and not session_id:
            argv = (_PROC / str(pid) / "cmdline").read_bytes().split(b"\0")
            if argv and Path(os.fsdecode(argv[0])).name == "codex":
                identity = _new_codex_rollout(pid, cwd, now, _process_started_at(start))
                process_state, current_start = _process(pid)
                if current_start != start or process_state in _STOPPED_STATES:
                    return result("unknown", "binding_changed")
                if identity:
                    if provenance is not None:
                        provenance["discovered_session_id"] = identity
                    return result("unknown", "restart_needed_for_observation")
        if not session_id or _canonical_session_id(session_id) != session_id:
            return result("unknown", "session_identity_unavailable")
        if provider == "claude-code":
            options = {"provenance": provenance} if provenance is not None else {}
            state, reason, observed_at = observe_claude(
                pid, session_id, cwd, now, _process_started_at(start), **options)
            process_state, current_start = _process(pid)
            if current_start != start:
                return result("unknown", "binding_changed")
            if process_state in _STOPPED_STATES:
                return result("stopped", "process_stopped")
            if provenance is not None and provenance.get("session_id"):
                provenance.update(pane_pid=pid, pane_start=start, provider=provider)
            return result(state, reason, observed_at)
        argv = (_PROC / str(pid) / "cmdline").read_bytes().split(b"\0")
        # The running executable must be Codex and explicitly resume this UUID.
        from app.services.codex_process_identity import explicit_resume
        if not explicit_resume(argv, session_id):
            if argv and Path(os.fsdecode(argv[0])).name == "codex":
                identity = _new_codex_rollout(pid, cwd, now, _process_started_at(start))
                process_state, current_start = _process(pid)
                if current_start != start or process_state in _STOPPED_STATES:
                    return result("unknown", "binding_changed")
                if identity == session_id:
                    return result("unknown", "restart_needed_for_observation")
            return result("unknown", "session_mismatch")
        home = _codex_home(pid)
        path = _process_rollout_path(pid, home, session_id) or _rollout_path(home, session_id, cwd)
        if path is None:
            return result("unknown", "native_log_unavailable")
        options = {"provenance": provenance} if provenance is not None else {}
        state, reason, observed_at = _native_state(path, session_id, cwd, now, _process_started_at(start), **options)
        process_state, current_start = _process(pid)
        if current_start != start:
            return result("unknown", "binding_changed")
        if process_state in _STOPPED_STATES:
            return result("stopped", "process_stopped")
        if provenance is not None and provenance.get("session_id"):
            provenance.update(pane_pid=pid, pane_start=start, provider=provider)
        return result(state, reason, observed_at)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, RuntimeError):
        return result("unknown", "observation_unavailable")


async def _team_inputs(db: AsyncSession, preset_id: int, max_rows: int | None = None):
    async def rows(query):
        if max_rows is not None:
            query = query.limit(max_rows + 1)
        values = list((await db.execute(query)).all())
        if max_rows is not None and len(values) > max_rows:
            raise ValueError("activity_context_limit")
        return values

    slots = [row[0] for row in await rows(select(AgentTeamSlot).where(
        AgentTeamSlot.preset_id == preset_id).execution_options(populate_existing=True))]
    options = await rows(select(AgentTeamSlot.launch_options).where(
        AgentTeamSlot.provider.in_(["codex-cli", "claude-code", "muse-cli"])))
    members = [row[0] for row in await rows(select(MailTeamMember).where(
        MailTeamMember.team_preset_id == preset_id).order_by(
            MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).execution_options(
                populate_existing=True))]
    bound_rows = await rows(select(AgentPaneBinding, MailAgentSession).join(
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
            MailPaneLifecycle.retired_at.is_(None)).execution_options(populate_existing=True))
    return _inputs_from_rows(slots, options, members, bound_rows)


def _inputs_from_rows(slots, options, members, bound_rows):
    """Build the same native inputs from an existing read snapshot."""
    # A rollout identifies a conversation, not its writer PID. Conservatively
    # reject UUID reuse anywhere in Deck, including other presets/disabled slots,
    # so another harness cannot supply a false Working event for this owner.
    native_identity_counts: dict[str, int] = {}
    for (launch_options,) in options:
        session_id = _canonical_session_id((launch_options or {}).get("session_id"))
        if session_id is not None:
            native_identity_counts[session_id] = native_identity_counts.get(session_id, 0) + 1
    current_member = {}
    for member in sorted(members, key=lambda m: (m.updated_at, m.id), reverse=True):
        current_member.setdefault(member.team_slot_id, member.id)
    bindings: dict[int, set[tuple[str, ActivityBinding]]] = {}
    for binding, session in bound_rows:
        if session.member_id == current_member.get(binding.slot_id) and session.cwd:
            bindings.setdefault(binding.slot_id, set()).add((session.provider, ActivityBinding(
                binding.pane_pid, binding.pane_proc_start, session.cwd,
                session.pid if session.provider == "pi-cli" else None,
                session.created_at if session.provider == "pi-cli" else None,
                getattr(binding, "tmux_target", None) or getattr(session, "pane_id", None),
                getattr(binding, "id", None))))
    return [(slot.id, slot.provider, (slot.launch_options or {}).get("session_id"),
               sorted((binding for provider, binding in bindings.get(slot.id, set())
                       if provider == slot.provider), key=lambda x: (
                           x.pane_pid, x.pane_start, x.cwd, x.native_pid or 0,
                           str(x.registered_at))),
               native_identity_counts.get(_canonical_session_id((slot.launch_options or {}).get("session_id")) or "", 0) > 1)
            for slot in slots]


async def _bounded_native_read(read):
    if not _BOUNDED_PRIVATE_WORKERS.acquire(blocking=False):
        raise ValueError("activity_observation_busy")
    task = asyncio.create_task(asyncio.to_thread(read))

    def finished(worker):
        _BOUNDED_PRIVATE_WORKERS.release()
        if not worker.cancelled():
            worker.exception()

    task.add_done_callback(finished)
    return await asyncio.shield(task)


async def observe_team(db: AsyncSession, preset_id: int, *, include_agent_status: bool = True,
                       persist_identities: bool = True, max_input_rows: int | None = None,
                       input_fence: dict | None = None) -> AgentTeamActivityResponse:
    inputs = await _team_inputs(db, preset_id) if max_input_rows is None else await _team_inputs(db, preset_id, max_input_rows)
    now = datetime.now(timezone.utc)
    metadata = [{} for _ in inputs]
    def read():
        return [_observe(*entry, now, provenance=details) for entry, details in zip(inputs, metadata)]
    observations = await asyncio.to_thread(read) if max_input_rows is None else await _bounded_native_read(read)
    refreshed = await _team_inputs(db, preset_id) if max_input_rows is None else await _team_inputs(db, preset_id, max_input_rows)
    current = {entry[0]: entry for entry in refreshed}
    if input_fence is not None:
        input_fence.update(current)
    for entry, observation in zip(inputs, observations):
        if current.get(entry[0]) != entry:
            observation.state = "unknown"
            observation.reason = "binding_changed"
            observation.observed_at = None
            observation.waiting_input = None
    notices_changed = await _record_input_waits(db, preset_id, inputs, metadata, current, now=now)
    if persist_identities and await _save_codex_identities(db, inputs, metadata, current):
        await db.commit()
    if notices_changed:
        await db.commit()
    if include_agent_status:
        from app.services.agent_status_service import agent_status_service, unknown_status
        statuses = await agent_status_service.for_team(
            db, preset_id, activities={entry.slot_id: entry for entry in observations})
        observations = [AgentActivityDisplayObservation(
            **entry.model_dump(), agent_status=statuses.get(entry.slot_id, unknown_status(now)))
            for entry in observations]
    else:
        observations = [AgentActivityDisplayObservation(**entry.model_dump()) for entry in observations]
    return AgentTeamActivityResponse(preset_id=preset_id, checked_at=now,
                                    valid_until=now + timedelta(seconds=15), slots=observations)


async def _record_input_waits(db, preset_id, inputs, metadata, current, *, now) -> bool:
    """Store one fixed notice per continuous wait under current binding authority."""
    changed = False
    for entry, details in zip(inputs, metadata):
        reason = details.get("input_wait_reason")
        if (not details.get("input_wait_known") or reason not in {"question", "trust", "sign_in", "clear"}
                or current.get(entry[0]) != entry):
            continue
        matching = [binding for binding in entry[3] if binding.binding_id == details.get("input_wait_binding_id")]
        if len(matching) != 1:
            continue
        binding = matching[0]
        # Recheck membership, authenticated session, slot and retirement in the write.
        newest_member = (select(MailTeamMember.id).where(MailTeamMember.team_preset_id == preset_id,
            MailTeamMember.team_slot_id == entry[0]).order_by(MailTeamMember.updated_at.desc(),
            MailTeamMember.id.desc()).limit(1).scalar_subquery())
        authenticated = exists(select(MailAgentSession.id).where(
            MailAgentSession.member_id == newest_member, MailAgentSession.source == "mcp",
            MailAgentSession.closed_at.is_(None), MailAgentSession.mailbox_status == "connected",
            MailAgentSession.capability_token_hash.is_not(None), MailAgentSession.cwd == binding.cwd,
            MailAgentSession.provider == entry[1], MailAgentSession.team_slot_id == entry[0],
            MailAgentSession.team_preset_id == preset_id, MailAgentSession.bound_pane_pid == binding.pane_pid,
            MailAgentSession.bound_pane_proc_start == binding.pane_start,
            or_(AgentPaneBinding.tmux_target == binding.tmux_target,
                and_(AgentPaneBinding.tmux_target.is_(None), MailAgentSession.pane_id == binding.tmux_target))))
        active_slot = exists(select(AgentTeamSlot.id).where(AgentTeamSlot.id == entry[0],
            AgentTeamSlot.preset_id == preset_id, AgentTeamSlot.provider == entry[1], AgentTeamSlot.enabled.is_(True)))
        retired = exists(select(MailPaneLifecycle.pane_pid).where(MailPaneLifecycle.pane_pid == binding.pane_pid,
            MailPaneLifecycle.pane_proc_start == binding.pane_start, MailPaneLifecycle.retired_at.is_not(None)))
        conditions = [AgentPaneBinding.id == binding.binding_id, AgentPaneBinding.slot_id == entry[0],
            AgentPaneBinding.preset_id == preset_id, AgentPaneBinding.pane_pid == binding.pane_pid,
            AgentPaneBinding.pane_proc_start == binding.pane_start, authenticated, active_slot, ~retired,
            or_(AgentPaneBinding.waiting_input_observed_at.is_(None), AgentPaneBinding.waiting_input_observed_at <= now)]
        if reason == "clear":
            result = await db.execute(update(AgentPaneBinding).where(*conditions).values(waiting_input_reason=None,
                waiting_input_started_at=None, waiting_input_notice_id=None, waiting_input_observed_at=now).execution_options(synchronize_session=False))
            changed = changed or result.rowcount == 1
            continue
        kept = await db.execute(update(AgentPaneBinding).where(*conditions,
            AgentPaneBinding.waiting_input_reason.is_not(None)).values(waiting_input_observed_at=now)
            .execution_options(synchronize_session=False))
        if kept.rowcount == 1:
            changed = True
            continue
        team = (await db.execute(select(AgentTeamPreset.supervisor_actor_id, AgentTeamPreset.leader_slot_id)
            .where(AgentTeamPreset.id == preset_id))).one_or_none()
        if team is None:
            continue
        actor_id, leader_slot_id = team
        recipient = None
        if actor_id is None:
            recipient = await db.scalar(select(MailTeamMember.id).join(AgentTeamSlot,
                AgentTeamSlot.id == MailTeamMember.team_slot_id).where(
                MailTeamMember.team_preset_id == preset_id, MailTeamMember.team_slot_id == leader_slot_id,
                AgentTeamSlot.preset_id == preset_id, AgentTeamSlot.enabled.is_(True))
                .order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).limit(1))
            if recipient is None:
                continue
        same_route = exists(select(AgentTeamPreset.id).where(AgentTeamPreset.id == preset_id,
            AgentTeamPreset.supervisor_actor_id.is_(None) if actor_id is None else AgentTeamPreset.supervisor_actor_id == actor_id,
            AgentTeamPreset.leader_slot_id == leader_slot_id if actor_id is None else True))
        if recipient is not None:
            leader_current = (select(MailTeamMember.id).where(MailTeamMember.team_preset_id == preset_id,
                MailTeamMember.team_slot_id == leader_slot_id).order_by(MailTeamMember.updated_at.desc(),
                MailTeamMember.id.desc()).limit(1).scalar_subquery())
            conditions.extend([leader_current == recipient, exists(select(AgentTeamSlot.id).where(
                AgentTeamSlot.id == leader_slot_id, AgentTeamSlot.preset_id == preset_id,
                AgentTeamSlot.enabled.is_(True)))])
        result = await db.execute(update(AgentPaneBinding).where(*conditions, same_route,
            AgentPaneBinding.waiting_input_reason.is_(None)).values(waiting_input_reason=reason,
            waiting_input_started_at=now, waiting_input_observed_at=now).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            continue
        payload = {"notice": "native_input_wait", "slot_id": entry[0], "reason": reason}
        if actor_id is not None:
            payload["supervisor_actor_id"] = actor_id
        message = MailMessage(kind="message", subject="Waiting for input",
            body_markdown=f"Slot {entry[0]} waits for input. Reason: {reason}.", payload=payload,
            audience_type="team_preset" if actor_id is not None else None,
            audience_id=str(preset_id) if actor_id is not None else None, recipient_member_id=recipient)
        db.add(message)
        await db.flush()
        if recipient is not None:
            db.add(MailReceipt(message_id=message.id, member_id=recipient))
        await db.execute(update(AgentPaneBinding).where(AgentPaneBinding.id == binding.binding_id)
            .values(waiting_input_notice_id=message.id).execution_options(synchronize_session=False))
        changed = True
    return changed


# First-launch session ids that Deck discovers from the live process.
_DISCOVERED_IDENTITY_PROVIDERS = {"codex-cli", "muse-cli"}


async def _save_codex_identities(db, inputs, metadata, current) -> bool:
    """Save a captured first-launch ID only while its original binding remains current."""
    changed = False
    for entry, details in zip(inputs, metadata):
        identity = details.get("discovered_session_id")
        if (not identity or entry[1] not in _DISCOVERED_IDENTITY_PROVIDERS or entry[2] is not None
                or current.get(entry[0]) != entry):
            continue
        slot = await db.get(AgentTeamSlot, entry[0])
        if slot is None or slot.provider != entry[1] or slot.launch_mode != "plain":
            continue
        previous = slot.launch_options
        if (previous or {}).get("session_id"):
            continue
        duplicate = exists(select(AgentTeamSlot.id).where(
            AgentTeamSlot.id != slot.id,
            AgentTeamSlot.provider.in_(["claude-code", "codex-cli", "muse-cli"]),
            AgentTeamSlot.launch_options["session_id"].as_string() == identity))
        options_match = (or_(AgentTeamSlot.launch_options.is_(None),
                             AgentTeamSlot.launch_options == JSON.NULL)
                         if previous is None else AgentTeamSlot.launch_options == previous)
        result = await db.execute(update(AgentTeamSlot).where(
            AgentTeamSlot.id == slot.id, AgentTeamSlot.provider == entry[1],
            AgentTeamSlot.launch_mode == "plain", options_match,
            ~duplicate,
        ).values(launch_options={**(previous or {}), "session_id": identity, "use_last": False},
                 launch_mode="resume").execution_options(synchronize_session=False))
        changed = changed or result.rowcount == 1
        if result.rowcount == 1:
            await db.refresh(slot)
    return changed


@dataclass(frozen=True)
class PrivateActivity:
    """Scheduler evidence. Never serialize this object through a public API."""

    state: str
    reason: str
    observed_at: datetime | None
    identity: str | None
    settlement_id: str | None
    cursor: str | None = None
    current_settlement_id: str | None = None
    binding_identity: str | None = None


def private_binding_identity(provider: str, pane_pid: int, pane_start: str, cwd: str,
                             native_pid: int | None = None, native_start: str | None = None) -> str:
    return hashlib.sha256(json.dumps(
        [provider, pane_pid, pane_start, str(Path(cwd).resolve()), native_pid, native_start],
        separators=(",", ":"),
    ).encode()).hexdigest()


async def observe_private_team(db: AsyncSession, preset_id: int,
                               max_input_rows: int | None = None) -> dict[int, PrivateActivity]:
    inputs = await _team_inputs(db, preset_id, max_input_rows)
    now = datetime.now(timezone.utc)
    captured = []

    def observations():
        values = {}
        for entry in inputs:
            metadata = {}
            observed = _observe(*entry, now, provenance=metadata)
            captured.append(metadata)
            identity = None
            binding_identity = None
            if metadata.get("session_id") and metadata.get("pane_pid"):
                identity = hashlib.sha256(json.dumps({key: metadata.get(key) for key in (
                    "provider", "session_id", "pane_pid", "pane_start", "native_pid", "native_start",
                )}, sort_keys=True).encode()).hexdigest()
                matching = [binding for binding in entry[3]
                            if binding.pane_pid == metadata["pane_pid"] and binding.pane_start == metadata["pane_start"]
                            and binding.native_pid == metadata.get("native_pid")]
                if matching:
                    binding_identity = private_binding_identity(
                        entry[1], metadata["pane_pid"], metadata["pane_start"], matching[0].cwd,
                        metadata.get("native_pid"), metadata.get("native_start"))
            settled = (observed.state == "idle" and observed.reason == "native_turn_completed"
                       and metadata.get("event_source") in {"agent_settled", "task_complete", "claude_end_turn"}
                       and observed.observed_at is not None
                       and 0 <= (now - observed.observed_at).total_seconds() <= _WORK_FRESHNESS_SECONDS)
            values[entry[0]] = PrivateActivity(observed.state, observed.reason, observed.observed_at,
                                               identity, metadata.get("event_id") if settled else None,
                                               metadata.get("event_id"),
                                               metadata.get("current_settlement_id") if observed.state == "idle" else None,
                                               binding_identity)
        return values

    if max_input_rows is None:
        values = await asyncio.to_thread(observations)
    else:
        values = await _bounded_native_read(observations)
    current = {entry[0]: entry for entry in await _team_inputs(db, preset_id, max_input_rows)}
    for entry in inputs:
        if current.get(entry[0]) != entry:
            values[entry[0]] = PrivateActivity("unknown", "binding_changed", None, None, None)
    await _save_codex_identities(db, inputs, captured, current)
    await _record_input_waits(db, preset_id, inputs, captured, current, now=now)
    return values
