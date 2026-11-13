"""Standalone Agent Mail MCP shim behavior."""
import json
import inspect
from io import StringIO
from types import SimpleNamespace

import pytest


def test_mcp_shim_imports_without_app_package_dependency():
    import mcp_shim.agent_mail_server as shim

    assert shim.mcp is not None
    assert callable(shim.synth_city_whoami)


def test_remaining_summary_uses_authenticated_context_and_makes_no_writes(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    from mcp_shim.work_remaining_protocol import parse_report
    requests = []
    context = dict(work_item_id=7, dispatch_nonce="dispatch", owner_slot_id=2,
                   scope_revision=0, source_sha="a" * 40, phase="implementation")
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})
    monkeypatch.setitem(shim._state, "member_id", 3)
    def read(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"remaining_work_context": context, "remaining_work": {"source_url": "https://github.com/o/r/issues/7#work-remaining"}}}
    monkeypatch.setattr(shim, "_team_request", read)
    result = shim.synth_city_prepare_work_remaining_summary(7, "Fix the interface, then review and merge.", "B2 publishes the next checkpoint.")
    assert result["ok"]
    parsed = parse_report(result["body_markdown"])
    assert parsed.work_item_id == 7 and parsed.reported_by == "Team member 3" and parsed.estimate() == "Unknown."
    assert requests == [("GET", "/github-work-items/7/remaining-work-context", {})]
    invalid = shim.synth_city_prepare_work_remaining_summary(7, "token=private", "Publish.")
    assert invalid["error"]["code"] == "invalid_remaining_summary" and "private" not in str(invalid)
    monkeypatch.setattr(shim, "_team_request", lambda *_: {"ok": True, "data": {"remaining_work_context": None}})
    assert shim.synth_city_prepare_work_remaining_summary(7, "Corrections.", "Publish.")["error"]["code"] == "progress_context_unavailable"
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": False, "error": {"code": "session_token_stale"}})
    assert shim.synth_city_prepare_work_remaining_summary(7, "Corrections.", "Publish.")["error"]["code"] == "session_token_stale"


def test_remaining_guidance_applies_to_each_member_writing_style():
    from app.services.team_communication_policy import team_communication_guidance
    for controlled in (True, False):
        text = team_communication_guidance(controlled)
        assert "three short lines: Remaining, Estimate, Next" in text
        assert "The owner supplies the estimate" in text
        assert "satisfies no approval, review, CI or milestone gate" in text


def test_backlog_assessment_forwards_optional_private_snapshot_token(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    posted = []
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})
    monkeypatch.setattr(shim, "_dispatch_request", lambda method, path, **kwargs: posted.append(
        (method, path, kwargs)) or {"ok": True})
    shim.synth_city_report_backlog_assessment(1, 2, 0, [], "fixture-private-read")
    shim.synth_city_report_backlog_assessment(1, 2, 3, [])
    assert posted[0] == ("POST", "/github-scopes/1/coordination-assessments", {"json": {
        "generation": 2, "request_sequence": 0, "entries": [], "snapshot_token": "fixture-private-read"}})
    assert posted[1][2]["json"]["snapshot_token"] is None


def test_owner_followup_forwards_explicit_event_and_private_challenge(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    posted = []
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})
    monkeypatch.setattr(shim, "_dispatch_request", lambda method, path, **kwargs: posted.append(
        (method, path, kwargs)) or {"ok": True})
    shim.synth_city_report_owner_followup(1, 2, "assess", "next_action_arranged", 3, "fixture-private-followup")
    assert posted == [("POST", "/github-scopes/1/owner-followups", {"json": {
        "work_item_id": 2, "action": "assess", "reason": "next_action_arranged",
        "expected_sequence": 3, "followup_token": "fixture-private-followup"}})]


def test_ensure_registered_refreshes_cached_member(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    monkeypatch.setenv("SYNTH_CITY_TEAM_PRESET_ID", "1")
    monkeypatch.setenv("SYNTH_CITY_TEAM_SLOT_ID", "2")

    requests = []
    monkeypatch.setitem(shim._state, "member_id", 7)
    monkeypatch.setitem(shim._state, "session_key", "mcp:test")
    monkeypatch.setattr(shim.os, "getcwd", lambda: "/tmp/repo")
    monkeypatch.setattr(shim.os, "getppid", lambda: 1234)

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"member": {"id": 8}}}

    monkeypatch.setattr(shim, "_request", fake_request)

    result = shim._ensure_registered()

    assert result["ok"] is True
    assert shim._state["member_id"] == 8
    assert len(requests) == 1
    method, path, kwargs = requests[0]
    assert (method, path) == ("POST", "/agent/register")
    assert kwargs["json"] == {
        "source": "mcp",
        "provider": shim.PROVIDER,
        "cwd": "/tmp/repo",
        "session_key": "mcp:test",
        "pid": 1234,
        "team_preset_id": 1,
        "team_slot_id": 2,
    }
    # The pi-cli shim adds a bounded total timeout; other providers do not.
    if shim.PROVIDER == "pi-cli":
        assert isinstance(kwargs["total_timeout"], (int, float))
        assert kwargs["total_timeout"] > 0
    else:
        assert "total_timeout" not in kwargs


def test_heartbeat_once_returns_normal_interval_when_registered(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})

    assert shim._heartbeat_once() == shim.HEARTBEAT_INTERVAL_SECONDS


def test_heartbeat_once_backs_off_when_deck_unavailable(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": False})

    assert shim._heartbeat_once() == shim.HEARTBEAT_UNAVAILABLE_INTERVAL_SECONDS


def test_start_heartbeat_thread_uses_daemon_thread(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    started = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            started.append(self)

    monkeypatch.setattr(shim.threading, "Thread", FakeThread)

    thread = shim._start_heartbeat_thread()

    assert started == [thread]
    assert thread.target == shim._heartbeat_loop
    assert thread.name == "albiex-synth-city-agent-mail-heartbeat"
    assert thread.daemon is True


def test_synth_city_reply_only_uses_answer_for_context_requests(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    posted = []
    shim._state["member_id"] = 7

    def fake_request(method, path, **kwargs):
        if method == "GET" and path == "/messages/10/thread":
            return {
                "ok": True,
                "data": {
                    "root": {
                        "kind": "handoff",
                        "request_status": "pending",
                        "recipient_member_id": 7,
                    }
                },
            }
        if method == "POST":
            posted.append(kwargs["json"])
            return {"ok": True, "data": {"id": 99}}
        if path.startswith("/agent/inbox"):
            return {"ok": True, "data": {"unread_count": 0, "pending_count": 0}}
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(shim, "_request", fake_request)
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})

    result = shim.synth_city_reply(10, "Completed the work.")

    assert result["ok"] is True
    assert posted[0]["kind"] == "message"


def test_synth_city_list_team_uses_cached_roster(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []
    shim._state["member_id"] = 7

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path == "/team?sync=false":
            return {
                "ok": True,
                "data": {
                    "members": [
                        {
                            "id": 7,
                            "display_name": "Planner",
                            "participant_kind": "team_slot",
                            "role": "Planner",
                            "repo_name": "deck",
                            "status": "connected",
                            "agent_status": {"session_state": "online", "activity_state": "idle",
                                             "wake_state": "cannot_wake", "wake_reason": "wake_target_unbound"},
                            "charter": "Plan work",
                            "team_preset_name": "Test team",
                            "team_slot_name": "Planner",
                        }
                    ]
                },
            }
        if path.startswith("/agent/inbox"):
            return {"ok": True, "data": {"unread_count": 0, "pending_count": 0}}
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(shim, "_request", fake_request)
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})

    result = shim.synth_city_list_team()

    assert result["ok"] is True
    assert requests[0][1] == "/team?sync=false"
    assert result["members"][0]["agent_status"]["wake_state"] == "cannot_wake"


def test_synth_city_check_inbox_returns_deck_unreachable_on_http_error(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    def fake_http_request(*args, **kwargs):
        raise shim.httpx.ConnectError("no server", request=SimpleNamespace())

    shim._state["member_id"] = None
    shim._state["offline_until"] = 0.0
    shim._state["last_error"] = None
    monkeypatch.setattr(shim.httpx, "request", fake_http_request)

    result = shim.synth_city_check_inbox()

    assert result["ok"] is False
    assert result["error"]["code"] == "synth_city_unreachable"


def test_mcp_request_uses_short_timeout_and_offline_backoff(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    calls = []

    def fake_http_request(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise shim.httpx.ConnectError("no server", request=SimpleNamespace())

    shim._state["offline_until"] = 0.0
    shim._state["last_error"] = None
    monkeypatch.setattr(shim.httpx, "request", fake_http_request)

    first = shim._request("GET", "/team")
    second = shim._request("GET", "/team")

    assert first["ok"] is False
    assert second["ok"] is False
    assert len(calls) == 1
    assert calls[0].connect == 0.5
    assert calls[0].read == 15.0


def test_registration_captures_the_capability_token(monkeypatch):
    """The plaintext arrives once; the shim must keep it."""
    from mcp_shim import agent_mail_server as shim

    responses = [
        {
            "ok": True,
            "data": {
                "member": {"id": 4},
                "session": {"id": 9},
                "capability_token": "tok-abc",
            },
        },
        {
            "ok": True,
            "data": {
                "member": {"id": 4},
                "session": {"id": 9},
                "capability_token": None,
            },
        },
    ]
    monkeypatch.setattr(shim, "_request", lambda *args, **kwargs: responses.pop(0))
    shim._state["capability_token"] = None
    shim._state["member_id"] = None

    shim._ensure_registered()
    assert shim._state["capability_token"] == "tok-abc"

    shim._ensure_registered()
    assert shim._state["capability_token"] == "tok-abc"


def test_synth_city_request_sends_the_session_token(monkeypatch):
    from mcp_shim import agent_mail_server as shim

    captured = {}

    def _fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers")

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {}

        return _Response()

    monkeypatch.setattr(shim.httpx, "request", _fake_request)
    shim._state["capability_token"] = "tok-abc"
    shim._state["offline_until"] = 0.0

    shim._synth_city_request("GET", "agent-mail", "/team")
    assert captured["headers"]["X-Synth-City-Session-Token"] == "tok-abc"


def test_synth_city_request_preserves_a_callers_headers(monkeypatch):
    from mcp_shim import agent_mail_server as shim

    captured = {}

    def _fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers")

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {}

        return _Response()

    monkeypatch.setattr(shim.httpx, "request", _fake_request)
    shim._state["capability_token"] = "tok-abc"
    shim._state["offline_until"] = 0.0

    shim._synth_city_request(
        "GET",
        "agent-bridge",
        "/x",
        headers={"X-Synth-City-Terminal-Token": "term"},
    )
    assert captured["headers"]["X-Synth-City-Terminal-Token"] == "term"
    assert captured["headers"]["X-Synth-City-Session-Token"] == "tok-abc"


def test_synth_city_request_sends_no_header_without_a_token(monkeypatch):
    from mcp_shim import agent_mail_server as shim

    captured = {}

    def _fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers")

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {}

        return _Response()

    monkeypatch.setattr(shim.httpx, "request", _fake_request)
    shim._state["capability_token"] = None
    shim._state["offline_until"] = 0.0

    shim._synth_city_request("GET", "agent-mail", "/team")
    assert "X-Synth-City-Session-Token" not in (captured["headers"] or {})


def test_synth_city_request_routes_by_api_prefix(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    urls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": "backend"}

    def fake_http_request(method, url, **kwargs):
        urls.append(url)
        return FakeResponse()

    shim._state["offline_until"] = 0.0
    shim._state["last_error"] = None
    monkeypatch.setattr(shim.httpx, "request", fake_http_request)

    mail_result = shim._request("GET", "/team")
    team_result = shim._team_request("GET", "/presets")

    assert mail_result["ok"] is True
    assert team_result["ok"] is True
    assert urls[0].endswith("/api/v1/agent-mail/team")
    assert urls[1].endswith("/api/v1/agent-teams/presets")


def test_http_error_result_preserves_backend_block_code():
    import mcp_shim.agent_mail_server as shim

    request = shim.httpx.Request("POST", "http://deck/api/v1/agent-teams/presets")
    response = shim.httpx.Response(
        400,
        request=request,
        json={
            "detail": {
                "message": "opencode-cli does not support reasoning_effort",
                "block_code": "reasoning_effort_unsupported",
            }
        },
    )
    error = shim.httpx.HTTPStatusError("bad request", request=request, response=response)

    result = shim._http_error_result(error)

    assert result["ok"] is False
    assert result["error"]["status_code"] == 400
    assert result["error"]["message"] == "opencode-cli does not support reasoning_effort"
    assert result["error"]["block_code"] == "reasoning_effort_unsupported"


def test_http_conflict_preserves_detail_code_without_credentials():
    import mcp_shim.agent_mail_server as shim

    request = shim.httpx.Request(
        "POST",
        "http://deck/api/v1/agent-mail/decisions",
        headers={"X-Synth-City-Session-Token": "request-secret"},
    )
    response = shim.httpx.Response(
        409,
        request=request,
        headers={"X-Debug-Token": "response-secret"},
        json={"detail": "request_not_pending"},
    )
    error = shim.httpx.HTTPStatusError("conflict", request=request, response=response)

    result = shim._http_error_result(error)

    assert result == {
        "ok": False,
        "error": {
            "code": "request_not_pending",
            "status_code": 409,
            "message": "request_not_pending",
        },
    }
    assert "request-secret" not in repr(result)
    assert "response-secret" not in repr(result)


def test_http_conflict_preserves_structured_recovery_detail_without_payload():
    import mcp_shim.agent_mail_server as shim

    request = shim.httpx.Request(
        "POST",
        "http://deck/api/v1/agent-teams/github-work-items/23/dispatch-status",
        json={"lease_token": "lease-secret", "allowed_commands": ["secret-command"]},
    )
    response = shim.httpx.Response(
        409,
        request=request,
        json={
            "detail": {
                "code": "diagnostic_tree_not_restored",
                "message": "The diagnostic tree does not match the persisted baseline.",
            }
        },
    )
    error = shim.httpx.HTTPStatusError("conflict", request=request, response=response)

    result = shim._http_error_result(error)

    assert result == {
        "ok": False,
        "error": {
            "code": "diagnostic_tree_not_restored",
            "status_code": 409,
            "message": "The diagnostic tree does not match the persisted baseline.",
        },
    }
    assert "lease-secret" not in repr(result)
    assert "secret-command" not in repr(result)


def test_request_work_item_approval_uses_agent_mail_authority_route(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []
    monkeypatch.setattr(shim, "_guard", lambda: None)

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path == "/approval-requests":
            return {
                "ok": True,
                "data": {
                    "id": 41,
                    "request_message_id": 73,
                    "status": "pending",
                    "approval_round": 2,
                },
            }
        if path.startswith("/agent/inbox"):
            return {"ok": True, "data": {"unread_count": 0, "pending_count": 1}}
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(shim, "_request", fake_request)

    result = shim.synth_city_request_work_item_approval(
        19,
        "nonce-19",
        "Change one file.",
        {"paths": ["src/example.py"]},
    )

    assert requests[0] == (
        "POST",
        "/approval-requests",
        {
            "json": {
                "work_item_id": 19,
                "dispatch_nonce": "nonce-19",
                "summary": "Change one file.",
                "plan_metadata": {"paths": ["src/example.py"]},
            }
        },
    )
    assert result == {
        "ok": True,
        "approval_request_id": 41,
        "request_message_id": 73,
        "status": "pending",
        "approval_round": 2,
        "unread_count": 0,
        "pending_count": 1,
    }


def test_approve_work_item_sends_required_request_id(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []
    monkeypatch.setattr(shim, "_guard", lambda: None)

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path == "/decisions":
            return {"ok": True, "data": {"id": 81, "decision": "approved"}}
        if path.startswith("/agent/inbox"):
            return {"ok": True, "data": {"unread_count": 0, "pending_count": 0}}
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(shim, "_request", fake_request)

    result = shim.synth_city_approve_work_item(
        19,
        "nonce-19",
        "approved",
        "Safe to proceed.",
        approval_request_id=41,
    )

    assert requests[0] == (
        "POST",
        "/decisions",
        {
            "json": {
                "work_item_id": 19,
                "dispatch_nonce": "nonce-19",
                "approval_request_id": 41,
                "decision": "approved",
                "reason": "Safe to proceed.",
            }
        },
    )
    assert result["message_id"] == 81


def test_continuation_mcp_tools_forward_explicit_authority(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    dispatch_requests = []
    mail_requests = []
    monkeypatch.setattr(shim, "_guard", lambda: None)
    monkeypatch.setattr(shim, "_counts", lambda: {})

    def fake_dispatch(method, path, **kwargs):
        dispatch_requests.append((method, path, kwargs))
        if path.endswith("/continuation-requests"):
            return {
                "ok": True,
                "data": {
                    "approval": {"id": 71, "status": "pending"},
                    "revision": {"id": 81, "revision": 2},
                },
            }
        if path.endswith("/ack"):
            return {"ok": True, "data": {"id": 19, "dispatch_status": "dispatched"}}
        if path.endswith("/scope-revisions"):
            return {"ok": True, "data": [{"id": 81, "revision": 2}]}
        raise AssertionError((method, path, kwargs))

    def fake_mail(method, path, **kwargs):
        mail_requests.append((method, path, kwargs))
        return {"ok": True, "data": {"id": 91, "decision": "approved"}}

    monkeypatch.setattr(shim, "_dispatch_request", fake_dispatch)
    monkeypatch.setattr(shim, "_request", fake_mail)

    requested = shim.synth_city_request_continuation(
        19,
        "nonce-19",
        "implementation",
        "workspace",
        "One bounded change",
        ["src/example.py"],
        ["edit_production", "push_pr_head", "request_verification"],
        ["pytest -q"],
        ["Do not edit CI"],
        1,
        {},
        "lease-secret",
    )
    decided = shim.synth_city_decide_continuation(
        71,
        19,
        "nonce-19",
        "approved",
        "Approved",
    )
    acknowledged = shim.synth_city_ack_continuation(
        19,
        2,
        "nonce-19",
        "lease-secret",
    )
    listed = shim.synth_city_list_scope_revisions(19)

    assert requested["approval"]["id"] == 71
    assert decided == {"ok": True, "message_id": 91, "decision": "approved"}
    assert acknowledged["work_item"]["dispatch_status"] == "dispatched"
    assert listed["revisions"] == [{"id": 81, "revision": 2}]
    assert dispatch_requests[0] == (
        "POST",
        "/github-work-items/19/continuation-requests",
        {
            "json": {
                "dispatch_nonce": "nonce-19",
                "phase": "implementation",
                "execution_target": "workspace",
                "summary": "One bounded change",
                "allowed_paths": ["src/example.py"],
                "allowed_actions": [
                    "edit_production",
                    "push_pr_head",
                    "request_verification",
                ],
                "allowed_commands": ["pytest -q"],
                "prohibited_actions": ["Do not edit CI"],
                "max_failed_heads": 1,
                "tool_fallbacks": {},
                "lease_token": "lease-secret",
            }
        },
    )
    assert mail_requests == [
        (
            "POST",
            "/continuation-decisions",
            {
                "json": {
                    "approval_request_id": 71,
                    "work_item_id": 19,
                    "dispatch_nonce": "nonce-19",
                    "decision": "approved",
                    "reason": "Approved",
                }
            },
        )
    ]
    signature = inspect.signature(shim.synth_city_decide_continuation)
    assert list(signature.parameters) == [
        "approval_request_id",
        "work_item_id",
        "dispatch_nonce",
        "decision",
        "reason",
    ]
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )


def test_continuation_mcp_preserves_backend_conflict_code(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    monkeypatch.setattr(shim, "_guard", lambda: None)
    monkeypatch.setattr(
        shim,
        "_dispatch_request",
        lambda *_args, **_kwargs: {
            "ok": False,
            "error": {
                "code": "continuation_head_changed",
                "status_code": 409,
                "message": "continuation_head_changed",
            },
        },
    )

    result = shim.synth_city_ack_continuation(
        19,
        2,
        "nonce-19",
        "lease-secret",
    )

    assert result["error"] == {
        "code": "continuation_head_changed",
        "status_code": 409,
        "message": "continuation_head_changed",
    }
    assert "lease-secret" not in repr(result)


def test_dispatch_status_tool_carries_completion_evidence(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})
    monkeypatch.setattr(
        shim,
        "_dispatch_request",
        lambda method, path, **kwargs: requests.append((method, path, kwargs))
        or {"ok": True},
    )

    result = shim.synth_city_report_dispatch_status(
        19,
        "continuation_completed",
        lease_token="lease-secret",
        revision=2,
        dispatch_nonce="nonce-19",
        current_head_sha="a" * 40,
        summary="Completed the bounded change",
        evidence={"checks": ["pytest -q"]},
    )

    assert result == {"ok": True}
    assert requests[0][2]["json"] == {
        "work_item_id": 19,
        "status": "continuation_completed",
        "pr_number": None,
        "head_ref": None,
        "reassign_to_slot_id": None,
        "note": None,
        "lease_token": "lease-secret",
        "revision": 2,
        "dispatch_nonce": "nonce-19",
        "current_head_sha": "a" * 40,
        "summary": "Completed the bounded change",
        "evidence": {"checks": ["pytest -q"]},
    }


def test_list_work_items_projects_safe_continuation_fields(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    monkeypatch.setattr(
        shim,
        "_ensure_registered",
        lambda: {"ok": True, "data": {"member": {"team_preset_id": 4}}},
    )
    monkeypatch.setattr(
        shim,
        "_dispatch_request",
        lambda *_args, **_kwargs: {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 19,
                        "issue_number": 867,
                        "dispatch_status": "dispatched",
                        "pr_number": 875,
                        "attempt_phase": "implementation",
                        "active_scope_revision": 2,
                        "diagnostic_retry_count": 1,
                        "continuation_nudged_at": "2026-08-29T10:00:00",
                        "continuation_activated_at": "2026-08-29T10:01:00",
                        "lease_token": "must-not-project",
                    }
                ]
            },
        },
    )

    result = shim.synth_city_list_work_items(status="")

    assert result["items"][0]["active_scope_revision"] == 2
    assert result["items"][0]["pr_number"] == 875
    assert "lease_token" not in result["items"][0]
    assert "must-not-project" not in repr(result)


def test_synth_city_create_team_posts_to_team_api(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []

    def fake_team_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"id": 12, "name": "Team", "slots": []}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.synth_city_create_team(
        "Team",
        "Generated by an agent",
        [{"display_name": "Dev", "provider": "codex-cli", "repo_path": "/tmp/repo", "ui_color": "blue"}],
        parent_issue_url="https://github.com/example/repo/issues/506",
    )

    assert result["ok"] is True
    assert result["preset"]["id"] == 12
    assert requests[0][0:2] == ("POST", "/presets")
    assert requests[0][2]["json"]["created_by"] == "mcp"
    assert requests[0][2]["json"]["slots"][0]["ui_color"] == "blue"
    assert requests[0][2]["json"]["parent_issue_url"].endswith("/issues/506")


def test_campaign_setter_sends_director_key_only_as_header(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    requests = []
    def request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if kwargs.get("headers", {}).get("X-Synth-City-Operator-Token") != "synthetic-director-key":
            return {"ok": False, "error": {"code": "operator_token_invalid"}}
        return {"ok": True, "data": {"id": 12, "backlog_milestone": "Campaign",
                                     "launch_options": {"secret": "private-launch"}}}
    monkeypatch.setattr(shim, "_team_request", request)
    planned = [{"text": "Decide promotion.", "state": "later"}]
    missing = shim.synth_city_update_team_campaign(12, "Campaign", planned)
    assert missing["ok"] is False and not requests
    wrong = shim.synth_city_update_team_campaign(12, "Campaign", planned, director_key="wrong-key")
    assert wrong["ok"] is False
    result = shim.synth_city_update_team_campaign(12, "Campaign", planned, director_key="synthetic-director-key")
    assert result["ok"] is True
    assert "synthetic-director-key" not in repr(result)
    assert "private-launch" not in repr(result)
    assert requests[-1] == ("PATCH", "/presets/12", {
        "headers": {"X-Synth-City-Operator-Token": "synthetic-director-key"},
        "json": {"backlog_milestone": "Campaign", "planned_decisions": planned}})


def test_campaign_setter_preserves_unknown_write_outcome_without_private_errors(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    monkeypatch.setattr(shim, "_team_request", lambda *args, **kwargs: {
        "ok": False, "error": {"code": "synth_city_unreachable", "message": "synthetic-director-key"},
        "outcome": "unknown", "suggestion": "private-request-details"})
    result = shim.synth_city_update_team_campaign(12, None, None, director_key="synthetic-director-key")
    assert result["ok"] is False and result["outcome"] == "unknown"
    assert result["suggestion"] == "Do not repeat this mutation blindly; reconcile its outcome first."
    assert "synthetic-director-key" not in repr(result) and "private-request-details" not in repr(result)


def test_campaign_setter_keeps_session_key_out_of_director_header(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    requests = []
    monkeypatch.setitem(shim._state, "capability_token", "synthetic-session-key")
    monkeypatch.setattr(shim, "_team_request", lambda *args, **kwargs: requests.append(kwargs))
    result = shim.synth_city_update_team_campaign(12, None, None)
    assert result["ok"] is False
    assert not requests


def test_team_summary_and_parent_link_tools_use_narrow_team_routes(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    requests = []
    def request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"preset_id": 12}}
    monkeypatch.setattr(shim, "_team_request", request)
    assert shim.synth_city_get_team_summary(12) == {"ok": True, "summary": {"preset_id": 12}}
    assert shim.synth_city_update_team_parent_issue(12, None)["ok"]
    assert requests == [("GET", "/presets/12/summary", {}),
                        ("PATCH", "/presets/12", {"json": {"parent_issue_url": None}})]
    monkeypatch.setattr(shim, "_team_request", lambda *args, **kwargs: {"ok": False, "error": "blocked"})
    assert not shim.synth_city_get_team_summary(12)["ok"]
    assert not shim.synth_city_update_team_parent_issue(12, None)["ok"]


def test_synth_city_attach_image_to_bridge_session_uploads_and_pastes(monkeypatch, tmp_path):
    import mcp_shim.agent_mail_server as shim

    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    requests = []

    def fake_bridge_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if (method, path) == ("GET", "/token?target=snazzy%3A0.0&purpose=attachment"):
            return {"ok": True, "data": {"token": f"token-{len(requests)}"}}
        assert kwargs["headers"]["X-Synth-City-Terminal-Token"].startswith("token-")
        if method == "POST" and path == "/sessions/snazzy%3A0.0/attachments":
            assert kwargs["data"]["created_by"] == "mcp"
            assert kwargs["data"]["prompt"] == "Inspect {path}"
            assert kwargs["files"]["file"][0] == "screen.png"
            return {"ok": True, "data": {"id": 7, "prompt_text": "Inspect /tmp/screen.png"}}
        if method == "POST" and path == "/sessions/snazzy%3A0.0/attachments/7/paste":
            assert kwargs["json"] == {"submit": True}
            return {"ok": True, "data": {"pasted": True, "submitted": True, "target": "snazzy:0.0"}}
        raise AssertionError((method, path))

    monkeypatch.setattr(shim, "_bridge_request", fake_bridge_request)

    result = shim.synth_city_attach_image_to_bridge_session(
        "snazzy:0.0",
        str(image_path),
        submit=True,
        prompt="Inspect {path}",
    )

    assert result["ok"] is True
    assert result["attachment"]["id"] == 7
    assert result["paste"]["submitted"] is True


def test_synth_city_attach_image_to_bridge_session_rejects_missing_file():
    import mcp_shim.agent_mail_server as shim

    result = shim.synth_city_attach_image_to_bridge_session("snazzy:0.0", "/tmp/does-not-exist.png")

    assert result["ok"] is False
    assert result["error"]["code"] == "image_file_not_found"


def test_synth_city_list_bridge_attachments_uses_bridge_api(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []

    def fake_bridge_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if (method, path) == ("GET", "/token?target=snazzy%3A0.0&purpose=attachment"):
            return {"ok": True, "data": {"token": "token"}}
        assert kwargs["headers"]["X-Synth-City-Terminal-Token"] == "token"
        return {"ok": True, "data": {"attachments": [{"id": 1}]}}

    monkeypatch.setattr(shim, "_bridge_request", fake_bridge_request)

    result = shim.synth_city_list_bridge_attachments("snazzy:0.0")

    assert result == {"ok": True, "attachments": [{"id": 1}]}
    assert requests[1][0:2] == ("GET", "/sessions/snazzy%3A0.0/attachments")


def test_synth_city_plan_team_launch_returns_plan_hash(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    def fake_team_request(method, path, **kwargs):
        assert (method, path) == ("POST", "/presets/12/plan-launch")
        assert kwargs["json"]["reuse_existing"] is True
        return {"ok": True, "data": {"plan_hash": "abc", "items": []}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.synth_city_plan_team_launch(12)

    assert result == {"ok": True, "plan": {"plan_hash": "abc", "items": []}}


def test_agent_team_tools_refuse_launch_overrides_without_http(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    def forbidden(*_args, **_kwargs):
        raise AssertionError("agent launch override reached Deck HTTP")

    monkeypatch.setattr(shim, "_team_request", forbidden)
    assert shim.synth_city_plan_team_launch(12, reuse_existing=False)["error"]["code"] == "operator_launch_override_required"
    assert shim.synth_city_plan_team_launch(12, include_disabled=True)["error"]["code"] == "operator_launch_override_required"
    assert shim.synth_city_launch_team(12, confirm_plan_hash="abc", reuse_existing=False)["error"]["code"] == "operator_launch_override_required"
    assert shim.synth_city_launch_team(12, force_without_plan=True)["error"]["code"] == "operator_launch_override_required"


def test_synth_city_launch_team_requires_plan_hash(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    called = False

    def fake_team_request(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True, "data": {}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.synth_city_launch_team(12)

    assert result["ok"] is False
    assert result["error"]["code"] == "plan_hash_required"
    assert called is False


def test_synth_city_launch_team_forwards_confirm_hash(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []

    def fake_team_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"launch_id": 9}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.synth_city_launch_team(12, confirm_plan_hash="abc")

    assert result["ok"] is True
    assert result["launch"]["launch_id"] == 9
    assert requests[0][0:2] == ("POST", "/presets/12/launch")
    assert requests[0][2]["json"]["confirm_plan_hash"] == "abc"
    assert requests[0][2]["json"]["skip_plan_confirmation"] is False


def test_codex_hook_shim_emits_backend_json(monkeypatch, capsys):
    import mcp_shim.agent_mail_hook as hook
    monkeypatch.setenv("SYNTH_CITY_TEAM_PRESET_ID", "1")
    monkeypatch.setenv("SYNTH_CITY_TEAM_SLOT_ID", "2")

    body = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Check Agent Mail now.",
        }
    }
    posts = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    def fake_post(url, **kwargs):
        posts.append((url, kwargs["json"]))
        return FakeResponse()

    monkeypatch.setattr(hook.httpx, "post", fake_post)
    monkeypatch.setattr(
        hook.sys,
        "argv",
        [
            "agent_mail_hook.py",
            "--synth-city-url",
            "http://deck",
            "--event",
            "user-prompt-submit",
            "--provider",
            "codex-cli",
        ],
    )
    monkeypatch.setattr(hook.sys, "stdin", StringIO('{"session_id":"s1","cwd":"/repo"}'))
    monkeypatch.setattr(hook.os, "getcwd", lambda: "/fallback")
    monkeypatch.setattr(hook.os, "getppid", lambda: 123)

    assert hook.main() == 0

    output = capsys.readouterr().out.strip()
    assert json.loads(output) == body
    assert posts == [
        (
            "http://deck/api/v1/agent-mail/hooks/user-prompt-submit",
            {
                "session_id": "s1",
                "cwd": "/repo",
                "provider": "codex-cli",
                "pid": 123,
                "team_preset_id": 1,
                "team_slot_id": 2,
            },
        )
    ]


def test_copilot_hook_shim_emits_additional_context(monkeypatch, capsys):
    import mcp_shim.agent_mail_hook as hook

    body = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Check Agent Mail now.",
        }
    }
    posts = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    def fake_post(url, **kwargs):
        posts.append((url, kwargs["json"]))
        return FakeResponse()

    monkeypatch.setattr(hook.httpx, "post", fake_post)
    monkeypatch.setattr(
        hook.sys,
        "argv",
        [
            "agent_mail_hook.py",
            "--synth-city-url",
            "http://deck",
            "--event",
            "user-prompt-submit",
            "--provider",
            "copilot-cli",
        ],
    )
    monkeypatch.setattr(hook.sys, "stdin", StringIO('{"sessionId":"s1","cwd":"/repo"}'))
    monkeypatch.setattr(hook.os, "getcwd", lambda: "/fallback")
    monkeypatch.setattr(hook.os, "getppid", lambda: 123)

    assert hook.main() == 0

    output = capsys.readouterr().out.strip()
    assert json.loads(output) == {"additionalContext": "Check Agent Mail now."}
    assert posts[0][1]["session_id"] == "s1"
    assert posts[0][1]["provider"] == "copilot-cli"


def test_codex_hook_shim_suppresses_empty_backend_response(monkeypatch, capsys):
    import mcp_shim.agent_mail_hook as hook

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    monkeypatch.setattr(hook.httpx, "post", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(
        hook.sys,
        "argv",
        ["agent_mail_hook.py", "--synth-city-url", "http://deck", "--event", "session-start"],
    )
    monkeypatch.setattr(hook.sys, "stdin", StringIO("{}"))
    monkeypatch.setattr(hook.os, "getcwd", lambda: "/repo")
    monkeypatch.setattr(hook.os, "getppid", lambda: 123)

    assert hook.main() == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name,arguments", [
    ("synth_city_create_team", {"name": "synthetic-probe-team"}),
    ("synth_city_retry_work_item", {"work_item_id": 123}),
])
def test_upgrade_probe_refuses_actual_dispatch_including_direct_http_tools(monkeypatch, name, arguments):
    import asyncio
    import importlib.util
    import sys
    from pathlib import Path
    from mcp import types

    path = Path(__file__).resolve().parents[2] / "mcp_shim/agent_mail_server.py"
    spec = importlib.util.spec_from_file_location("upgrade_dispatch_shim", path)
    monkeypatch.setattr(sys, "argv", ["agent_mail_server.py", "--synth-city-upgrade-tools-list-probe"])
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": 123}

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(shim.httpx, "request", request)
    denied = {"ok": False, "error": {"code": "upgrade_probe_read_only"}}

    async def exercise_probe():
        tools = await shim.mcp.list_tools()
        # These paths bypass/ignore _ensure_registered. Exercise FastMCP and
        # its installed wire handler, rather than calling the guard directly.
        result = await shim.mcp.call_tool(name, arguments)
        assert calls == [], "read-only probe emitted an HTTP mutation"
        assert result == denied
        wire = await shim.mcp._mcp_server.request_handlers[types.CallToolRequest](
            types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(
                name=name, arguments=arguments)))
        assert wire.root.structuredContent == denied
        assert len(tools) == 41
        # Every published tool is refused before validation or execution.
        for tool in tools:
            assert await shim.mcp.call_tool(tool.name, {}) == denied
        assert shim._state["member_id"] is None and shim._state["capability_token"] is None
        assert calls == []
        return [tool.model_dump() for tool in tools]

    probe_schemas = asyncio.run(exercise_probe())
    monkeypatch.setattr(sys, "argv", ["agent_mail_server.py"])
    normal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(normal)
    assert [tool.model_dump() for tool in asyncio.run(normal.mcp.list_tools())] == probe_schemas
    # The same tool remains executable in ordinary mode (synthetic HTTP only).
    asyncio.run(normal.mcp.call_tool("synth_city_create_team", {"name": "synthetic-normal-team"}))
    assert len(calls) == 1 and calls[0][0][0] == "POST"


def test_upgrade_probe_lists_tools_without_registration_and_cannot_call_member_tools(monkeypatch):
    import asyncio
    import importlib.util
    import sys
    from pathlib import Path
    monkeypatch.setattr(sys, "argv", ["agent_mail_server.py", "--synth-city-upgrade-tools-list-probe"])
    path = Path(__file__).resolve().parents[2] / "mcp_shim/agent_mail_server.py"
    spec = importlib.util.spec_from_file_location("upgrade_probe_shim", path)
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    calls = []
    monkeypatch.setattr(shim, "_request", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert len(asyncio.run(shim.mcp.list_tools())) == 41
    assert shim._ensure_registered() == {"ok": False, "error": {"code": "upgrade_probe_read_only"}}
    assert shim._state["member_id"] is None and shim._state["capability_token"] is None
    assert calls == []

    # A normal invocation retains the real registration and lifecycle guards.
    monkeypatch.setattr(sys, "argv", ["agent_mail_server.py"])
    normal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(normal)
    denied = {"ok": False, "error": {"code": "session_token_invalid"}}
    normal_calls = []
    def refuse(method, endpoint, **kwargs):
        normal_calls.append((method, endpoint))
        return denied
    monkeypatch.setattr(normal, "_request", refuse)
    assert normal.synth_city_ack_message(9) == denied
    assert normal._state["member_id"] is None and normal._state["capability_token"] is None
    assert normal_calls == [("POST", "/agent/register")]
    normal._state["closing"] = True
    assert normal.synth_city_ack_message(9) == {"ok": False, "error": {"code": "mail_generation_closing"}}
    assert normal_calls == [("POST", "/agent/register")]


def test_required_check_watch_passes_explicit_head_reviewer_and_attempt(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    calls=[]
    monkeypatch.setattr(shim,'_guard',lambda:None)
    monkeypatch.setattr(shim,'_request',lambda *a,**kw:calls.append((a,kw)) or {'ok':True})
    assert shim.synth_city_watch_required_checks(149,'fixture',0,'a'*40,45)=={'ok':True}
    assert calls==[(('POST','/required-check-watch'),{'json':{'work_item_id':149,
        'dispatch_nonce':'fixture','scope_revision':0,'head_sha':'a'*40,'reviewer_member_id':45}})]


def test_scope_amendment_and_negative_review_tools_bind_server_identity(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    calls = []
    monkeypatch.setattr(shim, "_guard", lambda: None)
    monkeypatch.setattr(shim, "_counts", lambda: {})
    monkeypatch.setattr(shim, "_dispatch_request", lambda method, path, **kwargs:
        calls.append((method, path, kwargs)) or {"ok": True, "data": {"id": 1}})
    assert shim.synth_city_request_scope_amendment(19, "attempt", "workspace", "Add tests",
        ["src/test.py"], ["edit_tests", "push_pr_head", "request_verification"], ["pytest -q"],
        ["No live factory"], 1, {}, "lease")["ok"]
    shim.synth_city_record_revision_review(19, 2, "attempt", "a" * 40, "Needs correction",
        "https://github.com/o/r/pull/5#pullrequestreview-1")
    shim.synth_city_withdraw_revision_review(19, 3, "attempt")
    shim.synth_city_end_submitted_revision(19, 3, "attempt", "Current negative review settled")
    assert [row[1] for row in calls] == ["/github-work-items/19/scope-amendments",
        "/github-work-items/19/revision-reviews", "/github-work-items/19/revision-reviews/3/withdraw",
        "/github-work-items/19/submitted-revision/end"]
    assert calls[0][2]["json"]["phase"] == "implementation"
    for _, _, kwargs in calls:
        assert not {"owner_member_id", "reviewer_member_id", "leader_member_id", "origin_kind"} & kwargs["json"].keys()


# --- #752: the reply tool with canonical thread roots and the request-routing guidance ----------

def test_request_routing_guidance_applies_to_each_member_writing_style():
    from app.services.team_communication_policy import team_communication_guidance
    for controlled in (True, False):
        text = team_communication_guidance(controlled)
        assert "Send a request that needs an answer as a context request addressed directly" in text
        assert "Do not send it as a thread reply" in text
        assert "canonical root id of the thread" in text
        assert "three short lines: Remaining, Estimate, Next" in text  # the existing guidance stays


def _bridge_shim_to_the_service(shim, db, member_id, monkeypatch, seen):
    """Route the shim's HTTP calls to the same service calls the routes make (not the HTTP layer)."""
    import asyncio

    from app.models.schemas import MailMessageCreate
    from app.services.agent_mail_service import agent_mail_service

    loop = asyncio.get_running_loop()

    def bridge(method, path, **kwargs):
        async def call():
            if method == "GET" and path.endswith("/thread"):
                thread = await agent_mail_service.get_thread(db, int(path.split("/")[2]), for_member_id=member_id)
                data = thread.model_dump(mode="json")
                seen.append(data)
                return {"ok": True, "data": data}
            if method == "POST" and path == "/messages":
                message = await agent_mail_service.send_message(
                    db, MailMessageCreate(**kwargs["json"]),
                    authenticated_sender_member_id=member_id, auto_nudge=False)
                return {"ok": True, "data": message.model_dump(mode="json")}
            if path.startswith("/agent/inbox"):
                return {"ok": True, "data": {"unread_count": 0, "pending_count": 0}}
            raise AssertionError((method, path, kwargs))
        return asyncio.run_coroutine_threadsafe(call(), loop).result(timeout=20)

    monkeypatch.setattr(shim, "_request", bridge)
    monkeypatch.setattr(shim, "_ensure_registered", lambda: {"ok": True})
    shim._state["member_id"] = member_id


async def _shim_members_and_root(db, tag, *, root_kind="context_request"):
    from app.models.database import MailTeamMember
    from app.models.schemas import MailMessageCreate
    from app.services.agent_mail_service import agent_mail_service

    asker = MailTeamMember(identity_key=f"repo:{tag}-a", repo_id=f"{tag}-a", repo_path="/tmp/a",
                           repo_name=f"{tag}-a", display_name=f"{tag}-a")
    asked = MailTeamMember(identity_key=f"repo:{tag}-b", repo_id=f"{tag}-b", repo_path="/tmp/b",
                           repo_name=f"{tag}-b", display_name=f"{tag}-b")
    db.add_all([asker, asked])
    await db.commit()
    root = await agent_mail_service.send_message(db, MailMessageCreate(
        kind=root_kind, sender_member_id=asker.id, recipient_member_id=asked.id, body_markdown="root"),
        auto_nudge=False)
    return asker, asked, root


@pytest.mark.asyncio
async def test_shim_reply_with_a_nested_id_answers_the_root_context_request(db, monkeypatch):
    """Service-backed shim sequence (the HTTP routes are not exercised): GET returns the canonical
    root, so a nested ORDINARY reply id still resolves the root context request."""
    import mcp_shim.agent_mail_server as shim
    from app.models.database import MailMessage
    from app.models.schemas import MailMessageCreate
    from app.services.agent_mail_service import agent_mail_service

    asker, asked, root = await _shim_members_and_root(db, "shimnest")
    follow_up = await agent_mail_service.send_message(db, MailMessageCreate(
        sender_member_id=asker.id, thread_root_id=root.id, body_markdown="follow-up"), auto_nudge=False)
    seen = []
    _bridge_shim_to_the_service(shim, db, asked.id, monkeypatch, seen)
    import asyncio
    result = await asyncio.to_thread(shim.synth_city_reply, follow_up.id, "Done.")
    assert result["ok"] is True and result["resolved_request"] is True, result
    assert seen[0]["root"]["id"] == root.id
    assert (await db.get(MailMessage, root.id)).request_status == "answered"


@pytest.mark.asyncio
async def test_shim_reply_in_a_thread_past_500_replies_keeps_a_canonical_root(db, monkeypatch):
    import asyncio

    import mcp_shim.agent_mail_server as shim
    from app.models.database import MailMessage

    asker, asked, root = await _shim_members_and_root(db, "shimlimit")
    db.add_all([MailMessage(kind="message", sender_member_id=asker.id, thread_root_id=root.id,
                            body_markdown=f"r{index}", audience_type="member", audience_id=str(asked.id))
                for index in range(501)])
    await db.commit()
    first_reply = (await db.scalars(MailMessage.__table__.select().with_only_columns(MailMessage.id)
                                    .where(MailMessage.thread_root_id == root.id).limit(1))).first()
    seen = []
    _bridge_shim_to_the_service(shim, db, asked.id, monkeypatch, seen)
    result = await asyncio.to_thread(shim.synth_city_reply, first_reply, "Done.")
    assert result["ok"] is True and result["resolved_request"] is True, result
    assert seen[0]["root"]["id"] == root.id
    assert seen[0]["replies_complete"] is False
    assert seen[0]["replies_incomplete_reason"] == "reply_limit"
    assert len(seen[0]["replies"]) == 500


@pytest.mark.asyncio
async def test_shim_does_not_resolve_a_legacy_nested_pending_request(db, monkeypatch):
    """Disclosed limitation: the shim only looks at the canonical root, so a legacy nested pending
    request stays pending when answered through the shim. Only an exact API answer resolves it."""
    import asyncio

    import mcp_shim.agent_mail_server as shim
    from app.models.database import MailMessage, MailReceipt

    asker, asked, root = await _shim_members_and_root(db, "shimlegacy", root_kind="message")
    nested = MailMessage(kind="context_request", sender_member_id=asker.id, recipient_member_id=asked.id,
                         thread_root_id=root.id, request_status="pending", body_markdown="nested ask",
                         audience_type="member", audience_id=str(asked.id))
    db.add(nested)
    await db.flush()
    db.add_all([MailReceipt(message_id=nested.id, member_id=asker.id),
                MailReceipt(message_id=nested.id, member_id=asked.id)])
    await db.commit()
    seen = []
    _bridge_shim_to_the_service(shim, db, asked.id, monkeypatch, seen)
    result = await asyncio.to_thread(shim.synth_city_reply, nested.id, "Plain reply.")
    assert result["ok"] is True and result["resolved_request"] is False, result
    assert seen[0]["root"]["id"] == root.id
    assert (await db.get(MailMessage, nested.id)).request_status == "pending"
