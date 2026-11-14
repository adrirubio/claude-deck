"""Dispatch workspace provisioning, slot identity readiness and the no-workspace note (#564)."""
import asyncio
import os
import subprocess
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services import github_workspace_readiness as readiness
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_workspace_service import GithubWorkspaceService, github_workspace_service
from app.models.schemas import TeamGithubScopeUpdate
from app.utils.repo_utils import derive_repo_identity
from tests.agent_teams.test_github_dispatch_service import _team

OPERATOR_TOKEN = "test-operator-token-for-provisioning"
HEADERS = {"X-Synth-City-Operator-Token": OPERATOR_TOKEN}
NO_WORKSPACE = "No dispatchable workspace is registered for this scope"


@pytest.fixture(autouse=True)
def operator_token(monkeypatch):
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def _git(*args, cwd=None):
    return subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=test@example.com", *args],
        check=True, capture_output=True, text=True, cwd=cwd,
    ).stdout.strip()


def _make_repo(path: Path) -> Path:
    path.mkdir()
    _git("init", "-b", "master", str(path))
    _git("-C", str(path), "commit", "--allow-empty", "-m", "base")
    return path


@pytest.fixture
def repo(tmp_path):
    return _make_repo(tmp_path / "repo")


async def _scope(db, repo: Path, concurrency=3, base_ref="master"):
    preset = AgentTeamPreset(name=f"Prov {repo.name}", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id, repo_owner="o", repo_name=repo.name, repo_path=str(repo),
        base_ref=base_ref, max_concurrent_dispatched=concurrency,
    )
    db.add(scope)
    await db.commit()
    return preset, scope


async def _rows(db, scope_id):
    return (await db.execute(
        select(GithubWorkspace).where(GithubWorkspace.scope_id == scope_id).order_by(GithubWorkspace.id)
    )).scalars().all()


class RecordingRunner:
    """Real git, with a record of every command."""

    def __init__(self):
        self.calls = []
        self._real = GithubWorkspaceService()._run_git

    async def __call__(self, args):
        self.calls.append(list(args))
        return await self._real(args)

    def worktree_adds(self):
        return [c for c in self.calls if "worktree" in c and "add" in c]


# ---- provisioning ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provisioning_creates_one_sibling_worktree_per_concurrent_item(db, repo):
    _, scope = await _scope(db, repo, concurrency=3)
    report = await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    expected = [str(repo.parent / f"dispatch-{n}") for n in (1, 2, 3)]
    assert report.created == expected and report.failures == [] and report.existing == 0
    rows = await _rows(db, scope.id)
    assert [r.path for r in rows] == expected
    assert all(r.kind == "worktree" and r.dispatchable and r.enabled for r in rows)
    common = os.path.realpath(repo / ".git")
    for path in expected:
        assert os.path.realpath(_git("-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir")) == common
        assert os.path.realpath(_git("-C", path, "rev-parse", "--path-format=absolute", "--git-dir")) != common


@pytest.mark.asyncio
async def test_concurrency_rise_adds_only_the_missing_workspaces(db, repo):
    _, scope = await _scope(db, repo, concurrency=2)
    service = GithubWorkspaceService()
    await service.ensure_dispatch_workspaces(db, scope)
    first = await _rows(db, scope.id)
    marker = Path(first[0].path) / "keep.txt"
    marker.write_text("mine")
    snapshot = [(r.id, r.path, r.leased_item_id, r.updated_at) for r in first]
    scope.max_concurrent_dispatched = 4
    await db.commit()
    report = await service.ensure_dispatch_workspaces(db, scope)
    assert report.created == [str(repo.parent / "dispatch-3"), str(repo.parent / "dispatch-4")]
    after = await _rows(db, scope.id)
    assert [(r.id, r.path, r.leased_item_id, r.updated_at) for r in after[:2]] == snapshot
    assert marker.read_text() == "mine" and len(after) == 4


@pytest.mark.asyncio
async def test_second_call_is_idempotent_and_runs_no_git_add(db, repo):
    _, scope = await _scope(db, repo, concurrency=2)
    runner = RecordingRunner()
    service = GithubWorkspaceService(runner=runner)
    await service.ensure_dispatch_workspaces(db, scope)
    assert len(runner.worktree_adds()) == 2
    runner.calls.clear()
    report = await service.ensure_dispatch_workspaces(db, scope)
    assert report.created == [] and report.failures == [] and report.existing == 2
    assert runner.worktree_adds() == [] and len(await _rows(db, scope.id)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["directory", "symlink"])
async def test_an_unrelated_existing_path_is_never_touched_or_adopted(db, repo, tmp_path, kind):
    _, scope = await _scope(db, repo, concurrency=2)
    taken = repo.parent / "dispatch-1"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("data")
    if kind == "directory":
        taken.mkdir()
        (taken / "precious").write_text("data")
        guarded = taken
    else:
        taken.symlink_to(outside)
        guarded = outside
    report = await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    assert str(taken) not in report.created
    assert report.created == [str(repo.parent / "dispatch-2"), str(repo.parent / "dispatch-3")]
    assert (guarded / "precious").read_text() == "data"
    assert sorted(p.name for p in guarded.iterdir()) == ["precious"]
    assert str(taken) not in [r.path for r in await _rows(db, scope.id)]


@pytest.mark.asyncio
async def test_a_registered_path_whose_directory_is_gone_is_not_recreated(db, repo):
    _, scope = await _scope(db, repo, concurrency=2)
    stale = repo.parent / "dispatch-1"
    db.add(GithubWorkspace(scope_id=scope.id, path=str(stale), kind="worktree", dispatchable=False, enabled=True))
    await db.commit()
    runner = RecordingRunner()
    report = await GithubWorkspaceService(runner=runner).ensure_dispatch_workspaces(db, scope)
    assert report.created == [str(repo.parent / "dispatch-2"), str(repo.parent / "dispatch-3")]
    assert not stale.exists() and all(str(stale) not in c for c in runner.worktree_adds())


@pytest.mark.asyncio
async def test_a_leased_workspace_counts_toward_the_target(db, repo):
    _, scope = await _scope(db, repo, concurrency=2)
    service = GithubWorkspaceService()
    await service.ensure_dispatch_workspaces(db, scope)
    holder = GithubWorkItem(scope_id=scope.id, issue_number=980, issue_title="h", issue_url="u",
                            github_updated_at=datetime.utcnow(), dispatch_status="dispatched")
    db.add(holder)
    await db.flush()
    first = (await _rows(db, scope.id))[0]
    first.leased_item_id, first.leased_at, first.lease_token = holder.id, datetime.utcnow(), "held"
    await db.commit()
    report = await service.ensure_dispatch_workspaces(db, scope)
    assert report.created == [] and report.existing == 2
    assert (await _rows(db, scope.id))[0].leased_item_id == holder.id


@pytest.mark.asyncio
async def test_the_search_for_a_free_name_is_bounded(db, repo):
    _, scope = await _scope(db, repo, concurrency=1)
    for n in range(1, 80):
        (repo.parent / f"dispatch-{n}").mkdir()
    runner = RecordingRunner()
    report = await GithubWorkspaceService(runner=runner).ensure_dispatch_workspaces(db, scope)
    assert report.created == [] and [f.code for f in report.failures] == ["no_free_workspace_name"]
    assert runner.worktree_adds() == [] and await _rows(db, scope.id) == []


@pytest.mark.asyncio
async def test_a_missing_scope_checkout_is_reported_without_running_git(db, tmp_path):
    _, scope = await _scope(db, tmp_path / "absent")
    runner = RecordingRunner()
    report = await GithubWorkspaceService(runner=runner).ensure_dispatch_workspaces(db, scope)
    assert [f.code for f in report.failures] == ["scope_checkout_missing"] and runner.calls == []


@pytest.mark.asyncio
async def test_a_git_failure_is_reported_with_a_sanitized_reason_and_stops(db, repo):
    _, scope = await _scope(db, repo, concurrency=3)
    calls = []

    async def failing(args):
        calls.append(args)
        return 128, "fatal: boom --lease supersecretvalue " + "x" * 600

    report = await GithubWorkspaceService(runner=failing).ensure_dispatch_workspaces(db, scope)
    assert report.created == [] and len(report.failures) == 1 and len(calls) == 1
    reason = report.failures[0].reason
    assert "supersecretvalue" not in reason and len(reason) <= 300 and "fatal: boom" in reason
    assert await _rows(db, scope.id) == []


@pytest.mark.asyncio
async def test_concurrent_requests_provision_exactly_the_target(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        _, scope = await _scope(setup, repo, concurrency=3)
        scope_id = scope.id
    service = GithubWorkspaceService()

    async def one():
        async with maker() as session:
            return await service.ensure_dispatch_workspaces(session, await session.get(TeamGithubScope, scope_id))

    reports = await asyncio.gather(one(), one(), one())
    assert all(r.failures == [] for r in reports)
    assert sorted(p for r in reports for p in r.created) == [str(repo.parent / f"dispatch-{n}") for n in (1, 2, 3)]
    async with maker() as check:
        assert len(await _rows(check, scope_id)) == 3
    assert sorted(p.name for p in repo.parent.iterdir() if p.name.startswith("dispatch-")) == [
        "dispatch-1", "dispatch-2", "dispatch-3"]
    await engine.dispose()


# ---- review findings: workers, reconfiguration, races, capacity, containment ---------------------


async def _file_db(tmp_path, name="w.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_independent_workers_do_not_exceed_the_target(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    engine, maker = await _file_db(tmp_path)
    async with maker() as setup:
        _, scope = await _scope(setup, repo, concurrency=1)
        scope_id = scope.id
    created, second_done = asyncio.Event(), asyncio.Event()
    real = GithubWorkspaceService()._run_git

    async def slow_first(args):
        result = await real(args)
        if "worktree" in args and "add" in args:
            created.set()
            await asyncio.wait_for(second_done.wait(), 10)
        return result

    async def first():
        async with maker() as session:
            return await GithubWorkspaceService(runner=slow_first).ensure_dispatch_workspaces(
                session, await session.get(TeamGithubScope, scope_id))

    async def second():
        await asyncio.wait_for(created.wait(), 10)
        try:
            async with maker() as session:
                return await GithubWorkspaceService().ensure_dispatch_workspaces(
                    session, await session.get(TeamGithubScope, scope_id))
        finally:
            second_done.set()

    first_report, second_report = await asyncio.gather(first(), second())
    async with maker() as session:
        rows = await _rows(session, scope_id)
    await engine.dispose()
    assert [r.path for r in rows] == [str(repo.parent / "dispatch-1")] and rows[0].dispatchable and rows[0].enabled
    assert second_report.created == [] and first_report.created == [str(repo.parent / "dispatch-1")]
    assert sorted(p.name for p in repo.parent.iterdir() if p.name.startswith("dispatch-")) == ["dispatch-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["repo_path", "base_ref"])
async def test_a_scope_reconfigured_mid_flight_never_binds_the_old_checkout(tmp_path, monkeypatch, change):
    from app.api.v1 import agent_teams as api

    repo = _make_repo(tmp_path / "repo")
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = _make_repo(other_root / "repo")
    engine, maker = await _file_db(tmp_path)
    async with maker() as setup:
        _, scope = await _scope(setup, repo, concurrency=1)
        scope.enabled = False
        await setup.commit()
        scope_id = scope.id
    created, changed = asyncio.Event(), asyncio.Event()
    real = GithubWorkspaceService()._run_git

    async def delayed(args):
        result = await real(args)
        if "worktree" in args and "add" in args and not created.is_set():
            created.set()
            await asyncio.wait_for(changed.wait(), 10)
        return result

    async def no_sync(*_a):
        return None

    monkeypatch.setattr(api, "_sync_github_jobs", no_sync)

    async def provision():
        async with maker() as session:
            return await GithubWorkspaceService(runner=delayed).ensure_dispatch_workspaces(
                session, await session.get(TeamGithubScope, scope_id))

    async def reconfigure():
        await asyncio.wait_for(created.wait(), 10)
        try:
            async with maker() as session:
                if change == "repo_path":
                    response = await api.update_github_scope(
                        scope_id, TeamGithubScopeUpdate(repo_path=str(other)), _operator=None, db=session)
                    assert response.repo_path == str(other)
                else:
                    await session.execute(update(TeamGithubScope).where(TeamGithubScope.id == scope_id)
                                          .values(base_ref="refs/heads/elsewhere"))
                    await session.commit()
        finally:
            changed.set()

    report, _ = await asyncio.gather(provision(), reconfigure())
    async with maker() as session:
        rows = await _rows(session, scope_id)
    await engine.dispose()
    assert rows == [] and report.created == []
    assert [f.code for f in report.failures] == ["scope_changed_during_provisioning"]
    assert not (repo.parent / "dispatch-1").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["clean_worktree", "empty_directory", "symlink", "populated_directory"])
async def test_a_path_that_appears_after_the_guard_is_never_adopted_or_written(db, repo, tmp_path, variant):
    _, scope = await _scope(db, repo, concurrency=1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("data")
    service = GithubWorkspaceService()

    def appear(path):
        if variant == "clean_worktree":
            _git("-C", str(repo), "worktree", "add", "--detach", path, "master")
        elif variant == "empty_directory":
            os.mkdir(path)
        elif variant == "symlink":
            os.symlink(outside, path)
        else:
            os.mkdir(path)
            Path(path, "theirs").write_text("keep")

    victim = repo.parent / "dispatch-1"
    first_call = {"done": False}
    original = service._create_workspace

    async def once(db_, reservation, *a, **k):
        if not first_call["done"]:
            first_call["done"] = True
            appear(reservation.path)
        return await original(db_, reservation, *a, **k)

    service._create_workspace = once
    report = await service.ensure_dispatch_workspaces(db, scope)
    assert str(victim) not in [r.path for r in await _rows(db, scope.id)]
    assert report.created == [str(repo.parent / "dispatch-2")] and report.failures == []
    assert victim.exists() or victim.is_symlink()
    if variant == "empty_directory":
        assert victim.is_dir() and list(victim.iterdir()) == []
    if variant == "populated_directory":
        assert (victim / "theirs").read_text() == "keep"
    if variant == "symlink":
        assert victim.is_symlink() and (outside / "precious").read_text() == "data"
        assert sorted(p.name for p in outside.iterdir()) == ["precious"]
    if variant == "clean_worktree":
        assert (victim / ".git").exists()


@pytest.mark.asyncio
async def test_a_target_lowered_mid_flight_does_not_enable_the_excess_workspace(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    engine, maker = await _file_db(tmp_path)
    async with maker() as setup:
        _, scope = await _scope(setup, repo, concurrency=2)
        scope_id = scope.id
    created, changed = asyncio.Event(), asyncio.Event()
    real = GithubWorkspaceService()._run_git

    async def delayed(args):
        result = await real(args)
        if "worktree" in args and "add" in args and not created.is_set():
            created.set()
            await asyncio.wait_for(changed.wait(), 10)
        return result

    async def provision():
        async with maker() as session:
            return await GithubWorkspaceService(runner=delayed).ensure_dispatch_workspaces(
                session, await session.get(TeamGithubScope, scope_id))

    async def lower_target():
        await asyncio.wait_for(created.wait(), 10)
        try:
            async with maker() as session:
                session.add(GithubWorkspace(scope_id=scope_id, path=str(tmp_path / "manual"), kind="worktree",
                                            dispatchable=True, enabled=True))
                await session.execute(update(TeamGithubScope).where(TeamGithubScope.id == scope_id)
                                      .values(max_concurrent_dispatched=1))
                await session.commit()
        finally:
            changed.set()

    report, _ = await asyncio.gather(provision(), lower_target())
    async with maker() as session:
        rows = await _rows(session, scope_id)
    await engine.dispose()
    assert [f.code for f in report.failures] == ["target_reduced_during_provisioning"] and report.created == []
    assert [r.path for r in rows] == [str(tmp_path / "manual")]
    assert not (repo.parent / "dispatch-1").exists()


@pytest.mark.asyncio
async def test_an_abandoned_reservation_stops_counting_and_keeps_its_row_and_files(db, repo):
    _, scope = await _scope(db, repo, concurrency=1)
    stale = repo.parent / "dispatch-1"
    stale.mkdir()
    (stale / "partial").write_text("x")
    db.add(GithubWorkspace(scope_id=scope.id, path=str(stale), kind="worktree", dispatchable=False, enabled=False,
                           provision_error="provisioning", created_at=datetime(2020, 1, 1)))
    await db.commit()
    report = await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    assert report.created == [str(repo.parent / "dispatch-2")]
    old = next(r for r in await _rows(db, scope.id) if r.path == str(stale))
    assert old.provision_error.startswith("abandoned") and not old.enabled and (stale / "partial").exists()


@pytest.mark.asyncio
async def test_a_checkout_swapped_for_a_link_after_creation_is_reported_and_left_alone(db, repo, tmp_path):
    _, scope = await _scope(db, repo, concurrency=1)
    real = GithubWorkspaceService()._run_git
    victim = repo.parent / "dispatch-1"
    moved = tmp_path / "moved-away"

    async def swapping(args):
        result = await real(args)
        if "worktree" in args and "add" in args and not moved.exists():
            os.rename(victim, moved)
            os.symlink(moved, victim)
        return result

    report = await GithubWorkspaceService(runner=swapping).ensure_dispatch_workspaces(db, scope)
    assert report.created == [] and [f.code for f in report.failures] == ["workspace_path_changed"]
    assert moved.is_dir() and (moved / ".git").exists() and victim.is_symlink()
    rows = await _rows(db, scope.id)
    assert len(rows) == 1 and not rows[0].enabled and not rows[0].dispatchable and "changed" in rows[0].provision_error


@pytest.mark.asyncio
async def test_cleanup_removes_only_a_checkout_this_call_created_and_can_still_identify(repo, tmp_path):
    from app.services.github_workspace_service import _Reservation

    service = GithubWorkspaceService()
    ours = repo.parent / "dispatch-1"
    claim = service._claim_directory(str(ours))
    _git("-C", str(repo), "worktree", "add", "--detach", "--force", str(ours), "master")
    res = _Reservation(1, 1, str(ours), str(repo), (str(repo), "master", "o", "repo"))
    assert await service._discard_created(res, claim) is True and not ours.exists()
    # The same path swapped for a link to somebody else's checkout is left alone.
    theirs = _make_repo(tmp_path / "theirs")
    claim = service._claim_directory(str(ours))
    os.rmdir(ours)
    os.symlink(theirs, ours)
    assert await service._discard_created(res, claim) is False
    assert ours.is_symlink() and (theirs / ".git").exists()
    # The same path re-created as someone else's real worktree of the same repository is left alone too.
    ours.unlink()
    _git("-C", str(repo), "worktree", "prune")
    claim = service._claim_directory(str(ours))
    os.rmdir(ours)
    _git("-C", str(repo), "worktree", "add", "--detach", str(ours), "master")
    assert await service._discard_created(res, claim) is False
    assert (ours / ".git").exists()


@pytest.mark.asyncio
async def test_a_scope_checkout_outside_the_home_directory_is_refused_before_any_filesystem_or_git_call(db, repo):
    _, scope = await _scope(db, repo, concurrency=1)
    scope.repo_path = "/usr"
    await db.commit()
    runner = RecordingRunner()
    report = await GithubWorkspaceService(runner=runner).ensure_dispatch_workspaces(db, scope)
    assert [f.code for f in report.failures] == ["scope_checkout_outside_home"]
    assert runner.calls == [] and await _rows(db, scope.id) == []


@pytest.mark.asyncio
async def test_a_missing_enabled_workspace_is_unavailable_capacity_not_ready(db, repo):
    _, scope = await _scope(db, repo, concurrency=1)
    gone = repo.parent / "dispatch-1"
    db.add(GithubWorkspace(scope_id=scope.id, path=str(gone), kind="worktree", dispatchable=True, enabled=True))
    await db.commit()
    before = [(r.id, r.path, r.enabled, r.dispatchable, r.leased_item_id) for r in await _rows(db, scope.id)]
    report = await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    assert report.created == [] and [f.code for f in report.failures] == ["workspace_unavailable"]
    assert report.failures[0].path == str(gone) and not gone.exists()
    assert [(r.id, r.path, r.enabled, r.dispatchable, r.leased_item_id) for r in await _rows(db, scope.id)] == before
    result = await readiness.build_readiness(db, scope)
    assert result["shortfall"] == 1 and result["dispatchable_workspaces"] == 0
    assert result["workspaces"][0]["status"] == "unavailable" and result["workspaces"][0]["code"] == "path_missing"


@pytest.mark.asyncio
async def test_a_workspace_of_another_repository_is_unavailable_capacity(db, repo, tmp_path):
    _, scope = await _scope(db, repo, concurrency=1)
    stranger = _make_repo(tmp_path / "stranger")
    _git("-C", str(stranger), "worktree", "add", "--detach", str(tmp_path / "dispatch-1"), "master")
    db.add(GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "dispatch-1"), kind="worktree",
                           dispatchable=True, enabled=True))
    await db.commit()
    result = await readiness.build_readiness(db, scope)
    assert result["shortfall"] == 1 and result["workspaces"][0]["code"] == "different_repository"
    report = await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    assert [f.code for f in report.failures] == ["workspace_unavailable"] and report.created == []


@pytest.mark.asyncio
async def test_an_in_flight_reservation_is_reported_as_provisioning(db, repo):
    _, scope = await _scope(db, repo, concurrency=1)
    db.add(GithubWorkspace(scope_id=scope.id, path=str(repo.parent / "dispatch-1"), kind="worktree",
                           dispatchable=False, enabled=False, provision_error="provisioning"))
    await db.commit()
    result = await readiness.build_readiness(db, scope)
    assert result["workspaces"][0]["status"] == "provisioning" and result["shortfall"] == 1
    note = await GithubWorkspaceService().no_workspace_note(db, scope)
    assert "still being provisioned" in note
    report = await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    assert report.created == [] and report.existing == 0 and len(await _rows(db, scope.id)) == 1


@pytest.mark.asyncio
async def test_a_literal_star_directory_is_never_emitted_as_a_safe_directory_entry(db, client, repo, tmp_path):
    preset, scope = await _scope(db, repo, concurrency=1)
    star = _make_repo(tmp_path / "*")
    mid = _make_repo(tmp_path / "a*b")
    await _slot(db, preset.id, star, "ffffffffffffffff", name="Star")
    await _slot(db, preset.id, mid, "gggggggggggggggg", name="Mid")
    body = (await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness", headers=HEADERS)).json()
    commands = [e["command"] for e in body["safe_directory"]["controller"] + body["safe_directory"]["native"]]
    assert all("*" not in c for c in commands)
    assert sorted(u["display_name"] for u in body["unsafe_paths"]) == ["Mid", "Star"]


# ---- scope create and update ----------------------------------------------------------------


async def _preset(db):
    preset = AgentTeamPreset(name="Prov API", description="", created_by="test")
    db.add(preset)
    await db.commit()
    return preset.id


def _body(repo, **extra):
    return {"repo_owner": "o", "repo_name": repo.name, "repo_path": str(repo), "base_ref": "master",
            "enabled": False, **extra}


@pytest.mark.asyncio
async def test_scope_create_provisions_and_reports_the_workspaces(db, client, repo):
    preset_id = await _preset(db)
    response = await client.post(f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
                                 json=_body(repo, max_concurrent_dispatched=2), headers=HEADERS)
    assert response.status_code == 200
    report = response.json()["workspace_provisioning"]
    assert report["target"] == 2 and report["failures"] == []
    assert report["created"] == [str(repo.parent / "dispatch-1"), str(repo.parent / "dispatch-2")]
    listed = await client.get(f"/api/v1/agent-teams/github-scopes/{response.json()['id']}/workspaces", headers=HEADERS)
    assert [w["path"] for w in listed.json()["workspaces"]] == report["created"]
    assert all(w["dispatchable"] for w in listed.json()["workspaces"])


@pytest.mark.asyncio
async def test_scope_is_kept_when_provisioning_fails(db, client, repo):
    preset_id = await _preset(db)
    response = await client.post(f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
                                 json=_body(repo, base_ref="refs/heads/missing"), headers=HEADERS)
    assert response.status_code == 200
    failures = response.json()["workspace_provisioning"]["failures"]
    assert len(failures) == 1 and failures[0]["reason"]
    saved = await db.get(TeamGithubScope, response.json()["id"])
    assert saved is not None and await _rows(db, saved.id) == []


@pytest.mark.asyncio
async def test_an_unexpected_provisioning_error_never_fails_the_scope_request(db, client, repo, monkeypatch):
    async def explode(*_a, **_k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(github_workspace_service, "ensure_dispatch_workspaces", explode)
    preset_id = await _preset(db)
    response = await client.post(f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
                                 json=_body(repo), headers=HEADERS)
    assert response.status_code == 200
    assert [f["code"] for f in response.json()["workspace_provisioning"]["failures"]] == ["provisioning_error"]
    assert await db.get(TeamGithubScope, response.json()["id"]) is not None


@pytest.mark.asyncio
async def test_scope_update_provisions_only_when_concurrency_rises(db, client, repo):
    preset_id = await _preset(db)
    created = (await client.post(f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
                                 json=_body(repo, max_concurrent_dispatched=1), headers=HEADERS)).json()
    url = f"/api/v1/agent-teams/github-scopes/{created['id']}"
    same = await client.patch(url, json={"max_concurrent_dispatched": 1, "dispatch_label": "other-label"}, headers=HEADERS)
    assert same.status_code == 200 and same.json()["workspace_provisioning"] is None
    lower_label = await client.patch(url, json={"dispatch_label": "third-label"}, headers=HEADERS)
    assert lower_label.json()["workspace_provisioning"] is None and len(await _rows(db, created["id"])) == 1
    rise = await client.patch(url, json={"max_concurrent_dispatched": 3}, headers=HEADERS)
    assert rise.status_code == 200
    assert rise.json()["workspace_provisioning"]["created"] == [
        str(repo.parent / "dispatch-2"), str(repo.parent / "dispatch-3")]
    assert len(await _rows(db, created["id"])) == 3


# ---- readiness ------------------------------------------------------------------------------


async def _slot(db, preset_id, repo_path, repo_id, name="Builder"):
    slot = AgentTeamSlot(
        preset_id=preset_id, position=0, display_name=name, provider="codex-cli", repo_id=repo_id,
        repo_path=str(repo_path), repo_name="repo", launch_mode="plain", launch_options={}, enabled=True,
    )
    db.add(slot)
    await db.commit()
    return slot


def test_repo_identity_formula_matches_the_slot_identity_helper(repo):
    import asyncio as _asyncio
    value = _asyncio.run(readiness.repo_id_for(str(repo), GithubWorkspaceService()._run_git))
    assert value == derive_repo_identity(str(repo))["repo_id"]


@pytest.mark.asyncio
async def test_readiness_requires_the_operator(db, client, repo):
    _, scope = await _scope(db, repo)
    url = f"/api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness"
    assert (await client.get(url)).status_code in (401, 403)
    assert (await client.get(url, headers={"X-Synth-City-Operator-Token": "wrong"})).status_code in (401, 403)
    assert (await client.get(url, headers=HEADERS)).status_code == 200
    missing = await client.get("/api/v1/agent-teams/github-scopes/999999/workspace-readiness", headers=HEADERS)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_readiness_reports_workspace_counts_and_a_matching_slot_as_ok(db, client, repo):
    preset, scope = await _scope(db, repo, concurrency=2)
    await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    await _slot(db, preset.id, repo, derive_repo_identity(str(repo))["repo_id"])
    body = (await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness", headers=HEADERS)).json()
    assert body["target"] == 2 and body["dispatchable_workspaces"] == 2 and body["shortfall"] == 0
    assert [s["status"] for s in body["slots"]] == ["ok"] and body["slots"][0]["code"] is None


@pytest.mark.asyncio
async def test_readiness_shortfall_when_no_workspaces_exist(db, client, repo):
    _, scope = await _scope(db, repo, concurrency=3)
    body = (await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness", headers=HEADERS)).json()
    assert body["dispatchable_workspaces"] == 0 and body["shortfall"] == 3 and body["workspaces"] == []


@pytest.mark.asyncio
async def test_readiness_names_the_owner_cause_when_git_refuses_a_slot_checkout(db, client, repo, tmp_path, monkeypatch):
    preset, scope = await _scope(db, repo)
    other = tmp_path / "slot-checkout"
    other.mkdir()
    await _slot(db, preset.id, other, "0123456789abcdef")
    real = GithubWorkspaceService()._run_git

    async def refusing(args):
        if args[:2] == ["-C", str(other)]:
            return 128, f"fatal: detected dubious ownership in repository at '{other}'"
        return await real(args)

    monkeypatch.setattr(github_workspace_service, "_runner", refusing)
    body = (await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness", headers=HEADERS)).json()
    slot = body["slots"][0]
    assert slot["status"] == "mismatch" and slot["code"] == "git_owner_differs"
    assert "git refused the checkout: the owner differs" in slot["message"]


@pytest.mark.asyncio
async def test_readiness_names_a_different_repository_a_missing_path_and_a_stale_identity(db, client, repo, tmp_path):
    preset, scope = await _scope(db, repo)
    stranger = _make_repo(tmp_path / "stranger")
    plain = tmp_path / "plain"
    plain.mkdir()
    await _slot(db, preset.id, stranger, derive_repo_identity(str(stranger))["repo_id"], name="Stranger")
    await _slot(db, preset.id, tmp_path / "gone", "aaaaaaaaaaaaaaaa", name="Gone")
    await _slot(db, preset.id, plain, "bbbbbbbbbbbbbbbb", name="Plain")
    await _slot(db, preset.id, repo, "cccccccccccccccc", name="Stale")
    body = (await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness", headers=HEADERS)).json()
    codes = {s["display_name"]: s["code"] for s in body["slots"]}
    assert codes == {"Stranger": "different_repository", "Gone": "path_missing",
                     "Plain": "not_a_git_checkout", "Stale": "stored_identity_stale"}
    stale = next(s for s in body["slots"] if s["display_name"] == "Stale")
    assert "save the slot's repository path again" in stale["message"]


@pytest.mark.asyncio
async def test_safe_directory_entries_are_exact_quoted_and_never_a_wildcard(db, client, repo, tmp_path):
    preset, scope = await _scope(db, repo, concurrency=1)
    await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    spaced = _make_repo(tmp_path / "with space")
    newline = tmp_path / "bad\nname"
    newline.mkdir()
    await _slot(db, preset.id, spaced, derive_repo_identity(str(spaced))["repo_id"], name="Spaced")
    await _slot(db, preset.id, newline, "dddddddddddddddd", name="Newline")
    body = (await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness", headers=HEADERS)).json()
    safe = body["safe_directory"]
    controller = [e["command"] for e in safe["controller"]]
    native = [e["command"] for e in safe["native"]]
    assert f"git config --global --add safe.directory {repo}" in controller
    assert f"git config --global --add safe.directory '{spaced}'" in controller
    assert native == [f"git config --global --add safe.directory {repo.parent / 'dispatch-1'}"]
    assert all("*" not in c and "\n" not in c for c in controller + native)
    assert str(newline) not in " ".join(controller + native)
    assert [u["display_name"] for u in body["unsafe_paths"]] == ["Newline"]


@pytest.mark.asyncio
async def test_readiness_is_read_only(db, client, repo):
    preset, scope = await _scope(db, repo, concurrency=2)
    await GithubWorkspaceService().ensure_dispatch_workspaces(db, scope)
    await _slot(db, preset.id, repo, "eeeeeeeeeeeeeeee")
    before = [(r.id, r.path, r.updated_at) for r in await _rows(db, scope.id)]
    names = sorted(p.name for p in repo.parent.iterdir())
    runner = RecordingRunner()
    result = await readiness.build_readiness(db, scope, runner=runner)
    assert result["slots"][0]["code"] == "stored_identity_stale"
    assert runner.calls and all(c[2] == "rev-parse" for c in runner.calls if c[:1] == ["-C"])
    assert [(r.id, r.path, r.updated_at) for r in await _rows(db, scope.id)] == before
    assert sorted(p.name for p in repo.parent.iterdir()) == names
    assert not any("worktree" in c or "config" in c for c in runner.calls)


# ---- the pending item says why --------------------------------------------------------------


async def _pending(db, scope, number):
    item = GithubWorkItem(
        scope_id=scope.id, issue_number=number, issue_title="No workspace", issue_url="u",
        github_updated_at=datetime.utcnow(), dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def launcher(*_a, **_k):
        raise AssertionError("launcher must not run without a workspace")

    return item, launcher


@pytest.mark.asyncio
async def test_a_pending_item_with_no_registered_workspace_says_so(db):
    _, slots, scope = await _team(db)
    await db.execute(GithubWorkspace.__table__.delete().where(GithubWorkspace.scope_id == scope.id))
    item, launcher = await _pending(db, scope, 960)
    await github_dispatch_service.dispatch_pending(db, scope, slots, launcher=launcher,
                                                   issue_labels_by_number={960: ["area:backend"]})
    assert item.pending_reason == "queued_no_workspace"
    assert NO_WORKSPACE in item.status_note and "workspace-readiness" in item.status_note


@pytest.mark.asyncio
async def test_a_pending_item_says_when_every_workspace_is_disabled(db):
    _, slots, scope = await _team(db)
    await db.execute(update(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).values(enabled=False))
    count = (await db.execute(select(func.count()).select_from(GithubWorkspace)
                              .where(GithubWorkspace.scope_id == scope.id))).scalar_one()
    item, launcher = await _pending(db, scope, 961)
    await github_dispatch_service.dispatch_pending(db, scope, slots, launcher=launcher,
                                                   issue_labels_by_number={961: ["area:backend"]})
    assert item.pending_reason == "queued_no_workspace"
    assert f"All {count} workspace(s) are disabled or not dispatchable" in item.status_note


@pytest.mark.asyncio
async def test_a_pending_item_says_when_every_workspace_is_leased(db):
    _, slots, scope = await _team(db)
    workspaces = await _rows(db, scope.id)
    count = len(workspaces)
    for number, workspace in enumerate(workspaces):
        holder = GithubWorkItem(scope_id=scope.id, issue_number=970 + number, issue_title="h", issue_url="u",
                                github_updated_at=datetime.utcnow(), dispatch_status="merged")
        db.add(holder)
        await db.flush()
        workspace.leased_item_id = holder.id
        workspace.leased_at = datetime.utcnow()
        workspace.lease_token = f"held-{number}"
    await db.commit()
    item, launcher = await _pending(db, scope, 963)
    await github_dispatch_service.dispatch_pending(db, scope, slots, launcher=launcher,
                                                   issue_labels_by_number={963: ["area:backend"]})
    assert item.pending_reason == "queued_no_workspace"
    assert f"All {count} dispatchable workspace(s) are leased by other items" in item.status_note


@pytest.mark.asyncio
async def test_the_note_names_a_differing_owner_slot_identity(db, monkeypatch):
    _, slots, scope = await _team(db)
    await db.execute(GithubWorkspace.__table__.delete().where(GithubWorkspace.scope_id == scope.id))

    async def mismatch(db_, scope_, slot, runner=None):
        return {"slot_id": slot.id, "display_name": slot.display_name, "status": "mismatch",
                "code": "git_owner_differs", "message": "git refused the checkout: the owner differs"}

    monkeypatch.setattr(readiness, "check_slot_identity", mismatch)
    item, launcher = await _pending(db, scope, 964)
    await github_dispatch_service.dispatch_pending(db, scope, slots, launcher=launcher,
                                                   issue_labels_by_number={964: ["area:backend"]})
    assert NO_WORKSPACE in item.status_note
    assert "git refused the checkout: the owner differs" in item.status_note
