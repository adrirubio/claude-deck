"""Durable owner settlement regressions. No native agents or GitHub writes."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from test_github_coordination import team  # Reuse the isolated coordination seed.
from app.models.coordination import OwnerFollowupRequest
from app.models.database import (
    AgentPaneBinding, GithubOwnerFollowup, GithubWorkItem, MailAgentSession, MailMessage, MailReceipt, TeamGithubScope,
)
from app.services.agent_activity_service import PrivateActivity
from app.services.agent_mail_service import MailWakeError, agent_mail_service
from app.services.github_coordination_service import CoordinationError, github_coordination_service
from app.services import github_owner_followup_service as module

service = module.github_owner_followup_service


@pytest_asyncio.fixture
async def watched(db, team, monkeypatch):
    leader = team.leader
    leader.pid = 1234
    leader.cwd = "/tmp/fixture"
    owner = MailAgentSession(member_id=team.approval.owner_member_id, provider="codex-cli", source="mcp",
        session_key="fixture-owner-session", team_preset_id=team.preset.id, team_slot_id=team.item.owner_slot_id,
        capability_token_hash="fixture-owner-capability", bound_pane_pid=2345, bound_pane_proc_start="2",
        pid=2345, cwd=team.lease.path, wake_enabled=True)
    db.add(owner)
    db.add_all([AgentPaneBinding(pane_pid=session.bound_pane_pid,
        pane_proc_start=session.bound_pane_proc_start, slot_id=session.team_slot_id, preset_id=team.preset.id)
        for session in (owner, leader)])
    question = MailMessage(kind="question", sender_member_id=owner.member_id,
                           recipient_member_id=leader.member_id, subject="Plan", body_markdown="Fixture plan")
    db.add(question); await db.flush()
    approval = team.approval
    approval.request_kind = "initial_plan"
    approval.request_message_id = question.id
    answer = MailMessage(kind="answer", sender_member_id=leader.member_id, recipient_member_id=owner.member_id,
        subject="Approved", body_markdown="Fixture decision", thread_root_id=question.id, decision="approved",
        approval_round=1, delivery_key=f"github-approval:{approval.id}:decision",
        payload={"approval_request_id": approval.id})
    db.add(answer); await db.flush()
    approval.decision_message_id = answer.id
    item = team.item
    item.dispatch_status = "dispatched"
    item.approval_round_count = 1
    item.dispatched_at = datetime.utcnow()
    item.ack_received_at = datetime.utcnow()
    item.ack_enforcement_epoch = 1
    item.ack_approval_round = 1
    item.ack_approver_member_id = leader.member_id
    item.ack_evidence_message_id = answer.id
    team.lease.leased_owner_pid = owner.bound_pane_pid
    team.lease.leased_owner_proc_start = owner.bound_pane_proc_start
    await db.commit()
    now = datetime.now(timezone.utc)
    activities = {
        leader.team_slot_id: PrivateActivity("working", "native_turn_started", now, "leader-native", None, "leader-working"),
        owner.team_slot_id: PrivateActivity("working", "native_turn_started", now, "owner-native", None, "owner-working"),
    }
    monkeypatch.setattr(module, "observe_private_team", AsyncMock(side_effect=lambda *_: dict(activities)))
    monkeypatch.setattr(module, "_DEBOUNCE", 0)
    monkeypatch.setattr(agent_mail_service, "sync_observed_sessions", AsyncMock())
    monkeypatch.setattr(agent_mail_service, "_last_auto_nudge_at", {})

    async def wake(*args, **kwargs):
        assert kwargs["expected_session_id"] == leader.id
        assert "force" not in kwargs
        assert await kwargs["delivery_guard"]()
        return {"method": "fixture"}

    monkeypatch.setattr(agent_mail_service, "_wake_member", AsyncMock(side_effect=wake))
    return SimpleNamespace(**vars(team), owner=owner, activities=activities,
                           native_wake=agent_mail_service._wake_member)


async def read(db, watched):
    values = await service.requests(db, watched.scope_id, watched.leader)
    return next(value for value in values if value["work_item_id"] == watched.item.id)


def request(value, action="watch", reason="unfinished_authorized_work"):
    return OwnerFollowupRequest(work_item_id=value["work_item_id"], action=action, reason=reason,
                               expected_sequence=value["event_sequence"], followup_token=value["followup_token"])


async def arm(db, watched):
    call = request(await read(db, watched))
    await service.report(db, watched.scope_id, watched.leader, call)
    return call


def settle(watched, *, leader_idle=True, event="owner-completed-1"):
    now = datetime.now(timezone.utc)
    watched.activities[watched.owner.team_slot_id] = PrivateActivity(
        "idle", "native_turn_completed", now, "owner-native", event, event)
    if leader_idle:
        watched.activities[watched.leader.team_slot_id] = PrivateActivity(
            "idle", "native_turn_completed", now, "leader-native", "leader-completed")


async def row(db, watched):
    return await db.get(GithubOwnerFollowup, watched.item.id, populate_existing=True)


async def count_notices(db):
    return await db.scalar(select(func.count()).select_from(MailMessage).where(
        MailMessage.delivery_key.like("owner-followup:%")))


@pytest.mark.asyncio
async def test_owner_settles_after_leader_without_root_mail_then_restart_deduplicates(db, watched):
    await arm(db, watched)
    watched.activities[watched.leader.team_slot_id] = replace(
        watched.activities[watched.leader.team_slot_id], state="idle", reason="native_turn_completed")
    await service.poll(db, watched.scope_id)
    assert await count_notices(db) == 0
    settle(watched)
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "delivered"
    assert await count_notices(db) == 1
    policy = await github_coordination_service.state(db, watched.scope_id)
    assert (policy.daily_requests, policy.snapshot_requests, policy.generation, policy.request_sequence) == (1, 1, 0, 0)
    watched.native_wake.assert_awaited_once()
    # A new service instance represents a controller restart; persisted delivery wins.
    await module.GithubOwnerFollowupService().poll(db, watched.scope_id)
    assert await count_notices(db) == 1
    watched.native_wake.assert_awaited_once()
    await db.refresh(watched.item); await db.refresh(watched.lease); await db.refresh(watched.approval)
    assert watched.item.pr_number == 25 and watched.item.active_scope_revision == 0
    assert watched.item.dispatch_nonce == "fixture-nonce" and watched.item.retry_count == 0
    assert watched.item.ack_evidence_message_id == watched.approval.decision_message_id
    assert watched.lease.lease_token == "fixture-lease" and watched.approval.status == "approved"


@pytest.mark.asyncio
async def test_short_turn_between_polls_and_busy_leader_retains_pending_event(db, watched):
    await arm(db, watched)
    settle(watched, leader_idle=False)
    await service.poll(db, watched.scope_id)
    pending = await row(db, watched)
    assert pending.sequence == 1 and pending.state == "pending"
    assert pending.outcome == "waiting_for_leader" and await count_notices(db) == 0
    watched.activities[watched.leader.team_slot_id] = replace(
        watched.activities[watched.leader.team_slot_id], state="idle", reason="native_turn_completed")
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "delivered"


@pytest.mark.asyncio
async def test_rearm_does_not_replay_assessed_settlement_or_spend_shared_quota(db, watched):
    await arm(db, watched)
    settle(watched)
    await service.poll(db, watched.scope_id)
    previous = await row(db, watched)
    await db.execute(update(MailReceipt).where(MailReceipt.message_id == previous.message_id).values(read_at=datetime.utcnow()))
    await db.commit()
    await service.report(db, watched.scope_id, watched.leader,
                         request(await read(db, watched), "assess", "next_action_arranged"))
    await arm(db, watched)  # The next owner turn has not started; the latest event is still E1.
    await service.poll(db, watched.scope_id)
    current = await row(db, watched)
    assert current.state == "waiting" and current.sequence == 1
    assert current.settlement_id is None and current.settled_at is None
    assert await count_notices(db) == 1
    policy = await github_coordination_service.state(db, watched.scope_id)
    assert (policy.daily_requests, policy.snapshot_requests) == (1, 1)
    watched.native_wake.assert_awaited_once()
    watched.activities[watched.owner.team_slot_id] = replace(
        watched.activities[watched.owner.team_slot_id], state="working", reason="native_turn_started",
        settlement_id=None, cursor="owner-working-2")
    await service.poll(db, watched.scope_id)
    settle(watched, event="owner-completed-2")
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "notified"  # Shared physical wake cooldown still applies.
    assert await count_notices(db) == 2
    watched.native_wake.assert_awaited_once()
    agent_mail_service._last_auto_nudge_at[watched.leader.member_id] = (
        datetime.utcnow() - timedelta(seconds=module.AUTO_NUDGE_COOLDOWN_SECONDS + 1))
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "delivered"
    assert (await row(db, watched)).sequence == 2
    assert await count_notices(db) == 2 and watched.native_wake.await_count == 2
    policy = await github_coordination_service.state(db, watched.scope_id)
    assert (policy.daily_requests, policy.snapshot_requests) == (2, 2)


@pytest.mark.asyncio
async def test_rearm_captures_different_fresh_settlement(db, watched):
    await arm(db, watched)
    settle(watched)
    await service.poll(db, watched.scope_id)
    await service.report(db, watched.scope_id, watched.leader,
                         request(await read(db, watched), "assess", "next_action_arranged"))
    rearm = request(await read(db, watched))
    settle(watched, event="owner-completed-2")
    await service.report(db, watched.scope_id, watched.leader, rearm)
    current = await row(db, watched)
    assert current.state == "pending" and current.sequence == 2
    assert current.settlement_id == "owner-completed-2"


@pytest.mark.asyncio
async def test_stale_leader_identity_retains_fresh_owner_debt_until_valid_idle(db, watched):
    await arm(db, watched)
    watched.activities[watched.leader.team_slot_id] = replace(
        watched.activities[watched.leader.team_slot_id], state="unknown", reason="native_event_stale",
        observed_at=datetime.now(timezone.utc) - timedelta(seconds=181))
    settle(watched, leader_idle=False)
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "pending" and (await row(db, watched)).sequence == 1
    assert await count_notices(db) == 0
    watched.native_wake.assert_not_awaited()
    # More than one activity window passes. Fresh SDK idle proof retains the same debt.
    watched.activities[watched.owner.team_slot_id] = replace(
        watched.activities[watched.owner.team_slot_id], settlement_id=None,
        observed_at=datetime.now(timezone.utc) - timedelta(seconds=600),
        current_settlement_id="owner-completed-1")
    await service.poll(db, watched.scope_id)
    assert await count_notices(db) == 0
    watched.native_wake.assert_not_awaited()
    watched.activities[watched.leader.team_slot_id] = replace(
        watched.activities[watched.leader.team_slot_id], state="idle", reason="native_turn_completed",
        observed_at=datetime.now(timezone.utc))
    await service.poll(db, watched.scope_id)
    await module.GithubOwnerFollowupService().poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "delivered" and (await row(db, watched)).sequence == 1
    assert await count_notices(db) == 1
    watched.native_wake.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [None, "replacement-leader"])
async def test_missing_or_changed_stale_leader_identity_cannot_capture_owner_debt(db, watched, identity):
    await arm(db, watched)
    watched.activities[watched.leader.team_slot_id] = replace(
        watched.activities[watched.leader.team_slot_id], state="unknown", reason="native_event_stale",
        identity=identity)
    settle(watched, leader_idle=False)
    await service.poll(db, watched.scope_id)
    current = await row(db, watched)
    assert current.sequence == 0 and current.settlement_id is None
    assert current.state == ("waiting" if identity is None else "invalidated")
    assert await count_notices(db) == 0
    watched.native_wake.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_read_cannot_ack_later_event_and_mail_read_is_not_ack(db, watched):
    arm_call = await arm(db, watched)
    old = await read(db, watched)
    settle(watched)
    await service.poll(db, watched.scope_id)
    pending = await row(db, watched)
    await db.execute(update(MailReceipt).where(MailReceipt.message_id == pending.message_id).values(read_at=datetime.utcnow()))
    await db.commit()
    with pytest.raises(CoordinationError, match="followup_read_changed"):
        await service.report(db, watched.scope_id, watched.leader, request(old, "assess", "next_action_arranged"))
    await service.report(db, watched.scope_id, watched.leader, arm_call)  # Exact arm retry cannot reset the event.
    assert (await row(db, watched)).sequence == 1
    fresh = await read(db, watched)
    ack = request(fresh, "assess", "next_action_arranged")
    await service.report(db, watched.scope_id, watched.leader, ack)
    await service.report(db, watched.scope_id, watched.leader, ack)
    assert (await row(db, watched)).state == "assessed"
    assert await count_notices(db) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", ["daily", "snapshot"])
async def test_cap_retains_event_and_signed_ack_without_budget_reset(db, watched, cap):
    await arm(db, watched)
    policy = await github_coordination_service.state(db, watched.scope_id)
    policy.budget_day = datetime.utcnow().strftime("%Y-%m-%d")
    policy.daily_requests = policy.max_daily_requests if cap == "daily" else 0
    policy.snapshot_requests = 3 if cap == "snapshot" else 1
    before = (policy.daily_requests, policy.snapshot_requests)
    await db.commit()
    settle(watched)
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "capped" and await count_notices(db) == 0
    await service.report(db, watched.scope_id, watched.leader, request(await read(db, watched), "assess", "blocked"))
    policy = await github_coordination_service.state(db, watched.scope_id)
    assert (policy.daily_requests, policy.snapshot_requests) == before


@pytest.mark.asyncio
async def test_unread_coordination_mail_coalesces_without_quota_or_new_notice(db, watched):
    await github_coordination_service.reconcile(db, watched.scope_id, watched.client)
    policy = await github_coordination_service.state(db, watched.scope_id)
    previous = (policy.message_id, policy.daily_requests, policy.snapshot_requests, policy.generation, policy.request_sequence)
    await arm(db, watched)
    settle(watched)
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).message_id == previous[0]
    assert await count_notices(db) == 0
    policy = await github_coordination_service.state(db, watched.scope_id)
    assert (policy.message_id, policy.daily_requests, policy.snapshot_requests, policy.generation, policy.request_sequence) == previous


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["nonce", "ack", "approval", "lease", "owner_native", "leader_native", "owner_session", "leader_session", "phase", "revision", "terminal", "escalated"])
async def test_changed_authority_invalidates_watch_without_wake(db, watched, change):
    await arm(db, watched)
    if change == "nonce": watched.item.dispatch_nonce = "different"
    elif change == "ack": watched.item.ack_evidence_message_id = None
    elif change == "approval": watched.approval.status = "rejected"
    elif change == "lease": watched.lease.lease_token = "new-acquisition"
    elif change == "owner_native": watched.activities[watched.owner.team_slot_id] = replace(watched.activities[watched.owner.team_slot_id], identity="replacement-native")
    elif change == "leader_native": watched.activities[watched.leader.team_slot_id] = replace(watched.activities[watched.leader.team_slot_id], identity="replacement-leader")
    elif change == "owner_session": watched.owner.capability_token_hash = "new-owner-generation"
    elif change == "leader_session": watched.leader.capability_token_hash = "new-leader-generation"
    elif change == "phase": watched.item.attempt_phase = "diagnostic"
    elif change == "revision": watched.item.active_scope_revision = 1
    elif change == "terminal": watched.item.dispatch_status = "ready_for_review"
    elif change == "escalated": watched.item.escalation_reason = "verification_failed"
    await db.commit()
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "invalidated"
    assert await count_notices(db) == 0
    watched.native_wake.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "reason"), [("unknown", "native_event_stale"), ("stopped", "process_ended"),
    ("idle", "native_input_requested"), ("idle", "native_turn_interrupted"), ("unknown", "observation_unavailable")])
async def test_unknown_input_interrupted_and_stopped_do_not_create_event(db, watched, state, reason):
    await arm(db, watched)
    watched.activities[watched.owner.team_slot_id] = PrivateActivity(state, reason, datetime.now(timezone.utc), None, None)
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).sequence == 0
    assert await count_notices(db) == 0
    watched.native_wake.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["off", "hold"])
async def test_off_hold_suppress_and_resume_cannot_replay_old_baseline(db, watched, monkeypatch, tmp_path, gate):
    await arm(db, watched)
    settle(watched)
    hold = tmp_path / "HOLD"
    if gate == "off":
        watched.preset.autonomy_enabled = False
        await db.commit()
    else:
        hold.write_text("hold")
        monkeypatch.setattr(module, "hold_code", lambda: "hold" if hold.exists() else None)
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "paused"
    watched.preset.autonomy_enabled = True
    hold.unlink(missing_ok=True)
    await db.commit()
    await service.poll(db, watched.scope_id)
    assert await count_notices(db) == 0


@pytest.mark.asyncio
async def test_uncertain_transport_is_not_automatically_repeated(db, watched):
    await arm(db, watched)
    settle(watched)
    watched.native_wake.side_effect = MailWakeError("wake_transport_failed")
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).outcome == "transport_uncertain"
    assert (await row(db, watched)).delivery_attempts == 1
    await module.GithubOwnerFollowupService().poll(db, watched.scope_id)
    watched.native_wake.assert_awaited_once()
    assert await count_notices(db) == 1


@pytest.mark.asyncio
async def test_public_summary_omits_private_authority_and_challenges(db, watched):
    import json
    await arm(db, watched)
    public = json.dumps(await service.summary(db, watched.scope_id))
    for private in ("fixture-nonce", "fixture-lease", "fixture-owner-capability", "owner-native", "leader-native", "followup_token", "context"):
        assert private not in public


@pytest.mark.asyncio
async def test_watch_registration_retains_owner_settlement_during_read_and_write(db, watched):
    initial = request(await read(db, watched))
    settle(watched)
    await service.report(db, watched.scope_id, watched.leader, initial)
    assert (await row(db, watched)).state == "pending"
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "delivered"


@pytest.mark.asyncio
async def test_fresh_settlement_before_registration_becomes_pending(db, watched):
    settle(watched)
    await arm(db, watched)
    assert (await row(db, watched)).sequence == 1
    await service.poll(db, watched.scope_id)
    assert await count_notices(db) == 1


@pytest.mark.asyncio
async def test_settlement_after_registration_observation_before_commit_is_not_lost(db, watched, monkeypatch):
    call = request(await read(db, watched))
    original = db.execute
    injected = False

    async def execute(statement, *args, **kwargs):
        nonlocal injected
        if not injected and str(statement).startswith("UPDATE github_backlog_coordination"):
            injected = True
            settle(watched)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", execute)
    await service.report(db, watched.scope_id, watched.leader, call)
    await service.poll(db, watched.scope_id)
    assert injected and await count_notices(db) == 1


@pytest.mark.asyncio
async def test_new_event_after_read_notice_gets_bounded_new_mail(db, watched):
    await arm(db, watched)
    settle(watched)
    await service.poll(db, watched.scope_id)
    previous = await row(db, watched)
    await db.execute(update(MailReceipt).where(MailReceipt.message_id == previous.message_id).values(read_at=datetime.utcnow()))
    await db.commit()
    stale = request(await read(db, watched), "assess", "next_action_arranged")
    settle(watched, event="owner-completed-2")
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).sequence == 2
    assert await count_notices(db) == 2
    with pytest.raises(CoordinationError, match="followup_read_changed"):
        await service.report(db, watched.scope_id, watched.leader, stale)
    assert (await github_coordination_service.state(db, watched.scope_id)).snapshot_requests == 2


@pytest.mark.asyncio
async def test_delivered_unassessed_event_has_finite_fallback(db, watched):
    await arm(db, watched)
    settle(watched)
    await service.poll(db, watched.scope_id)
    pending = await row(db, watched)
    await db.execute(update(MailReceipt).where(MailReceipt.message_id == pending.message_id).values(read_at=datetime.utcnow()))
    pending.last_notified_at = datetime.utcnow() - timedelta(hours=2)
    pending.last_delivery_at = datetime.utcnow() - timedelta(hours=2)
    agent_mail_service._last_auto_nudge_at.clear()
    await db.commit()
    await service.poll(db, watched.scope_id)
    assert await count_notices(db) == 2
    assert (await row(db, watched)).state == "delivered"
    assert (await row(db, watched)).notification_count == 2


@pytest.mark.asyncio
async def test_new_event_does_not_clear_transport_uncertainty(db, watched):
    await arm(db, watched)
    settle(watched)
    watched.native_wake.side_effect = MailWakeError("wake_transport_uncertain")
    await service.poll(db, watched.scope_id)
    settle(watched, event="owner-completed-2")
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "delivery_unknown"
    assert (await row(db, watched)).sequence == 2
    watched.native_wake.assert_awaited_once()
    assert await count_notices(db) == 1


@pytest.mark.asyncio
async def test_many_historical_watches_do_not_block_current_reads(db, watched):
    await arm(db, watched)
    for number in range(100, 140):
        item = GithubWorkItem(scope_id=watched.scope_id, issue_number=number, issue_title="History",
            issue_url="u", github_updated_at=datetime.utcnow(), dispatch_status="completed")
        db.add(item); await db.flush()
        db.add(GithubOwnerFollowup(work_item_id=item.id, scope_id=watched.scope_id, state="assessed",
            context={}, registered_at=datetime.utcnow(), baseline_event="history", last_action_hash="history"))
    await db.commit()
    assert len(await service.summary(db, watched.scope_id)) == 1
    assert (await read(db, watched))["followup_token"]
    assert await db.scalar(select(func.count()).select_from(GithubOwnerFollowup)) == 41


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "leader"])
async def test_new_scope_or_leader_session_at_final_cas_refuses_watch(db, watched, monkeypatch, change):
    call = request(await read(db, watched))
    original = db.execute
    injected = False

    async def execute(statement, *args, **kwargs):
        nonlocal injected
        if not injected and str(statement).startswith("UPDATE github_backlog_coordination"):
            injected = True
            if change == "scope":
                db.add(TeamGithubScope(preset_id=watched.preset.id, repo_owner="o", repo_name="extra", repo_path="/tmp/extra"))
            else:
                db.add(MailAgentSession(member_id=watched.leader.member_id, source="mcp", provider="codex-cli",
                    session_key="fixture-new-leader", team_slot_id=watched.leader.team_slot_id,
                    team_preset_id=watched.preset.id, bound_pane_pid=9999, bound_pane_proc_start="9",
                    wake_enabled=True, capability_token_hash="replacement"))
            await db.flush()
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", execute)
    with pytest.raises(CoordinationError, match="followup_read_changed"):
        await service.report(db, watched.scope_id, watched.leader, call)
    assert injected
    # A failed CAS rolled back the inserted candidate and did not persist a watch.
    assert await db.scalar(select(func.count()).select_from(GithubOwnerFollowup)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["lookup", "text", "enter"])
async def test_guarded_transport_rechecks_after_lookup_and_staged_text_is_uncertain(monkeypatch, boundary):
    from app.services import agent_mail_service as mail_module
    sent = []
    allowed = True
    pane = SimpleNamespace(pid=1234, pane_id="%1", tmux_target="fixture:%1")

    def run(command, **kwargs):
        nonlocal allowed
        sent.append(command)
        if command[1] == "display-message":
            if boundary == "lookup": allowed = False
            return SimpleNamespace(stdout="%1|1234\n")
        if "-l" in command and boundary == "text": allowed = False
        if command[-1] == "Enter" and boundary == "enter":
            raise mail_module.subprocess.TimeoutExpired(command, 5)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(mail_module.subprocess, "run", run)
    monkeypatch.setattr(mail_module.peer_process, "pane_is_alive", lambda *_: True)
    monkeypatch.setattr(mail_module, "TMUX_ENTER_DELAY_SECONDS", 0)
    guard = AsyncMock(side_effect=lambda: allowed)
    with pytest.raises(MailWakeError, match="wake_target_stale" if boundary == "lookup" else "wake_transport_uncertain"):
        await agent_mail_service._send_guarded_tmux_inbox_check(pane, "Fixture notice", "1", guard, lambda: True)
    assert any("-l" in command for command in sent) == (boundary != "lookup")
    assert any(command[-1] == "Enter" for command in sent) == (boundary == "enter")


@pytest.mark.asyncio
async def test_api_requires_current_authenticated_leader_and_uses_private_read_only_token(db, watched, monkeypatch):
    import httpx
    from app.database import get_db
    from app.main import app
    from app.config import settings
    monkeypatch.setattr(settings, "operator_token", "fixture-operator")
    async def fixture_db():
        yield db
    app.dependency_overrides[get_db] = fixture_db
    body = request(await read(db, watched)).model_dump()
    path = f"/api/v1/agent-teams/github-scopes/{watched.scope_id}/owner-followups"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            assert (await client.post(path, json=body)).status_code == 401
            assert (await client.post(path, json=body, headers={"X-Deck-Operator-Token":"fixture-operator"})).status_code == 401
            accepted = await client.post(path, json=body, headers={"X-Deck-Session-Token":"fixture-session-token"})
            assert accepted.status_code == 200, accepted.text
            assert accepted.headers["cache-control"] == "no-store"
            assert "followup_token" not in accepted.text
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_fresh_sdk_idle_attestation_preserves_busy_leader_debt(db, watched):
    await arm(db, watched)
    settle(watched, leader_idle=False)
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).sequence == 1
    watched.activities[watched.owner.team_slot_id] = replace(
        watched.activities[watched.owner.team_slot_id], settlement_id=None,
        current_settlement_id="owner-completed-1")
    watched.activities[watched.leader.team_slot_id] = replace(
        watched.activities[watched.leader.team_slot_id], state="idle", reason="native_turn_completed")
    await service.poll(db, watched.scope_id)
    assert (await row(db, watched)).state == "delivered"
    assert (await row(db, watched)).sequence == 1
    assert await count_notices(db) == 1
