"""Claude native activity fixtures. No harness, credentials, or live database."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services import agent_activity_service as activity
from app.services import claude_activity_service as claude
from app.utils.path_utils import convert_path_to_folder_name


@pytest.fixture
def native(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    cwd = tmp_path / "project"; cwd.mkdir()
    home = tmp_path / "config"
    directory = home / "projects" / convert_path_to_folder_name(str(cwd))
    directory.mkdir(parents=True)
    session = str(uuid4())
    log = directory / (session + ".jsonl")
    proc = tmp_path / "proc"; (proc / "50").mkdir(parents=True)
    (proc / "50" / "cmdline").write_bytes(b"claude\0--resume\0" + session.encode() + b"\0")
    monkeypatch.setattr(claude, "_PROC", proc)
    monkeypatch.setattr(claude, "_home", lambda pid: home)
    monkeypatch.setattr(activity, "_process", lambda pid: ("S", "1000"))
    monkeypatch.setattr(activity, "_process_started_at", lambda start: now - timedelta(seconds=10))

    def row(kind, seconds, **values):
        return {"type": kind, "uuid": str(uuid4()), "sessionId": session,
                "cwd": str(cwd), "isSidechain": False,
                "timestamp": (now + timedelta(seconds=seconds)).isoformat(), **values}
    user = row("user", -4, message={"role": "user", "content": "Complete the assigned fixture."})
    tool = row("assistant", -3, message={"role": "assistant", "stop_reason": "tool_use"})
    result = row("user", -2, message={"role": "user", "content": [{"type": "tool_result"}]})
    end = row("assistant", -1, message={"role": "assistant", "stop_reason": "end_turn"})
    duration = row("system", -.5, subtype="turn_duration", parentUuid=end["uuid"])
    records = [user, tool, result, end, duration]
    def write(rows=None):
        log.write_text("".join(json.dumps(r) + "\n" for r in (records if rows is None else rows)))
    def observe(identity=session, duplicate=False, provenance=None):
        return activity._observe(2, "claude-code", identity,
            [activity.ActivityBinding(50, "1000", str(cwd))], duplicate, now, provenance=provenance)
    write()
    return locals()


@pytest.mark.parametrize("count,expected", [(1,"working"),(2,"working"),(3,"working"),(4,"idle"),(5,"idle")])
def test_claude_main_turn_boundaries(native, count, expected):
    native["write"](native["records"][:count])
    result = native["observe"]()
    assert result.state == expected
    assert set(result.model_dump()) == {"slot_id", "state", "reason", "observed_at"}
    assert str(native["cwd"]) not in result.model_dump_json()


def test_claude_duration_deduplicates_completion(native):
    first, second = {}, {}
    native["write"](native["records"][:4]); a = native["observe"](provenance=first)
    native["write"](); b = native["observe"](provenance=second)
    assert a.observed_at == b.observed_at
    assert first["event_id"] == second["event_id"]
    assert second["event_source"] == "claude_end_turn"


@pytest.mark.parametrize("field,value", [("sessionId",str(uuid4())),("cwd","/different"),("timestamp","2099-01-01T00:00:00Z")])
def test_claude_invalid_record_is_unknown(native, field, value):
    native["end"][field] = value; native["write"]()
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("argv", [b"claude\0prompt UUID\0",b"node\0--resume\0UUID\0",b"claude\0--resume\0other\0",b"claude\0--\0--resume\0UUID\0"])
def test_claude_uuid_must_be_bound_as_an_option(native, argv):
    (native["proc"] / "50" / "cmdline").write_bytes(argv.replace(b"UUID",native["session"].encode()))
    assert native["observe"]().reason == "session_mismatch"


def test_claude_duplicate_and_missing_identity_are_unknown(native):
    assert native["observe"](duplicate=True).reason == "duplicate_native_identity"
    assert native["observe"](identity=None).reason == "session_identity_unavailable"


def test_claude_inherited_completion_is_not_current(native):
    for row in native["records"]:
        row["timestamp"] = (native["now"] - timedelta(seconds=100)).isoformat()
    native["write"]()
    assert native["observe"]().state == "unknown"


def test_claude_stale_working_is_unknown(native):
    native["user"]["timestamp"] = (native["now"] - timedelta(seconds=200)).isoformat()
    native["write"]([native["user"]])
    # The current process predates the stale turn.
    from unittest.mock import patch
    with patch.object(activity,"_process_started_at",return_value=native["now"] - timedelta(seconds=300)):
        assert native["observe"]().reason == "native_event_stale"


@pytest.mark.parametrize("flag",["isSidechain","isReplay"])
def test_claude_other_completion_cannot_settle_main_turn(native, flag):
    native["end"][flag] = True
    native["write"](native["records"][:4])
    assert native["observe"]().state == "working"


def test_claude_new_turn_invalidates_prior_completion(native):
    native["write"](native["records"]+[native["row"]("user",0,message={"role":"user","content":"Next fixture."})])
    assert native["observe"]().state == "working"


def test_claude_unsupported_system_event_invalidates_prior_completion(native):
    native["write"](native["records"]+[native["row"]("system",0,subtype="input_requested")])
    metadata = {}; result = native["observe"](provenance=metadata)
    assert result.state == "unknown" and metadata.get("event_source") is None


def test_claude_tool_result_without_start_does_not_settle(native):
    native["write"]([native["result"],native["end"],native["duration"]])
    assert native["observe"]().state == "unknown"


def test_claude_interruption_is_not_successful_completion(native):
    native["write"]([native["user"],native["row"]("user",0,message={"role":"user","content":"[Request interrupted by user]"})])
    metadata = {}; result = native["observe"](provenance=metadata)
    assert result.reason == "native_turn_interrupted" and metadata.get("event_source") is None


def test_claude_partial_record_is_unknown(native):
    native["log"].write_text(native["log"].read_text().rstrip("\n"))
    assert native["observe"]().reason == "observation_incomplete"


def test_claude_world_writable_log_is_unknown(native):
    native["log"].chmod(0o666)
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("count,state", [(3, "working"), (5, "idle")])
def test_claude_workspace_subdirectory_keeps_main_turn(native, count, state):
    backend = native["cwd"] / "backend"
    backend.mkdir()
    for row in native["records"][1:4]:
        row["cwd"] = str(backend)
    native["write"](native["records"][:count])
    assert native["observe"]().state == state


def test_claude_relative_cwd_is_not_bound_to_workspace(native):
    native["end"]["cwd"] = "backend"
    native["write"]()
    assert native["observe"]().state == "unknown"


def test_claude_subdirectory_symlink_outside_workspace_is_unknown(native):
    outside = native["cwd"].parent / "outside"
    outside.mkdir()
    link = native["cwd"] / "linked"
    link.symlink_to(outside, target_is_directory=True)
    native["end"]["cwd"] = str(link)
    native["write"]()
    assert native["observe"]().state == "unknown"


def _long_turn(native, *, completed=False):
    result = dict(native["result"])
    result["message"] = {"role": "user", "content": [
        {"type": "tool_result", "content": "x" * (2 * claude._TAIL_BYTES)},
    ]}
    rows = [native["user"], native["tool"], result]
    if completed:
        rows += [native["end"], native["duration"]]
    else:
        rows.append(native["row"]("assistant", -1,
                    message={"role": "assistant", "stop_reason": "tool_use"}))
    native["write"](rows)
    return rows


@pytest.mark.parametrize("completed,state", [(False, "working"), (True, "idle")])
def test_claude_long_turn_keeps_proven_start(native, completed, state):
    _long_turn(native, completed=completed)
    assert native["log"].stat().st_size > claude._TAIL_BYTES
    metadata = {}
    result = native["observe"](provenance=metadata)
    assert result.state == state
    if completed:
        assert result.reason == "native_turn_completed"
        assert metadata["event_source"] == "claude_end_turn"
    else:
        assert result.reason == "native_progress"
        assert metadata.get("event_source") is None


@pytest.mark.parametrize("field,value", [
    ("sessionId", str(uuid4())), ("cwd", "/different"),
    ("timestamp", "2099-01-01T00:00:00Z"),
])
def test_claude_lookback_start_must_keep_its_binding(native, field, value):
    native["user"][field] = value
    _long_turn(native)
    assert native["observe"]().state == "unknown"


@pytest.mark.parametrize("flag", ["isSidechain", "isReplay"])
def test_claude_lookback_cannot_use_other_turn_start(native, flag):
    native["user"][flag] = True
    _long_turn(native, completed=True)
    metadata = {}
    assert native["observe"](provenance=metadata).state == "unknown"
    assert metadata.get("event_source") is None


def test_claude_lookback_does_not_cross_unsupported_event(native):
    rows = _long_turn(native)
    rows.insert(1, native["row"]("system", -3.5, subtype="input_requested"))
    native["write"](rows)
    assert native["observe"]().state == "unknown"


def test_claude_lookback_does_not_accept_stale_progress(native, monkeypatch):
    rows = _long_turn(native)
    for row in rows:
        row["timestamp"] = (native["now"] - timedelta(seconds=200)).isoformat()
    native["write"](rows)
    monkeypatch.setattr(activity, "_process_started_at",
                        lambda start: native["now"] - timedelta(seconds=300))
    assert native["observe"]().reason == "native_event_stale"


def _track_reads(monkeypatch, callback=None):
    original = claude.os.fdopen
    reads = []

    class TrackedStream:
        def __init__(self, *args, **kwargs):
            self.stream = original(*args, **kwargs)

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def seek(self, offset):
            return self.stream.seek(offset)

        def read(self, size):
            value = self.stream.read(size)
            reads.append(len(value))
            if callback:
                callback(len(reads))
            return value

    monkeypatch.setattr(claude.os, "fdopen", TrackedStream)
    return reads


def test_claude_lookback_byte_budget_stays_unknown(native, monkeypatch):
    monkeypatch.setattr(claude, "_TAIL_BYTES", 512)
    monkeypatch.setattr(claude, "_MAX_HISTORY_BYTES", 4096)
    result = dict(native["result"])
    result["message"] = {"role": "user", "content": [
        {"type": "tool_result", "content": "x" * 8192},
    ]}
    native["write"]([native["user"], native["tool"], result,
                     native["end"], native["duration"]])
    reads = _track_reads(monkeypatch)
    metadata = {}
    observed = native["observe"](provenance=metadata)
    assert observed.state == "unknown" and observed.reason == "native_history_limit"
    assert sum(reads) == claude._MAX_HISTORY_BYTES
    assert len(reads) <= 8
    assert metadata.get("event_source") is None


def test_claude_file_change_during_lookback_is_unknown(native, monkeypatch):
    _long_turn(native)

    def change_on_second_read(count):
        if count == 2:
            with native["log"].open("a") as stream:
                stream.write(json.dumps(native["row"]("user", 0,
                    message={"role": "user", "content": "Next fixture."})) + "\n")

    reads = _track_reads(monkeypatch, change_on_second_read)
    assert native["observe"]().reason == "binding_changed"
    assert len(reads) > 1


@pytest.mark.parametrize("completed,state", [(False, "working"), (True, "idle")])
def test_claude_prior_turn_order_does_not_poison_new_turn(native, completed, state):
    earlier_prompt = native["row"]("user", -8,
        message={"role": "user", "content": "Earlier fixture."})
    earlier_tool = native["row"]("assistant", -6,
        message={"role": "assistant", "stop_reason": "tool_use"})
    earlier_result = native["row"]("user", -7,
        message={"role": "user", "content": [{"type": "tool_result"}]})
    earlier_end = native["row"]("assistant", -5,
        message={"role": "assistant", "stop_reason": "end_turn"})
    current = native["records"] if completed else native["records"][:3]
    native["write"]([earlier_prompt, earlier_tool, earlier_result, earlier_end] + current)
    assert native["observe"]().state == state


def test_claude_current_turn_order_still_refuses(native):
    native["result"]["timestamp"] = native["user"]["timestamp"]
    native["write"]()
    assert native["observe"]().reason == "observation_invalid"


def test_claude_latest_mismatched_prompt_does_not_reuse_prior_turn(native):
    prompt = native["row"]("user", 0, sessionId=str(uuid4()),
        message={"role": "user", "content": "Other fixture."})
    native["write"](native["records"] + [prompt])
    metadata = {}
    assert native["observe"](provenance=metadata).reason == "session_mismatch"
    assert metadata.get("event_source") is None
