"""The team-supervisor guard reads Claude Code and Codex transcripts.

Record shapes are taken from real Codex 0.159 rollouts and Claude Code 2.1
transcripts on the factory host. The guard stops a team on a provider safety
notice in the agent's own output, never on quoted user input or tool output.
"""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "product-factory" / "team-supervisor"
NOTICE = "This content was flagged for possible cybersecurity risk."


def _load():
    loader = importlib.machinery.SourceFileLoader("team_supervisor", str(SCRIPT))
    spec = importlib.util.spec_from_loader("team_supervisor", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ts = _load()


def _codex_agent_message(text):
    return {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "AgentMessage", "id": "m1", "phase": "final", "content": [{"type": "Text", "text": text}]}}}


def test_codex_agent_message_notice_is_found():
    assert ts.notice(_codex_agent_message(NOTICE)) == "cybersecurity_notice"


def test_codex_assistant_response_item_notice_is_found():
    record = {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                   "content": [{"type": "output_text", "text": NOTICE}]}}
    assert ts.notice(record) == "cybersecurity_notice"


def test_codex_error_event_code_is_found():
    record = {"type": "event_msg", "payload": {"type": "error", "message": "request failed: cybersecurity_blocked"}}
    assert ts.notice(record) == "cybersecurity_blocked"


@pytest.mark.parametrize("record", [
    {"type": "response_item", "payload": {"type": "message", "role": "user",
                                          "content": [{"type": "input_text", "text": NOTICE}]}},
    {"type": "response_item", "payload": {"type": "custom_tool_call_output", "output": NOTICE}},
    {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "CommandExecution", "aggregated_output": NOTICE}}},
    {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "UserMessage", "content": [{"type": "Text", "text": NOTICE}]}}},
], ids=["user_input", "tool_output", "command_output", "user_item"])
def test_quoted_or_tool_text_never_creates_a_hold(record):
    assert ts.notice(record) is None


def test_claude_assistant_notice_is_unchanged():
    record = {"type": "assistant", "message": {"content": [{"type": "text", "text": NOTICE}]}}
    assert ts.notice(record) == "cybersecurity_notice"


def _supervisor(tmp_path, **extra):
    config = {
        "state_path": str(tmp_path / "state.json"), "hold_path": str(tmp_path / "HOLD.json"),
        "native_project_root": str(tmp_path / "claude-projects"), "codex_sessions_root": str(tmp_path / "codex-sessions"),
        "preset_id": 3, "slot_ids": [1, 2, 3], "scope_ids": [4], **extra,
    }
    return ts.Supervisor(config)


SESSION = "01a13115-7287-73b1-a44f-c5609e22ae2d"


def test_codex_rollout_is_found_in_its_date_folder_and_cached(tmp_path):
    rollout = tmp_path / "codex-sessions" / "2026" / "10" / "12" / f"rollout-2026-10-12T19-07-31-{SESSION}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("")
    sup = _supervisor(tmp_path)

    assert sup.transcript("codex-cli", "/w/backend", SESSION) == rollout
    assert sup.state["native_paths"][SESSION] == str(rollout)


def test_codex_rollout_missing_or_ambiguous_fails_closed(tmp_path):
    sup = _supervisor(tmp_path)
    (tmp_path / "codex-sessions").mkdir()
    with pytest.raises(FileNotFoundError, match="native_transcript_missing"):
        sup.transcript("codex-cli", "/w/backend", SESSION)
    for day in ("12", "13"):
        path = tmp_path / "codex-sessions" / "2026" / "10" / day / f"rollout-x-{SESSION}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    with pytest.raises(FileNotFoundError, match="native_transcript_ambiguous"):
        sup.transcript("codex-cli", "/w/backend", SESSION)


def test_claude_transcript_path_is_unchanged(tmp_path):
    path = tmp_path / "claude-projects" / "-w-leader" / f"{SESSION}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("")
    assert _supervisor(tmp_path).transcript("claude-code", "/w/leader", SESSION) == path


def test_unsupported_provider_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="native_provider_unsupported"):
        _supervisor(tmp_path).transcript("pi-cli", "/w/x", SESSION)


def _tick(tmp_path, monkeypatch, **extra):
    sup = _supervisor(tmp_path, **extra)
    stopped = []
    preset = {"autonomy_enabled": True, "slots": [{"id": i, "enabled": True} for i in (1, 2, 3)]}
    members = [{"team_preset_id": 3, "team_slot_id": i, "status": "connected", "wake_state": "wakeable"} for i in (1, 2)]

    def api(method, path, body=None):
        return {"members": members} if path.startswith("/agent-mail/team") else preset

    monkeypatch.setattr(sup, "api", api)
    monkeypatch.setattr(sup, "bindings", lambda: [])
    monkeypatch.setattr(sup, "stop", lambda reason, **kw: stopped.append(reason))
    for _ in range(3):
        sup.tick()
    return sup, stopped


def test_a_stopped_on_demand_slot_is_not_a_missing_member(tmp_path, monkeypatch):
    sup, stopped = _tick(tmp_path, monkeypatch, on_demand_slot_ids=[3])
    assert stopped == []
    assert sup.state["missing_slots"] == []
    assert json.loads(Path(sup.state_path).read_text())["mode"] == "SUPERVISING"


def test_a_missing_required_member_still_stops_the_team(tmp_path, monkeypatch):
    _, stopped = _tick(tmp_path, monkeypatch)
    assert stopped == ["authenticated_member_missing"]
