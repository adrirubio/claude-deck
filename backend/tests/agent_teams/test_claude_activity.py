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
