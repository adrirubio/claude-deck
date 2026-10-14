from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.muse_activity_service import discover_muse_session, muse_state_from_lines

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "muse_sessions"
SID = "01a13be9-b3fa-79f3-941d-e49637f03184"
CWD = "/tmp/muse-fixture-ws"
NOW = datetime(2026, 10, 14, 17, 50, tzinfo=timezone.utc)
START = NOW - timedelta(hours=1)


def state(name, **kwargs):
    lines = (FIX / f"{name}.jsonl").read_bytes().splitlines(keepends=True)
    values = {"session_id": SID, "cwd": CWD, "now": NOW, "started_at": START, **kwargs}
    return muse_state_from_lines(lines, **values)[:2]


@pytest.mark.parametrize("name,expected", [
    ("turn_completed", ("idle", "native_turn_completed")),
    ("tool_turn_working", ("working", "native_progress")),
    ("question_waiting", ("waiting_input", "native_question_open")),
])
def test_states(name, expected):
    assert state(name) == expected


def test_answered_question_is_not_waiting():
    assert state("question_answered")[0] == "idle"


def test_wrong_session_or_workspace_is_a_mismatch():
    assert state("turn_completed", session_id="01a13be9-0000-7000-8000-000000000000")[1] == "session_mismatch"
    assert state("turn_completed", cwd="/elsewhere")[1] == "session_mismatch"


def test_events_before_process_start_are_ignored():
    assert state("turn_completed", started_at=NOW - timedelta(seconds=1))[0] == "unknown"


def test_partial_last_line_is_incomplete():
    lines = (FIX / "turn_completed.jsonl").read_bytes().splitlines(keepends=True)
    lines[-1] = lines[-1].rstrip(b"\n")[:-5]
    assert muse_state_from_lines(lines, SID, CWD, NOW, START)[:2] == ("unknown", "observation_incomplete")


def test_discovery_uses_this_process_lock_only(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions" / "2026" / "10" / "14"
    for sid in (SID, "01a13be9-ffff-7fff-bfff-ffffffffffff"):
        folder = sessions / sid
        folder.mkdir(parents=True)
        (folder / ".session.lock").write_text("")
        text = (FIX / "turn_completed.jsonl").read_text()
        (folder / "session.jsonl").write_text(text.replace(SID, sid))
    monkeypatch.setenv("MUSE_DATA_DIR", str(tmp_path))
    fds = tmp_path / "fd"
    fds.mkdir()
    (fds / "7").symlink_to(sessions / SID / ".session.lock")
    import app.services.muse_activity_service as m
    monkeypatch.setattr(m, "_process_fd_dir", lambda pid: fds)
    assert discover_muse_session(123, CWD) == SID


def test_answered_question_mid_turn_is_working_not_waiting():
    # The turn goes on after the answer; only the settle event can clear the question.
    lines = (FIX / "question_answered.jsonl").read_bytes().splitlines(keepends=True)
    settled = next(i for i, line in enumerate(lines) if b"user_input_prompt_settled" in line)
    assert muse_state_from_lines(lines[:settled + 2], SID, CWD, NOW, START)[:2] == ("working", "native_progress")
    assert muse_state_from_lines(lines[:settled], SID, CWD, NOW, START)[:2] == ("waiting_input", "native_question_open")


def _dispatch(monkeypatch, session_id, observed=None, discovered=None):
    from app.services import agent_activity_service as activity
    monkeypatch.setattr(activity, "_process", lambda _: ("S", "27"))
    monkeypatch.setattr(activity, "discover_muse_session", lambda pid, cwd: discovered)
    monkeypatch.setattr(activity, "observe_muse", lambda *args, **kwargs: observed)
    binding = activity.ActivityBinding(41000, "27", CWD, tmux_target="%8", binding_id=1)
    metadata = {}
    result = activity._observe(1, "muse-cli", session_id, [binding], False, datetime.now(timezone.utc),
                               provenance=metadata)
    return result, metadata


def test_first_launch_discovers_the_session_and_asks_for_resume(monkeypatch):
    result, metadata = _dispatch(monkeypatch, None, discovered=SID)
    assert (result.state, result.reason) == ("unknown", "restart_needed_for_observation")
    assert metadata["discovered_session_id"] == SID


def test_no_discoverable_session_is_unknown(monkeypatch):
    result, metadata = _dispatch(monkeypatch, None, discovered=None)
    assert result.reason == "session_identity_unavailable" and "discovered_session_id" not in metadata


def test_open_question_becomes_a_bound_wait(monkeypatch):
    result, metadata = _dispatch(monkeypatch, SID, observed=("waiting_input", "native_question_open", None))
    assert result.waiting_input is not None and result.waiting_input.reason == "question"
    assert (result.state, result.reason) == ("idle", "native_input_wait")
    assert metadata["input_wait_reason"] == "question" and metadata["input_wait_binding_id"] == 1


def test_a_finished_turn_clears_the_wait(monkeypatch):
    result, metadata = _dispatch(monkeypatch, SID, observed=("idle", "native_turn_completed", None))
    assert result.waiting_input is None and result.state == "idle"
    assert metadata["input_wait_reason"] == "clear"


@pytest.mark.asyncio
async def test_discovered_muse_identity_switches_the_slot_to_resume(db):
    from app.models.database import AgentTeamPreset, AgentTeamSlot
    from app.services import agent_activity_service as activity
    preset = AgentTeamPreset(name="muse team")
    db.add(preset)
    await db.flush()
    slots = [AgentTeamSlot(preset_id=preset.id, position=i, display_name=f"M{i}", provider="muse-cli",
                           repo_id=f"r{i}", repo_path=f"/w{i}", repo_name=f"w{i}", launch_mode="plain",
                           launch_options={"model": "muse-wonder-1.0"}) for i in (1, 2)]
    db.add_all(slots)
    await db.commit()
    first, second = ((slot.id, "muse-cli", None) for slot in slots)
    current = {first[0]: first, second[0]: second}
    assert await activity._save_codex_identities(db, [first], [{"discovered_session_id": SID}], current)
    await db.refresh(slots[0])
    assert slots[0].launch_mode == "resume"
    assert slots[0].launch_options == {"model": "muse-wonder-1.0", "session_id": SID, "use_last": False}
    # The same id cannot be bound to a second slot.
    assert not await activity._save_codex_identities(db, [second], [{"discovered_session_id": SID}], current)
    await db.refresh(slots[1])
    assert slots[1].launch_mode == "plain" and "session_id" not in slots[1].launch_options


def test_a_log_larger_than_the_tail_keeps_its_binding(tmp_path):
    # The metadata and opened records are written once, at the head; a long session pushes them out of the tail.
    import json
    import os
    import app.services.muse_activity_service as m

    lines = (FIX / "turn_completed.jsonl").read_bytes().splitlines(keepends=True)
    started = next(i for i, line in enumerate(lines) if b'"prompt"' in line)
    filler = json.loads(lines[started])
    filler["payload"]["event"] = {"kind": "output", "text": "x" * 4096}
    filler_line = (json.dumps(filler) + "\n").encode()
    count = m._TAIL_BYTES // len(filler_line) + 10
    path = tmp_path / "session.jsonl"
    path.write_bytes(b"".join(lines[:started]) + filler_line * count + b"".join(lines[started:]))

    tail, _offset, failure = m._read_lines(path, os.getuid())

    assert failure is None
    assert muse_state_from_lines(tail, SID, CWD, NOW, START)[:2] == ("idle", "native_turn_completed")


def test_an_out_of_range_timestamp_is_invalid_not_an_error():
    import json

    lines = (FIX / "turn_completed.jsonl").read_bytes().splitlines(keepends=True)
    row = json.loads(lines[-1])
    row["recorded_at"] = 10**25
    lines[-1] = (json.dumps(row) + "\n").encode()
    with pytest.raises(ValueError):
        muse_state_from_lines(lines, SID, CWD, NOW, START)
