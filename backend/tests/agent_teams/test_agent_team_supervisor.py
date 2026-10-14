"""An optional supervisor promises its next check without gaining authority."""
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import AgentTeamPreset, MailExternalActor


@pytest_asyncio.fixture
async def supervisor_client(db, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "synthetic-director-token")

    async def database():
        yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


async def supervisor_team(db):
    team = AgentTeamPreset(name="Supervised", description="Optional supervision.")
    actor = MailExternalActor(actor_key="supervisor-fixture", display_name="Supervisor",
                              kind="external_tool", token_hash=hashlib.sha256(b"synthetic-actor-token").hexdigest())
    db.add_all([team, actor])
    await db.commit()
    return team, actor


@pytest.mark.asyncio
async def test_director_can_bind_supervisor_without_starting_automation(db, supervisor_client):
    team, actor = await supervisor_team(db)
    team_id, actor_id = team.id, actor.id
    response = await supervisor_client.put(f"/api/v1/agent-teams/presets/{team_id}/supervisor",
        headers={"X-Deck-Operator-Token": "synthetic-director-token"}, json={"actor_id": actor_id})
    assert response.status_code == 200
    assert response.json()["actor_id"] == actor_id
    assert response.json()["status"] == "absent"
    await db.refresh(team)
    assert team.supervisor_actor_id == actor_id
    assert not team.autonomy_enabled


@pytest.mark.parametrize("elapsed,status", [(-1, "healthy"), (0, "late"), (1799, "late"), (1800, "absent")])
def test_supervisor_status_uses_clock_boundaries(elapsed, status):
    from app.services.agent_team_supervisor_service import supervisor_observation
    promised = datetime(2026, 10, 13, tzinfo=timezone.utc)
    team = SimpleNamespace(supervisor_actor_id=7, supervisor_checked_at=promised - timedelta(minutes=10),
        supervisor_next_check_at=promised, supervisor_grace_seconds=None, supervisor_note="Checked.")
    result = supervisor_observation(team, now=promised + timedelta(seconds=elapsed))
    assert result["status"] == status
    assert result["grace_seconds"] == 1800
    assert result["attention"] == ("Supervisor check-in overdue" if status in {"late", "absent"} else None)


def test_supervisor_status_none_is_optional_and_default_grace_uses_last_interval():
    from app.services.agent_team_supervisor_service import supervisor_observation
    promised = datetime(2026, 10, 13)
    team = SimpleNamespace(supervisor_actor_id=None, supervisor_checked_at=None,
        supervisor_next_check_at=None, supervisor_grace_seconds=None, supervisor_note=None)
    assert supervisor_observation(team, now=promised)["status"] == "none"
    team.supervisor_actor_id = 7
    assert supervisor_observation(team, now=promised)["status"] == "absent"
    team.supervisor_checked_at = promised - timedelta(hours=1)
    team.supervisor_next_check_at = promised
    assert supervisor_observation(team, now=promised)["grace_seconds"] == 7200
    team.supervisor_grace_seconds = 120
    assert supervisor_observation(team, now=promised + timedelta(seconds=120))["status"] == "absent"


@pytest.mark.parametrize("seconds", [-1, 0, 86401])
def test_supervisor_refuses_invalid_promises(seconds):
    from app.services.agent_team_supervisor_service import validate_promise
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="supervisor_next_check_invalid"):
        validate_promise(now + timedelta(seconds=seconds), now=now)


@pytest.mark.asyncio
async def test_supervisor_checkin_requires_the_bound_external_actor(db, supervisor_client):
    team, actor = await supervisor_team(db)
    path = "/api/v1/external/agent-mail/supervisor-checkin"
    payload = {"preset_id": team.id, "next_check_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
    assert (await supervisor_client.post(path, json=payload)).status_code == 401
    assert (await supervisor_client.post(path, json=payload,
        headers={"X-Deck-Session-Token": "synthetic-member-token"})).status_code == 401
    auth = {"Authorization": "Bearer synthetic-actor-token"}
    assert (await supervisor_client.post(path, json=payload, headers=auth)).status_code == 403
    bind = f"/api/v1/agent-teams/presets/{team.id}/supervisor"
    assert (await supervisor_client.put(bind, json={"actor_id": actor.id}, headers=auth)).status_code == 401
    await supervisor_client.put(bind, json={"actor_id": actor.id},
        headers={"X-Deck-Operator-Token": "synthetic-director-token"})
    response = await supervisor_client.post(path, json={**payload, "note": "token=private-note\nChecked."}, headers=auth)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert "private-note" not in response.text
    assert response.json()["address"]["actor_id"] == actor.id
    assert (await supervisor_client.post(path, json={**payload, "status": "healthy"}, headers=auth)).status_code == 422
    other = MailExternalActor(actor_key="foreign-fixture", display_name="Foreign", kind="external_tool",
        token_hash=hashlib.sha256(b"synthetic-foreign-token").hexdigest())
    db.add(other); await db.commit()
    assert (await supervisor_client.post(path, json=payload,
        headers={"Authorization": "Bearer synthetic-foreign-token"})).status_code == 403


@pytest.mark.asyncio
async def test_supervisor_checkins_audit_changes_without_audit_noise(db):
    from sqlalchemy import select
    from app.models.database import FactoryAuditEvent
    from app.services.agent_team_supervisor_service import bind_supervisor, observe_supervisor, supervisor_checkin
    team, actor = await supervisor_team(db)
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    await bind_supervisor(db, team.id, actor_id=actor.id, grace_seconds=None, set_grace=False, now=now)
    await supervisor_checkin(db, actor, team.id, now + timedelta(minutes=10), now=now)
    await supervisor_checkin(db, actor, team.id, now + timedelta(minutes=11), now=now + timedelta(minutes=1))
    await observe_supervisor(db, team.id, now=now + timedelta(minutes=11))
    await observe_supervisor(db, team.id, now=now + timedelta(minutes=11))
    await observe_supervisor(db, team.id, now=now + timedelta(minutes=41))
    events = (await db.scalars(select(FactoryAuditEvent).order_by(FactoryAuditEvent.id))).all()
    assert len(events) == 4
    assert [event.actor_kind for event in events] == ["operator", "system", "system", "system"]
    assert [event.after_values.get("supervisor_status") for event in events[1:]] == ["healthy", "late", "absent"]
    assert events[0].after_values["supervisor_actor_id"] == actor.id
    await bind_supervisor(db, team.id, actor_id=None, grace_seconds=None, set_grace=False, now=now)
    await db.refresh(team)
    assert team.supervisor_checked_at is None and team.supervisor_next_check_at is None
    assert team.supervisor_note is None and team.supervisor_observed_status == "none"
    assert not team.autonomy_enabled


@pytest.mark.asyncio
async def test_supervisor_audit_failure_rolls_back_binding(db, monkeypatch):
    from app.services.agent_team_supervisor_service import bind_supervisor
    team, actor = await supervisor_team(db)
    team_id, actor_id = team.id, actor.id
    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr("app.services.agent_team_supervisor_service.audit.record_event", fail)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        await bind_supervisor(db, team_id, actor_id=actor_id, grace_seconds=None, set_grace=False)
    await db.refresh(team)
    assert team.supervisor_actor_id is None


async def supervisor_member(db, team):
    from app.models.database import AgentTeamSlot, MailAgentSession, MailTeamMember
    slot = AgentTeamSlot(preset_id=team.id, position=0, display_name="Member", provider="codex-cli",
        repo_id="supervisor-repo", repo_path="/tmp/supervisor-repo", repo_name="supervisor-repo")
    db.add(slot); await db.flush()
    member = MailTeamMember(identity_key=f"supervisor-member:{team.id}", repo_id=slot.repo_id,
        repo_path=slot.repo_path, repo_name=slot.repo_name, display_name="Member",
        team_preset_id=team.id, team_slot_id=slot.id)
    db.add(member); await db.flush()
    session = MailAgentSession(member_id=member.id, provider="codex-cli", source="mcp",
        session_key=f"supervisor-session:{team.id}", team_preset_id=team.id, team_slot_id=slot.id,
        capability_token_hash=hashlib.sha256(b"synthetic-member-token").hexdigest())
    db.add(session); await db.commit()
    return member, session


@pytest.mark.asyncio
async def test_team_member_can_address_only_the_current_supervisor(db, supervisor_client, monkeypatch):
    from app.services.agent_team_supervisor_service import bind_supervisor
    team, actor = await supervisor_team(db)
    team_id, actor_id = team.id, actor.id
    _, session = await supervisor_member(db, team)
    session.bound_pane_pid = 321
    session.bound_pane_proc_start = "test-start"
    session.mailbox_status = "connected"
    await db.commit()
    monkeypatch.setattr("app.utils.peer_process.pane_is_alive", lambda *_: True)
    path = "/api/v1/agent-mail/supervisor/messages"
    auth = {"X-Deck-Session-Token": "synthetic-member-token"}
    message = {"actor_id": actor_id, "body_markdown": "Please inspect the incident."}
    assert (await supervisor_client.post(path, headers=auth, json=message)).status_code == 403
    await bind_supervisor(db, team_id, actor_id=actor_id, grace_seconds=None, set_grace=False)
    response = await supervisor_client.post(path, headers=auth, json=message)
    assert response.status_code == 200
    assert response.json()["sender_type"] == "member"
    assert response.json()["payload"]["supervisor_actor_id"] == actor_id
    inbox_path = "/api/v1/external/agent-mail/supervisor-inbox"
    inbox = await supervisor_client.get(inbox_path, headers={"Authorization": "Bearer synthetic-actor-token"})
    assert inbox.status_code == 200
    assert [entry["id"] for entry in inbox.json()] == [response.json()["id"]]
    thread_id = response.json()["id"]
    actor_auth = {"Authorization": "Bearer synthetic-actor-token"}
    thread_path = f"/api/v1/external/agent-mail/threads/{thread_id}"
    assert (await supervisor_client.get(thread_path, headers=actor_auth)).status_code == 200
    reply = await supervisor_client.post(thread_path + "/replies", headers=actor_auth,
        json={"body_markdown": "I will inspect the incident."})
    assert reply.status_code == 200
    foreign = MailExternalActor(actor_key="foreign-message-fixture", display_name="Foreign", kind="external_tool",
        token_hash=hashlib.sha256(b"synthetic-foreign-token").hexdigest())
    db.add(foreign); await db.commit()
    foreign_auth = {"Authorization": "Bearer synthetic-foreign-token"}
    assert (await supervisor_client.get(thread_path, headers=foreign_auth)).status_code == 403
    assert (await supervisor_client.post(thread_path + "/replies", headers=foreign_auth,
        json={"body_markdown": "Foreign message."})).status_code == 403
    assert (await supervisor_client.post(path, headers=auth, json={**message, "actor_id": actor_id + 100})).status_code == 403
    await bind_supervisor(db, team_id, actor_id=None, grace_seconds=None, set_grace=False)
    assert (await supervisor_client.get(inbox_path, headers={"Authorization": "Bearer synthetic-actor-token"})).status_code == 403
    assert (await supervisor_client.get(thread_path, headers=actor_auth)).status_code == 403


@pytest.mark.asyncio
async def test_member_identity_has_safe_supervisor_address_and_rebind_clears_old_address(db, monkeypatch):
    from app.services.agent_mail_service import agent_mail_service
    from app.services.agent_team_supervisor_service import bind_supervisor
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: [])
    team, actor = await supervisor_team(db)
    team_id, actor_id = team.id, actor.id
    member, _ = await supervisor_member(db, team)
    member_id = member.id
    await bind_supervisor(db, team_id, actor_id=actor_id, grace_seconds=60, set_grace=True)
    me = next(value for value in await agent_mail_service.list_team(db) if value.id == member_id)
    assert me.supervisor_address.actor_id == actor_id
    assert me.supervisor_address.address == f"external_actor:{actor_id}"
    assert "synthetic-actor-token" not in me.model_dump_json()
    await bind_supervisor(db, team_id, actor_id=None, grace_seconds=None, set_grace=False)
    me = next(value for value in await agent_mail_service.list_team(db) if value.id == member_id)
    assert me.supervisor_address is None


@pytest.mark.asyncio
async def test_actor_can_supervise_multiple_teams_and_grace_is_operator_controlled(db, supervisor_client):
    from app.services.agent_team_supervisor_service import bind_supervisor, supervisor_checkin
    team, actor = await supervisor_team(db)
    second = AgentTeamPreset(name="Second supervised team")
    db.add(second); await db.commit()
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    for team_id in (team.id, second.id):
        await bind_supervisor(db, team_id, actor_id=actor.id, grace_seconds=60, set_grace=True, now=now)
        result = await supervisor_checkin(db, actor, team_id, now + timedelta(hours=24), now=now)
        assert result["status"] == "healthy" and result["grace_seconds"] == 60
    path = f"/api/v1/agent-teams/presets/{second.id}/supervisor"
    assert (await supervisor_client.put(path, json={"actor_id": actor.id, "grace_seconds": 0},
        headers={"X-Deck-Operator-Token": "synthetic-director-token"})).status_code == 422


def test_dispatch_brief_names_supervisor_without_changing_the_escalation_order():
    from app.models.database import GithubWorkItem, TeamGithubScope
    from app.services.github_dispatch_service import github_dispatch_service
    item = GithubWorkItem(id=7, issue_number=549, issue_title="Supervisor", issue_url="https://github.com/example/repo/issues/549",
        issue_type="autonomous", dispatch_base_ref="origin/release/v3.1", dispatch_head_ref="example-supervisor",
        dispatch_nonce="synthetic-nonce", delivery_policy={}, delivery_policy_revision=1)
    scope = TeamGithubScope(repo_owner="example", repo_name="repo", github_auth_mode="token", preset_id=1,
                            max_build_parallelism=2, builds_out_of_tree=False)
    workspace = SimpleNamespace(path="/tmp/example-supervisor", kind="worktree", lease_token="synthetic-lease")
    brief = github_dispatch_service._dispatch_brief(item, scope, workspace, owner_slot_id=1, preset_slots=[],
        supervisor={"actor_id": 9, "address": "external_actor:9", "display_name": "Supervisor"})
    assert "Supervisor address: external_actor:9 (actor_id=9)" in brief
    assert "Escalate to the Leader first. Then contact the Supervisor." in brief
    assert "Retained operator decisions require the current operator-action record." in brief


@pytest.mark.asyncio
async def test_supervisor_message_refuses_membership_changed_before_insert(db, monkeypatch):
    from sqlalchemy import select, update
    from sqlalchemy.sql.dml import Insert
    from app.models.database import MailMessage, MailTeamMember
    from app.models.schemas import SupervisorMessageRequest
    from app.services.agent_team_supervisor_service import bind_supervisor, send_supervisor_message
    team, actor = await supervisor_team(db)
    team_id, actor_id = team.id, actor.id
    member, session = await supervisor_member(db, team)
    member_id = member.id
    await bind_supervisor(db, team_id, actor_id=actor_id, grace_seconds=None, set_grace=False)
    execute = db.execute
    changed = False
    async def concurrent_membership(statement, *args, **kwargs):
        nonlocal changed
        if isinstance(statement, Insert) and statement.table.name == "mail_messages" and not changed:
            changed = True
            await execute(update(MailTeamMember).where(MailTeamMember.id == member_id).values(team_preset_id=None))
            await db.commit()
        return await execute(statement, *args, **kwargs)
    monkeypatch.setattr(db, "execute", concurrent_membership)
    with pytest.raises(PermissionError, match="supervisor_address_not_bound"):
        await send_supervisor_message(db, session, SupervisorMessageRequest(actor_id=actor_id, body_markdown="Incident."))
    assert (await db.scalars(select(MailMessage))).all() == []
