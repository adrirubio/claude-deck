"""Terminal grants never turn read-only access into pane input."""

from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from app.api.v1.agent_bridge import router as agent_bridge
from app.api.v1.cc_bridge import router as cc_bridge
from app.services.cc_bridge.pty_relay import PtyRelay


@pytest.fixture(autouse=True)
def terminal_grants(monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "test-operator-secret")
    agent_bridge._terminal_tokens._tokens.clear()
    cc_bridge._terminal_tokens._tokens.clear()
    yield
    agent_bridge._terminal_tokens._tokens.clear()
    cc_bridge._terminal_tokens._tokens.clear()


async def _issue(namespace: str, *, target: str = "deck:0.0", purpose: str = "readonly", headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(
            f"/api/v1/{namespace}/token",
            params={"target": target, "purpose": purpose},
            headers=headers,
        )


def _connect(namespace: str, target: str, token: str, mode: str):
    return TestClient(app).websocket_connect(
        f"/api/v1/{namespace}/sessions/{target}/terminal?mode={mode}",
        headers={"host": "testserver"},
        subprotocols=[f"deck-terminal.{token}"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["agent-bridge", "cc-bridge"])
async def test_interactive_token_requires_operator_and_binds_websocket(namespace, monkeypatch):
    for headers in (None, {"X-Deck-Session-Token": "agent-token"}, {"X-Deck-Operator-Token": "wrong"}):
        refused = await _issue(namespace, purpose="interactive", headers=headers)
        assert refused.status_code == 401
        assert "token" not in refused.json()

    wrong_mode = await _issue(
        namespace,
        purpose="interactive",
        headers={"X-Deck-Operator-Token": "test-operator-secret"},
    )
    with pytest.raises(WebSocketDisconnect) as refused:
        with _connect(namespace, "deck:0.0", wrong_mode.json()["token"], "readonly"):
            pass
    assert refused.value.code == 4401

    observed = []

    async def fake_run(self, websocket):
        observed.append((self.target, self.read_only))
        await websocket.accept()
        await websocket.close()

    monkeypatch.setattr(PtyRelay, "run", fake_run)
    granted = await _issue(
        namespace,
        purpose="interactive",
        headers={"X-Deck-Operator-Token": "test-operator-secret"},
    )
    assert granted.status_code == 200
    assert granted.headers["cache-control"] == "no-store"
    with _connect(namespace, "deck:0.0", granted.json()["token"], "interactive"):
        pass
    assert observed == [("deck:0.0", False)]


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["agent-bridge", "cc-bridge"])
async def test_interactive_token_refuses_unconfigured_operator_and_missing_target(namespace, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "")
    refused = await _issue(namespace, purpose="interactive", headers={"X-Deck-Operator-Token": ""})
    assert refused.status_code == 503
    assert "token" not in refused.json()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing_target = await client.get(f"/api/v1/{namespace}/token", params={"purpose": "readonly"})
    assert missing_target.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["agent-bridge", "cc-bridge"])
async def test_readonly_grant_cannot_change_mode_target_or_replay(namespace, monkeypatch):
    observed = []

    async def fake_run(self, websocket):
        observed.append((self.target, self.read_only))
        await websocket.accept()
        await websocket.close()

    monkeypatch.setattr(PtyRelay, "run", fake_run)
    token = (await _issue(namespace)).json()["token"]
    with pytest.raises(WebSocketDisconnect) as refused:
        with _connect(namespace, "deck:0.0", token, "interactive"):
            pass
    assert refused.value.code == 4401

    token = (await _issue(namespace)).json()["token"]
    with pytest.raises(WebSocketDisconnect) as refused:
        with _connect(namespace, "other:0.0", token, "readonly"):
            pass
    assert refused.value.code == 4401

    token = (await _issue(namespace)).json()["token"]
    with _connect(namespace, "deck:0.0", token, "readonly"):
        pass
    with pytest.raises(WebSocketDisconnect) as refused:
        with _connect(namespace, "deck:0.0", token, "readonly"):
            pass
    assert refused.value.code == 4401
    assert observed == [("deck:0.0", True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace,store", [
    ("agent-bridge", agent_bridge._terminal_tokens),
    ("cc-bridge", cc_bridge._terminal_tokens),
])
async def test_expired_and_unknown_mode_grants_fail_closed(namespace, store):
    token = (await _issue(namespace)).json()["token"]
    store._tokens[token] = replace(store._tokens[token], issued_at=store._tokens[token].issued_at - 31)
    with pytest.raises(WebSocketDisconnect) as refused:
        with _connect(namespace, "deck:0.0", token, "readonly"):
            pass
    assert refused.value.code == 4401

    token = (await _issue(namespace)).json()["token"]
    with pytest.raises(WebSocketDisconnect) as refused:
        with _connect(namespace, "deck:0.0", token, "other"):
            pass
    assert refused.value.code == 4401


@pytest.mark.asyncio
async def test_attachment_grant_cannot_be_used_for_terminal():
    token = (await _issue("agent-bridge", purpose="attachment")).json()["token"]
    with pytest.raises(WebSocketDisconnect) as refused:
        with _connect("agent-bridge", "deck:0.0", token, "readonly"):
            pass
    assert refused.value.code == 4401


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["agent-bridge", "cc-bridge"])
async def test_query_token_and_missing_subprotocol_never_authorize_terminal(namespace):
    token = (await _issue(namespace)).json()["token"]
    with pytest.raises(WebSocketDisconnect) as refused:
        with TestClient(app).websocket_connect(
            f"/api/v1/{namespace}/sessions/deck:0.0/terminal?mode=readonly&token={token}",
            headers={"host": "testserver"},
        ):
            pass
    assert refused.value.code == 4401


def test_readonly_relay_rejects_mode_control_upgrade():
    readonly = PtyRelay("deck:0.0", read_only=True)
    readonly.set_read_only(False)
    assert readonly.read_only is True

    interactive = PtyRelay("deck:0.0", read_only=False)
    interactive.set_read_only(True)
    assert interactive.read_only is True
    interactive.set_read_only(False)
    assert interactive.read_only is False
