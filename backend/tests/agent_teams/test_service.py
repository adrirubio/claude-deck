"""Issue #843: explicit team wait settings and bound Supervisor notice delivery."""
from types import SimpleNamespace

import pytest

from app.models.database import AgentTeamPreset, MailExternalActor, MailMessage
from app.models.schemas import AgentTeamPresetCreate, AgentTeamPresetUpdate
from app.services.agent_team_service import agent_team_service
from app.services.agent_team_supervisor_service import is_supervisor_message, supervisor_inbox


@pytest.mark.parametrize("field", ["leader_ack_timeout_seconds", "leader_ack_max_wait_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, "300", 86401])
@pytest.mark.parametrize("model", [AgentTeamPresetCreate, AgentTeamPresetUpdate])
def test_ack_override_rejects_invalid_values(field, value, model):
    values = {field: value}
    if model is AgentTeamPresetCreate:
        values["name"] = "Wait settings"
    with pytest.raises(ValueError):
        model(**values)


@pytest.mark.asyncio
async def test_ack_settings_persist_copy_omit_and_clear(db):
    created = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="Long turns", leader_ack_timeout_seconds=600, leader_ack_max_wait_seconds=3600))
    assert created.leader_ack_timeout_seconds == 600
    assert created.leader_ack_max_wait_seconds == 3600
    renamed = await agent_team_service.update_preset(db, created.id, name="Longer turns")
    assert renamed.leader_ack_timeout_seconds == 600
    copied = await agent_team_service.duplicate_preset(db, created.id)
    assert copied.leader_ack_timeout_seconds == 600 and copied.leader_ack_max_wait_seconds == 3600
    cleared = await agent_team_service.update_preset(db, created.id,
        leader_ack_timeout_seconds=None, leader_ack_max_wait_seconds=None)
    assert cleared.leader_ack_timeout_seconds is None and cleared.leader_ack_max_wait_seconds is None


@pytest.mark.asyncio
async def test_ack_settings_refuse_inverted_effective_windows(db):
    with pytest.raises(ValueError):
        await agent_team_service.create_preset(db, AgentTeamPresetCreate(
            name="Invalid windows", leader_ack_timeout_seconds=1200, leader_ack_max_wait_seconds=600))


def notice(actor=1):
    return dict(notice="leader_ack_wait", work_item_id=12, approval_request_id=34,
                leader_slot_id=56, supervisor_actor_id=actor)


def test_supervisor_classifies_only_strict_system_ack_notices():
    fields = dict(kind="message", audience_type="team_preset", audience_id="1",
                  sender_type="system", sender_member_id=None, sender_actor_id=None, recipient_member_id=None,
                  subject="Leader approval waiting", thread_root_id=None, payload=notice())
    assert is_supervisor_message(SimpleNamespace(**fields))
    for change in [dict(sender_type="member"), dict(sender_actor_id=9), dict(subject="Anything"),
                   dict(payload=notice() | {"untrusted": "extra"}),
                   dict(payload=notice() | {"work_item_id": True}),
                   dict(payload=notice() | {"approval_request_id": 0})]:
        assert not is_supervisor_message(SimpleNamespace(**(fields | change)))


@pytest.mark.asyncio
async def test_supervisor_inbox_exposes_ack_notice_only_to_current_bound_actor(db):
    actors = [MailExternalActor(actor_key=f"ack-{i}", display_name=f"Actor {i}",
                               kind="supervisor", token_hash=f"synthetic-{i}") for i in range(2)]
    db.add_all(actors)
    await db.flush()
    teams = [AgentTeamPreset(name=f"Team {i}", supervisor_actor_id=actor.id) for i, actor in enumerate(actors)]
    db.add_all(teams)
    await db.flush()
    db.add(MailMessage(kind="message", audience_type="team_preset", audience_id=str(teams[0].id),
                       subject="Leader approval waiting", body_markdown="A bounded wait, not approval.",
                       payload=notice(actors[0].id)))
    await db.commit()
    assert len(await supervisor_inbox(db, actors[0])) == 1
    assert await supervisor_inbox(db, actors[1]) == []


@pytest.mark.asyncio
async def test_ack_settings_patch_api_preserves_omission_and_accepts_null(db):
    from app.api.v1.agent_teams import create_preset, update_preset
    created = await create_preset(AgentTeamPresetCreate(name='API wait',
        leader_ack_timeout_seconds=700, leader_ack_max_wait_seconds=2700), None, db)
    patched = await update_preset(created.id, AgentTeamPresetUpdate(name='API renamed'), None, db)
    assert (patched.leader_ack_timeout_seconds, patched.leader_ack_max_wait_seconds) == (700, 2700)
    patched = await update_preset(created.id, AgentTeamPresetUpdate(leader_ack_timeout_seconds=800), None, db)
    assert (patched.leader_ack_timeout_seconds, patched.leader_ack_max_wait_seconds) == (800, 2700)
    cleared = await update_preset(created.id, AgentTeamPresetUpdate(
        leader_ack_timeout_seconds=None, leader_ack_max_wait_seconds=None), None, db)
    assert cleared.leader_ack_timeout_seconds is None and cleared.leader_ack_max_wait_seconds is None


@pytest.mark.asyncio
async def test_ack_settings_create_from_mail_and_bridge(db, monkeypatch):
    from unittest.mock import AsyncMock
    from app.models.schemas import AgentTeamCreateFromMailRequest, AgentTeamCreateFromBridgeRequest
    from app.services.agent_mail_service import agent_mail_service
    monkeypatch.setattr(agent_mail_service, 'sync_observed_sessions', AsyncMock())
    monkeypatch.setattr(agent_team_service, '_fallback_provider', AsyncMock(return_value='codex-cli'))
    mail = await agent_team_service.create_from_agent_mail(db, AgentTeamCreateFromMailRequest(
        name='Mail wait', member_ids=[], leader_ack_timeout_seconds=600, leader_ack_max_wait_seconds=2700))
    assert (mail.leader_ack_timeout_seconds, mail.leader_ack_max_wait_seconds) == (600, 2700)
    monkeypatch.setattr(agent_team_service, '_discover_sessions', lambda: [
        {'provider': 'codex-cli', 'cwd': '/tmp/bridge-wait', 'session_name': 'Leader'}])
    monkeypatch.setattr(agent_team_service, '_normalize_repo', lambda path: (
        path, {'repo_id': 'bridge-wait', 'repo_name': 'bridge-wait'}))
    bridge = await agent_team_service.create_from_agent_bridge(db, AgentTeamCreateFromBridgeRequest(
        name='Bridge wait', leader_ack_timeout_seconds=700, leader_ack_max_wait_seconds=2800))
    assert (bridge.leader_ack_timeout_seconds, bridge.leader_ack_max_wait_seconds) == (700, 2800)


@pytest.mark.asyncio
async def test_partial_ack_settings_validate_effective_values_before_mutation(db):
    from app.config import settings
    created = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name='Ordered wait',
        leader_ack_timeout_seconds=600, leader_ack_max_wait_seconds=900))
    with pytest.raises(ValueError):
        await agent_team_service.update_preset(db, created.id, leader_ack_timeout_seconds=1000)
    await db.refresh(await db.get(AgentTeamPreset, created.id))
    unchanged = await agent_team_service.get_preset(db, created.id)
    assert unchanged.leader_ack_timeout_seconds == 600
    with pytest.raises(ValueError):
        await agent_team_service.create_preset(db, AgentTeamPresetCreate(name='Default ordered',
            leader_ack_max_wait_seconds=settings.github_leader_ack_timeout_seconds - 1))
