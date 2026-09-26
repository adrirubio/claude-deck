import asyncio
import importlib.util
import threading
import time
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def shim(monkeypatch):
    import mcp_shim.agent_mail_server as module

    monkeypatch.setattr(module, "PROVIDER", "pi-cli")
    monkeypatch.setattr(module, "_state", {
        "member_id": None, "capability_token": None, "session_key": "mcp:fixture",
        "offline_until": 0.0, "last_error": None, "closing": False, "closed": False,
    })
    monkeypatch.setattr(module, "_register_lock", threading.Lock())
    monkeypatch.setattr(module, "_heartbeat_stop", threading.Event())
    monkeypatch.setattr(module, "_heartbeat_thread", None)
    return module


def test_pi_bind_pending_handshake_uses_one_key_and_one_heartbeat(shim, monkeypatch):
    sent = []
    started = []
    responses = iter([
        {"ok": False, "error": {"code": "bind_pending", "status_code": 409}},
        {"ok": True, "data": {"member": {"id": 1}, "capability_token": "synthetic-token"}},
    ])
    def request(method, path, **kwargs):
        sent.append(kwargs["json"]["session_key"])
        return next(responses)
    monkeypatch.setattr(shim, "_request", request)
    monkeypatch.setattr(shim._heartbeat_stop, "wait", lambda _: False)
    monkeypatch.setattr(shim, "_start_heartbeat_thread", lambda: started.append(True))
    assert shim._ensure_registered()["ok"]
    assert sent == ["mcp:fixture", "mcp:fixture"] and len(started) == 1
    assert shim._state["capability_token"] == "synthetic-token"


def test_pi_bind_pending_deadline_and_other_refusals_do_not_restart(shim, monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(shim.time, "monotonic", lambda: clock[0])
    def wait(duration):
        clock[0] += duration
        return False
    monkeypatch.setattr(shim._heartbeat_stop, "wait", wait)
    def request(*_args, **_kwargs):
        calls.append(True)
        return {"ok": False, "error": {"code": "bind_pending"}}
    monkeypatch.setattr(shim, "_request", request)
    assert not shim._ensure_registered()["ok"]
    assert clock[0] == 15.0 and len(calls) < 20
    assert shim._heartbeat_thread is None
    calls.clear()
    monkeypatch.setattr(shim, "_request", lambda *_args, **_kwargs: calls.append(True) or {"ok": False, "error": {"code": "slot_claim_mismatch"}})
    assert not shim._ensure_registered()["ok"] and len(calls) == 1


def test_private_close_ack_is_terminal_and_never_returns_capability(shim, monkeypatch):
    shim._state["capability_token"] = "synthetic-token"
    calls = []
    monkeypatch.setattr(shim, "_request", lambda method, path, **kwargs: calls.append((method, path)) or {"ok": True, "data": {"closed": True}})
    assert shim.__deck_mail_close_generation() == {"ok": True, "closed": True}
    assert shim.__deck_mail_close_generation() == {"ok": True, "closed": True}
    assert calls == [("POST", "/agent/close")]
    assert shim._heartbeat_stop.is_set()
    assert not shim._ensure_registered()["ok"]


def test_private_close_without_ack_does_not_claim_terminal_success(shim, monkeypatch):
    shim._state["capability_token"] = "synthetic-token"
    monkeypatch.setattr(shim, "_request", lambda *_args, **_kwargs: {"ok": True, "data": {}})
    assert not shim.__deck_mail_close_generation()["ok"]
    assert not shim._state["closed"] and shim._state["closing"]


def test_post_transport_failure_preserves_outcome_uncertainty(shim, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("synthetic timeout")
    monkeypatch.setattr(shim.httpx, "request", timeout)
    result = shim._request("POST", "/messages", json={"body_markdown": "fixture"})
    assert result["outcome"] == "unknown"
    assert "Do not repeat" in result["suggestion"]


@pytest.mark.parametrize("provider", ["pi-cli", "codex-cli", "claude-code", "unknown"])
def test_actual_mcp_tool_list_keeps_close_private_to_pi(monkeypatch, provider):
    monkeypatch.setenv("CLAUDE_DECK_PROVIDER", provider)
    location = Path(__file__).resolve().parents[2] / "mcp_shim/agent_mail_server.py"
    spec = importlib.util.spec_from_file_location(f"fixture_shim_{provider}", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = {tool.name for tool in asyncio.run(module.mcp.list_tools())}
    assert ("__deck_mail_close_generation" in names) == (provider == "pi-cli")
    assert "deck_decide_continuation" in names
    assert len({name for name in names if name.startswith("deck_")}) == 25


def test_delayed_bind_pending_never_starts_a_send_after_deadline(shim, monkeypatch):
    clock = [0.0]
    budgets = []
    monkeypatch.setattr(shim.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(shim._heartbeat_stop, "wait", lambda duration: clock.__setitem__(0, clock[0] + duration) or False)
    def request(*_args, **kwargs):
        budgets.append(kwargs["total_timeout"])
        clock[0] += 14.9
        return {"ok": False, "error": {"code": "bind_pending"}}
    monkeypatch.setattr(shim, "_request", request)
    assert shim._ensure_registered()["error"]["code"] == "mail_startup_expired"
    assert budgets == [15.0] and clock[0] == 15.0


def test_registration_success_within_budget_does_not_retry(shim, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(shim.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(shim, "_start_heartbeat_thread", lambda: None)
    def request(*_args, **kwargs):
        assert kwargs["total_timeout"] == 15.0
        clock[0] += 14.99
        return {"ok": True, "data": {"member": {"id": 1}, "capability_token": "fixture"}}
    monkeypatch.setattr(shim, "_request", request)
    assert shim._ensure_registered()["ok"]


def test_http_total_budget_cancels_sequential_phases_and_preserves_uncertainty(shim, monkeypatch):
    cancelled = threading.Event()
    async def request(_self, *_args, **_kwargs):
        try:
            await asyncio.sleep(0.08)
            await asyncio.sleep(0.08)
        finally:
            cancelled.set()
        return httpx.Response(200, json={"member": {"id": 1}}, request=httpx.Request("POST", "http://fixture"))
    monkeypatch.setattr(shim.httpx.AsyncClient, "request", request)
    started = time.monotonic()
    result = shim._request("POST", "/agent/register", total_timeout=0.12, json={})
    assert time.monotonic() - started < 0.3
    assert result["outcome"] == "unknown"
    assert cancelled.wait(1.0)


def test_whoami_requests_share_the_registration_deadline(shim, monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(shim.time, "monotonic", lambda: clock[0])
    def request(method, _prefix, path, **kwargs):
        calls.append((path, shim._request_budget.deadline))
        if method == "POST":
            clock[0] = 14.5
            return {"ok": True, "data": {"member": {"id": 1}}}
        return {"ok": True, "data": {"members": [], "unread_count": 0, "pending_count": 0}}
    monkeypatch.setattr(shim, "_deck_request", request)
    monkeypatch.setattr(shim, "_start_heartbeat_thread", lambda: None)
    assert shim.deck_whoami()["ok"]
    assert len(calls) == 3 and all(deadline == 15.0 for _, deadline in calls)
    assert not hasattr(shim._request_budget, "deadline")
