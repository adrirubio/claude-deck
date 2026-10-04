"""Isolated backlog coordination regressions; no GitHub or live panes."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.config import settings
from app.models.coordination import CoordinationAssessment, CoordinationPolicy
from app.models.database import (
    AgentTeamPreset, AgentTeamSlot, GithubApprovalRequest, GithubBacklogCoordination,
    GithubWorkItem, GithubWorkspace, MailAgentSession, MailMessage, MailTeamMember,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service
from app.services.github_coordination_service import (
    CoordinationError, github_coordination_service as service, hold_code,
)
from app.services.github_dispatch_service import github_dispatch_service


class Client:
    def __init__(self):
        self.calls = 0
        self.issues = {n: {"number": n, "state": "open", "updated_at": "2026-10-04T10:00:00Z",
                          "repository_url": "https://api.github.com/repos/o/r", "labels": []}
                       for n in [7, 8]}

    async def get_issues_by_number(self, owner, repo, numbers):
        self.calls += 1
        return {n: self.issues[n] for n in numbers if n in self.issues}


def report(row, *, eligible=True):
    return CoordinationAssessment(generation=row.generation, request_sequence=row.request_sequence, entries=[
        {"issue_number": 7, "disposition": "human_decision_blocked", "reason": "human_merge",
         "required_actor": "operator", "evidence_issue_numbers": [7]},
        {"issue_number": 8, "disposition": "eligible" if eligible else "human_decision_blocked",
         "reason": "admission" if eligible else "pilot_decision",
         "required_actor": "leader" if eligible else "operator", "evidence_issue_numbers": [7, 8]},
    ])


@pytest_asyncio.fixture
async def team(db, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "github_coordination_hold_paths", [])
    monkeypatch.setattr(settings, "github_recovery_only_attempt", "")
    monkeypatch.setattr("app.utils.peer_process.pane_is_alive", lambda *_: True)
    wake = AsyncMock(return_value=[])
    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", wake)
    monkeypatch.setattr(agent_mail_service, "_nudge_session_for_member", AsyncMock(return_value=SimpleNamespace(pid=1234)))
    preset = AgentTeamPreset(name="Fixture", autonomy_enabled=True)
    db.add(preset); await db.flush()
    slot = AgentTeamSlot(preset_id=preset.id, position=0, display_name="Leader", provider="codex-cli",
                         repo_id="r", repo_path="/tmp/fixture", repo_name="r", role="Leader")
    owner_slot = AgentTeamSlot(preset_id=preset.id, position=1, display_name="Owner", provider="codex-cli",
                               repo_id="r", repo_path="/tmp/fixture-owner", repo_name="r", role="Implementer")
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="o", repo_name="r", repo_path="/tmp/fixture",
                            merge_policy="human", max_concurrent_dispatched=2)
    db.add_all([slot, owner_slot, scope]); await db.flush()
    member = MailTeamMember(identity_key="fixture-leader", repo_id="r", repo_path="/tmp/fixture", repo_name="r",
                            display_name="Leader", participant_kind="team_slot",
                            team_preset_id=preset.id, team_slot_id=slot.id)
    owner_member = MailTeamMember(identity_key="fixture-owner", repo_id="r", repo_path="/tmp/fixture-owner", repo_name="r",
                                  display_name="Owner", participant_kind="team_slot",
                                  team_preset_id=preset.id, team_slot_id=owner_slot.id)
    db.add_all([member, owner_member]); await db.flush()
    session = MailAgentSession(member_id=member.id, provider="codex-cli", source="mcp",
                               session_key="fixture-session", team_preset_id=preset.id, team_slot_id=slot.id,
                               capability_token_hash=agent_mail_service.hash_capability_token("fixture-session-token"),
                               bound_pane_pid=1234, bound_pane_proc_start="1", wake_enabled=True)
    item = GithubWorkItem(scope_id=scope.id, issue_number=7, issue_title="Waiting", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="ready_for_review",
                          pr_number=25, owner_slot_id=owner_slot.id,
                          last_verified_sha="a" * 40, dispatch_nonce="fixture-nonce")
    db.add_all([session, item]); await db.flush()
    lease = GithubWorkspace(scope_id=scope.id, path="/tmp/fixture-one", leased_item_id=item.id,
                            lease_token="fixture-lease", leased_at=datetime.utcnow())
    free = GithubWorkspace(scope_id=scope.id, path="/tmp/fixture-two")
    approval = GithubApprovalRequest(work_item_id=item.id, request_kind="initial",
                                    dispatch_nonce=item.dispatch_nonce, approval_round=1,
                                    owner_member_id=owner_member.id, leader_member_id=member.id, status="approved",
                                    request_fingerprint="fixture-approved-request")
    db.add_all([lease, free, approval]); await db.commit()
    await service.configure(db, scope.id, CoordinationPolicy(expected_version=0, enabled=True, issue_numbers=[7, 8]))
    return SimpleNamespace(preset=preset, scope=scope, scope_id=scope.id, leader=session, item=item, lease=lease,
                           free=free, approval=approval, client=Client(), wake=wake)


@pytest.mark.asyncio
async def test_review_wait_does_not_stop_assessment_of_independent_unlabelled_work(db, team):
    original = (team.item.dispatch_nonce, team.item.last_verified_sha, team.lease.lease_token, team.approval.status)
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert row.snapshot["active_implementations"] == 0
    assert row.snapshot["available_workspaces"] == 1
    assert row.snapshot["leased_workspaces"] == 1
    assert await github_dispatch_service.scope_active_count(db, team.scope_id) == 0
    await service.assess(db, team.scope_id, team.leader, report(row), team.client)
    summary = await service.summary(db, team.scope_id)
    assert summary["eligible_count"] == 1 and summary["assessment_current"] is True
    assert not team.client.issues[8]["labels"]  # Advice does not mutate labels or authority.
    assert original == (team.item.dispatch_nonce, team.item.last_verified_sha, team.lease.lease_token, team.approval.status)


@pytest.mark.asyncio
async def test_leader_admission_dispatches_independent_work_preserving_review_item(db, team, monkeypatch):
    from app.services.github_workspace_service import github_workspace_service
    original = (team.item.dispatch_nonce, team.item.last_verified_sha, team.lease.lease_token, team.approval.status)
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    await service.assess(db, team.scope_id, team.leader, report(row), team.client)
    # Simulate the Leader's separately authorized admission after reviewing gates.
    team.client.issues[8]["labels"] = [{"name": team.scope.dispatch_label}, {"name": "area:backend"}]
    owner = await db.get(AgentTeamSlot, team.item.owner_slot_id)
    owner.area_labels = ["area:backend"]
    team.scope.github_auth_mode = "ambient"
    team.scope.base_ref = "origin/master"
    for field in ("github_app_id", "github_app_private_key_path", "github_app_bot_login"):
        monkeypatch.setattr(settings, field, "")
    independent = GithubWorkItem(scope_id=team.scope_id, issue_number=8, issue_title="Independent",
        issue_url="u", github_updated_at=datetime.utcnow(), dispatch_status="pending")
    db.add(independent); await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 999999)
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: [])
    for method in ("reset_workspace", "configure_dispatch_worktree", "validate_app_remote"):
        monkeypatch.setattr(github_workspace_service, method, AsyncMock(return_value=None))
    monkeypatch.setattr(github_workspace_service, "_runner", AsyncMock(return_value=(0, "")))
    team.client.list_repo_labels = AsyncMock(return_value=[team.scope.dispatch_label, "area:backend"])
    slots = list((await db.scalars(select(AgentTeamSlot).where(AgentTeamSlot.preset_id == team.preset.id))).all())
    await github_dispatch_service.dispatch_pending(db, team.scope, slots, client=team.client,
        launcher=AsyncMock(return_value=SimpleNamespace(launch_id=99)),
        issue_labels_by_number={8: [team.scope.dispatch_label, "area:backend"]})
    await db.refresh(independent); await db.refresh(team.lease); await db.refresh(team.item); await db.refresh(team.approval)
    assert independent.dispatch_status == "dispatched", (independent.pending_reason, independent.status_note)
    assert independent.owner_slot_id == owner.id
    assert await github_dispatch_service.scope_active_count(db, team.scope_id) == 1
    assert original == (team.item.dispatch_nonce, team.item.last_verified_sha, team.lease.lease_token, team.approval.status)
    assert team.item.pr_number == 25 and team.item.dispatch_status == "ready_for_review"


@pytest.mark.asyncio
async def test_pilot_gate_visible_without_implementation_dispatch(db, team):
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    await service.assess(db, team.scope_id, team.leader, report(row, eligible=False), team.client)
    summary = await service.summary(db, team.scope_id)
    assert summary["eligible_count"] == 0
    assert summary["entries"][1]["reason"] == "pilot_decision"
    assert await db.scalar(select(func.count()).select_from(GithubWorkItem)) == 1


@pytest.mark.asyncio
async def test_unchanged_polls_heartbeat_and_receipt_do_not_repeat_mail(db, team):
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    generation = row.generation
    receipt = report(row)
    await service.assess(db, team.scope_id, team.leader, receipt, team.client)
    first_time = (await service.state(db, team.scope_id)).last_assessed_at
    team.leader.last_seen_at = datetime.utcnow()
    team.item.updated_at = datetime.utcnow()
    await db.commit()
    await service.reconcile(db, team.scope_id, team.client)
    await service.assess(db, team.scope_id, team.leader, receipt, team.client)
    row = await service.state(db, team.scope_id)
    assert row.generation == generation and row.daily_requests == 1
    assert row.last_assessed_at == first_time
    assert await db.scalar(select(func.count()).select_from(MailMessage)) == 1
    assert team.wake.await_count == 1


@pytest.mark.asyncio
async def test_fresh_github_change_refuses_old_assessment(db, team):
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    receipt = report(row)
    team.client.issues[8]["updated_at"] = "2026-10-04T11:00:00Z"
    with pytest.raises(CoordinationError, match="coordination_snapshot_changed"):
        await service.assess(db, team.scope_id, team.leader, receipt, team.client)
    assert not row.assessments


@pytest.mark.asyncio
async def test_changed_snapshot_debounces_then_sends_new_request(db, team):
    await service.reconcile(db, team.scope_id, team.client)
    team.client.issues[8]["updated_at"] = "2026-10-04T11:00:00Z"
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert row.generation == 2 and row.requested_generation == 1
    row.last_requested_at -= timedelta(seconds=61); await db.commit()
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert row.requested_generation == 2 and row.daily_requests == 2


@pytest.mark.asyncio
async def test_budget_survives_config_edit_restart_and_fallback_is_bounded(db, team, monkeypatch):
    await service.reconcile(db, team.scope_id, team.client)
    for _ in range(4):
        row = await service.state(db, team.scope_id)
        row.last_requested_at -= timedelta(hours=1); await db.commit()
        await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert row.daily_requests == 3 and row.snapshot_requests == 3
    assert row.error_code == "coordination_capped"
    await service.configure(db, team.scope_id, CoordinationPolicy(expected_version=row.version,
                             enabled=True, issue_numbers=[7, 8], max_daily_requests=3))
    monkeypatch.setattr("app.services.github_coordination_service._BOOT_ID", "fixture-restart")
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert row.daily_requests == 3
    assert await db.scalar(select(func.count()).select_from(MailMessage)) == 3


@pytest.mark.asyncio
async def test_unknown_backlog_is_not_reported_as_empty(db, team):
    await service.reconcile(db, team.scope_id, team.client)
    del team.client.issues[8]
    await service.reconcile(db, team.scope_id, team.client)
    summary = await service.summary(db, team.scope_id)
    assert summary["status"] == "backlog_unavailable" and summary["eligible_count"] is None


@pytest.mark.asyncio
async def test_wrong_repository_observation_is_unknown(db, team):
    team.client.issues[8]["repository_url"] = "https://api.github.com/repos/other/r"
    await service.reconcile(db, team.scope_id, team.client)
    assert (await service.summary(db, team.scope_id))["status"] == "backlog_unavailable"
    assert team.wake.await_count == 0


@pytest.mark.asyncio
async def test_off_hold_and_stale_leader_do_not_write_assessments(db, team, tmp_path, monkeypatch):
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    receipt = report(row)
    hold = tmp_path / "HOLD.json"; hold.write_text("{}")
    monkeypatch.setattr(settings, "github_coordination_hold_paths", [str(hold)])
    before = row.version
    await service.reconcile(db, team.scope_id, team.client)
    with pytest.raises(CoordinationError, match="hold"):
        await service.assess(db, team.scope_id, team.leader, receipt, team.client)
    assert (await service.state(db, team.scope_id)).version == before
    hold.unlink()
    team.preset.autonomy_enabled = False; await db.commit()
    with pytest.raises(CoordinationError, match="autonomy_off"):
        await service.assess(db, team.scope_id, team.leader, receipt, team.client)
    await service.reconcile(db, team.scope_id, team.client)
    assert (await service.state(db, team.scope_id)).version == before
    team.preset.autonomy_enabled = True; team.leader.closed_at = datetime.utcnow(); await db.commit()
    with pytest.raises(CoordinationError, match="leader_unavailable"):
        await service.assess(db, team.scope_id, team.leader, receipt, team.client)


def test_unreadable_or_invalid_hold_configuration_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "github_coordination_hold_paths", ["relative-marker"])
    assert hold_code() == "hold_unavailable"
    marker = tmp_path / "HOLD"; marker.symlink_to(tmp_path / "missing")
    monkeypatch.setattr(settings, "github_coordination_hold_paths", [str(marker)])
    assert hold_code() == "hold"


@pytest.mark.asyncio
async def test_full_assessment_and_assigned_evidence_required(db, team):
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    receipt = report(row)
    duplicate = receipt.model_copy(update={"entries": [receipt.entries[0], receipt.entries[0]]})
    with pytest.raises(CoordinationError, match="complete_assessment_required"):
        await service.assess(db, team.scope_id, team.leader, duplicate, team.client)
    receipt.entries[1].evidence_issue_numbers = [999]
    with pytest.raises(CoordinationError, match="assigned_evidence_required"):
        await service.assess(db, team.scope_id, team.leader, receipt, team.client)


@pytest.mark.asyncio
async def test_disabled_workspace_not_claimed_available(db, team):
    team.free.dispatchable = False; await db.commit()
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert row.snapshot["available_workspaces"] == 0
    with pytest.raises(CoordinationError, match="implementation_not_available"):
        await service.assess(db, team.scope_id, team.leader, report(row), team.client)


@pytest.mark.asyncio
async def test_transport_failure_is_bounded_and_sanitized(db, team):
    team.client.get_issues_by_number = AsyncMock(side_effect=httpx.ConnectError("fixture-only"))
    await service.reconcile(db, team.scope_id, team.client)
    summary = await service.summary(db, team.scope_id)
    assert summary["status"] == "backlog_unavailable"
    assert "fixture-only" not in str(summary)


@pytest.mark.asyncio
async def test_mail_failure_rolls_back_reserved_quota_and_linkage(db, team, monkeypatch):
    monkeypatch.setattr(agent_mail_service, "send_message", AsyncMock(side_effect=RuntimeError("fixture")))
    with pytest.raises(RuntimeError, match="fixture"):
        await service.reconcile(db, team.scope_id, team.client)
    await db.rollback()
    row = await service.state(db, team.scope_id)
    assert row.daily_requests == 0 and row.request_sequence == 0 and row.message_id is None
    assert await db.scalar(select(func.count()).select_from(MailMessage)) == 0


@pytest.mark.asyncio
async def test_policy_edit_immediately_invalidates_old_current_assessment(db, team):
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    await service.assess(db, team.scope_id, team.leader, report(row), team.client)
    row = await service.state(db, team.scope_id)
    await service.configure(db, team.scope_id, CoordinationPolicy(
        expected_version=row.version, enabled=True, issue_numbers=[7, 8], fallback_seconds=3600,
    ))
    summary = await service.summary(db, team.scope_id)
    assert summary["eligible_count"] is None and not summary["assessment_current"]
    assert summary["entries"] and summary["requests_today"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["restart", "resume", "workspace"])
async def test_local_authority_change_invalidates_summary_before_next_poll(db, team, monkeypatch, change):
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    await service.assess(db, team.scope_id, team.leader, report(row), team.client)
    if change == "restart":
        monkeypatch.setattr("app.services.github_coordination_service._BOOT_ID", "next-fixture-boot")
    elif change == "resume":
        team.preset.updated_at = datetime.utcnow()
    else:
        team.free.dispatchable = False
    await db.commit()
    summary = await service.summary(db, team.scope_id)
    assert summary["status"] == "stale" and summary["eligible_count"] is None


@pytest.mark.asyncio
async def test_work_change_between_snapshot_and_claim_cannot_send_request(db, team, monkeypatch):
    original = service._context
    async def changed_context(*args):
        result = await original(*args)
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == team.item.id).values(dispatch_status="verifying"))
        return result
    monkeypatch.setattr(service, "_context", changed_context)
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert row.daily_requests == 0 and row.message_id is None
    assert team.wake.await_count == 0


@pytest.mark.asyncio
async def test_disable_after_mail_commit_prevents_wake(db, team, monkeypatch):
    original = db.commit
    commits = 0
    async def commit_then_disable():
        nonlocal commits
        await original()
        commits += 1
        if commits == 2:
            await db.execute(update(GithubBacklogCoordination).where(
                GithubBacklogCoordination.scope_id == team.scope_id,
            ).values(enabled=False, version=GithubBacklogCoordination.version + 1))
            await original()
    monkeypatch.setattr(db, "commit", commit_then_disable)
    await service.reconcile(db, team.scope_id, team.client)
    row = await service.state(db, team.scope_id)
    assert not row.enabled and row.daily_requests == 1
    assert team.wake.await_count == 0


@pytest.mark.asyncio
async def test_api_requires_operator_for_policy_and_exact_leader_for_receipt(db, team, monkeypatch):
    from app.database import get_db
    from app.main import app
    monkeypatch.setattr(settings, "operator_token", "fixture-operator-token")
    monkeypatch.setattr("app.services.github_coordination_service.github_client", team.client)
    async def fixture_db():
        yield db
    app.dependency_overrides[get_db] = fixture_db
    path = f"/api/v1/agent-teams/github-scopes/{team.scope_id}/coordination"
    leader_headers = {"X-Deck-Session-Token": "fixture-session-token"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            policy = {"expected_version": 1, "enabled": True, "issue_numbers": [7, 8]}
            assert (await client.put(path + "-policy", json=policy, headers=leader_headers)).status_code == 401
            assert (await client.get(path + "-request")).status_code == 401
            await service.reconcile(db, team.scope_id, team.client)
            row = await service.state(db, team.scope_id)
            payload = report(row).model_dump()
            assert (await client.post(path + "-assessments", json=payload)).status_code == 401
            assert (await client.post(path + "-assessments", json=payload,
                headers={"X-Deck-Operator-Token": "fixture-operator-token"})).status_code == 401
            result = await client.post(path + "-assessments", json=payload, headers=leader_headers)
            assert result.status_code == 200, result.text
            assert result.json()["eligible_count"] == 1
            public = await client.get(path)
            assert public.headers["cache-control"] == "no-store"
            for private in ("fixture-nonce", "fixture-lease", "fixture-session-token", "snapshot_hash", "leader_session_id"):
                assert private not in public.text
    finally:
        app.dependency_overrides.pop(get_db, None)
