"""Standalone Agent Mail MCP shim behavior."""
import json
from io import StringIO
from types import SimpleNamespace


def test_mcp_shim_imports_without_app_package_dependency():
    import mcp_shim.agent_mail_server as shim

    assert shim.mcp is not None
    assert callable(shim.deck_whoami)


def test_ensure_registered_refreshes_cached_member(monkeypatch):
    import mcp_shim.agent_mail_server as shim

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
    assert requests == [
        (
            "POST",
            "/agent/register",
            {
                "json": {
                    "source": "mcp",
                    "provider": shim.PROVIDER,
                    "cwd": "/tmp/repo",
                    "session_key": "mcp:test",
                    "pid": 1234,
                }
            },
        )
    ]


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
    assert thread.name == "claude-deck-agent-mail-heartbeat"
    assert thread.daemon is True


def test_deck_reply_only_uses_answer_for_context_requests(monkeypatch):
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

    result = shim.deck_reply(10, "Completed the work.")

    assert result["ok"] is True
    assert posted[0]["kind"] == "message"


def test_deck_list_team_uses_cached_roster(monkeypatch):
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

    result = shim.deck_list_team()

    assert result["ok"] is True
    assert requests[0][1] == "/team?sync=false"


def test_deck_check_inbox_returns_deck_unreachable_on_http_error(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    def fake_http_request(*args, **kwargs):
        raise shim.httpx.ConnectError("no server", request=SimpleNamespace())

    shim._state["member_id"] = None
    shim._state["offline_until"] = 0.0
    shim._state["last_error"] = None
    monkeypatch.setattr(shim.httpx, "request", fake_http_request)

    result = shim.deck_check_inbox()

    assert result["ok"] is False
    assert result["error"]["code"] == "deck_unreachable"


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


def test_deck_request_sends_the_session_token(monkeypatch):
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

    shim._deck_request("GET", "agent-mail", "/team")
    assert captured["headers"]["X-Deck-Session-Token"] == "tok-abc"


def test_deck_request_preserves_a_callers_headers(monkeypatch):
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

    shim._deck_request(
        "GET",
        "agent-bridge",
        "/x",
        headers={"X-Claude-Deck-Terminal-Token": "term"},
    )
    assert captured["headers"]["X-Claude-Deck-Terminal-Token"] == "term"
    assert captured["headers"]["X-Deck-Session-Token"] == "tok-abc"


def test_deck_request_sends_no_header_without_a_token(monkeypatch):
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

    shim._deck_request("GET", "agent-mail", "/team")
    assert "X-Deck-Session-Token" not in (captured["headers"] or {})


def test_deck_request_routes_by_api_prefix(monkeypatch):
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
        headers={"X-Deck-Session-Token": "request-secret"},
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

    result = shim.deck_request_work_item_approval(
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

    result = shim.deck_approve_work_item(
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


def test_deck_create_team_posts_to_team_api(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []

    def fake_team_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"id": 12, "name": "Team", "slots": []}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.deck_create_team(
        "Team",
        "Generated by an agent",
        [{"display_name": "Dev", "provider": "codex-cli", "repo_path": "/tmp/repo", "ui_color": "blue"}],
    )

    assert result["ok"] is True
    assert result["preset"]["id"] == 12
    assert requests[0][0:2] == ("POST", "/presets")
    assert requests[0][2]["json"]["created_by"] == "mcp"
    assert requests[0][2]["json"]["slots"][0]["ui_color"] == "blue"


def test_deck_attach_image_to_bridge_session_uploads_and_pastes(monkeypatch, tmp_path):
    import mcp_shim.agent_mail_server as shim

    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    requests = []

    def fake_bridge_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if (method, path) == ("GET", "/token"):
            return {"ok": True, "data": {"token": f"token-{len(requests)}"}}
        assert kwargs["headers"]["X-Claude-Deck-Terminal-Token"].startswith("token-")
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

    result = shim.deck_attach_image_to_bridge_session(
        "snazzy:0.0",
        str(image_path),
        submit=True,
        prompt="Inspect {path}",
    )

    assert result["ok"] is True
    assert result["attachment"]["id"] == 7
    assert result["paste"]["submitted"] is True


def test_deck_attach_image_to_bridge_session_rejects_missing_file():
    import mcp_shim.agent_mail_server as shim

    result = shim.deck_attach_image_to_bridge_session("snazzy:0.0", "/tmp/does-not-exist.png")

    assert result["ok"] is False
    assert result["error"]["code"] == "image_file_not_found"


def test_deck_list_bridge_attachments_uses_bridge_api(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []

    def fake_bridge_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if (method, path) == ("GET", "/token"):
            return {"ok": True, "data": {"token": "token"}}
        assert kwargs["headers"]["X-Claude-Deck-Terminal-Token"] == "token"
        return {"ok": True, "data": {"attachments": [{"id": 1}]}}

    monkeypatch.setattr(shim, "_bridge_request", fake_bridge_request)

    result = shim.deck_list_bridge_attachments("snazzy:0.0")

    assert result == {"ok": True, "attachments": [{"id": 1}]}
    assert requests[1][0:2] == ("GET", "/sessions/snazzy%3A0.0/attachments")


def test_deck_plan_team_launch_returns_plan_hash(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    def fake_team_request(method, path, **kwargs):
        assert (method, path) == ("POST", "/presets/12/plan-launch")
        assert kwargs["json"]["reuse_existing"] is False
        return {"ok": True, "data": {"plan_hash": "abc", "items": []}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.deck_plan_team_launch(12, reuse_existing=False)

    assert result == {"ok": True, "plan": {"plan_hash": "abc", "items": []}}


def test_deck_launch_team_requires_plan_hash(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    called = False

    def fake_team_request(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True, "data": {}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.deck_launch_team(12)

    assert result["ok"] is False
    assert result["error"]["code"] == "plan_hash_required"
    assert called is False


def test_deck_launch_team_forwards_confirm_hash(monkeypatch):
    import mcp_shim.agent_mail_server as shim

    requests = []

    def fake_team_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"launch_id": 9}}

    monkeypatch.setattr(shim, "_team_request", fake_team_request)

    result = shim.deck_launch_team(12, confirm_plan_hash="abc")

    assert result["ok"] is True
    assert result["launch"]["launch_id"] == 9
    assert requests[0][0:2] == ("POST", "/presets/12/launch")
    assert requests[0][2]["json"]["confirm_plan_hash"] == "abc"
    assert requests[0][2]["json"]["skip_plan_confirmation"] is False


def test_codex_hook_shim_emits_backend_json(monkeypatch, capsys):
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
            "--deck-url",
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
            "--deck-url",
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
        ["agent_mail_hook.py", "--deck-url", "http://deck", "--event", "session-start"],
    )
    monkeypatch.setattr(hook.sys, "stdin", StringIO("{}"))
    monkeypatch.setattr(hook.os, "getcwd", lambda: "/repo")
    monkeypatch.setattr(hook.os, "getppid", lambda: 123)

    assert hook.main() == 0
    assert capsys.readouterr().out == ""
