"""HTTP surface for team and messages."""
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.database import MailAgentSession, MailTeamMember


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _member(db, repo_id, name):
    member = MailTeamMember(
        repo_id=repo_id,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
async def test_team_empty(client):
    resp = await client.get("/api/v1/agent-mail/team?sync=false")
    assert resp.status_code == 200
    assert resp.json() == {"members": []}


@pytest.mark.asyncio
async def test_patch_member_sets_role_and_charter(client, db):
    member = await _member(db, "ra", "alpha")
    resp = await client.patch(
        f"/api/v1/agent-mail/members/{member.id}",
        json={
            "display_name": "Backend",
            "role": "backend expert",
            "charter": "Owns API",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Backend"
    assert body["role"] == "backend expert"


@pytest.mark.asyncio
async def test_patch_unknown_member_404(client):
    resp = await client.patch("/api/v1/agent-mail/members/999", json={"role": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_and_thread_roundtrip(client, db):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    resp = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "context_request",
            "sender_member_id": a.id,
            "recipient_member_id": b.id,
            "subject": "q",
            "body_markdown": "?",
        },
    )
    assert resp.status_code == 200
    root_id = resp.json()["id"]

    resp = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "answer",
            "sender_member_id": b.id,
            "thread_root_id": root_id,
            "body_markdown": "!",
        },
    )
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/agent-mail/messages/{root_id}/thread")
    assert resp.status_code == 200
    assert resp.json()["root"]["request_status"] == "answered"
    assert len(resp.json()["replies"]) == 1


@pytest.mark.asyncio
async def test_invalid_kind_is_400(client, db):
    b = await _member(db, "rb", "beta")
    resp = await client.post(
        "/api/v1/agent-mail/messages",
        json={"kind": "bogus", "recipient_member_id": b.id, "body_markdown": "x"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_inbox_read_ack_endpoints(client, db):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    resp = await client.post(
        "/api/v1/agent-mail/messages",
        json={"sender_member_id": a.id, "recipient_member_id": b.id, "body_markdown": "hi"},
    )
    msg_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/agent-mail/agent/inbox?member_id={b.id}")
    assert resp.json()["unread_count"] == 1

    await client.post(f"/api/v1/agent-mail/messages/{msg_id}/read", json={"member_id": b.id})
    resp = await client.get(f"/api/v1/agent-mail/agent/inbox?member_id={b.id}")
    assert resp.json()["unread_count"] == 0

    resp = await client.post(f"/api/v1/agent-mail/messages/{msg_id}/ack", json={"member_id": b.id})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_agent_inbox_refreshes_stale_mcp_session(client, db):
    member = await _member(db, "ra", "alpha")
    stale_seen_at = datetime.utcnow() - timedelta(hours=3)
    session = MailAgentSession(
        member_id=member.id,
        provider="codex-cli",
        source="mcp",
        session_key="mcp:abc",
        cwd=member.repo_path,
        mailbox_status="offline",
        last_seen_at=stale_seen_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    resp = await client.get(f"/api/v1/agent-mail/agent/inbox?member_id={member.id}")

    assert resp.status_code == 200
    await db.refresh(session)
    assert session.mailbox_status == "connected"
    assert session.last_seen_at > stale_seen_at

    resp = await client.get("/api/v1/agent-mail/team?sync=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["members"][0]["status"] == "connected"
