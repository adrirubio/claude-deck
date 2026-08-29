"""Hosted autonomous GitHub dispatch scheduler tests."""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_dispatch_scheduler import GithubDispatchScheduler
from app.services.github_watcher_service import github_watcher_service
from app.services.github_workspace_service import github_workspace_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _scope(db, *, repo_owner="o", repo_name="r", autonomy=True, enabled=True):
    preset = AgentTeamPreset(name=f"{repo_owner}/{repo_name}", autonomy_enabled=autonomy)
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Owner",
        provider="codex-cli",
        repo_id=repo_name,
        repo_path=f"/tmp/{repo_name}",
        repo_name=repo_name,
    )
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner=repo_owner,
        repo_name=repo_name,
        repo_path=f"/tmp/{repo_name}",
        base_ref="origin/master",
        enabled=enabled,
    )
    db.add_all([slot, scope])
    await db.flush()
    return scope


class _FakeWatcher:
    def __init__(self):
        self.calls = []

    async def poll_scope(self, db, scope, client):
        self.calls.append(scope.id)


class _FakeDispatch:
    def __init__(self):
        self.dispatch_calls = []
        self.monitor_calls = []
        self.continuation_calls = []
        self.recovery_calls = []
        self.remind_calls = []

    async def dispatch_pending(self, db, scope, slots, **kwargs):
        self.dispatch_calls.append((scope.id, [slot.id for slot in slots]))

    async def monitor_dispatched(self, db, scope, slots):
        self.monitor_calls.append(scope.id)

    async def monitor_continuation(self, db, scope, slots):
        self.continuation_calls.append(scope.id)

    async def monitor_recovery(self, db, scope, slots):
        self.recovery_calls.append(scope.id)

    async def remind_held_leases(self, db, scope):
        self.remind_calls.append(scope.id)


class _FakeVerification:
    def __init__(self):
        self.calls = []

    async def process_scope(self, db, scope, client=None):
        self.calls.append(scope.id)


class _RoutingDispatch:
    async def dispatch_pending(self, *args, **kwargs):
        await github_dispatch_service.dispatch_pending(*args, **kwargs)

    async def monitor_dispatched(self, db, scope, slots):
        return None

    async def monitor_continuation(self, db, scope, slots):
        return None

    async def monitor_recovery(self, db, scope, slots):
        return None

    async def remind_held_leases(self, db, scope):
        return await github_dispatch_service.remind_held_leases(db, scope)


class _FakeClient:
    async def get_issues_by_number(self, owner, repo, numbers):
        return {
            number: {
                "labels": [
                    {"name": "claude-deck-ready"},
                    {"name": "area:backend"},
                ]
            }
            for number in numbers
        }


class _RetryFlowClient:
    def __init__(self, issue):
        self.issue = issue

    async def list_issues_with_label(self, owner, repo, label):
        return [self.issue]

    async def get_open_issues_by_number(self, owner, repo, numbers):
        return {number: self.issue for number in numbers if number == self.issue["number"]}

    async def get_issues_by_number(self, owner, repo, numbers):
        return {number: self.issue for number in numbers if number == self.issue["number"]}


class _FakeJob:
    def __init__(self, job_id):
        self.id = job_id


class _FakeScheduler:
    running = False

    def __init__(self):
        self.jobs = {}

    def get_jobs(self):
        return [_FakeJob(job_id) for job_id in self.jobs]

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = kwargs

    def remove_job(self, job_id):
        self.jobs.pop(job_id)

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False


@pytest.mark.asyncio
async def test_run_repo_once_only_processes_enabled_autonomy_scopes(db):
    active = await _scope(db, repo_owner="o", repo_name="r", autonomy=True, enabled=True)
    await _scope(db, repo_owner="o", repo_name="r", autonomy=False, enabled=True)
    await _scope(db, repo_owner="o", repo_name="r", autonomy=True, enabled=False)
    await _scope(db, repo_owner="o", repo_name="other", autonomy=True, enabled=True)
    db.add(
        GithubWorkItem(
            scope_id=active.id,
            issue_number=1,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="pending",
        )
    )
    await db.commit()
    watcher = _FakeWatcher()
    dispatch = _FakeDispatch()
    verification = _FakeVerification()
    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=watcher,
        dispatch=dispatch,
        verification=verification,
    )

    await service.run_repo_once(db, "o", "r", client=_FakeClient())

    assert watcher.calls == [active.id]
    assert [call[0] for call in dispatch.dispatch_calls] == [active.id]
    assert dispatch.monitor_calls == [active.id]
    assert dispatch.continuation_calls == [active.id]
    assert dispatch.recovery_calls == [active.id]
    assert dispatch.remind_calls == [active.id]
    assert verification.calls == [active.id]


@pytest.mark.asyncio
async def test_scheduler_orders_disjoint_monitors_around_verification(db):
    scope = await _scope(db, autonomy=True, enabled=True)
    order = []

    class OrderedWatcher(_FakeWatcher):
        async def poll_scope(self, db, scope, client):
            order.append("watcher")

    class OrderedDispatch(_FakeDispatch):
        async def dispatch_pending(self, db, scope, slots, **kwargs):
            order.append("dispatch")

        async def monitor_dispatched(self, db, scope, slots):
            order.append("initial_monitor")

        async def monitor_continuation(self, db, scope, slots):
            order.append("continuation_monitor")

        async def monitor_recovery(self, db, scope, slots):
            order.append("recovery_monitor")

        async def remind_held_leases(self, db, scope):
            order.append("lease_reminder")

    class OrderedVerification(_FakeVerification):
        async def process_scope(self, db, scope, client=None):
            order.append("verification")

    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=OrderedWatcher(),
        dispatch=OrderedDispatch(),
        verification=OrderedVerification(),
    )

    await service.run_repo_once(db, "o", "r", client=_FakeClient())

    assert scope.id is not None
    assert order == [
        "watcher",
        "dispatch",
        "initial_monitor",
        "continuation_monitor",
        "verification",
        "recovery_monitor",
        "lease_reminder",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop_after",
    [
        "dispatch",
        "initial_monitor",
        "continuation_monitor",
        "verification",
        "recovery_monitor",
    ],
)
async def test_scheduler_stops_after_autonomy_is_disabled_between_stages(
    db,
    stop_after,
):
    scope = await _scope(db, autonomy=True, enabled=True)
    order = []

    async def record(db, current_scope, stage):
        order.append(stage)
        if stage == stop_after:
            preset = await db.get(AgentTeamPreset, current_scope.preset_id)
            preset.autonomy_enabled = False

    class ToggleWatcher(_FakeWatcher):
        async def poll_scope(self, db, scope, client):
            order.append("watcher")

    class ToggleDispatch(_FakeDispatch):
        async def dispatch_pending(self, db, scope, slots, **kwargs):
            await record(db, scope, "dispatch")

        async def monitor_dispatched(self, db, scope, slots):
            await record(db, scope, "initial_monitor")

        async def monitor_continuation(self, db, scope, slots):
            await record(db, scope, "continuation_monitor")

        async def monitor_recovery(self, db, scope, slots):
            await record(db, scope, "recovery_monitor")

        async def remind_held_leases(self, db, scope):
            order.append("lease_reminder")

    class ToggleVerification(_FakeVerification):
        async def process_scope(self, db, scope, client=None):
            await record(db, scope, "verification")

    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=ToggleWatcher(),
        dispatch=ToggleDispatch(),
        verification=ToggleVerification(),
    )

    await service.run_repo_once(db, "o", "r", client=_FakeClient())

    stages = [
        "watcher",
        "dispatch",
        "initial_monitor",
        "continuation_monitor",
        "verification",
        "recovery_monitor",
        "lease_reminder",
    ]
    assert order == stages[: stages.index(stop_after) + 1]


@pytest.mark.asyncio
async def test_scheduler_reloads_then_recovers_new_verification_escalation(db):
    scope = await _scope(db, autonomy=True, enabled=True)
    now = datetime.utcnow()
    items = [
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=101,
            issue_title="Initial dispatch",
            issue_url="u",
            github_updated_at=now,
            dispatch_status="pending",
        ),
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=102,
            issue_title="Active implementation continuation",
            issue_url="u",
            github_updated_at=now,
            dispatch_status="dispatched",
            pr_number=102,
            active_scope_revision=1,
            attempt_phase="implementation",
        ),
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=103,
            issue_title="Diagnostic verification",
            issue_url="u",
            github_updated_at=now,
            dispatch_status="verifying",
            pr_number=103,
            active_scope_revision=2,
            attempt_phase="diagnostic",
        ),
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=104,
            issue_title="Verification becomes recoverable",
            issue_url="u",
            github_updated_at=now,
            dispatch_status="verifying",
            pr_number=104,
            attempt_phase="implementation",
        ),
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=105,
            issue_title="Already recoverable",
            issue_url="u",
            github_updated_at=now,
            dispatch_status="escalated",
            escalation_reason="retry_count_exhausted",
            pr_number=105,
        ),
    ]
    db.add_all(items)
    await db.commit()
    touches = []

    class StageDispatch(_FakeDispatch):
        async def dispatch_pending(self, db, scope, slots, **kwargs):
            pending = (
                await db.execute(
                    select(GithubWorkItem).where(
                        GithubWorkItem.scope_id == scope.id,
                        GithubWorkItem.dispatch_status == "pending",
                    )
                )
            ).scalars().all()
            touches.append(("dispatch", [item.issue_number for item in pending]))
            for item in pending:
                item.dispatch_status = "dispatched"

        async def monitor_dispatched(self, db, scope, slots):
            initial = (
                await db.execute(
                    select(GithubWorkItem).where(
                        GithubWorkItem.scope_id == scope.id,
                        GithubWorkItem.dispatch_status == "dispatched",
                        GithubWorkItem.pr_number.is_(None),
                        GithubWorkItem.active_scope_revision == 0,
                    )
                )
            ).scalars().all()
            touches.append(("initial_monitor", [item.issue_number for item in initial]))

        async def monitor_continuation(self, db, scope, slots):
            active = (
                await db.execute(
                    select(GithubWorkItem).where(
                        GithubWorkItem.scope_id == scope.id,
                        GithubWorkItem.dispatch_status == "dispatched",
                        GithubWorkItem.pr_number.is_not(None),
                        GithubWorkItem.active_scope_revision > 0,
                    )
                )
            ).scalars().all()
            touches.append(
                ("continuation_monitor", [item.issue_number for item in active])
            )

        async def monitor_recovery(self, db, scope, slots):
            recoverable = (
                await db.execute(
                    select(GithubWorkItem).where(
                        GithubWorkItem.scope_id == scope.id,
                        GithubWorkItem.dispatch_status == "escalated",
                    )
                )
            ).scalars().all()
            touches.append(
                ("recovery_monitor", [item.issue_number for item in recoverable])
            )
            for item in recoverable:
                item.continuation_nudged_at = datetime.utcnow()

        async def remind_held_leases(self, db, scope):
            touches.append(("lease_reminder", []))

    class StageVerification(_FakeVerification):
        async def process_scope(self, db, scope, client=None):
            verifying = (
                await db.execute(
                    select(GithubWorkItem).where(
                        GithubWorkItem.scope_id == scope.id,
                        GithubWorkItem.dispatch_status == "verifying",
                    )
                )
            ).scalars().all()
            touches.append(("verification", [item.issue_number for item in verifying]))
            for item in verifying:
                if item.issue_number == 104:
                    item.dispatch_status = "escalated"
                    item.escalation_reason = "retry_count_exhausted"

    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=_FakeWatcher(),
        dispatch=StageDispatch(),
        verification=StageVerification(),
    )

    await service.run_repo_once(db, "o", "r", client=_FakeClient())

    await db.refresh(items[3])
    await db.refresh(items[4])

    assert touches == [
        ("dispatch", [101]),
        ("initial_monitor", [101]),
        ("continuation_monitor", [102]),
        ("verification", [103, 104]),
        ("recovery_monitor", [104, 105]),
        ("lease_reminder", []),
    ]
    assert items[3].continuation_nudged_at is not None
    assert items[4].continuation_nudged_at is not None


@pytest.mark.asyncio
async def test_scheduler_escalates_pending_item_after_dispatch_label_is_removed(db):
    scope = await _scope(db, autonomy=True, enabled=True)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=2,
        issue_title="stale pending item",
        issue_url="https://github.com/o/r/issues/2",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    client = _RetryFlowClient(
        {
            "number": 2,
            "state": "open",
            "labels": [{"name": "area:backend"}],
        }
    )
    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=_FakeWatcher(),
        dispatch=_RoutingDispatch(),
        verification=_FakeVerification(),
    )

    await service.run_repo_once(db, "o", "r", client=client)

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"


@pytest.mark.asyncio
async def test_scheduler_checks_held_leases_with_no_enabled_slots(db):
    scope = await _scope(db, autonomy=True, enabled=True)
    slot = (
        await db.execute(
            select(AgentTeamSlot).where(AgentTeamSlot.preset_id == scope.preset_id)
        )
    ).scalar_one()
    slot.enabled = False
    await db.commit()
    dispatch = _FakeDispatch()
    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=_FakeWatcher(),
        dispatch=dispatch,
        verification=_FakeVerification(),
    )

    await service.run_repo_once(db, "o", "r", client=_FakeClient())

    assert dispatch.monitor_calls == [scope.id]
    assert dispatch.continuation_calls == [scope.id]
    assert dispatch.recovery_calls == [scope.id]
    assert dispatch.remind_calls == [scope.id]


@pytest.mark.asyncio
async def test_torn_attempt_does_not_skip_scope_monitoring(db, monkeypatch):
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 999_999)
    scope = await _scope(db, autonomy=True, enabled=True)
    slot = (
        await db.execute(
            select(AgentTeamSlot).where(AgentTeamSlot.preset_id == scope.preset_id)
        )
    ).scalar_one()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=88,
        issue_title="torn attempt",
        issue_url="https://github.com/o/r/issues/88",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
        owner_slot_id=slot.id,
        dispatch_nonce="0123456789abcdef",
    )
    db.add(item)
    await db.commit()

    class _TornAttemptDispatch(_FakeDispatch):
        async def dispatch_pending(self, db, scope, slots, **kwargs):
            self.dispatch_calls.append((scope.id, [slot.id for slot in slots]))
            await github_dispatch_service.dispatch_pending(db, scope, slots, **kwargs)

    dispatch = _TornAttemptDispatch()
    verification = _FakeVerification()
    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=_FakeWatcher(),
        dispatch=dispatch,
        verification=verification,
    )

    await service.run_repo_once(db, "o", "r", client=_FakeClient())

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "plan_blocked"
    assert dispatch.monitor_calls == [scope.id]
    assert dispatch.continuation_calls == [scope.id]
    assert dispatch.recovery_calls == [scope.id]
    assert dispatch.remind_calls == [scope.id]
    assert verification.calls == [scope.id]


@pytest.mark.asyncio
async def test_scheduler_promotes_retry_before_fetching_labels_and_routes_by_label(
    db, monkeypatch
):
    async def reset_succeeds(*_args, **_kwargs):
        return None

    async def git_succeeds(_args):
        return 0, ""

    monkeypatch.setattr(github_workspace_service, "reset_workspace", reset_succeeds)
    monkeypatch.setattr(github_workspace_service, "_runner", git_succeeds)
    monkeypatch.setattr(
        github_dispatch_service, "_available_memory_mb", lambda: 999_999
    )
    scope = await _scope(db, autonomy=True, enabled=True)
    slot = (
        await db.execute(select(AgentTeamSlot).where(AgentTeamSlot.preset_id == scope.preset_id))
    ).scalar_one()
    slot.area_labels = ["area:backend"]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=77,
        issue_title="retry routing",
        issue_url="https://github.com/o/r/issues/77",
        github_updated_at=datetime(2026, 7, 4),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        retry_requested_at=datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    db.add(GithubWorkspace(scope_id=scope.id, path="/tmp/r-retry-workspace"))
    await db.commit()
    issue = {
        "number": 77,
        "title": "retry routing",
        "html_url": "https://github.com/o/r/issues/77",
        "updated_at": "2026-07-04T00:00:00Z",
        "state": "open",
        "labels": [{"name": "claude-deck-ready"}, {"name": "area:backend"}],
    }
    client = _RetryFlowClient(issue)

    class _Result:
        launch_id = 77
        items = []

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    service = GithubDispatchScheduler(
        scheduler=_FakeScheduler(),
        watcher=github_watcher_service,
        dispatch=_RoutingDispatch(),
        verification=_FakeVerification(),
    )

    await service.run_repo_once(db, "o", "r", client=client, launcher=fake_launcher)

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.routing_method == "label"
    assert item.owner_slot_id == slot.id


@pytest.mark.asyncio
async def test_sync_jobs_uses_one_job_per_distinct_enabled_repo(db):
    await _scope(db, repo_owner="o", repo_name="r", autonomy=True, enabled=True)
    await _scope(db, repo_owner="o", repo_name="r", autonomy=True, enabled=True)
    await _scope(db, repo_owner="o", repo_name="disabled", autonomy=True, enabled=False)
    await _scope(db, repo_owner="o", repo_name="manual", autonomy=False, enabled=True)
    scheduler = _FakeScheduler()
    service = GithubDispatchScheduler(scheduler=scheduler, interval_seconds=30)

    await service.sync_jobs(db)

    assert list(scheduler.jobs) == ["github-dispatch:o/r"]
    assert scheduler.jobs["github-dispatch:o/r"]["seconds"] == 30
