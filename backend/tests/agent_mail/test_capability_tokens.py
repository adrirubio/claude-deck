"""Spec §3.7 — capability token tests for PR0."""

import hashlib
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text

import app.api.v1.agent_mail as agent_mail_routes
from app.config import Settings, settings
from app.database import get_db
from app.main import app
from app.models.database import (
    AgentPaneBinding,
    AgentTeamPreset,
    AgentTeamSlot,
    MailAgentSession,
    MailMessage,
    MailReceipt,
    MailTeamMember,
)
from app.models.schemas import MailAgentRegisterRequest
from app.services.agent_mail_service import agent_mail_service
from app.utils.peer_process import PeerPane
from app.utils.repo_utils import derive_repo_identity


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def team_slots(db, tmp_path):
    repo = tmp_path / "binding-repo"
    repo.mkdir()
    identity = derive_repo_identity(str(repo))
    preset = AgentTeamPreset(name="Binding team")
    db.add(preset)
    await db.flush()
    slots = [
        AgentTeamSlot(
            preset_id=preset.id,
            position=position,
            display_name=name,
            provider="codex-cli",
            repo_id=identity["repo_id"],
            repo_path=identity["repo_root"],
            repo_name=identity["repo_name"],
        )
        for position, name in enumerate(("Primary", "Other"))
    ]
    db.add_all(slots)
    await db.commit()
    for team_slot in slots:
        await db.refresh(team_slot)
    return slots


@pytest_asyncio.fixture
async def slot(team_slots):
    return team_slots[0]


@pytest_asyncio.fixture
async def other_slot(team_slots):
    return team_slots[1]


@pytest.fixture
def pane_resolver(monkeypatch):
    """Override route resolution because ASGITransport fakes the peer port."""

    def _set(pane):
        monkeypatch.setattr(
            agent_mail_routes,
            "resolve_request_pane",
            lambda http_request: pane,
        )

    return _set


def _register(cwd: str, session_key: str = "mcp:abc123") -> MailAgentRegisterRequest:
    return MailAgentRegisterRequest(
        source="mcp",
        provider="claude",
        cwd=cwd,
        session_key=session_key,
    )


def _pane(pid: int = 3000, start: str = "111", target: str | None = "team:0.1") -> PeerPane:
    return PeerPane(pane_pid=pid, pane_proc_start=start, tmux_target=target, peer_pid=pid + 1)


def _body(cwd, session_key="mcp:bind", **extra):
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(cwd),
        "session_key": session_key,
    }
    body.update(extra)
    return body


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


def test_capability_token_settings_default_to_grace_mode():
    """PR0 ships enforcement off, so an unconfigured deploy behaves exactly as before.

    Assert the DECLARED defaults, not the resolved singleton. `Settings` reads
    `backend/.env`, so any developer or deploy that configures `operator_token`
    -- which Tasks 8-11 require -- makes the resolved value non-empty. Asserting
    the singleton made this test fail on exactly the machines that had followed
    the rollout, and printed the operator token into the pytest failure output.
    """
    fields = Settings.model_fields
    assert fields["mail_capability_tokens_required"].default is False
    assert fields["operator_token"].default == ""


def test_session_model_carries_the_three_binding_columns():
    columns = MailAgentSession.__table__.columns
    assert columns["capability_token_hash"].nullable is True
    assert columns["bound_pane_pid"].nullable is True
    assert columns["bound_pane_proc_start"].nullable is True


def test_pane_binding_table_is_unique_on_pid_and_proc_start():
    names = {column.name for column in AgentPaneBinding.__table__.columns}
    assert names == {
        "id",
        "pane_pid",
        "pane_proc_start",
        "slot_id",
        "preset_id",
        "tmux_target",
        "created_at",
    }
    unique = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in AgentPaneBinding.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("pane_pid", "pane_proc_start") in unique


@pytest.mark.asyncio
async def test_pane_binding_round_trips(db):
    """create_all makes the table; a row survives a raw-SQL read-back."""
    db.add(
        AgentPaneBinding(
            pane_pid=4242,
            pane_proc_start="123456",
            slot_id=None,
            preset_id=None,
            tmux_target="deck-team:0.1",
        )
    )
    await db.commit()

    row = (
        await db.execute(
            text(
                "SELECT pane_pid, pane_proc_start, tmux_target "
                "FROM agent_pane_bindings WHERE pane_pid = 4242"
            )
        )
    ).first()
    assert row == (4242, "123456", "deck-team:0.1")


@pytest.mark.asyncio
async def test_ensure_capability_token_mints_once(db, tmp_path):
    _member, session = await agent_mail_service.register_session(db, _register(str(tmp_path)))
    assert session.capability_token_hash is None

    token = await agent_mail_service.ensure_capability_token(db, session)
    assert token is not None
    assert len(token) >= 32

    stored = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).scalar_one()
    assert stored == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert stored != token, "the plaintext must never be stored"


@pytest.mark.asyncio
async def test_ensure_capability_token_does_not_rotate(db, tmp_path):
    """The shim re-registers before every tool call. Rotating would break it."""
    _member, session = await agent_mail_service.register_session(db, _register(str(tmp_path)))
    first = await agent_mail_service.ensure_capability_token(db, session)

    _member, again = await agent_mail_service.register_session(db, _register(str(tmp_path)))
    assert again.id == session.id
    second = await agent_mail_service.ensure_capability_token(db, again)

    assert second is None, "a re-registration must not hand out a second plaintext"
    stored = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).scalar_one()
    assert stored == hashlib.sha256(first.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_peek_session_by_key_reads_without_writing(db, tmp_path):
    """The rebind check runs BEFORE register_session, so its lookup must not write.

    register_session rewrites member_id/cwd/pid on a known key (:206-213). If the
    check reused it, the row would already be repointed by the time we refused.
    """
    _member, session = await agent_mail_service.register_session(
        db, _register(str(tmp_path), session_key="mcp:peek1")
    )
    before = (
        await db.execute(
            text("SELECT member_id, cwd, pid, last_seen_at FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).one()

    found = await agent_mail_service.peek_session_by_key(db, "mcp:peek1")
    assert found is not None and found.id == session.id
    assert await agent_mail_service.peek_session_by_key(db, "mcp:nosuchkey") is None

    after = (
        await db.execute(
            text("SELECT member_id, cwd, pid, last_seen_at FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).one()
    assert tuple(after) == tuple(before), "peek must not touch the row"


@pytest.mark.asyncio
async def test_two_sessions_get_different_tokens(db, tmp_path):
    _member, first = await agent_mail_service.register_session(
        db, _register(str(tmp_path), session_key="mcp:one")
    )
    _member, second = await agent_mail_service.register_session(
        db, _register(str(tmp_path), session_key="mcp:two")
    )
    first_token = await agent_mail_service.ensure_capability_token(db, first)
    second_token = await agent_mail_service.ensure_capability_token(db, second)
    assert first_token != second_token


@pytest.mark.asyncio
async def test_register_route_returns_the_token_once(client, tmp_path):
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:route1",
    }
    first = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert first.status_code == 200
    token = first.json()["capability_token"]
    assert token

    second = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert second.status_code == 200
    assert second.json()["capability_token"] is None


@pytest.mark.asyncio
async def test_a_hashless_existing_row_refuses_rather_than_minting(
    client, db, tmp_path, monkeypatch
):
    """Under enforcement: refuse, and mint nothing."""
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:pre-pr0",
    }
    first = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert first.status_code == 200
    assert first.json()["capability_token"]

    await db.execute(
        text("UPDATE mail_agent_sessions SET capability_token_hash = NULL WHERE session_key = :k"),
        {"k": "mcp:pre-pr0"},
    )
    await db.commit()

    replay = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert replay.status_code == 409
    assert replay.json()["detail"] == "token_required_for_rebind"
    assert "capability_token" not in replay.text

    still_null = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:pre-pr0"},
        )
    ).scalar_one()
    assert still_null is None, "the refusal must not mint as a side effect"


@pytest.mark.asyncio
async def test_the_refusal_does_not_repoint_the_row(client, db, tmp_path, monkeypatch):
    """The refusal must precede register_session, not follow it."""
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:norepoint",
        "pid": 1111,
    }
    assert (await client.post("/api/v1/agent-mail/agent/register", json=body)).status_code == 200
    await db.execute(
        text("UPDATE mail_agent_sessions SET capability_token_hash = NULL WHERE session_key = :k"),
        {"k": "mcp:norepoint"},
    )
    await db.commit()
    before = (
        await db.execute(
            text("SELECT member_id, cwd, pid FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:norepoint"},
        )
    ).one()

    other = dict(body, cwd=str(tmp_path / "elsewhere"), pid=2222)
    (tmp_path / "elsewhere").mkdir()
    replay = await client.post("/api/v1/agent-mail/agent/register", json=other)
    assert replay.status_code == 409

    after = (
        await db.execute(
            text("SELECT member_id, cwd, pid FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:norepoint"},
        )
    ).one()
    assert tuple(after) == tuple(before), "a refused registration must change nothing"


@pytest.mark.asyncio
async def test_a_hashless_row_in_grace_mode_neither_mints_nor_refuses(client, db, tmp_path):
    """The same row shape, enforcement off: 200 with no token, hash still NULL."""
    assert settings.mail_capability_tokens_required is False
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:grace1",
    }
    assert (await client.post("/api/v1/agent-mail/agent/register", json=body)).status_code == 200
    await db.execute(
        text("UPDATE mail_agent_sessions SET capability_token_hash = NULL WHERE session_key = :k"),
        {"k": "mcp:grace1"},
    )
    await db.commit()

    replay = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert replay.status_code == 200, "grace mode must not break a running shim"
    payload = replay.json()
    assert payload["capability_token"] is None
    assert payload["member"]["id"] and payload["session"]["session_key"] == "mcp:grace1"

    still_null = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:grace1"},
        )
    ).scalar_one()
    assert still_null is None, "grace mode must not backfill a hash either"


@pytest.mark.asyncio
async def test_a_fresh_session_key_from_the_same_pane_still_mints(client, tmp_path):
    """A restarted shim gets a fresh row and token from its new session key."""
    base = {"source": "mcp", "provider": "claude", "cwd": str(tmp_path)}
    first = await client.post(
        "/api/v1/agent-mail/agent/register", json=dict(base, session_key="mcp:aaa")
    )
    assert first.status_code == 200 and first.json()["capability_token"]

    restarted = await client.post(
        "/api/v1/agent-mail/agent/register", json=dict(base, session_key="mcp:bbb")
    )
    assert restarted.status_code == 200
    assert restarted.json()["capability_token"], "a restarted shim must not be locked out"
    assert restarted.json()["capability_token"] != first.json()["capability_token"]


@pytest.mark.asyncio
async def test_resolve_pane_binding_matches_on_pid_and_proc_start(db):
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="111", slot_id=None, preset_id=None))
    await db.commit()

    found = await agent_mail_service.resolve_pane_binding(db, _pane())
    assert found is not None and found.pane_pid == 3000


@pytest.mark.asyncio
async def test_resolve_pane_binding_ignores_a_row_with_a_stale_proc_start(db):
    """Pid reuse: the number matches, the process does not."""
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="OLD", slot_id=None, preset_id=None))
    await db.commit()

    assert await agent_mail_service.resolve_pane_binding(db, _pane(start="111")) is None


@pytest.mark.asyncio
async def test_resolve_pane_binding_prunes_rows_for_dead_panes(db, monkeypatch):
    """A row whose pane is gone is deleted, as session rows already are."""
    from app.utils import peer_process

    db.add(AgentPaneBinding(pane_pid=7777, pane_proc_start="OLD", slot_id=None, preset_id=None))
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="111", slot_id=None, preset_id=None))
    await db.commit()

    monkeypatch.setattr(peer_process, "pane_is_alive", lambda pid, start: pid == 3000)
    await agent_mail_service.resolve_pane_binding(db, _pane())

    remaining = (
        await db.execute(text("SELECT pane_pid FROM agent_pane_bindings ORDER BY pane_pid"))
    ).scalars().all()
    assert remaining == [3000]


@pytest.mark.asyncio
async def test_resolve_pane_binding_keeps_a_row_it_cannot_observe(db, monkeypatch):
    """None means 'cannot observe'. Never prune on doubt."""
    from app.utils import peer_process

    db.add(AgentPaneBinding(pane_pid=7777, pane_proc_start="OLD", slot_id=None, preset_id=None))
    await db.commit()

    monkeypatch.setattr(peer_process, "pane_is_alive", lambda pid, start: None)
    await agent_mail_service.resolve_pane_binding(db, _pane())

    remaining = (
        await db.execute(text("SELECT pane_pid FROM agent_pane_bindings"))
    ).scalars().all()
    assert remaining == [7777]


@pytest.mark.asyncio
async def test_row_with_a_slot_binds_the_session(client, db, tmp_path, pane_resolver, slot):
    db.add(
        AgentPaneBinding(
            pane_pid=3000,
            pane_proc_start="111",
            slot_id=slot.id,
            preset_id=slot.preset_id,
        )
    )
    await db.commit()
    pane_resolver(_pane())

    # The cwd and provider must satisfy _slot_matches_registration, or
    # _resolve_team_context discards the derived slot and returns (None, None).
    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(slot.repo_path, provider=slot.provider),
    )
    assert response.status_code == 200
    assert response.json()["capability_token"]

    row = (
        await db.execute(
            text(
                "SELECT team_slot_id, bound_pane_pid, bound_pane_proc_start "
                "FROM mail_agent_sessions WHERE session_key = 'mcp:bind'"
            )
        )
    ).first()
    assert row == (slot.id, 3000, "111")


@pytest.mark.asyncio
async def test_row_with_a_null_slot_mints_unbound(client, db, tmp_path, pane_resolver):
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="111", slot_id=None, preset_id=None))
    await db.commit()
    pane_resolver(_pane())

    response = await client.post("/api/v1/agent-mail/agent/register", json=_body(tmp_path))
    assert response.status_code == 200
    assert response.json()["capability_token"]
    slot_id = (
        await db.execute(
            text("SELECT team_slot_id FROM mail_agent_sessions WHERE session_key = 'mcp:bind'")
        )
    ).scalar_one()
    assert slot_id is None


@pytest.mark.asyncio
async def test_no_row_and_no_claim_mints_unbound(client, tmp_path, pane_resolver):
    """A hand-started pane Deck never launched is an ordinary repo member."""
    pane_resolver(_pane())
    response = await client.post("/api/v1/agent-mail/agent/register", json=_body(tmp_path))
    assert response.status_code == 200
    assert response.json()["capability_token"]


@pytest.mark.asyncio
async def test_no_row_but_a_team_claim_is_bind_pending(
    client, tmp_path, pane_resolver, slot
):
    """Retryable: Deck may not have committed the binding yet."""
    pane_resolver(_pane())
    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, team_slot_id=slot.id, team_preset_id=slot.preset_id),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "bind_pending"


@pytest.mark.asyncio
async def test_a_disagreeing_slot_claim_is_403(
    client, db, tmp_path, pane_resolver, slot, other_slot
):
    db.add(
        AgentPaneBinding(
            pane_pid=3000,
            pane_proc_start="111",
            slot_id=slot.id,
            preset_id=slot.preset_id,
        )
    )
    await db.commit()
    pane_resolver(_pane())

    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(
            tmp_path,
            team_slot_id=other_slot.id,
            team_preset_id=other_slot.preset_id,
        ),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_no_pane_ancestor_mints_unbound(client, tmp_path, pane_resolver):
    pane_resolver(None)
    response = await client.post("/api/v1/agent-mail/agent/register", json=_body(tmp_path))
    assert response.status_code == 200
    assert response.json()["capability_token"]


@pytest.mark.asyncio
async def test_unresolvable_peer_refuses_under_enforcement(
    client, tmp_path, pane_resolver, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    pane_resolver(None)
    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, team_slot_id=1, team_preset_id=1),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "bind_unverifiable"


@pytest.mark.asyncio
async def test_unresolvable_peer_mints_unbound_in_grace_mode(client, tmp_path, pane_resolver):
    assert settings.mail_capability_tokens_required is False
    pane_resolver(None)
    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, team_slot_id=1, team_preset_id=1),
    )
    assert response.status_code == 200
    assert response.json()["capability_token"]


@pytest.mark.asyncio
async def test_write_with_a_valid_token_derives_the_sender(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, session_key="mcp:send"),
    )
    token = register.json()["capability_token"]
    sender_id = register.json()["member"]["id"]
    recipient = await _member(db, "other-repo", "other")

    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "recipient_member_id": recipient.id,
            "subject": "hello",
            "body_markdown": "hi",
        },
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["sender_member_id"] == sender_id


@pytest.mark.asyncio
async def test_write_with_no_token_is_401_under_enforcement(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    recipient = await _member(db, "other-repo", "other")
    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": recipient.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_required"


@pytest.mark.asyncio
async def test_an_invalid_token_never_falls_back(client, db, tmp_path, monkeypatch):
    assert settings.mail_capability_tokens_required is False
    recipient = await _member(db, "other-repo", "other")
    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": recipient.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
        headers={"X-Deck-Session-Token": "not-a-real-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_invalid"


@pytest.mark.asyncio
async def test_grace_mode_accepts_a_tokenless_write(client, db, tmp_path):
    assert settings.mail_capability_tokens_required is False
    sender = await _member(db, "sender-repo", "sender")
    recipient = await _member(db, "other-repo", "other")
    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": sender.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
    )
    assert response.status_code == 200
    assert response.json()["sender_member_id"] == sender.id


@pytest.mark.asyncio
async def test_a_disagreeing_sender_is_403(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, session_key="mcp:forge"),
    )
    token = register.json()["capability_token"]
    victim = await _member(db, "victim-repo", "victim")
    recipient = await _member(db, "other-repo", "other")

    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": victim.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "sender_not_token_holder"


@pytest.mark.asyncio
async def test_inbox_without_a_token_is_401(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    member = await _member(db, "inbox-repo", "inbox")
    response = await client.get(f"/api/v1/agent-mail/agent/inbox?member_id={member.id}")
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_required"


@pytest.mark.asyncio
async def test_the_forged_liveness_attack_writes_nothing(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, session_key="mcp:victim"),
    )
    leader_id = register.json()["member"]["id"]

    stale = datetime.utcnow() - timedelta(days=30)
    session_row = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.member_id == leader_id)
        )
    ).scalar_one()
    session_row.last_seen_at = stale
    session_row.mailbox_status = "offline"

    sender = await _member(db, "sender-repo", "sender")
    message = MailMessage(
        kind="message",
        sender_member_id=sender.id,
        recipient_member_id=leader_id,
        subject="dispatch brief",
        body_markdown="do the thing",
    )
    db.add(message)
    await db.flush()
    receipt = MailReceipt(message_id=message.id, member_id=leader_id)
    db.add(receipt)
    leader = await db.get(MailTeamMember, leader_id)
    leader.last_inbox_checked_at = None
    await db.commit()

    response = await client.get(
        f"/api/v1/agent-mail/agent/inbox?member_id={leader_id}&mark_read=true"
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_required"

    message_id = message.id
    db.expire_all()
    session_row = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.member_id == leader_id)
        )
    ).scalar_one()
    assert session_row.last_seen_at == stale
    assert session_row.mailbox_status == "offline"
    receipt = (
        await db.execute(select(MailReceipt).where(MailReceipt.message_id == message_id))
    ).scalar_one()
    assert receipt.read_at is None
    leader = await db.get(MailTeamMember, leader_id)
    assert leader.last_inbox_checked_at is None


@pytest.mark.asyncio
async def test_inbox_with_a_token_ignores_a_disagreeing_member_id(
    client, db, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, session_key="mcp:holder"),
    )
    token = register.json()["capability_token"]
    holder_id = register.json()["member"]["id"]
    victim = await _member(db, "victim-repo", "victim")

    response = await client.get(
        "/api/v1/agent-mail/agent/inbox",
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["member_id"] == holder_id

    response = await client.get(
        f"/api/v1/agent-mail/agent/inbox?member_id={holder_id}",
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["member_id"] == holder_id

    response = await client.get(
        f"/api/v1/agent-mail/agent/inbox?member_id={victim.id}",
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "member_not_token_holder"
