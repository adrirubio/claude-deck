"""External Agent Mail orchestration API behavior."""
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.database import MailAgentSession, MailTeamMember
from app.services.external_agent_mail_service import external_agent_mail_service


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean_external_rate_limits(monkeypatch):
    external_agent_mail_service._send_windows.clear()
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: [])


async def _member(db, repo_id, name):
    member = MailTeamMember(
        identity_key=f"repo:{repo_id}",
        repo_id=repo_id,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def _actor_token(client, key="openclaw", name="OpenClaw"):
    resp = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={
            "actor_key": key,
            "display_name": name,
            "kind": "external_tool",
            "description": "local orchestrator",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    return body["token"], body["actor"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_external_actor_registration_and_auth(client, db):
    await _member(db, "repo-alpha", "alpha")
    token, actor = await _actor_token(client)

    assert actor["display_name"] == "OpenClaw"

    unauthenticated = await client.get("/api/v1/external/agent-mail/members")
    assert unauthenticated.status_code == 401

    resp = await client.get("/api/v1/external/agent-mail/members", headers=_auth(token))
    assert resp.status_code == 200
    members = resp.json()["members"]
    assert members[0]["display_name"] == "alpha"
    assert "wake_state" in members[0]

    me = await client.get("/api/v1/external/agent-mail/actors/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["actor_key"] == "openclaw"


@pytest.mark.asyncio
async def test_external_context_request_preserves_sender_attribution(client, db):
    recipient = await _member(db, "repo-beta", "beta")
    token, _ = await _actor_token(client)

    resp = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient.id,
            "subject": "Need repo context",
            "body_markdown": "Please inspect the API owner.",
            "why_needed": "OpenClaw validation",
            "files_or_symbols": ["backend/app/api/v1/agent_mail.py"],
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["actor"]["display_name"] == "OpenClaw"
    assert body["message"]["sender_name"] == "OpenClaw"
    assert body["message"]["sender_type"] == "external_actor"
    assert body["message"]["sender_member_id"] is None
    assert body["message"]["sender_actor_id"] == body["actor"]["id"]
    assert body["recipients"][0]["member_id"] == recipient.id

    messages = await client.get("/api/v1/agent-mail/messages")
    assert messages.status_code == 200
    assert messages.json()[0]["sender_name"] == "OpenClaw"
    assert messages.json()[0]["sender_type"] == "external_actor"


@pytest.mark.asyncio
async def test_legacy_message_create_cannot_spoof_external_actor(client, db):
    recipient = await _member(db, "repo-beta", "beta")
    _, actor = await _actor_token(client)

    resp = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "sender_actor_id": actor["id"],
            "recipient_member_id": recipient.id,
            "body_markdown": "Pretend to be OpenClaw.",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["sender_actor_id"] is None
    assert body["sender_type"] == "director"
    assert body["sender_name"] == "Director"


@pytest.mark.asyncio
async def test_external_actor_cannot_read_other_actor_threads(client, db):
    recipient = await _member(db, "repo-beta", "beta")
    token, _ = await _actor_token(client, key="openclaw", name="OpenClaw")
    other_token, _ = await _actor_token(client, key="runner", name="Runner")
    created = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient.id,
            "subject": "Private request",
            "body_markdown": "Only OpenClaw should read this.",
        },
    )
    message_id = created.json()["message"]["id"]

    thread = await client.get(
        f"/api/v1/external/agent-mail/threads/{message_id}",
        headers=_auth(other_token),
    )
    status = await client.get(
        f"/api/v1/external/agent-mail/requests/{message_id}/status",
        headers=_auth(other_token),
    )
    wait = await client.get(
        f"/api/v1/external/agent-mail/requests/{message_id}/wait?timeout_seconds=0",
        headers=_auth(other_token),
    )

    assert thread.status_code == 403
    assert status.status_code == 403
    assert wait.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["codex-cli", "claude-code"])
async def test_external_delivery_reports_non_tmux_agent_as_delivered_waiting(client, db, provider):
    recipient = await _member(db, "repo-beta", "beta")
    db.add(
        MailAgentSession(
            member_id=recipient.id,
            provider=provider,
            source="mcp",
            session_key="mcp:beta",
            cwd=recipient.repo_path,
            mailbox_status="connected",
        )
    )
    await db.commit()
    token, _ = await _actor_token(client)

    resp = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient.id,
            "subject": "Need repo context",
            "body_markdown": "Please inspect this.",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["delivery_state"] == "delivered_waiting"
    assert body["recipients"][0]["status"] == "delivered_waiting"
    assert body["recipients"][0]["wake_state"] == "delivered_waiting"
    assert body["recipients"][0]["wake_attempted"] is False
    assert body["recipients"][0]["wake_succeeded"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "display_name"),
    [("codex-cli", "Codex"), ("claude-code", "Claude Code")],
)
async def test_external_delivery_reports_tmux_wake_success(
    client,
    db,
    tmp_path,
    monkeypatch,
    provider,
    display_name,
):
    cwd = tmp_path / "repo-beta"
    cwd.mkdir()
    fake = [
        {
            "provider": provider,
            "provider_display_name": display_name,
            "tmux_target": "deck:0.1",
            "session_name": "deck",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", lambda delay: None)

    token, _ = await _actor_token(client)
    members = await client.get("/api/v1/external/agent-mail/members", headers=_auth(token))
    recipient_id = members.json()["members"][0]["id"]

    resp = await client.post(
        "/api/v1/external/agent-mail/messages",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient_id,
            "subject": "Wake check",
            "body_markdown": "Please check your inbox.",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["delivery_state"] == "wake_succeeded"
    assert body["recipients"][0]["status"] == "wake_succeeded"
    assert body["recipients"][0]["wake_method"] == "tmux"
    tmux_calls = [call for call in calls if call[0][0] == "tmux"]
    assert len(tmux_calls) == 2


@pytest.mark.asyncio
async def test_external_request_status_wait_and_ack_lifecycle(client, db):
    recipient = await _member(db, "repo-beta", "beta")
    token, _ = await _actor_token(client)
    created = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient.id,
            "subject": "Round trip",
            "body_markdown": "Please answer.",
        },
    )
    message_id = created.json()["message"]["id"]

    pending = await client.get(
        f"/api/v1/external/agent-mail/requests/{message_id}/status",
        headers=_auth(token),
    )
    assert pending.status_code == 200
    assert pending.json()["request_status"] == "pending"

    answer = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "answer",
            "sender_member_id": recipient.id,
            "thread_root_id": message_id,
            "body_markdown": "Here is the answer.",
        },
    )
    assert answer.status_code == 200

    waited = await client.get(
        f"/api/v1/external/agent-mail/requests/{message_id}/wait?timeout_seconds=1",
        headers=_auth(token),
    )
    assert waited.status_code == 200
    assert waited.json()["answered"] is True
    assert waited.json()["request_status"] == "answered"

    acked = await client.post(
        f"/api/v1/external/agent-mail/requests/{message_id}/ack",
        headers=_auth(token),
    )
    assert acked.status_code == 200
    assert acked.json()["acknowledged"] is True
    assert acked.json()["request_status"] == "acknowledged"


@pytest.mark.asyncio
async def test_external_actor_can_reply_in_own_thread(client, db):
    recipient = await _member(db, "repo-beta", "beta")
    token, _ = await _actor_token(client)
    created = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient.id,
            "subject": "Thread",
            "body_markdown": "Initial request.",
        },
    )
    message_id = created.json()["message"]["id"]

    reply = await client.post(
        f"/api/v1/external/agent-mail/threads/{message_id}/replies",
        headers=_auth(token),
        json={
            "body_markdown": "Adding external follow-up detail.",
        },
    )

    assert reply.status_code == 200
    assert reply.json()["message"]["thread_root_id"] == message_id

    thread = await client.get(
        f"/api/v1/external/agent-mail/threads/{message_id}",
        headers=_auth(token),
    )
    assert thread.status_code == 200
    assert len(thread.json()["replies"]) == 1
    assert thread.json()["replies"][0]["sender_name"] == "OpenClaw"


@pytest.mark.asyncio
async def test_external_message_rate_limit_returns_429(client, db, monkeypatch):
    recipient = await _member(db, "repo-beta", "beta")
    token, _ = await _actor_token(client)
    monkeypatch.setattr(
        "app.services.external_agent_mail_service.EXTERNAL_RATE_LIMIT_MAX_MESSAGES",
        1,
    )

    first = await client.post(
        "/api/v1/external/agent-mail/messages",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient.id,
            "body_markdown": "one",
        },
    )
    second = await client.post(
        "/api/v1/external/agent-mail/messages",
        headers=_auth(token),
        json={
            "recipient_member_id": recipient.id,
            "body_markdown": "two",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "external_agent_mail_rate_limited"
    assert int(second.headers["retry-after"]) >= 1
