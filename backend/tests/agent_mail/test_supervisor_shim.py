"""Supervisor transport uses an external actor credential without member registration."""
import json

import httpx
import pytest


def test_supervisor_checkin_fails_closed_without_actor_credential(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    monkeypatch.delenv("CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN", raising=False)
    monkeypatch.setattr(shim, "_guard", lambda: pytest.fail("Member registration must not run"))
    monkeypatch.setattr(shim.httpx, "request", lambda *a, **kw: pytest.fail("HTTP must not run"))
    assert shim.deck_supervisor_checkin(7, "2026-10-13T02:00:00Z") == {
        "ok": False, "error": {"code": "supervisor_actor_credential_missing"}}


def test_supervisor_checkin_sends_only_actor_authentication(monkeypatch):
    import mcp_shim.agent_mail_server as shim
    monkeypatch.setenv("CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN", "synthetic-private-actor-token")
    monkeypatch.setitem(shim._state, "capability_token", "synthetic-private-member-token")
    monkeypatch.setattr(shim, "_guard", lambda: pytest.fail("Member registration must not run"))
    def request(method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/external-agent-mail/supervisor-checkin")
        assert kwargs["headers"] == {"Authorization": "Bearer synthetic-private-actor-token"}
        assert kwargs["json"] == {"preset_id": 7, "next_check_at": "2026-10-13T02:00:00Z", "note": "Checked."}
        return httpx.Response(200, json={"status": "healthy"}, request=httpx.Request(method, url))
    monkeypatch.setattr(shim.httpx, "request", request)
    assert shim.deck_supervisor_checkin(7, "2026-10-13T02:00:00Z", "Checked.") == {
        "ok": True, "data": {"status": "healthy"}}


@pytest.mark.parametrize("mode", ["http", "timeout"])
def test_supervisor_transport_never_returns_error_prose(monkeypatch, mode):
    import mcp_shim.agent_mail_server as shim
    secret = "synthetic-private-actor-token"
    monkeypatch.setenv("CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN", secret)
    def request(method, url, **kwargs):
        if mode == "timeout":
            raise httpx.ReadTimeout(secret)
        return httpx.Response(403, json={"detail": secret}, request=httpx.Request(method, url))
    monkeypatch.setattr(shim.httpx, "request", request)
    result = shim.deck_supervisor_checkin(7, "2026-10-13T02:00:00Z")
    assert not result["ok"]
    assert secret not in json.dumps(result)
    if mode == "timeout":
        assert result["outcome"] == "unknown"
