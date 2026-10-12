"""Shared display facts do not change wake or work authority."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.database import (
    AgentTeamPreset, AgentTeamSlot, AgentPaneBinding, MailTeamMember, MailAgentSession,
    TeamGithubScope, GithubWorkItem, GithubWorkspace, MailPaneLifecycle,
)
from app.models.schemas import AgentActivityObservation
from app.services import agent_activity_service as activity
from app.services.agent_mail_service import agent_mail_service, MailWakeError
from app.api.v1.agent_bridge.router import _project_mail_wake_state
from app.utils import peer_process


async def seed_agent(db, monkeypatch, *, observation_age=timedelta(hours=3)):
    now = datetime.utcnow()
    team = AgentTeamPreset(name="Status fixture")
    db.add(team)
    await db.flush()
    slot = AgentTeamSlot(preset_id=team.id, display_name="Owner", provider="codex-cli",
                         repo_id="fixture", repo_name="fixture", repo_path="/tmp/status-fixture",
                         launch_options={"session_id": "11111111-1111-4111-8111-111111111111"})
    db.add(slot)
    await db.flush()
    member = MailTeamMember(identity_key=f"slot:{slot.id}", participant_kind="team_slot",
                            team_preset_id=team.id, team_slot_id=slot.id,
                            repo_id="fixture", repo_name="fixture", repo_path=slot.repo_path,
                            display_name="Owner")
    db.add(member)
    await db.flush()
    pane = MailAgentSession(member_id=member.id, provider=slot.provider, source="observed",
                           session_key="tmux:%fixture", pane_id="%fixture", pid=710001,
                           tmux_target="status-fixture:0.0", team_preset_id=team.id,
                           team_slot_id=slot.id, mailbox_status="observed",
                           last_seen_at=now-observation_age)
    mcp = MailAgentSession(member_id=member.id, provider=slot.provider, source="mcp",
                          session_key="mcp:fixture", team_preset_id=team.id,
                          team_slot_id=slot.id, mailbox_status="connected", last_seen_at=now,
                          capability_token_hash="synthetic-private-hash", wake_enabled=True,
                          bound_pane_pid=pane.pid, bound_pane_proc_start="fixture-start",
                          cwd=slot.repo_path)
    db.add_all([pane,mcp,AgentPaneBinding(preset_id=team.id, slot_id=slot.id,
                  pane_pid=pane.pid, pane_proc_start="fixture-start", tmux_target=pane.tmux_target)])
    scope = TeamGithubScope(preset_id=team.id, repo_owner="fixture", repo_name="repo",
                            repo_path=slot.repo_path)
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="Status fixture",
                         issue_url="https://github.com/fixture/repo/issues/1",
                         github_updated_at=now, dispatch_status="dispatched",
                         owner_slot_id=slot.id, dispatch_nonce="fixture-epoch")
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(scope_id=scope.id, path="/tmp/status-fixture-owner",
                                leased_item_id=item.id, lease_token="synthetic-private-lease",
                                lease_last_owner_contact_at=now-timedelta(minutes=5))
    db.add(workspace)
    await db.commit()
    idle_at = (now-observation_age).replace(tzinfo=timezone.utc)
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda *_: True)
    monkeypatch.setattr(agent_mail_service, "_pid_is_running", lambda *_: True)
    def native_observation(slot_id, *_args, **_kwargs):
        return AgentActivityObservation(slot_id=slot_id, state="idle",
                                        reason="native_turn_completed", observed_at=idle_at)
    monkeypatch.setattr(activity, "_observe", native_observation)
    return team,slot,member,pane,mcp,item,workspace,idle_at


@pytest.mark.asyncio
async def test_old_observation_has_shared_online_idle_and_actual_wake_refusal(db, monkeypatch):
    team,slot,member,pane,mcp,item,workspace,idle_at = await seed_agent(db,monkeypatch)
    before = (pane.last_seen_at,mcp.last_seen_at,item.dispatch_status,item.last_nudge_at,
              item.ack_received_at,workspace.lease_token,workspace.lease_last_owner_contact_at)
    async def no_input(*_args, **_kwargs):
        raise AssertionError("A status read must not send input")
    monkeypatch.setattr(agent_mail_service,"_wake_member",no_input)
    with pytest.raises(MailWakeError,match="wake_target_unbound"):
        await agent_mail_service._nudge_session_for_member(db,member.id,datetime.utcnow())
    mail = next(m for m in await agent_mail_service.list_team(db) if m.id==member.id)
    live = (await _project_mail_wake_state([{"provider":slot.provider,"tmux_target":pane.tmux_target,
                  "pane_id":pane.pane_id,"cwd":slot.repo_path,"pid":str(pane.pid)}],db))[0]
    roster = (await activity.observe_team(db,team.id)).slots[0]
    facts = [mail.model_dump(mode="json").get("agent_status"), live.get("agent_status"),
             roster.model_dump(mode="json").get("agent_status")]
    for status in facts:
        assert status is not None, "Each real read must expose the shared display status"
        assert status["session_state"]=="online"
        assert status["activity_state"]=="idle"
        assert status["wake_state"]=="cannot_wake"
        assert status["wake_reason"]=="wake_target_unbound"
        assert status["idle_since"]==idle_at.isoformat().replace("+00:00","Z")
    await db.refresh(pane)
    await db.refresh(mcp)
    await db.refresh(item)
    await db.refresh(workspace)
    after = (pane.last_seen_at,mcp.last_seen_at,item.dispatch_status,item.last_nudge_at,
             item.ack_received_at,workspace.lease_token,workspace.lease_last_owner_contact_at)
    assert after==before
    assert "synthetic-private" not in str(facts)


@pytest.mark.asyncio
async def test_factory_session_uses_the_same_display_facts(db,monkeypatch):
    from app.services.factory_projection_service import work_projections
    team,slot,member,pane,mcp,item,workspace,idle_at = await seed_agent(db,monkeypatch)
    scope = await db.get(TeamGithubScope,item.scope_id)
    projections = await work_projections(db,[(item,scope,team)],datetime.now(timezone.utc))
    status = projections[0].session.agent_status
    assert status is not None
    assert status.session_state=="online"
    assert status.activity_state=="idle"
    assert status.wake_state=="cannot_wake"
    assert status.wake_reason=="wake_target_unbound"
    assert status.idle_since==idle_at


@pytest.mark.asyncio
@pytest.mark.parametrize("native_state",["unknown","stopped"])
async def test_mail_activity_does_not_override_native_evidence(db,monkeypatch,native_state):
    from app.services.agent_status_service import agent_status_service
    team,slot,member,pane,mcp,*_ = await seed_agent(db,monkeypatch)
    mcp.activity="working"
    await db.commit()
    monkeypatch.setattr(activity,"_observe",lambda slot_id,*args,**kwargs:
                        AgentActivityObservation(slot_id=slot_id,state=native_state,
                                                 reason="native_log_unavailable"))
    status=(await agent_status_service.for_members(db,[member]))[member.id]
    assert status.activity_state==native_state
    assert status.idle_since is None


@pytest.mark.asyncio
async def test_shared_status_read_cannot_save_native_identity(db,monkeypatch):
    from app.services.agent_status_service import agent_status_service
    team,slot,member,pane,mcp,*_=await seed_agent(db,monkeypatch)
    before=dict(slot.launch_options)
    def fake_native(slot_id,*args,provenance=None,**kwargs):
        if provenance is not None:
            provenance["discovered_session_id"]="22222222-2222-4222-8222-222222222222"
        return AgentActivityObservation(slot_id=slot_id,state="unknown",
                                         reason="restart_needed_for_observation")
    monkeypatch.setattr(activity,"_observe",fake_native)
    async def no_save(*args,**kwargs):
        raise AssertionError("The shared display must not save native identity")
    monkeypatch.setattr(activity,"_save_codex_identities",no_save)
    status=(await agent_status_service.for_members(db,[member]))[member.id]
    assert status.activity_state=="unknown"
    await db.refresh(slot)
    assert slot.launch_options==before


@pytest.mark.asyncio
async def test_shared_status_unknown_idle_time_is_not_mailbox_age(db,monkeypatch):
    from app.services.agent_status_service import agent_status_service
    team,slot,member,*_=await seed_agent(db,monkeypatch)
    monkeypatch.setattr(activity,"_observe",lambda slot_id,*args,**kwargs:
                        AgentActivityObservation(slot_id=slot_id,state="idle",
                                                 reason="native_turn_completed"))
    status=(await agent_status_service.for_members(db,[member]))[member.id]
    assert status.activity_state=="idle"
    assert status.idle_since is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case,reason", [
    ("fresh", None), ("opted_out", "wake_opted_out"),
    ("expired_mcp", "wake_target_unbound"), ("ambiguous", "wake_target_ambiguous"),
    ("wrong_provider", "wake_target_unbound"), ("wrong_slot", "wake_target_unbound"),
])
async def test_shared_wake_state_matches_delivery_resolver(db, monkeypatch, case, reason):
    from app.services.agent_status_service import agent_status_service
    team, slot, member, pane, mcp, *_ = await seed_agent(
        db, monkeypatch, observation_age=timedelta(seconds=1))
    if case == "opted_out":
        mcp.wake_enabled = False
    elif case == "expired_mcp":
        mcp.last_seen_at = datetime.utcnow() - timedelta(hours=3)
    elif case == "wrong_provider":
        mcp.provider = "claude-code"
    elif case == "wrong_slot":
        mcp.team_slot_id = slot.id + 100
    elif case == "ambiguous":
        db.add(MailAgentSession(
            member_id=member.id, provider=mcp.provider, source="mcp", session_key="mcp:second",
            team_preset_id=team.id, team_slot_id=slot.id, mailbox_status="connected",
            capability_token_hash="synthetic-second-hash", last_seen_at=datetime.utcnow(),
            bound_pane_pid=pane.pid, bound_pane_proc_start=mcp.bound_pane_proc_start,
            cwd=slot.repo_path, wake_enabled=True))
    await db.commit()
    if reason is None:
        assert (await agent_mail_service._nudge_session_for_member(db, member.id, datetime.utcnow())).id == pane.id
    else:
        with pytest.raises(MailWakeError, match=reason):
            await agent_mail_service._nudge_session_for_member(db, member.id, datetime.utcnow())
    status = (await agent_status_service.for_members(db, [member]))[member.id]
    assert status.wake_state == ("can_wake" if reason is None else "cannot_wake")
    assert status.wake_reason == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("retired", [False, True])
async def test_factory_native_inputs_match_team_inputs_for_lifecycle(db, monkeypatch, retired):
    from app.services.agent_status_service import agent_status_service
    from app.services.factory_projection_service import actor_evidence
    team, slot, member, pane, mcp, *_ = await seed_agent(db, monkeypatch)
    db.add(MailPaneLifecycle(pane_pid=pane.pid, pane_proc_start=mcp.bound_pane_proc_start,
                            retired_at=datetime.utcnow() if retired else None))
    await db.commit()
    expected = await activity._team_inputs(db, team.id)
    seen = []
    def capture_inputs(slot_id, provider, session_id, bindings, duplicate, now):
        seen.append((slot_id, provider, session_id, bindings, duplicate))
        return AgentActivityObservation(slot_id=slot_id, state="unknown", reason="observation_unavailable")
    monkeypatch.setattr(activity, "_observe", capture_inputs)
    slots, members, sessions, bindings, lifecycles = await actor_evidence(db, {team.id}, {})
    # Legacy association keeps membership for both lifecycle rows.
    assert (pane.pid, mcp.bound_pane_proc_start) in lifecycles
    await agent_status_service.for_snapshot(db, members, slots, sessions, bindings, lifecycles)
    assert seen == expected
    assert bool(seen[0][3]) is not retired
