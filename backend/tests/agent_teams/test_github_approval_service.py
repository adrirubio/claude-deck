"""Leader timeout clocks and initial approval history use disposable data."""
import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update

from app.api.v1 import agent_mail
from app.config import settings
from app.models.database import (
    AgentTeamSlot, GithubApprovalRequest, GithubAttemptScopeRevision,
    GithubWorkItem, GithubWorkspace, MailAgentSession, MailMessage, TeamGithubScope,
)
from app.models.schemas import MailApprovalRequestCreate
from app.services.agent_mail_service import agent_mail_service
from app.services.github_approval_service import GithubApprovalError, github_approval_service
from app.services.github_dispatch_service import github_dispatch_service
from app.utils import peer_process
from tests.agent_mail.test_api import _dispatch_approval_fixture


START = datetime(2026, 10, 12, 12, 0, 0, 123456)


class Clock(datetime):
    value = START

    @classmethod
    def utcnow(cls):
        return cls.value


@pytest_asyncio.fixture
async def timed_attempt(db, monkeypatch, tmp_path):
    Clock.value = START
    monkeypatch.setattr(importlib.import_module("app.services.github_dispatch_service"), "datetime", Clock)
    monkeypatch.setattr(importlib.import_module("app.services.github_approval_service"), "datetime", Clock)
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "github_leader_ack_timeout_seconds", 300)
    monkeypatch.setattr(settings, "github_nudge_grace_seconds", 120)
    monkeypatch.setattr(settings, "github_owner_idle_timeout_seconds", 1800)
    monkeypatch.setattr(settings, "github_owner_registration_grace_seconds", 120)
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda *_args: True)
    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", AsyncMock())
    monkeypatch.setattr(importlib.import_module("app.services.native_owner_contact"), "renew_native_owner_contact", AsyncMock())
    item, members, _tokens = await _dispatch_approval_fixture(db)
    scope = await db.get(TeamGithubScope, item.scope_id)
    slots = list((await db.scalars(select(AgentTeamSlot).where(AgentTeamSlot.preset_id == scope.preset_id).order_by(AgentTeamSlot.position))).all())
    item.created_at = item.updated_at = item.dispatched_at = START
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path), leased_item_id=item.id,
                                lease_token="timeout-fixture", leased_at=START, lease_last_owner_contact_at=START)
    db.add(workspace)
    await db.commit()
    return SimpleNamespace(item=item, scope=scope, slots=slots, leader=members[0], owner=members[1], workspace=workspace)


async def request_plan(db, attempt, minutes=6):
    Clock.value = START + timedelta(minutes=minutes)
    session = await db.scalar(select(MailAgentSession).where(MailAgentSession.member_id == attempt.owner.id))
    response = await agent_mail.request_work_item_approval(
        MailApprovalRequestCreate(work_item_id=attempt.item.id, dispatch_nonce=attempt.item.dispatch_nonce, summary="Bounded timeout fixture"),
        session, db)
    approval = await db.get(GithubApprovalRequest, response.id)
    approval.created_at = Clock.value
    await db.commit()
    return approval


async def monitor(db, attempt, minutes):
    Clock.value = START + timedelta(minutes=minutes)
    await github_dispatch_service.monitor_dispatched(db, attempt.scope, attempt.slots,
        wake_state_by_slot={slot.id: "wakeable" for slot in attempt.slots})
    await db.refresh(attempt.item)


@pytest.mark.asyncio
async def test_plan_after_six_minutes_leaves_four_minutes_for_leader(db, timed_attempt):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    attempt.item.last_nudge_at = START + timedelta(minutes=5)
    await db.commit()
    await monitor(db, attempt, minutes=10)
    assert attempt.item.dispatch_status == "dispatched"
    assert attempt.item.escalation_reason is None
    decided, changed = await github_approval_service.decide(db, attempt.item,
        authenticated_leader_member_id=attempt.leader.id, decision="approved", reason="Within the plan clock", request_id=approval.id)
    assert changed and decided.status == "approved"
    assert decided.decided_at == START + timedelta(minutes=10)
    assert attempt.item.dispatch_status == "dispatched"


@pytest.mark.asyncio
async def test_no_plan_after_ten_minutes_does_not_time_out_leader(db, timed_attempt):
    attempt = timed_attempt
    attempt.item.last_nudge_at = START + timedelta(minutes=7)
    await db.commit()
    await monitor(db, attempt, minutes=10)
    assert attempt.item.dispatch_status == "dispatched"
    assert attempt.item.escalation_reason is None
    assert await github_approval_service.current_pending(db, attempt.item.id) is None


@pytest.mark.asyncio
async def test_real_leader_timeout_supersedes_initial_request_and_allows_retry(db, timed_attempt):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    attempt.item.last_nudge_at = START + timedelta(minutes=11, seconds=1)
    await db.commit()
    await monitor(db, attempt, minutes=14)
    await db.refresh(approval)
    assert attempt.item.dispatch_status == "escalated"
    assert attempt.item.escalation_reason == "leader_ack_timeout"
    assert approval.status == "superseded"
    assert approval.superseded_at == START + timedelta(minutes=14)
    root = await db.get(MailMessage, approval.request_message_id)
    assert root.request_status == "superseded"
    assert await github_approval_service.current_pending(db, attempt.item.id) is None
    assert github_dispatch_service.retry_eligibility(attempt.item, pending_approval=False).allowed
    assert await github_dispatch_service.can_auto_retry_from_issue_update(db, attempt.item)
    await db.refresh(attempt.workspace)
    assert attempt.workspace.lease_token == "timeout-fixture"
    assert attempt.workspace.leased_item_id == attempt.item.id
    assert attempt.item.approval_round_count == 1
    assert attempt.item.retry_count == 0


@pytest.mark.asyncio
async def test_nudge_before_plan_does_not_consume_new_request_grace(db, timed_attempt):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    attempt.item.last_nudge_at = START + timedelta(minutes=5)
    await db.commit()
    await monitor(db, attempt, minutes=12)
    assert attempt.item.dispatch_status == "dispatched"
    assert attempt.item.last_nudge_at == START + timedelta(minutes=12)
    await monitor(db, attempt, minutes=14)
    await db.refresh(approval)
    assert attempt.item.dispatch_status == "dispatched"
    assert approval.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["nonce", "round", "owner", "leader", "continuation", "other_item"])
async def test_timeout_keeps_unbound_requests_pending(db, timed_attempt, binding):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    if binding == "nonce":
        approval.dispatch_nonce = "older-attempt"
    elif binding == "round":
        approval.approval_round = 0
    elif binding == "owner":
        approval.owner_member_id = attempt.leader.id
    elif binding == "leader":
        approval.leader_member_id = attempt.owner.id
    elif binding == "continuation":
        revision = GithubAttemptScopeRevision(
            work_item_id=attempt.item.id, dispatch_nonce=attempt.item.dispatch_nonce,
            revision=1, owner_slot_id=attempt.item.owner_slot_id,
            owner_member_id=attempt.owner.id, phase="diagnostic",
            execution_target="collect evidence", summary="bounded scope",
            allowed_paths=["backend/tests"], allowed_actions=["inspect"],
            allowed_commands=["pytest -q"], prohibited_actions=["merge"],
            tool_fallbacks={}, baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
            originating_escalation_reason="owner_idle_timeout",
            expected_workspace_id=attempt.workspace.id, expected_lease_token_hash="fixture-hash",
            max_failed_heads=1, approval_request_id=approval.id,
        )
        db.add(revision)
        await db.flush()
        approval.request_kind = "continuation"
        approval.scope_revision_id = revision.id
    else:
        other = GithubWorkItem(scope_id=attempt.scope.id, issue_number=92,
            issue_title="Other item", issue_url="u", github_updated_at=START)
        db.add(other)
        await db.flush()
        approval.work_item_id = other.id
    attempt.item.last_nudge_at = START + timedelta(minutes=11, seconds=1)
    await db.commit()
    await monitor(db, attempt, minutes=14)
    assert attempt.item.dispatch_status == "dispatched"
    assert not await github_approval_service.supersede_initial_for_timeout(db, attempt.item, approval)
    await db.rollback()
    await db.refresh(approval)
    assert approval.status == "pending"
    assert approval.superseded_at is None
    root = await db.get(MailMessage, approval.request_message_id)
    assert root.request_status == "pending"
    if binding == "nonce":
        await db.refresh(attempt.item)
        await db.refresh(attempt.leader)
        with pytest.raises(GithubApprovalError, match="stale_nonce"):
            await github_approval_service.decide(db, attempt.item,
                authenticated_leader_member_id=attempt.leader.id,
                decision="approved", reason="Stale request", request_id=approval.id)
        await db.refresh(approval)
        assert approval.status == "pending"
    if binding == "continuation":
        await db.refresh(revision)
        assert revision.status == "proposed"


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["nonce", "round", "owner", "ack", "nudge", "pr", "scope", "request_time"])
async def test_timeout_refuses_database_changes_after_request_read(db, timed_attempt, monkeypatch, drift):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    attempt.item.last_nudge_at = START + timedelta(minutes=11, seconds=1)
    await db.commit()
    original = github_approval_service.supersede_initial_for_timeout

    async def change_before_guard(db_, item, request):
        if drift == "request_time":
            statement = update(GithubApprovalRequest).where(GithubApprovalRequest.id == request.id).values(created_at=START + timedelta(minutes=13))
        else:
            changes = {
                "nonce": {"dispatch_nonce": "new-attempt"},
                "round": {"approval_round_count": 2},
                "owner": {"owner_slot_id": attempt.leader.team_slot_id},
                "ack": {"ack_received_at": Clock.value},
                "nudge": {"last_nudge_at": Clock.value},
                "pr": {"pr_number": 200},
                "scope": {"active_scope_revision": 1},
            }
            statement = update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(**changes[drift])
        await db_.execute(statement.execution_options(synchronize_session=False))
        await db_.commit()
        return await original(db_, item, request)

    monkeypatch.setattr(github_approval_service, "supersede_initial_for_timeout", change_before_guard)
    await monitor(db, attempt, minutes=14)
    await db.refresh(approval)
    assert attempt.item.dispatch_status == "dispatched"
    assert attempt.item.escalation_reason is None
    assert approval.status == "pending"


@pytest.mark.asyncio
async def test_leader_decision_before_timeout_write_remains_approved(db, timed_attempt, monkeypatch):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    attempt.item.last_nudge_at = START + timedelta(minutes=11, seconds=1)
    await db.commit()
    original = github_approval_service.supersede_initial_for_timeout

    async def decide_before_guard(db_, item, request):
        await github_approval_service.decide(db_, item,
            authenticated_leader_member_id=attempt.leader.id,
            decision="approved", reason="Decision won the race", request_id=request.id)
        return await original(db_, item, request)

    monkeypatch.setattr(github_approval_service, "supersede_initial_for_timeout", decide_before_guard)
    await monitor(db, attempt, minutes=14)
    await db.refresh(approval)
    assert attempt.item.dispatch_status == "dispatched"
    assert approval.status == "approved"
    assert approval.superseded_at is None


@pytest.mark.asyncio
async def test_failed_timeout_commit_keeps_item_and_request_unchanged(db, timed_attempt, monkeypatch):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    attempt.item.last_nudge_at = START + timedelta(minutes=11, seconds=1)
    await db.commit()
    broadcast = AsyncMock()
    monkeypatch.setattr(github_dispatch_service, "_send_escalation_broadcast", broadcast)
    monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("Commit failed")))
    with pytest.raises(RuntimeError, match="Commit failed"):
        await monitor(db, attempt, minutes=14)
    await db.rollback()
    await db.refresh(attempt.item)
    await db.refresh(approval)
    assert attempt.item.dispatch_status == "dispatched"
    assert attempt.item.escalation_reason is None
    assert approval.status == "pending"
    assert approval.superseded_at is None
    root = await db.get(MailMessage, approval.request_message_id)
    assert root.request_status == "pending"
    broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_notice_failure_keeps_timeout_and_supersession_committed(db, timed_attempt, monkeypatch):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    attempt.item.last_nudge_at = START + timedelta(minutes=11, seconds=1)
    await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_send_escalation_broadcast",
        AsyncMock(side_effect=RuntimeError("Mail failed")))
    await monitor(db, attempt, minutes=14)
    await db.refresh(approval)
    assert attempt.item.dispatch_status == "escalated"
    assert attempt.item.escalation_reason == "leader_ack_timeout"
    assert approval.status == "superseded"
    root = await db.get(MailMessage, approval.request_message_id)
    assert root.request_status == "superseded"


@pytest.mark.asyncio
async def test_timeout_accepts_legacy_whole_second_dispatch_timestamp(db, timed_attempt):
    attempt = timed_attempt
    approval = await request_plan(db, attempt)
    await db.execute(text("UPDATE github_work_items SET dispatched_at = :stamp WHERE id = :item_id"),
        {"stamp": "2026-10-12 12:00:00", "item_id": attempt.item.id})
    attempt.item.last_nudge_at = START + timedelta(minutes=11, seconds=1)
    await db.commit()
    await db.refresh(attempt.item)
    await monitor(db, attempt, minutes=14)
    await db.refresh(approval)
    assert attempt.item.dispatch_status == "escalated"
    assert approval.status == "superseded"
