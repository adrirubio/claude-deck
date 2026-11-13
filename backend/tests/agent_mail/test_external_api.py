"""External Agent Mail orchestration API behavior."""
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import AgentTeamPreset, AgentTeamSlot, MailAgentSession, MailTeamMember
from app.services.agent_mail_service import agent_mail_service
from app.services.external_agent_mail_service import external_agent_mail_service
from app.utils import peer_process
from app.utils.repo_utils import derive_repo_identity


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "test-director-key")
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
        headers={"X-Synth-City-Operator-Token": "test-director-key"},
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
    assert members[0]["agent_status"]["session_state"] == "offline"
    assert members[0]["agent_status"]["wake_state"] == "cannot_wake"
    assert members[0]["agent_status"]["wake_reason"] == "wake_target_unbound"

    me = await client.get("/api/v1/external/agent-mail/actors/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["actor_key"] == "openclaw"


@pytest.mark.asyncio
async def test_external_broadcast_requires_scoped_audience(client, db):
    scoped_member = await _member(db, "broadcast-repo", "broadcast-repo")
    other_member = await _member(db, "other-repo", "other-repo")
    token, _ = await _actor_token(client)
    endpoint = "/api/v1/external/agent-mail/broadcasts"
    base = {"subject": "Scoped notice", "body_markdown": "For one repository."}

    anonymous = await client.post(endpoint, json={
        **base,
        "audience_type": "repository",
        "audience_id": "broadcast-repo",
    })
    implicit_global = await client.post(
        endpoint,
        headers=_auth(token),
        json=base,
    )
    operator_global = await client.post(
        endpoint,
        headers=_auth(token),
        json={**base, "audience_type": "operator_global"},
    )
    sent = await client.post(
        endpoint,
        headers=_auth(token),
        json={
            **base,
            "audience_type": "repository",
            "audience_id": "broadcast-repo",
        },
    )

    assert anonymous.status_code == 401
    assert (implicit_global.status_code, implicit_global.json()["detail"]) == (
        400,
        "broadcast_audience_required",
    )
    assert (operator_global.status_code, operator_global.json()["detail"]) == (
        403,
        "operator_global_forbidden",
    )
    assert sent.status_code == 200
    assert sent.json()["message"]["audience_type"] == "repository"
    assert sent.json()["message"]["audience_id"] == "broadcast-repo"
    assert {recipient["member_id"] for recipient in sent.json()["recipients"]} == {
        scoped_member.id
    }
    assert other_member.id not in {
        recipient["member_id"] for recipient in sent.json()["recipients"]
    }


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

    messages = await client.get("/api/v1/agent-mail/messages", headers={"X-Synth-City-Operator-Token": "test-director-key"})
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

    assert resp.status_code == 401
    assert resp.json()["detail"] == "session_token_required"


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
    roster = await client.get("/api/v1/external/agent-mail/members", headers=_auth(token))
    member = next(m for m in roster.json()["members"] if m["id"] == recipient.id)
    assert member["agent_status"]["session_state"] == "online"
    assert member["agent_status"]["wake_state"] == "cannot_wake"
    assert member["agent_status"]["wake_reason"] == "wake_target_unbound"


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
    preset = AgentTeamPreset(name="External wake team")
    db.add(preset)
    await db.flush()
    identity = derive_repo_identity(str(cwd))
    slot = AgentTeamSlot(
        preset_id=preset.id, position=0, display_name="Recipient",
        provider=provider, repo_id=identity["repo_id"],
        repo_path=identity["repo_root"], repo_name=identity["repo_name"],
    )
    db.add(slot)
    await db.flush()
    fake[0]["team_preset_id"] = preset.id
    fake[0]["team_slot_id"] = slot.id
    recipient = await agent_mail_service.get_or_create_slot_member(db, slot)
    db.add(MailAgentSession(
        member_id=recipient.id, provider=provider, source="mcp",
        session_key=f"mcp:external:{provider}", cwd=str(cwd),
        team_preset_id=preset.id, team_slot_id=slot.id,
        mailbox_status="connected", last_seen_at=datetime.utcnow(),
        capability_token_hash=agent_mail_service.hash_capability_token("external-bound-token"),
        bound_pane_pid=4242, bound_pane_proc_start="external-start",
        wake_enabled=True,
    ))
    await db.commit()
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda _pid, _start: True)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            stdout="%7|4242" if command[1] == "display-message" else "",
            stderr="", returncode=0,
        )

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
    assert len(tmux_calls) == 4
    assert tmux_calls[1][0][3] == "%7"
    assert [call[0][1] for call in tmux_calls] == [
        "display-message", "send-keys", "display-message", "send-keys"
    ]


@pytest.mark.asyncio
async def test_external_request_status_wait_and_ack_lifecycle(client, db):
    recipient = await _member(db, "repo-beta", "beta")
    recipient_token = "recipient-session-token"
    db.add(
        MailAgentSession(
            member_id=recipient.id,
            provider="codex-cli",
            source="mcp",
            session_key="mcp:external-answer",
            cwd=recipient.repo_path,
            mailbox_status="connected",
            capability_token_hash=agent_mail_service.hash_capability_token(
                recipient_token
            ),
        )
    )
    await db.commit()
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
        headers={"X-Synth-City-Session-Token": recipient_token},
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


# --- #752: external actors and canonical thread roots ----------------------------------------

@pytest.mark.asyncio
async def test_external_actor_reply_with_a_nested_id_is_stored_under_the_canonical_root(client, db):
    recipient = await _member(db, "repo-nested-ext", "nested-ext")
    token, _ = await _actor_token(client)
    created = await client.post(
        "/api/v1/external/agent-mail/context-requests", headers=_auth(token),
        json={"recipient_member_id": recipient.id, "subject": "Thread", "body_markdown": "Initial request."})
    root_id = created.json()["message"]["id"]
    first = await client.post(
        f"/api/v1/external/agent-mail/threads/{root_id}/replies", headers=_auth(token),
        json={"body_markdown": "First follow-up."})
    first_id = first.json()["message"]["id"]
    nested = await client.post(
        f"/api/v1/external/agent-mail/threads/{first_id}/replies", headers=_auth(token),
        json={"body_markdown": "Follow-up by a reply id."})
    assert nested.status_code == 200, nested.text
    assert nested.json()["message"]["thread_root_id"] == root_id
    assert [item["member_id"] for item in nested.json()["recipients"]] == [recipient.id]
    thread = await client.get(f"/api/v1/external/agent-mail/threads/{root_id}", headers=_auth(token))
    assert len(thread.json()["replies"]) == 2


@pytest.mark.asyncio
async def test_external_actor_cannot_reach_a_foreign_thread_through_a_nested_id(client, db):
    from app.models.database import MailMessage

    member = await _member(db, "repo-foreign-ext", "foreign-ext")
    other = await _member(db, "repo-foreign-ext-2", "foreign-ext-2")
    owner_token, _ = await _actor_token(client)
    other_token, other_actor = await _actor_token(client, key="runner", name="Runner")
    created = await client.post(
        "/api/v1/external/agent-mail/context-requests", headers=_auth(owner_token),
        json={"recipient_member_id": member.id, "subject": "Thread", "body_markdown": "Owner request."})
    root_id = created.json()["message"]["id"]
    # An older release could leave another actor's own row inside this thread.
    planted = MailMessage(kind="message", thread_root_id=root_id, sender_actor_id=other_actor["id"],
                          body_markdown="planted", audience_type="member", audience_id=str(member.id))
    db.add(planted)
    await db.commit()
    before = (await client.get(f"/api/v1/external/agent-mail/threads/{root_id}",
                               headers=_auth(owner_token))).json()["replies"]
    for target in (root_id, planted.id):
        refused = await client.post(
            f"/api/v1/external/agent-mail/threads/{target}/replies", headers=_auth(other_token),
            json={"body_markdown": "Not mine."})
        assert refused.status_code in {403, 404}, (target, refused.status_code, refused.text)
    after = (await client.get(f"/api/v1/external/agent-mail/threads/{root_id}",
                              headers=_auth(owner_token))).json()["replies"]
    assert [item["id"] for item in after] == [item["id"] for item in before]
    assert other.id != member.id


@pytest.mark.asyncio
async def test_external_service_refuses_a_request_with_a_thread_id_and_accepts_a_plain_message(client, db):
    from app.models.database import MailExternalActor
    from app.models.schemas import ExternalAgentMailMessageRequest

    member = await _member(db, "repo-ext-req", "ext-req")
    token, actor_data = await _actor_token(client, key="ext-req", name="ExtReq")
    created = await client.post(
        "/api/v1/external/agent-mail/context-requests", headers=_auth(token),
        json={"recipient_member_id": member.id, "subject": "Thread", "body_markdown": "Owner request."})
    root_id = created.json()["message"]["id"]
    actor = await db.get(MailExternalActor, actor_data["id"])
    request = ExternalAgentMailMessageRequest(recipient_member_id=member.id, body_markdown="Nested request")
    from sqlalchemy import func, select
    from app.models.database import MailMessage
    before = await db.scalar(select(func.count()).select_from(MailMessage))
    with pytest.raises(ValueError, match="a request starts its own thread"):
        await external_agent_mail_service.send_message(
            db, actor, request, kind="context_request", recipient_member_id=member.id, thread_root_id=root_id)
    assert await db.scalar(select(func.count()).select_from(MailMessage)) == before
    ok = await client.post(f"/api/v1/external/agent-mail/threads/{root_id}/replies", headers=_auth(token),
                           json={"body_markdown": "A plain follow-up."})
    assert ok.status_code == 200 and ok.json()["message"]["thread_root_id"] == root_id
