"""Hosted autonomous GitHub dispatch scheduler tests."""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, TeamGithubScope
from app.services.github_dispatch_scheduler import GithubDispatchScheduler


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

    async def dispatch_pending(self, db, scope, slots, **kwargs):
        self.dispatch_calls.append((scope.id, [slot.id for slot in slots]))

    async def monitor_dispatched(self, db, scope, slots):
        self.monitor_calls.append(scope.id)


class _FakeVerification:
    def __init__(self):
        self.calls = []

    async def process_scope(self, db, scope, client=None):
        self.calls.append(scope.id)


class _FakeClient:
    async def get_issues_by_number(self, owner, repo, numbers):
        return {number: {"labels": [{"name": "area:backend"}]} for number in numbers}


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
    assert verification.calls == [active.id]


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
