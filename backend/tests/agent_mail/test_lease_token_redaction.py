"""Lease tokens reach only their owner's authenticated inbox.

The dispatch brief and the release reminder carry a workspace lease token, so
the owner can report status. The all-messages list, the thread read and the
external-actor thread read do not authenticate a recipient, so they must never
return a lease token, in the body or in the payload.
"""
import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service

from tests.agent_mail.test_api import _member, _session_headers

LEASE = "1fad69cb13958580"
SHA = "0b6274c9ced07978fb14976aa84d87e58a86ef28"
BODY = (
    f"Release the workspace for #5 at {SHA}:\n\n"
    "```\n"
    "deck_report_dispatch_status(\n"
    "    work_item_id=1,\n"
    '    status="workspace_released",\n'
    f'    lease_token="{LEASE}",\n'
    ")\n"
    "```\n"
    f"Unquoted form: lease_token={LEASE}; single quotes: lease_token='{LEASE}'."
)


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _brief(db, owner):
    return await agent_mail_service.send_message(db, MailMessageCreate(
        kind="message",
        recipient_member_id=owner.id,
        subject="Release needed: issue #5",
        body_markdown=BODY,
        payload={"kind": "github_lease_release_reminder", "work_item_id": 1,
                 "lease_token": LEASE, "nested": {"lease_token": LEASE}},
    ))


@pytest.mark.asyncio
async def test_message_list_never_returns_a_lease_token(client, db):
    owner = await _member(db, "lease-owner", "lease-owner")
    await _brief(db, owner)

    response = await client.get("/api/v1/agent-mail/messages")

    assert response.status_code == 200
    assert LEASE not in response.text
    message = next(m for m in response.json() if m["subject"] == "Release needed: issue #5")
    assert 'lease_token="[redacted]"' in message["body_markdown"]
    assert "lease_token=[redacted]" in message["body_markdown"]
    assert "lease_token='[redacted]'" in message["body_markdown"]
    assert SHA in message["body_markdown"], "a commit SHA is public and stays"
    assert message["payload"]["lease_token"] == "[redacted]"
    assert message["payload"]["nested"]["lease_token"] == "[redacted]"
    assert message["payload"]["work_item_id"] == 1


@pytest.mark.asyncio
async def test_thread_read_never_returns_a_lease_token(client, db):
    owner = await _member(db, "lease-thread", "lease-thread")
    sent = await _brief(db, owner)

    for query in ("", f"?member_id={owner.id}"):
        response = await client.get(f"/api/v1/agent-mail/messages/{sent.id}/thread{query}")
        assert response.status_code == 200
        assert LEASE not in response.text
        assert 'lease_token="[redacted]"' in response.json()["root"]["body_markdown"]


@pytest.mark.asyncio
async def test_owner_inbox_still_delivers_the_lease_token(client, db):
    owner = await _member(db, "lease-inbox", "lease-inbox")
    headers = await _session_headers(db, owner, "lease-inbox")
    await _brief(db, owner)

    response = await client.get("/api/v1/agent-mail/agent/inbox", headers=headers)

    assert response.status_code == 200
    assert f'lease_token="{LEASE}"' in response.json()["messages"][0]["body_markdown"]


@pytest.mark.asyncio
async def test_external_actor_thread_never_returns_a_lease_token(client, db):
    owner = await _member(db, "lease-external", "lease-external")
    actor = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={"actor_key": "lease-supervisor", "display_name": "Supervisor"},
    )
    bearer = {"Authorization": f"Bearer {actor.json()['token']}"}
    sent = await client.post(
        "/api/v1/external/agent-mail/messages",
        headers=bearer,
        json={"recipient_member_id": owner.id, "subject": "Status", "body_markdown": BODY},
    )
    assert sent.status_code == 200, sent.text
    root_id = sent.json()["message"]["id"]

    response = await client.get(f"/api/v1/external/agent-mail/threads/{root_id}", headers=bearer)

    assert response.status_code == 200, response.text
    assert LEASE not in response.text


@pytest.mark.asyncio
async def test_external_request_status_reads_never_return_a_lease_token(client, db):
    owner = await _member(db, "lease-request", "lease-request")
    actor = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={"actor_key": "lease-requester", "display_name": "Supervisor"},
    )
    bearer = {"Authorization": f"Bearer {actor.json()['token']}"}
    sent = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=bearer,
        json={"recipient_member_id": owner.id, "body_markdown": BODY},
    )
    assert sent.status_code == 200, sent.text
    root_id = sent.json()["message"]["id"]

    reads = [
        ("GET", f"/api/v1/external/agent-mail/requests/{root_id}/status"),
        ("GET", f"/api/v1/external/agent-mail/requests/{root_id}/wait?timeout_seconds=0"),
        ("POST", f"/api/v1/external/agent-mail/requests/{root_id}/ack"),
        ("POST", f"/api/v1/external/agent-mail/requests/{root_id}/actor-ack"),
    ]
    for method, url in reads:
        response = await client.request(method, url, headers=bearer)
        assert response.status_code == 200, (url, response.text)
        assert LEASE not in response.text, url
        assert 'lease_token="[redacted]"' in response.json()["root"]["body_markdown"], url
