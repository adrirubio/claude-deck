"""OpenCode v2 member identity: session ids and process argv (#731)."""
import re

import pytest

from app.services import opencode_process_identity as identity


def test_new_session_id_has_the_native_shape():
    ids = {identity.new_session_id() for _ in range(50)}
    assert len(ids) == 50
    for value in ids:
        assert re.fullmatch(r"ses_[0-9A-Za-z]{26}", value)
        assert identity.is_session_id(value)


@pytest.mark.parametrize("value", [
    "ses_e2e111c0dffe5XAqhRWBFFBZDf", "ses_abc", "ses_deck-slot-29_issue-729",
])
def test_session_ids_must_start_with_ses(value):
    assert identity.is_session_id(value)


@pytest.mark.parametrize("value", [
    None, "", "deck-slot-29", "0b5b3c1e-4c1d-4b6f-9f0e-0d4d6d1f2a3b", "ses", "ses_a b",
    "ses_;rm", "SES_abc", "ses_" + "a" * 200, 42,
])
def test_other_values_are_not_session_ids(value):
    assert not identity.is_session_id(value)


def test_member_argv_parses_the_v2_launch():
    member = identity.parse_member_argv([
        "/opt/bin/opencode", "/work/repo", "--standalone", "--session", "ses_abc", "--auto",
        "--prompt", "--session ses_other",
    ])
    assert member == identity.OpenCodeMember("/work/repo", "ses_abc", True)
    assert identity.parse_member_argv(
        ["opencode", "/work/repo", "--standalone", "--session", "ses_abc"]
    ) == identity.OpenCodeMember("/work/repo", "ses_abc", False)


@pytest.mark.parametrize("argv", [
    [],
    ["claude", "/work/repo", "--standalone", "--session", "ses_abc"],
    ["opencode", "/work/repo", "--session", "ses_abc"],  # shared service mixes up members
    ["opencode", "/work/repo", "--standalone"],
    ["opencode", "/work/repo", "--standalone", "--continue"],
    ["opencode", "/work/repo", "--standalone", "--session", "ses_abc", "--continue"],
    ["opencode", "/work/repo", "--standalone", "--session", "ses_abc", "--session", "ses_abc"],
    ["opencode", "/work/repo", "--standalone", "--session", "not-a-ses-id"],
    ["opencode", "/work/repo", "--standalone", "--session", "ses_abc", "--model", "x/y"],
    ["opencode", "/work/repo", "--standalone", "--session", "ses_abc", "--agent", "plan"],
    ["opencode", "/work/repo", "--standalone", "--session", "ses_abc", "extra"],
    ["opencode", "/work/repo", "--standalone", "--session"],
    ["opencode", "--standalone", "--session", "ses_abc"],
    ["opencode", "serve", "--stdio", "--port", "0"],
    ["opencode", "serve", "--service"],
])
def test_other_argv_is_not_a_member(argv):
    assert identity.parse_member_argv(argv) is None


def test_private_server_and_shared_service_are_told_apart():
    assert identity.is_private_server_argv(["/opt/bin/opencode", "serve", "--stdio", "--port", "0"])
    assert not identity.is_private_server_argv(["opencode", "serve", "--service"])
    assert not identity.is_private_server_argv(["opencode", "serve", "--stdio", "--service"])
    assert not identity.is_private_server_argv(["opencode", "/work/repo", "--standalone"])
    assert identity.is_server_argv(["opencode", "serve", "--service"])
    assert identity.is_server_argv(["opencode", "serve", "--stdio"])
    assert not identity.is_server_argv(["opencode", "/work/repo", "--standalone", "--session", "ses_a"])
    assert not identity.is_server_argv(["node", "serve"])


def test_config_content_carries_model_agent_and_provider_allowlist():
    import json

    content = identity.config_content(model="anthropic/claude-sonnet-4.6#high", agent="plan")
    assert "\n" not in content
    deny = [{"action": "question", "resource": "*", "effect": "deny"}]
    assert json.loads(content) == {
        "model": "anthropic/claude-sonnet-4.6#high",
        "default_agent": "plan",
        "update": "disable",
        "enabled_providers": ["anthropic"],
        "permissions": deny,  # unattended members never stall on a question (#732)
    }
    # Without a model, the hosted free models are disabled so no silent fallback happens (#729 F5).
    assert json.loads(identity.config_content(model=None, agent=None)) == {
        "update": "disable",
        "disabled_providers": ["opencode"],
        "permissions": deny,
    }


@pytest.mark.parametrize("model", [
    "anthropic/claude-sonnet-4.6", "openai/gpt-5.5#high", "amazon-bedrock/anthropic.claude-sonnet-4-6-v1:0",
    "openrouter/moonshotai/kimi-k3",
])
def test_models_need_a_provider_prefix(model):
    assert identity.is_model(model)


@pytest.mark.parametrize("model", [
    "claude-sonnet-4.6", "/gpt-5.5", "openai/", "openai/gpt-5.5#", "openai/gpt 5.5", "openai/gpt-5.5#a#b",
    "openai/gpt-5.5\n", "-x/y", "",
])
def test_models_without_the_v2_shape_are_refused(model):
    assert not identity.is_model(model)


@pytest.mark.parametrize("agent,ok", [("plan", True), ("deck-member_2", True), ("", False), ("a b", False), ("-plan", False)])
def test_agent_names(agent, ok):
    assert identity.is_agent(agent) is ok


def test_duplicate_opencode_session_ids_are_flagged_like_uuids():
    from types import SimpleNamespace

    from app.services import agent_activity_service

    slots = [SimpleNamespace(id=index, provider="opencode-cli", launch_options={"session_id": sid})
             for index, sid in ((1, "ses_same"), (2, "ses_same"), (3, "ses_other"))]
    options = [(slot.launch_options,) for slot in slots]
    inputs = agent_activity_service._inputs_from_rows(slots, options, [], [])
    assert {entry[0]: entry[4] for entry in inputs} == {1: True, 2: True, 3: False}
    # A ses… id is never a UUID identity for the other harnesses.
    assert agent_activity_service._canonical_session_id("ses_same") is None


_MEMBER = ["/opt/bin/opencode", "/work/repo", "--standalone", "--session", "ses_owner"]
_SERVER = ["/opt/bin/opencode", "serve", "--stdio", "--port", "0"]


@pytest.mark.parametrize("case,accepted", [
    ("member_and_private_server", True),
    ("session_pid_is_the_pane", True),
    ("other_session_id", False),
    ("continue", False),
    ("no_standalone", False),
    ("shared_service", False),
    ("server_not_a_child", False),
    ("version_not_ready", False),
    ("slot_id_not_ses", False),
    ("argv_unreadable", False),
])
def test_owner_identity_needs_the_exact_opencode_member(monkeypatch, case, accepted):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.services import opencode_version
    from app.services import owner_observation_pause as pause
    from app.utils import peer_process

    pane, server = 11, 12
    argv = {pane: list(_MEMBER), server: list(_SERVER)}
    parent = {server: pane}
    slot_id = "ses_owner"
    session_pid = server
    if case == "session_pid_is_the_pane":
        session_pid = pane
    elif case == "other_session_id":
        argv[pane][-1] = "ses_other"
    elif case == "continue":
        argv[pane] = ["opencode", "/work/repo", "--standalone", "--continue"]
    elif case == "no_standalone":
        argv[pane] = ["opencode", "/work/repo", "--session", "ses_owner"]
    elif case == "shared_service":
        argv[server] = ["opencode", "serve", "--service"]
    elif case == "server_not_a_child":
        parent[server] = 1
    elif case == "slot_id_not_ses":
        slot_id = "0b5b3c1e-4c1d-4b6f-9f0e-0d4d6d1f2a3b"
    elif case == "argv_unreadable":
        argv.pop(pane)
    ready = case != "version_not_ready"

    monkeypatch.setattr(pause.activity, "_process", lambda _pid: ("S", "fixture-start"))
    monkeypatch.setattr(pause.activity, "_process_started_at",
                        lambda _start: datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(identity, "read_argv", lambda pid: argv.get(pid))
    monkeypatch.setattr(peer_process, "read_proc_stat", lambda pid: (parent.get(pid, 1), "fixture-start"))
    monkeypatch.setattr(opencode_version, "member_gate_for_pane", lambda pid, start: opencode_version.VersionGate(
        "ok" if ready else "unsupported", "2.2.7" if ready else "1.17.11", None))
    slot = SimpleNamespace(provider="opencode-cli", launch_options={"session_id": slot_id})
    session = SimpleNamespace(pid=session_pid, created_at=datetime.utcnow(), cwd="/work/repo")
    workspace = SimpleNamespace(leased_owner_pid=pane, leased_owner_proc_start="fixture-start")
    if accepted:
        assert pause._process_identity(slot, session, workspace) == "fixture-start"
    else:
        with pytest.raises(ValueError, match="owner_native_identity_changed"):
            pause._process_identity(slot, session, workspace)


def _write_cmdline(root, pid, argv):
    proc = root / str(pid)
    proc.mkdir(parents=True, exist_ok=True)
    (proc / "cmdline").write_bytes(b"\0".join(part.encode() for part in argv) + b"\0")


def _sized_prompt(prefix, total):
    """A --prompt value that makes the NUL-terminated cmdline exactly ``total`` bytes."""
    used = sum(len(part.encode()) + 1 for part in prefix) + 1  # +1 for the prompt's own NUL
    return "x" * (total - used)


@pytest.mark.parametrize("over_cap", [True, False])
def test_an_oversized_cmdline_is_never_parsed_from_a_truncated_prefix(monkeypatch, tmp_path, over_cap):
    # V1 F3: a long --prompt must not hide a forbidden tail such as --continue.
    from app.services import opencode_version
    from app.utils import peer_process

    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(tmp_path))
    monkeypatch.setattr(opencode_version, "member_gate_for_pane",
                        lambda pid, start: opencode_version.VersionGate("ok", "2.2.7", None))
    prefix = ["/opt/bin/opencode", "/work/repo", "--standalone", "--session", "ses_owner", "--prompt"]
    if over_cap:
        argv = prefix + [_sized_prompt(prefix, identity.CMDLINE_CAP)] + ["--continue"]
    else:
        argv = prefix + [_sized_prompt(prefix, identity.CMDLINE_CAP)]
    _write_cmdline(tmp_path, 11, argv)

    assert len((tmp_path / "11" / "cmdline").read_bytes()) == identity.CMDLINE_CAP + (len("--continue") + 1 if over_cap else 0)
    if over_cap:
        assert identity.read_argv(11) is None
        assert identity.is_current_member(11, "start", "ses_owner") is False
    else:
        assert identity.read_argv(11) == argv
        assert identity.is_current_member(11, "start", "ses_owner") is True
