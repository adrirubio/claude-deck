"""Native observation fixtures. No harness, credentials or live database."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services import agent_activity_service as activity
from app.services import pi_activity_service as pi
from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, MailAgentSession,
    MailPaneLifecycle, MailTeamMember,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow_query", range(4))
async def test_bounded_activity_inputs_refuse_each_complete_query_on_overflow(overflow_query):
    from types import SimpleNamespace
    statements = []

    class Database:
        async def execute(self, statement):
            statements.append(statement)
            assert statement._limit_clause.value == 3
            values = [(None,)] * 3 if len(statements) - 1 == overflow_query else []
            return SimpleNamespace(all=lambda: values)

    with pytest.raises(ValueError, match="activity_context_limit"):
        await activity._team_inputs(Database(), 1, 2)
    assert len(statements) == overflow_query + 1
    if overflow_query > 0:
        # Duplicate UUID evidence remains global, including disabled slots.
        query = str(statements[1])
        assert "preset_id" not in query and "enabled" not in query


@pytest.mark.asyncio
async def test_bounded_native_worker_keeps_capacity_after_response_timeout(monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(activity, "_team_inputs", AsyncMock(return_value=[(1, "pi-cli", None, [], False)]))

    def observe(*_args, **_kwargs):
        started.set()
        assert release.wait(2)
        return SimpleNamespace(state="unknown", reason="fixture", observed_at=None)

    monkeypatch.setattr(activity, "_observe", observe)
    first = asyncio.create_task(activity.observe_private_team(None, 1, 256))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(first, .01)
        with pytest.raises(ValueError, match="activity_observation_busy"):
            await activity.observe_private_team(None, 1, 256)
    finally:
        release.set()
    # The capacity becomes available only after the actual native worker ends.
    for _ in range(100):
        if activity._BOUNDED_PRIVATE_WORKERS.acquire(blocking=False):
            activity._BOUNDED_PRIVATE_WORKERS.release()
            break
        await asyncio.sleep(.01)
    else:
        pytest.fail("native worker did not release capacity")
    result = await activity.observe_private_team(None, 1, 256)
    assert result[1].state == "unknown"


@pytest.fixture
def native(tmp_path, monkeypatch):
    cwd = tmp_path / "project"
    cwd.mkdir()
    directory = tmp_path / "sessions"
    directory.mkdir()
    proc = tmp_path / "proc"
    now = datetime.now(timezone.utc)
    pane_pid, native_pid = 50000, 50010
    pane_start, native_start = "1000", "1001"

    def process(pid, parent, start, state="S", command=b"pi\0"):
        path = proc / str(pid)
        path.mkdir(parents=True, exist_ok=True)
        fields = [state, str(parent)] + ["0"] * 17 + [start]
        (path / "stat").write_text(f"{pid} (pi worker) " + " ".join(fields))
        (path / "cmdline").write_bytes(command)
        if not (path / "cwd").exists():
            (path / "cwd").symlink_to(cwd, target_is_directory=True)

    process(pane_pid, 1, pane_start, command=b"zsh\0")
    process(native_pid, pane_pid, native_start)
    monkeypatch.setattr(pi, "_PROC", proc)
    monkeypatch.setattr(pi, "pi_session_directory", lambda project: directory)
    monkeypatch.setattr(activity, "_process", lambda pid: (pi._process(pid)[0], pi._process(pid)[2]))
    monkeypatch.setattr(activity, "_process_started_at", lambda start: now - timedelta(seconds=10))
    session_id = str(uuid4())
    header = {"type": "session", "version": 3, "id": session_id, "cwd": str(cwd)}
    log = directory / f"2026-10-05_{session_id}.jsonl"
    log.write_text(json.dumps(header) + "\n")
    marker = directory / f".deck-native-{pane_pid}-{pane_start}.json"
    value = {
        "version": 1, "pane": {"pid": pane_pid, "start": pane_start},
        "native": {"pid": native_pid, "start": native_start}, "cwd": str(cwd),
        "session_id": session_id, "session_file": str(log), "session_header": header,
        "session_persisted": True, "state": "working", "reason": "native_turn_started",
        "observed_at": (now - timedelta(seconds=1)).isoformat(),
    }

    def write():
        marker.write_text(json.dumps(value))

    def observe(provider="pi-cli", candidates=None):
        return activity._observe(2, provider, None, candidates if candidates is not None else [
            activity.ActivityBinding(pane_pid, pane_start, str(cwd), native_pid,
                                     now - timedelta(seconds=5))], False, now)

    write()
    return {
        "value": value, "write": write, "observe": observe, "process": process,
        "marker": marker, "log": log, "cwd": cwd, "proc": proc, "now": now,
        "pane_pid": pane_pid, "native_pid": native_pid, "pane_start": pane_start,
        "native_start": native_start, "directory": directory,
    }


@pytest.mark.parametrize(("state", "reason"), [
    ("working", "native_turn_started"), ("working", "native_progress"),
    ("idle", "native_turn_completed"), ("idle", "native_turn_interrupted"),
    ("idle", "native_input_requested"), ("unknown", "no_native_event"),
    ("unknown", "native_session_ended"),
])
def test_pi_native_boundaries(native, state, reason):
    native["value"].update(state=state, reason=reason)
    native["write"]()
    result = native["observe"]()
    assert (result.state, result.reason) == (state, reason)
    assert result.observed_at is not None
    assert set(result.model_dump()) == {"slot_id", "state", "reason", "observed_at"}
    assert str(native["cwd"]) not in result.model_dump_json()


def test_pi_first_pending_turn_uses_exact_sdk_header(native):
    native["log"].unlink()
    native["value"]["session_persisted"] = False
    native["write"]()
    assert native["observe"]().state == "working"


def test_pi_missing_persisted_log_is_unknown(native):
    native["log"].unlink()
    assert native["observe"]().state == "unknown"


def test_pi_uses_marker_instead_of_newest_file(native):
    other = dict(native["value"]["session_header"], id=str(uuid4()))
    (native["directory"] / "2099-newest.jsonl").write_text(json.dumps(other) + "\n")
    assert native["observe"]().state == "working"


@pytest.mark.parametrize("field", ["pane", "native", "cwd", "session_id", "session_file", "session_header", "state", "reason", "observed_at", "session_persisted"])
def test_pi_missing_fields_fail_closed(native, field):
    del native["value"][field]
    native["write"]()
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize(("field", "value"), [
    ("version", True), ("version", 2), ("pane", {"pid": 50000, "start": "different"}),
    ("native", {"pid": True, "start": "1001"}),
    ("native", {"pid": 50010, "start": "0"}),
    ("native", {"pid": 50010, "start": "reused"}),
    ("session_id", "partial"), ("session_file", "relative.jsonl"),
    ("state", "approved"), ("state", "stopped"), ("reason", "private prompt"),
    ("session_persisted", "false"),
])
def test_pi_invalid_metadata_fails_closed(native, field, value):
    native["value"][field] = value
    native["write"]()
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize(("state", "reason"), [
    ("working", "native_turn_started"), ("idle", "native_turn_completed"),
])
def test_pi_expired_observation_does_not_infer_activity(native, state, reason):
    native["value"].update(state=state, reason=reason,
        observed_at=(native["now"] - timedelta(seconds=181)).isoformat())
    # A long-lived process can have an old, otherwise valid native event.
    native_start = native["now"] - timedelta(seconds=300)
    native["write"]()
    result = pi.observe_pi(native["pane_pid"], native["pane_start"], str(native["cwd"]),
                           native["now"], native_start, native["native_pid"], native["native_start"])
    assert (result[0], result[1]) == ("unknown", "native_event_stale")


@pytest.mark.parametrize("offset", [-11, 6])
def test_pi_old_or_future_native_event_is_unknown(native, offset):
    native["value"]["observed_at"] = (native["now"] + timedelta(seconds=offset)).isoformat()
    native["write"]()
    assert native["observe"]().state == "unknown"


def test_pi_naive_time_is_unknown(native):
    native["value"]["observed_at"] = native["now"].replace(tzinfo=None).isoformat()
    native["write"]()
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("content", ["", "{", "null", "[]", "x" * 16385])
def test_pi_partial_malformed_or_excessive_marker_is_unknown(native, content):
    native["marker"].write_text(content)
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("field", ["id", "cwd", "version", "type"])
def test_pi_foreign_file_header_is_unknown(native, field):
    header = dict(native["value"]["session_header"], **{field: "foreign"})
    native["log"].write_text(json.dumps(header) + "\n")
    assert native["observe"]().state == "unknown"


def test_pi_unreadable_marker_is_unknown(native, monkeypatch):
    monkeypatch.setattr(pi, "_read", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError()))
    assert native["observe"]().state == "unknown"


def test_pi_cross_user_cwd_access_uses_authenticated_project_and_headers(native, monkeypatch):
    from pathlib import Path
    original = Path.resolve
    restricted = native["proc"] / str(native["native_pid"]) / "cwd"
    def resolve(path, *args, **kwargs):
        if path == restricted:
            raise PermissionError()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolve)
    assert native["observe"]().state == "working"
    native["value"]["session_header"]["cwd"] = "/foreign"
    native["write"]()
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("target", ["marker", "log"])
def test_pi_symlink_is_unknown(native, target):
    path = native[target]
    moved = path.with_suffix(".old")
    path.rename(moved)
    path.symlink_to(moved)
    assert native["observe"]().state == "unknown"


def test_pi_world_writable_marker_is_unknown(native):
    native["marker"].chmod(0o666)
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("identity", ["pane", "native"])
def test_pi_pid_reuse_cannot_supply_working(native, identity):
    pid = native[f"{identity}_pid"]
    native["process"](pid, 1 if identity == "pane" else native["pane_pid"], "9999")
    assert native["observe"]().state != "working"


def test_pi_unrelated_native_process_is_unknown(native):
    native["process"](native["native_pid"], 1, native["native_start"])
    assert native["observe"]().state == "unknown"


def test_pi_wrong_executable_is_unknown(native):
    native["process"](native["native_pid"], native["pane_pid"], native["native_start"], command=b"python\0")
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("state", ["T", "Z"])
def test_pi_stopped_native_process_is_static(native, state):
    native["process"](native["native_pid"], native["pane_pid"], native["native_start"], state=state)
    assert native["observe"]().state == "stopped"


def test_pi_marker_changed_during_observation_is_unknown(native, monkeypatch):
    original = pi._read
    reads = 0
    def changed(path, *args, **kwargs):
        nonlocal reads
        if path == native["marker"]:
            reads += 1
            if reads == 2:
                return b'{}'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(pi, "_read", changed)
    result = native["observe"]()
    assert (result.state, result.reason) == ("unknown", "binding_changed")


def test_no_binding_or_unsupported_provider_stays_unknown(native):
    assert native["observe"](candidates=[]).state == "unknown"
    assert native["observe"](provider="claude-code").reason == "provider_unsupported"


def test_codex_still_requires_explicit_session_identity(native):
    assert native["observe"](provider="codex-cli").reason == "session_identity_unavailable"


@pytest.mark.parametrize(("event", "expected"), [
    ("task_started", "working"), ("task_complete", "idle"),
    ("turn_aborted", "idle"), ("error", "idle"), ("token_count", "unknown"),
])
def test_codex_native_parser_is_preserved(native, event, expected):
    session_id = str(uuid4())
    native["log"].write_text(json.dumps({"type": "session_meta", "payload": {
        "id": session_id, "cwd": str(native["cwd"])}}) + "\n" + json.dumps({
        "type": "event_msg", "payload": {"type": event},
        "timestamp": (native["now"] - timedelta(seconds=1)).isoformat()}) + "\n")
    result = activity._native_state(native["log"], session_id, str(native["cwd"]),
                                    native["now"], native["now"] - timedelta(seconds=10))
    assert result[0] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "closed", "no_capability", "observed", "retired", "provider", "old_member"])
async def test_pi_inputs_require_current_authenticated_live_mail_binding(db, native, invalid):
    preset = AgentTeamPreset(name="Fixture")
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(preset_id=preset.id, display_name="Worker", provider="pi-cli",
        repo_id="fixture", repo_path=str(native["cwd"]), repo_name="fixture")
    db.add(slot)
    await db.flush()
    member = MailTeamMember(identity_key="fixture-member", repo_id="fixture",
        repo_path=str(native["cwd"]), repo_name="fixture", display_name="Worker",
        team_preset_id=preset.id, team_slot_id=slot.id)
    db.add(member)
    await db.flush()
    session = MailAgentSession(member_id=member.id, provider="pi-cli", source="mcp",
        session_key="fixture", cwd=str(native["cwd"]), team_preset_id=preset.id,
        team_slot_id=slot.id, capability_token_hash="fixture-only", mailbox_status="connected",
        pid=native["native_pid"], created_at=(native["now"] - timedelta(seconds=5)).replace(tzinfo=None),
        bound_pane_pid=native["pane_pid"], bound_pane_proc_start=native["pane_start"])
    db.add(session)
    db.add(AgentPaneBinding(pane_pid=native["pane_pid"], pane_proc_start=native["pane_start"],
        slot_id=slot.id, preset_id=preset.id))
    if invalid == "closed":
        session.closed_at = datetime.utcnow()
    elif invalid == "no_capability":
        session.capability_token_hash = None
    elif invalid == "observed":
        session.source = "observed"
    elif invalid == "retired":
        db.add(MailPaneLifecycle(pane_pid=native["pane_pid"], pane_proc_start=native["pane_start"],
            retired_at=datetime.utcnow()))
    elif invalid == "provider":
        session.provider = "codex-cli"
    elif invalid == "old_member":
        db.add(MailTeamMember(identity_key="replacement", repo_id="fixture", repo_path=str(native["cwd"]),
            repo_name="fixture", display_name="Replacement", team_preset_id=preset.id,
            team_slot_id=slot.id, updated_at=datetime.utcnow() + timedelta(seconds=1)))
    await db.commit()
    entries = await activity._team_inputs(db, preset.id)
    assert len(entries) == 1
    assert bool(entries[0][3]) is (invalid is None)


@pytest.mark.asyncio
async def test_team_binding_is_checked_after_native_observation(native, monkeypatch):
    entries = [(2, "pi-cli", None, [activity.ActivityBinding(native["pane_pid"], native["pane_start"],
        str(native["cwd"]), native["native_pid"], native["now"] - timedelta(seconds=5))], False)]
    calls = 0
    async def inputs(db, preset):
        nonlocal calls
        calls += 1
        return entries if calls == 1 else []
    monkeypatch.setattr(activity, "_team_inputs", inputs)
    result = await activity.observe_team(None, 1)
    assert result.slots[0].state == "unknown"
    assert result.slots[0].reason == "binding_changed"
    assert result.slots[0].observed_at is None


def test_pi_refused_sibling_cannot_supply_current_owners_activity(native):
    sibling_pid = 50020
    native["process"](sibling_pid, native["pane_pid"], "1002")
    native["value"]["native"] = {"pid": sibling_pid, "start": "1002"}
    native["write"]()
    result = native["observe"]()
    assert (result.state, result.reason) == ("unknown", "native_identity_mismatch")


def test_pi_dead_auxiliary_session_does_not_hide_live_owner(native):
    owner = activity.ActivityBinding(native["pane_pid"], native["pane_start"], str(native["cwd"]),
        native["native_pid"], native["now"] - timedelta(seconds=5))
    dead = activity.ActivityBinding(native["pane_pid"], native["pane_start"], "/fixture-other-cwd",
        99999, native["now"] - timedelta(seconds=5))
    assert native["observe"](candidates=[owner, dead]).state == "working"


def test_pi_multiple_live_authenticated_native_processes_remain_unknown(native):
    sibling_pid = 50020
    native["process"](sibling_pid, native["pane_pid"], "1002")
    candidates = [activity.ActivityBinding(native["pane_pid"], native["pane_start"], str(native["cwd"]),
        pid, native["now"] - timedelta(seconds=5)) for pid in (native["native_pid"], sibling_pid)]
    assert native["observe"](candidates=candidates).reason == "ambiguous_binding"


def test_pi_reused_native_pid_after_registration_is_rejected(native, monkeypatch):
    monkeypatch.setattr(activity, "_process_started_at", lambda start: native["now"])
    assert native["observe"]().state != "working"


def test_pi_missing_authenticated_native_identity_is_unknown(native):
    binding = activity.ActivityBinding(native["pane_pid"], native["pane_start"], str(native["cwd"]))
    assert native["observe"](candidates=[binding]).reason == "native_identity_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, "ui_prompt_end", "agent_settled"])
async def test_private_pi_settlement_requires_explicit_sdk_provenance(native, monkeypatch, source):
    event_id = str(uuid4())
    native["value"].update(state="idle", reason="native_turn_completed", event_id=event_id)
    if source:
        native["value"]["event_source"] = source
    native["write"]()
    entries = [(2, "pi-cli", None, [activity.ActivityBinding(native["pane_pid"], native["pane_start"],
        str(native["cwd"]), native["native_pid"], native["now"] - timedelta(seconds=5))], False)]
    from unittest.mock import AsyncMock
    monkeypatch.setattr(activity, "_team_inputs", AsyncMock(return_value=entries))
    private = (await activity.observe_private_team(None, 1))[2]
    assert private.identity and private.state == "idle"
    assert private.settlement_id == (event_id if source == "agent_settled" else None)
    assert "event_id" not in native["observe"]().model_dump()


def test_codex_settlement_cursor_contains_no_reply_or_tool_data(native):
    session_id = str(uuid4())
    timestamp = (native["now"] - timedelta(seconds=1)).isoformat()
    native["log"].write_text(json.dumps({"type": "session_meta", "payload": {
        "id": session_id, "cwd": str(native["cwd"])}}) + "\n" + json.dumps({
        "type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "Private fixture reply"},
        "timestamp": timestamp}) + "\n")
    metadata = {}
    result = activity._native_state(native["log"], session_id, str(native["cwd"]),
        native["now"], native["now"] - timedelta(seconds=10), provenance=metadata)
    assert result[1] == "native_turn_completed" and metadata["event_source"] == "task_complete"
    assert len(metadata["event_id"]) == 64
    assert "Private fixture reply" not in json.dumps(metadata)


def test_stale_codex_turn_retains_private_identity_without_activity_or_settlement(native):
    session_id = str(uuid4())
    native["log"].write_text(json.dumps({"type": "session_meta", "payload": {
        "id": session_id, "cwd": str(native["cwd"])}}) + "\n" + json.dumps({
        "type": "event_msg", "payload": {"type": "task_started"},
        "timestamp": (native["now"] - timedelta(seconds=181)).isoformat()}) + "\n")
    metadata = {}
    result = activity._native_state(native["log"], session_id, str(native["cwd"]),
        native["now"], native["now"] - timedelta(seconds=300), provenance=metadata)
    assert result[:2] == ("unknown", "native_event_stale")
    assert metadata["session_id"] == session_id and len(metadata["event_id"]) == 64
    assert "event_source" not in metadata and "current_settlement_id" not in metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "reason", "source"), [
    ("working", "native_turn_started", "agent_start"),
    ("idle", "native_turn_completed", "agent_settled"),
])
async def test_stale_pi_event_retains_private_identity_without_settlement(native, monkeypatch, state, reason, source):
    from unittest.mock import AsyncMock
    event_id = str(uuid4())
    native["value"].update(state=state, reason=reason, event_id=event_id, event_source=source,
        observed_at=(native["now"] - timedelta(seconds=181)).isoformat())
    native["write"]()
    monkeypatch.setattr(activity, "_process_started_at", lambda _: native["now"] - timedelta(seconds=300))
    entries = [(2, "pi-cli", None, [activity.ActivityBinding(native["pane_pid"], native["pane_start"],
        str(native["cwd"]), native["native_pid"], native["now"] - timedelta(seconds=250))], False)]
    monkeypatch.setattr(activity, "_team_inputs", AsyncMock(return_value=entries))
    private = (await activity.observe_private_team(None, 1))[2]
    assert private.identity and private.cursor == event_id
    assert (private.state, private.reason) == ("unknown", "native_event_stale")
    assert private.settlement_id is None and private.current_settlement_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("attestation", ["fresh", "expired", "future", "before_event", "heartbeat"])
async def test_sdk_idle_attestation_keeps_old_debt_current_without_creating_new_event(native, monkeypatch, attestation):
    from unittest.mock import AsyncMock
    event_id = str(uuid4())
    native["value"].update(state="idle", reason="native_turn_completed", event_id=event_id,
        event_source="agent_settled", observed_at=(native["now"] - timedelta(seconds=600)).isoformat(),
        attested_at=native["now"].isoformat(), attestation_source="sdk_idle")
    if attestation == "expired": native["value"]["attested_at"] = (native["now"] - timedelta(seconds=31)).isoformat()
    elif attestation == "future": native["value"]["attested_at"] = (native["now"] + timedelta(seconds=10)).isoformat()
    elif attestation == "before_event": native["value"]["attested_at"] = (native["now"] - timedelta(seconds=601)).isoformat()
    elif attestation == "heartbeat": native["value"]["attestation_source"] = "mail_heartbeat"
    native["write"]()
    monkeypatch.setattr(activity, "_process_started_at", lambda _: native["now"] - timedelta(seconds=700))
    entries = [(2, "pi-cli", None, [activity.ActivityBinding(native["pane_pid"], native["pane_start"],
        str(native["cwd"]), native["native_pid"], native["now"] - timedelta(seconds=650))], False)]
    monkeypatch.setattr(activity, "_team_inputs", AsyncMock(return_value=entries))
    private = (await activity.observe_private_team(None, 1))[2]
    assert private.settlement_id is None  # An old event cannot create a new trigger.
    assert private.current_settlement_id == (event_id if attestation == "fresh" else None)
    assert private.state == ("idle" if attestation == "fresh" else "unknown")
