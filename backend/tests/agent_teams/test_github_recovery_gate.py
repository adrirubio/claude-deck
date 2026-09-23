"""Fail-closed scheduler isolation for one preserved recovery attempt."""
from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service
from app.services.github_approval_service import github_approval_service
from app.services.github_dispatch_scheduler import GithubDispatchScheduler, github_dispatch_scheduler
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_recovery_gate import GithubRecoveryOnlyAttempt
from app.services.github_verification_service import github_verification_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _attempt(db):
    preset = AgentTeamPreset(name="soak", autonomy_enabled=True)
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Owner",
        provider="codex-cli",
        repo_id="repo",
        repo_path="/tmp/repo",
        repo_name="repo",
    )
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo",
        repo_path="/tmp/repo",
        base_ref="origin/master",
        continuation_enabled=True,
        merge_policy="human",
    )
    db.add_all([slot, scope])
    await db.flush()
    target = GithubWorkItem(
        scope_id=scope.id,
        issue_number=821,
        issue_title="Recovery",
        issue_url="https://example.test/issues/821",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        owner_slot_id=slot.id,
        pr_number=875,
        dispatch_nonce="4173e3b8851fccc8",
        dispatch_head_ref="deck/slot-6/issue-821-4173e3b8851fccc8",
    )
    unrelated = GithubWorkItem(
        scope_id=scope.id,
        issue_number=818,
        issue_title="Protected pending issue",
        issue_url="https://example.test/issues/818",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add_all([target, unrelated])
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/preserved-workspace",
        leased_item_id=target.id,
        leased_at=datetime.utcnow(),
        lease_token="preserved-token",
    )
    member = MailTeamMember(
        identity_key="member:owner",
        repo_id="repo",
        repo_path="/tmp/repo",
        repo_name="repo",
        display_name="Owner",
        team_preset_id=preset.id,
        team_slot_id=slot.id,
    )
    db.add_all([workspace, member])
    await db.flush()
    db.add(GithubAttemptScopeRevision(
        work_item_id=target.id,
        dispatch_nonce=target.dispatch_nonce,
        revision=1,
        owner_slot_id=slot.id,
        owner_member_id=member.id,
        phase="implementation",
        execution_target="hosted_ci",
        summary="Preserved attempt",
        allowed_paths=["tests/playback_smoke.py.in"],
        allowed_actions=["push_pr_head", "request_verification"],
        allowed_commands=[],
        prohibited_actions=[],
        tool_fallbacks={},
        baseline_head_sha="baseline-head",
        baseline_tree_sha="baseline-tree",
        originating_escalation_reason="continuation_budget_exhausted",
        expected_workspace_id=workspace.id,
        expected_lease_token_hash=github_approval_service.lease_token_hash(
            workspace.lease_token
        ),
        max_failed_heads=2,
        status="exhausted",
    ))
    await db.commit()
    selector = GithubRecoveryOnlyAttempt(
        scope.id,
        target.id,
        875,
        target.dispatch_nonce,
        target.dispatch_head_ref,
    )
    return preset, slot, scope, target, unrelated, selector


@pytest.mark.parametrize("value", [
    "1:23:875:4173e3b8851fccc8",
    "0:23:875:4173e3b8851fccc8:branch",
    "1:23:0:4173e3b8851fccc8:branch",
    "1:23:875:wrong:branch",
    "1:23:875:4173e3b8851fccc8:branch name",
])
def test_recovery_only_attempt_rejects_incomplete_or_invalid_identity(value):
    with pytest.raises(ValueError):
        GithubRecoveryOnlyAttempt.parse(value)


def test_recovery_only_attempt_requires_explicit_activation():
    assert GithubRecoveryOnlyAttempt.parse("") is None
    parsed = GithubRecoveryOnlyAttempt.parse(
        "1:23:875:4173e3b8851fccc8:deck/slot-6/issue-821-4173e3b8851fccc8"
    )
    assert parsed == GithubRecoveryOnlyAttempt(
        1, 23, 875, "4173e3b8851fccc8", "deck/slot-6/issue-821-4173e3b8851fccc8"
    )


def test_recovery_only_scheduler_refuses_invalid_configuration(monkeypatch):
    monkeypatch.setattr(settings, "github_recovery_only_attempt", "1:23:875:incomplete")
    with pytest.raises(ValueError):
        GithubDispatchScheduler()


@pytest.mark.asyncio
async def test_recovery_only_scheduler_skips_watcher_dispatch_and_other_items(db, monkeypatch):
    _preset, _slot, scope, target, unrelated, selector = await _attempt(db)
    monkeypatch.setattr(settings, "github_recovery_only_attempt", (
        f"{selector.scope_id}:{selector.work_item_id}:{selector.pr_number}:"
        f"{selector.dispatch_nonce}:{selector.head_ref}"
    ))
    order = []

    async def sync_observed(_db, *, strict):
        assert strict is True
        order.append("observe")

    class Watcher:
        async def poll_scope(self, *_args):
            raise AssertionError("watcher must not run in recovery-only mode")

    class Dispatch:
        async def dispatch_pending(self, *_args, **_kwargs):
            raise AssertionError("pending dispatch must not run in recovery-only mode")

        async def monitor_dispatched(self, *_args):
            raise AssertionError("PR-less monitor must not run in recovery-only mode")

        async def remind_held_leases(self, *_args):
            raise AssertionError("lease reminders must not run in recovery-only mode")

        async def monitor_continuation(self, _db, current_scope, _slots, *, recovery_only_attempt):
            assert current_scope.id == scope.id
            assert recovery_only_attempt == selector
            order.append("continuation")

        async def monitor_recovery(self, _db, current_scope, _slots, *, recovery_only_attempt):
            assert current_scope.id == scope.id
            assert recovery_only_attempt == selector
            order.append("recovery")

    class Verification:
        async def process_scope(self, _db, current_scope, *, client, recovery_only_attempt):
            assert current_scope.id == scope.id
            assert recovery_only_attempt == selector
            order.append("verification")

    monkeypatch.setattr(agent_mail_service, "sync_observed_sessions", sync_observed)
    service = GithubDispatchScheduler(
        watcher=Watcher(), dispatch=Dispatch(), verification=Verification()
    )
    await service.run_repo_once(db, "owner", "repo", client=object())

    await db.refresh(target)
    await db.refresh(unrelated)
    assert order == ["observe", "continuation", "verification", "recovery"]
    assert target.dispatch_status == "escalated"
    assert unrelated.dispatch_status == "pending"


@pytest.mark.asyncio
async def test_recovery_only_scheduler_stops_when_autonomy_turns_off_mid_tick(db, monkeypatch):
    preset, _slot, _scope, _target, _unrelated, selector = await _attempt(db)
    monkeypatch.setattr(settings, "github_recovery_only_attempt", (
        f"{selector.scope_id}:{selector.work_item_id}:{selector.pr_number}:"
        f"{selector.dispatch_nonce}:{selector.head_ref}"
    ))

    async def sync_observed(_db, *, strict):
        assert strict is True

    class Dispatch:
        async def monitor_continuation(self, current_db, _scope, _slots, *, recovery_only_attempt):
            assert recovery_only_attempt == selector
            preset.autonomy_enabled = False
            await current_db.commit()

        async def monitor_recovery(self, *_args, **_kwargs):
            raise AssertionError("recovery ran after autonomy was disabled")

    class Verification:
        async def process_scope(self, *_args, **_kwargs):
            raise AssertionError("verification ran after autonomy was disabled")

    monkeypatch.setattr(agent_mail_service, "sync_observed_sessions", sync_observed)
    service = GithubDispatchScheduler(dispatch=Dispatch(), verification=Verification())
    await service.run_repo_once(db, "owner", "repo", client=object())


@pytest.mark.asyncio
async def test_recovery_only_scheduler_schedules_only_selected_scope(db, monkeypatch):
    _preset, _slot, _scope, _target, _unrelated, selector = await _attempt(db)
    other_preset = AgentTeamPreset(name="other", autonomy_enabled=True)
    db.add(other_preset)
    await db.flush()
    db.add(TeamGithubScope(
        preset_id=other_preset.id,
        repo_owner="elsewhere",
        repo_name="repo",
        repo_path="/tmp/elsewhere",
        base_ref="origin/master",
    ))
    await db.commit()
    monkeypatch.setattr(settings, "github_recovery_only_attempt", (
        f"{selector.scope_id}:{selector.work_item_id}:{selector.pr_number}:"
        f"{selector.dispatch_nonce}:{selector.head_ref}"
    ))

    class Scheduler:
        def __init__(self):
            self.jobs = {}

        def get_jobs(self):
            return []

        def add_job(self, _function, _trigger, **kwargs):
            self.jobs[kwargs["id"]] = kwargs

    scheduler = Scheduler()
    await GithubDispatchScheduler(scheduler=scheduler).sync_jobs(db)
    assert list(scheduler.jobs) == ["github-dispatch:owner/repo"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [
    "pr", "nonce", "head", "lease", "replaced_token", "revision", "owner", "policy", "merge"
])
async def test_recovery_only_scheduler_refuses_stale_or_unsafe_target(db, monkeypatch, changed):
    _preset, slot, scope, target, unrelated, selector = await _attempt(db)
    monkeypatch.setattr(settings, "github_recovery_only_attempt", (
        f"{selector.scope_id}:{selector.work_item_id}:{selector.pr_number}:"
        f"{selector.dispatch_nonce}:{selector.head_ref}"
    ))
    if changed == "pr":
        target.pr_number = 876
    elif changed == "nonce":
        target.dispatch_nonce = "aaaaaaaaaaaaaaaa"
    elif changed == "head":
        target.dispatch_head_ref = "another-branch"
    elif changed == "lease":
        workspace = await db.get(GithubWorkspace, 1)
        workspace.lease_token = None
    elif changed == "replaced_token":
        workspace = await db.get(GithubWorkspace, 1)
        workspace.lease_token = "replacement-token"
    elif changed == "revision":
        revision = await db.get(GithubAttemptScopeRevision, 1)
        await db.delete(revision)
    elif changed == "owner":
        replacement = AgentTeamSlot(
            preset_id=slot.preset_id,
            position=1,
            display_name="Replacement",
            provider="codex-cli",
            repo_id="repo",
            repo_path="/tmp/repo",
            repo_name="repo",
        )
        db.add(replacement)
        await db.flush()
        target.owner_slot_id = replacement.id
    elif changed == "policy":
        scope.continuation_enabled = False
    else:
        scope.merge_policy = "auto"
    await db.commit()

    class RefuseWork:
        async def poll_scope(self, *_args):
            raise AssertionError("watcher ran")

        async def monitor_continuation(self, *_args, **_kwargs):
            raise AssertionError("continuation monitor ran")

        async def process_scope(self, *_args, **_kwargs):
            raise AssertionError("verification ran")

        async def monitor_recovery(self, *_args, **_kwargs):
            raise AssertionError("recovery monitor ran")

    async def unexpected_sync(*_args, **_kwargs):
        raise AssertionError("observed sessions were synchronized for an invalid target")

    monkeypatch.setattr(agent_mail_service, "sync_observed_sessions", unexpected_sync)
    service = GithubDispatchScheduler(
        watcher=RefuseWork(), dispatch=RefuseWork(), verification=RefuseWork()
    )
    await service.run_repo_once(db, "owner", "repo", client=object())
    await db.refresh(unrelated)
    assert unrelated.dispatch_status == "pending"


@pytest.mark.asyncio
async def test_recovery_only_filters_all_monitors_and_verification(db, monkeypatch):
    _preset, slot, scope, target, unrelated, selector = await _attempt(db)
    unrelated.dispatch_status = "escalated"
    unrelated.pr_number = 999
    unrelated.dispatch_nonce = "aaaaaaaaaaaaaaaa"
    unrelated.dispatch_head_ref = "unrelated-head"
    await db.commit()
    reconciled = []

    async def record_reconcile(_db, _scope, item, *, now):
        reconciled.append(item.id)

    monkeypatch.setattr(github_dispatch_service, "_reconcile_revision_exhaustion", record_reconcile)
    await github_dispatch_service.monitor_recovery(
        db, scope, [slot], recovery_only_attempt=selector
    )
    assert reconciled == [target.id]

    unrelated.dispatch_status = "dispatched"
    unrelated.active_scope_revision = 1
    await db.commit()
    monitored = []

    def record_monitor(item, **_kwargs):
        monitored.append(item.id)

    monkeypatch.setattr(github_dispatch_service, "_log_continuation_monitor", record_monitor)
    await github_dispatch_service.monitor_continuation(
        db, scope, [slot], recovery_only_attempt=selector
    )
    assert monitored == []
    await github_dispatch_service.monitor_continuation(db, scope, [slot])
    assert monitored == [unrelated.id]

    unrelated.dispatch_status = "ready_for_review"
    await db.commit()
    reviewed = []

    async def record_review(_db, _scope, item, _client):
        reviewed.append(item.id)

    monkeypatch.setattr(github_verification_service, "_process_review_item", record_review)
    await github_verification_service.process_scope(
        db, scope, client=object(), recovery_only_attempt=selector
    )
    assert reviewed == []
    await github_verification_service.process_scope(db, scope, client=object())
    assert reviewed == [unrelated.id]


@pytest.mark.asyncio
async def test_recovery_only_filters_diagnostic_notification_repair(db, monkeypatch):
    _preset, slot, scope, _target, unrelated, selector = await _attempt(db)
    member = MailTeamMember(
        identity_key="member:other",
        repo_id="repo",
        repo_path="/tmp/repo",
        repo_name="repo",
        display_name="Other",
    )
    db.add(member)
    await db.flush()
    unrelated.dispatch_status = "escalated"
    unrelated.pr_number = 999
    unrelated.dispatch_nonce = "aaaaaaaaaaaaaaaa"
    unrelated.dispatch_head_ref = "unrelated-head"
    unrelated.attempt_phase = "diagnostic"
    unrelated.active_scope_revision = 1
    unrelated.escalation_reason = "continuation_budget_exhausted"
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/other-workspace",
        leased_item_id=unrelated.id,
        leased_at=datetime.utcnow(),
        lease_token="other-token",
    )
    db.add(workspace)
    await db.flush()
    db.add(GithubAttemptScopeRevision(
        work_item_id=unrelated.id,
        dispatch_nonce=unrelated.dispatch_nonce,
        revision=1,
        owner_slot_id=slot.id,
        owner_member_id=member.id,
        phase="diagnostic",
        execution_target="hosted_ci",
        summary="Other diagnostic",
        allowed_paths=["tests/other.py"],
        allowed_actions=["revert_diagnostic_changes"],
        allowed_commands=[],
        prohibited_actions=[],
        tool_fallbacks={},
        baseline_head_sha="baseline-head",
        baseline_tree_sha="baseline-tree",
        originating_escalation_reason="owner_idle_timeout",
        expected_workspace_id=workspace.id,
        expected_lease_token_hash="other-hash",
        max_failed_heads=1,
        last_failed_head_sha="failed-head",
        status="exhausted",
    ))
    await db.commit()
    notified = []

    async def record_notification(_db, item, _revision, _head_sha):
        notified.append(item.id)

    monkeypatch.setattr(
        github_verification_service, "_notify_diagnostic_failure", record_notification
    )
    await github_verification_service._repair_exhausted_diagnostic_notifications(
        db, scope, recovery_only_attempt=selector
    )
    assert notified == []
    await github_verification_service._repair_exhausted_diagnostic_notifications(db, scope)
    assert notified == [unrelated.id]


@pytest.mark.asyncio
async def test_recovery_only_suppresses_dependency_unblock_broadcasts(db, monkeypatch):
    _preset, _slot, scope, target, _unrelated, selector = await _attempt(db)
    monkeypatch.setattr(settings, "github_recovery_only_attempt", (
        f"{selector.scope_id}:{selector.work_item_id}:{selector.pr_number}:"
        f"{selector.dispatch_nonce}:{selector.head_ref}"
    ))
    notifications = []

    async def record_notification(_db, _scope, item, _slots):
        notifications.append(item.id)

    monkeypatch.setattr(
        github_dispatch_service, "notify_blocker_merged", record_notification
    )
    await github_verification_service._notify_blocker_merged(db, scope, target)
    assert notifications == []
    monkeypatch.setattr(settings, "github_recovery_only_attempt", "")
    await github_verification_service._notify_blocker_merged(db, scope, target)
    assert notifications == [target.id]


@pytest.mark.asyncio
async def test_recovery_gate_preflight_requires_operator_and_reports_paused_target(db, monkeypatch):
    preset, _slot, scope, _target, _unrelated, selector = await _attempt(db)
    preset.autonomy_enabled = False
    await db.commit()
    monkeypatch.setattr(settings, "operator_token", "test-operator-token")
    monkeypatch.setattr(github_dispatch_scheduler, "recovery_only_attempt", selector)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            endpoint = "/api/v1/agent-teams/github-recovery-gate"
            assert (await client.get(endpoint)).status_code == 401
            assert (
                await client.get(endpoint, headers={"X-Deck-Operator-Token": "wrong"})
            ).status_code == 401
            response = await client.get(
                endpoint, headers={"X-Deck-Operator-Token": "test-operator-token"}
            )
            monkeypatch.setattr(github_dispatch_scheduler, "recovery_only_attempt", None)
            inactive_response = await client.get(
                endpoint, headers={"X-Deck-Operator-Token": "test-operator-token"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "scope_id": scope.id,
        "work_item_id": selector.work_item_id,
        "pr_number": selector.pr_number,
        "dispatch_nonce": selector.dispatch_nonce,
        "head_ref": selector.head_ref,
        "identity_matches": True,
        "scheduler_running": False,
        "job_scheduled": False,
    }
    assert inactive_response.status_code == 200
    assert inactive_response.json() == {"active": False}
