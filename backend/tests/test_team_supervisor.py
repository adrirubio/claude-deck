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


def test_a_second_rollout_after_caching_is_still_ambiguous(tmp_path):
    first = tmp_path / "codex-sessions" / "2026" / "10" / "12" / f"rollout-a-{SESSION}.jsonl"
    first.parent.mkdir(parents=True)
    first.write_text("")
    sup = _supervisor(tmp_path)
    assert sup.transcript("codex-cli", "/w/backend", SESSION) == first

    second = tmp_path / "codex-sessions" / "2026" / "10" / "13" / f"rollout-b-{SESSION}.jsonl"
    second.parent.mkdir(parents=True)
    second.write_text(json.dumps(_codex_agent_message(NOTICE)) + "\n")
    with pytest.raises(FileNotFoundError, match="native_transcript_ambiguous"):
        sup.transcript("codex-cli", "/w/backend", SESSION)


@pytest.mark.parametrize("seed", ["0", "1", "2", "3", "4", "5"])
def test_error_code_matching_does_not_depend_on_hash_order(seed):
    import subprocess, sys
    code = (
        "import importlib.machinery as m, importlib.util as u;"
        f"l=m.SourceFileLoader('t', {str(SCRIPT)!r}); s=u.spec_from_loader('t', l); t=u.module_from_spec(s); l.exec_module(t);"
        "print(t.notice({'type':'event_msg','payload':{'type':'error','message':'request failed: cybersecurity_blocked'}}))"
    )
    out = subprocess.run([sys.executable, "-c", code], env={"PYTHONHASHSEED": seed}, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "cybersecurity_blocked"


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


def _scan_file(tmp_path, monkeypatch, lines, **extra):
    path = tmp_path / "claude-projects" / "-w-leader" / f"{SESSION}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"".join(lines))
    sup = _supervisor(tmp_path, **extra)
    stopped = []
    monkeypatch.setattr(sup, "stop", lambda reason, **kw: stopped.append(kw.get("rule")))
    binding = {"provider": "claude-code", "repo_path": "/w/leader", "launch_options": json.dumps({"session_id": SESSION})}
    return sup, sup.scan([binding]), stopped


CRASH = b"\x00" * 600
SNAPSHOT = json.dumps({"type": "file-history-snapshot", "messageId": "m"}).encode()
NOTICE_LINE = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": NOTICE}]}}).encode()


def test_crash_padding_before_a_valid_record_is_inspected(tmp_path, monkeypatch):
    sup, ok, stopped = _scan_file(tmp_path, monkeypatch, [SNAPSHOT + b"\n", CRASH + NOTICE_LINE + b"\n"])
    assert ok is False and stopped == ["cybersecurity_notice"]
    assert sup.state["damaged_records_seen"] == 1


def test_a_line_of_only_crash_padding_is_skipped(tmp_path, monkeypatch):
    sup, ok, stopped = _scan_file(tmp_path, monkeypatch, [CRASH + b"\n", SNAPSHOT + b"\n"])
    assert ok is True and stopped == []


def test_a_damaged_fragment_fails_closed(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="native_record_damaged"):
        _scan_file(tmp_path, monkeypatch, [CRASH + b'"messageId": "frag"}' + b"\n"])


def test_an_acknowledged_damaged_fragment_is_skipped(tmp_path, monkeypatch):
    import hashlib
    line = CRASH + b'"messageId": "frag"}' + b"\n"
    sup, ok, stopped = _scan_file(tmp_path, monkeypatch, [line, SNAPSHOT + b"\n"],
                                  acknowledged_damaged_records=[hashlib.sha256(line).hexdigest()])
    assert ok is True and stopped == []


@pytest.mark.parametrize("line", [b"null\n", CRASH + b"null\n", b"[1]\n"], ids=["null", "padded_null", "list"])
def test_a_record_that_is_not_an_object_fails_closed(tmp_path, monkeypatch, line):
    with pytest.raises(ValueError, match="native_record_not_object"):
        _scan_file(tmp_path, monkeypatch, [line])


def _muse(kind, **event):
    return {"payload_type": "runtime.session", "stream": {"kind": "session", "id": SESSION},
            "payload": {"kind": "session", "event": {"kind": kind, **event}}}


def test_muse_agent_reply_notice_is_found():
    assert ts.notice(_muse("assistant_message_committed", text=NOTICE)) == "cybersecurity_notice"


@pytest.mark.parametrize("record", [
    _muse("started", prompt=NOTICE),
    _muse("tool_result_batch_committed", results=[{"output": NOTICE}]),
    _muse("output", final_result={"text": NOTICE}),
    _muse("reasoning_committed", text=NOTICE),
], ids=["user_prompt", "tool_result", "task_output", "reasoning"])
def test_muse_quoted_or_tool_text_never_creates_a_hold(record):
    assert ts.notice(record) is None


def test_muse_error_event_code_is_found():
    assert ts.notice(_muse("error", message="request failed: cybersecurity_blocked")) == "cybersecurity_blocked"


def test_muse_transcript_is_found_in_its_date_folder(tmp_path):
    path = tmp_path / "muse-sessions" / "2026" / "10" / "14" / SESSION / "session.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("")
    sup = _supervisor(tmp_path, muse_sessions_root=str(tmp_path / "muse-sessions"))
    assert sup.transcript("muse-cli", "/w/research", SESSION) == path


def test_muse_transcript_missing_or_ambiguous_fails_closed(tmp_path):
    root = tmp_path / "muse-sessions"
    root.mkdir()
    sup = _supervisor(tmp_path, muse_sessions_root=str(root))
    with pytest.raises(FileNotFoundError, match="native_transcript_missing"):
        sup.transcript("muse-cli", "/w/research", SESSION)
    for day in ("13", "14"):
        path = root / "2026" / "10" / day / SESSION / "session.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("")
    with pytest.raises(FileNotFoundError, match="native_transcript_ambiguous"):
        sup.transcript("muse-cli", "/w/research", SESSION)


def test_muse_sessions_root_must_be_configured(tmp_path):
    # The guard runs as root, so a ~ default would point at root's home.
    with pytest.raises(KeyError):
        _supervisor(tmp_path).transcript("muse-cli", "/w/research", SESSION)


# --- OpenCode 2 (#733 guard checkpoint) -------------------------------------
# Schema from pinned anomalyco/opencode fedc6f208aa2bd54c1019227214568083f6380ad
# (v2.2.7): packages/core/src/database/schema.gen.ts. Assistant content is its
# session_part rows by ordinal, then inline data.content (session/history.ts
# L91-122); answer text is {type: "text", text} (schema/session-message.ts L185).
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402

OC_SESSION = "ses_0abcDEF1234567890ghijKLMNo"
OC_REPO = "/w/opencode-member"
OC_DDL = [
    "CREATE TABLE session_v2 (id text PRIMARY KEY, project_id text NOT NULL, slug text NOT NULL, directory text NOT NULL, "
    "version text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, time_busy integer, "
    "time_idle integer, idle_outcome text, time_suspended integer)",
    "CREATE TABLE session_message (id text PRIMARY KEY, session_id text NOT NULL, type text NOT NULL, seq integer NOT NULL, "
    "time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL)",
    "CREATE TABLE session_part (message_id text NOT NULL, session_id text NOT NULL, ordinal integer NOT NULL, "
    "type text NOT NULL, call_id text, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL, "
    "PRIMARY KEY(message_id, ordinal))",
]


def _oc_db(path, *, schema=OC_DDL, directory=OC_REPO, session=OC_SESSION):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        for statement in schema:
            db.execute(statement)
        if session:
            db.execute("INSERT INTO session_v2 (id, project_id, slug, directory, version, time_created, time_updated) "
                       "VALUES (?, 'p', 's', ?, '2.2.7', 1, 1)", (session, directory))
    os.chmod(path, 0o600)
    return path


def _oc_message(path, seq, *, kind="assistant", inline=None, completed=True, parts=()):
    data = {"time": {"created": 1, **({"completed": 2} if completed else {})}}
    if inline is not None:
        data["content"] = inline
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO session_message VALUES (?, ?, ?, ?, 1, 1, ?)",
                   (f"msg{seq}", OC_SESSION, kind, seq, json.dumps(data)))
        for ordinal, (part_type, part) in enumerate(parts):
            db.execute("INSERT INTO session_part VALUES (?, ?, ?, ?, NULL, 1, 1, ?)",
                       (f"msg{seq}", OC_SESSION, ordinal, part_type, part if isinstance(part, str) else json.dumps(part)))


def _oc_supervisor(tmp_path, roots=None, **extra):
    root = tmp_path / "oc-data"
    return _supervisor(tmp_path, opencode_data_roots=[str(r) for r in (roots or [root])], agent_uid=os.getuid(), **extra)


def _oc_scan(sup, monkeypatch, session=OC_SESSION, repo=OC_REPO):
    stopped = []
    monkeypatch.setattr(sup, "stop", lambda reason, **kw: stopped.append(kw.get("rule")))
    binding = {"provider": "opencode-cli", "repo_path": repo, "launch_options": json.dumps({"session_id": session})}
    return sup.scan([binding]), stopped


def _text(text):
    return ("text", {"type": "text", "text": text})


def test_opencode_assistant_text_notice_in_a_part_stops(tmp_path, monkeypatch):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, parts=[_text("hello"), _text(NOTICE)])
    ok, stopped = _oc_scan(_oc_supervisor(tmp_path), monkeypatch)
    assert ok is False and stopped == ["cybersecurity_notice"]


def test_opencode_inline_assistant_text_notice_stops(tmp_path, monkeypatch):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, inline=[{"type": "text", "text": NOTICE}])
    ok, stopped = _oc_scan(_oc_supervisor(tmp_path), monkeypatch)
    assert ok is False and stopped == ["cybersecurity_notice"]


@pytest.mark.parametrize("case", ["reasoning_part", "tool_part", "user_message", "reasoning_inline"])
def test_opencode_reasoning_tool_or_user_text_never_holds(tmp_path, monkeypatch, case):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    if case == "reasoning_part":
        _oc_message(db, 1, parts=[("reasoning", {"type": "reasoning", "text": NOTICE})])
    elif case == "tool_part":
        _oc_message(db, 1, parts=[("tool", {"type": "tool", "state": {"output": NOTICE}})])
    elif case == "user_message":
        _oc_message(db, 1, kind="user", inline=[{"type": "text", "text": NOTICE}])
    else:
        _oc_message(db, 1, inline=[{"type": "reasoning", "text": NOTICE}])
    ok, stopped = _oc_scan(_oc_supervisor(tmp_path), monkeypatch)
    assert ok is True and stopped == []


def test_opencode_updated_or_reopened_message_is_rescanned(tmp_path, monkeypatch):
    # message-updater.ts L93-94 / L220-239 can replace or reopen a completed message
    # without a new seq, so every tick rescans all assistant text.
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, parts=[_text("fine")])
    sup = _oc_supervisor(tmp_path)
    assert _oc_scan(sup, monkeypatch) == (True, [])
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE session_part SET data=? WHERE message_id='msg1'", (json.dumps({"type": "text", "text": NOTICE}),))
        conn.execute("UPDATE session_message SET data=? WHERE id='msg1'", (json.dumps({"time": {"created": 1}}),))
    assert _oc_scan(sup, monkeypatch) == (False, ["cybersecurity_notice"])


def test_opencode_stale_unfinished_row_does_not_hide_later_text(tmp_path, monkeypatch):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, completed=False, parts=[_text("still streaming")])
    for seq in range(2, 62):
        _oc_message(db, seq, parts=[_text(NOTICE if seq == 61 else "ok")])
    assert _oc_scan(_oc_supervisor(tmp_path), monkeypatch) == (False, ["cybersecurity_notice"])


def test_opencode_db_replacement_refuses(tmp_path, monkeypatch):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, parts=[_text("ok")])
    sup = _oc_supervisor(tmp_path)
    assert _oc_scan(sup, monkeypatch) == (True, [])
    copy = tmp_path / "copy.db"
    shutil.copy2(db, copy)
    os.replace(copy, db)  # same content, new inode
    with pytest.raises(ValueError, match="opencode_db_replaced"):
        _oc_scan(sup, monkeypatch)


@pytest.mark.parametrize("case,reason", [
    ("no_db", "opencode_db_missing"),
    ("two_channel_dbs", "opencode_db_ambiguous"),
    ("wrong_directory", "opencode_session_missing"),
    ("two_roots", "opencode_session_ambiguous"),
    ("missing_part_table", "opencode_schema_unsupported"),
    ("not_sqlite", "opencode_db_unsafe_file"),
])
def test_opencode_discovery_refusals(tmp_path, monkeypatch, case, reason):
    root, other = tmp_path / "oc-data", tmp_path / "oc-other"
    roots = [root]
    if case == "no_db":
        root.mkdir()
    elif case == "two_channel_dbs":
        _oc_db(root / "opencode-beta.db")
        _oc_db(root / "opencode-dev.db")
    elif case == "wrong_directory":
        _oc_db(root / "opencode.db", directory="/w/elsewhere")
    elif case == "two_roots":
        _oc_db(root / "opencode.db")
        _oc_db(other / "opencode.db")
        roots = [root, other]
    elif case == "missing_part_table":
        _oc_db(root / "opencode.db", schema=OC_DDL[:2])
    else:
        root.mkdir()
        (root / "opencode.db").write_bytes(b"not a database at all")
        os.chmod(root / "opencode.db", 0o600)
    with pytest.raises(ValueError, match=reason):
        _oc_scan(_oc_supervisor(tmp_path, roots=roots), monkeypatch)


@pytest.mark.parametrize("case", ["symlink", "group_writable", "wrong_owner"])
def test_opencode_unsafe_db_file_refuses(tmp_path, monkeypatch, case):
    root = tmp_path / "oc-data"
    if case == "symlink":
        real = _oc_db(tmp_path / "elsewhere" / "opencode.db")
        root.mkdir()
        (root / "opencode.db").symlink_to(real)
        sup = _oc_supervisor(tmp_path)
    else:
        db = _oc_db(root / "opencode.db")
        if case == "group_writable":
            os.chmod(db, 0o620)
            sup = _oc_supervisor(tmp_path)
        else:
            sup = _supervisor(tmp_path, opencode_data_roots=[str(root)], agent_uid=os.getuid() + 1)
    with pytest.raises(ValueError, match="opencode_db_unsafe_file"):
        _oc_scan(sup, monkeypatch)


@pytest.mark.parametrize("session", ["abc_123", "01a13115-7287-73b1-a44f-c5609e22ae2d", "ses_" + "x" * 200, "ses_a/b"])
def test_opencode_session_id_must_be_an_opencode_id(tmp_path, monkeypatch, session):
    _oc_db(tmp_path / "oc-data" / "opencode.db")
    with pytest.raises(ValueError, match="opencode_session_id_invalid"):
        _oc_scan(_oc_supervisor(tmp_path), monkeypatch, session=session)


def test_opencode_nul_and_multibyte_text_is_scanned(tmp_path, monkeypatch):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, parts=[_text("naïve 日本語 \x00 ok"), _text("ünïcode " + NOTICE)])
    assert _oc_scan(_oc_supervisor(tmp_path), monkeypatch) == (False, ["cybersecurity_notice"])


@pytest.mark.parametrize("case", ["bad_json_part", "non_string_text", "non_object_message", "inline_non_string"])
def test_opencode_malformed_records_refuse(tmp_path, monkeypatch, case):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    if case == "bad_json_part":
        _oc_message(db, 1, parts=[("text", "{not json")])
    elif case == "non_string_text":
        _oc_message(db, 1, parts=[("text", {"type": "text", "text": 7})])
    elif case == "inline_non_string":
        _oc_message(db, 1, inline=[{"type": "text", "text": ["x"]}])
    else:
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO session_message VALUES ('m1', ?, 'assistant', 1, 1, 1, '[1, 2]')", (OC_SESSION,))
    with pytest.raises(ValueError, match="opencode_record_malformed"):
        _oc_scan(_oc_supervisor(tmp_path), monkeypatch)


@pytest.mark.parametrize("limit,value,reason", [
    ("OC_CELL_MAX", 32, "opencode_record_too_large"),
    ("OC_FETCH_MAX", 200, "opencode_guard_budget"),
    ("OC_TEXT_MAX", 40, "opencode_guard_budget"),
    ("OC_MAX_MESSAGES", 2, "opencode_guard_budget"),
    ("OC_MAX_PARTS", 3, "opencode_guard_budget"),
    ("OC_VM_MAX", 1, "opencode_guard_budget"),
    ("OC_DEADLINE", 0.0, "opencode_guard_deadline"),
])
def test_opencode_bounds_refuse_and_never_skip(tmp_path, monkeypatch, limit, value, reason):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    for seq in range(1, 5):
        _oc_message(db, seq, parts=[_text("a fairly ordinary reply number %d" % seq)])
    monkeypatch.setattr(ts, limit, value)
    if limit == "OC_VM_MAX":
        monkeypatch.setattr(ts, "OC_VM_INTERVAL", 1)  # fixture queries are far below 1000 VM operations
    with pytest.raises(ValueError, match=reason):
        _oc_scan(_oc_supervisor(tmp_path), monkeypatch)


def test_opencode_clean_session_passes_and_records_identity(tmp_path, monkeypatch):
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, parts=[_text("all fine")])
    sup = _oc_supervisor(tmp_path)
    assert _oc_scan(sup, monkeypatch) == (True, [])
    stat = os.lstat(db)
    assert sup.state["opencode_db_identity"][OC_SESSION] == [stat.st_dev, stat.st_ino, stat.st_uid]


def test_opencode_fetch_budget_counts_the_last_part_before_decoding(tmp_path, monkeypatch):
    # The overflow falls on the final part, so no later message check can catch it.
    db = _oc_db(tmp_path / "oc-data" / "opencode.db")
    _oc_message(db, 1, parts=[_text("x" * 100)])
    monkeypatch.setattr(ts, "OC_FETCH_MAX", 80)  # the message cell fits; message + part does not
    with pytest.raises(ValueError, match="opencode_guard_budget"):
        _oc_scan(_oc_supervisor(tmp_path), monkeypatch)
