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
