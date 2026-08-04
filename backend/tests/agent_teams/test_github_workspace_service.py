"""Workspace lease, provisioning, adoption, and reset tests."""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
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
from app.services.github_workspace_service import (
    GIT_TIMEOUT_SECONDS,
    GithubWorkspaceError,
    GithubWorkspaceResetError,
    GithubWorkspaceService,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


class FakeGitRunner:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.identities: dict[str, tuple[str, str, str] | None] = {}
        self.statuses: dict[str, str] = {}
        self.rev_counts: dict[str, str] = {}
        self.failures: dict[str, str] = {}

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        path = args[1] if len(args) > 1 and args[0] == "-C" else ""
        command = args[2] if len(args) > 2 else ""
        failure = self.failures.get(command)
        if failure is not None:
            return 1, failure
        if command == "rev-parse":
            identity = self.identities.get(path)
            if identity is None:
                return 128, "fatal: not a git repository"
            return 0, "\n".join(identity) + "\n"
        if command == "status":
            return 0, self.statuses.get(path, "")
        if command == "rev-list":
            return 0, self.rev_counts.get(path, "0") + "\n"
        return 0, ""


async def _context(db, repo_path: Path):
    preset = AgentTeamPreset(name="Workspace Team", description="", created_by="test")
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Generalist",
        provider="codex-cli",
        repo_id="repo",
        repo_path=str(repo_path),
        repo_name="repo",
        launch_mode="plain",
        launch_options={},
        enabled=True,
    )
    db.add(slot)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo",
        repo_path=str(repo_path),
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=304,
        issue_title="Provision workspaces",
        issue_url="https://github.com/owner/repo/issues/304",
        github_updated_at=datetime.utcnow(),
        owner_slot_id=slot.id,
    )
    db.add(item)
    await db.commit()
    return scope, slot, item


def _set_identity(runner: FakeGitRunner, path: Path, common_dir: Path, *, linked: bool):
    git_dir = common_dir / "worktrees" / path.name if linked else common_dir
    runner.identities[str(path)] = (str(git_dir), str(common_dir), str(path))


@pytest.mark.asyncio
async def test_lease_columns_default_to_null(db, tmp_path):
    """A lease predating G2 must read as no information."""
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()

    assert workspace.lease_token is None
    assert workspace.leased_owner_pid is None
    assert workspace.leased_owner_proc_start is None
    assert workspace.lease_last_owner_contact_at is None
    assert workspace.lease_release_reminded_at is None
    assert item.retry_requested_at is None
    assert item.brief_delivery_nudge_at is None
    assert item.brief_delivery_nudge_count is None
    assert item.brief_message_id is None


def test_read_proc_start_handles_comm_containing_spaces_and_parens():
    """Field 2 of /proc/<pid>/stat is parenthesized and may contain spaces or parens.

    A naive split() puts starttime at the wrong index. Spec §3.2 pins the
    rindex(")") recipe; this fixture is the case that breaks the naive version.

    Correction (2026-08-03): an earlier draft used range(100, 118) filler and
    landed the sentinel at index 25, so the test failed on its own arithmetic
    before reaching any production code. The field list is now built explicitly
    and its length asserted, because the bug was a hand-count and a hand-count
    is exactly what must not be trusted twice.
    """
    service = GithubWorkspaceService(runner=FakeGitRunner())

    # Everything after comm and before starttime: state + the six fixed numeric
    # fields (ppid pgrp session tty_nr tpgid flags), then filler. starttime is
    # field 22 overall = index 19 counting from state, so exactly 19 values
    # precede it.
    before_starttime = ["S", "1", "12345", "12345", "0", "-1", "4194560"] + [
        str(n) for n in range(100, 112)
    ]
    assert len(before_starttime) == 19  # guards the fixture, not the code
    raw = (
        "12345 (weird (proc) name) "
        + " ".join(before_starttime)
        + " 987654321 "
        + " ".join(str(n) for n in range(200, 210))
    )

    assert raw[raw.rindex(")") + 2:].split()[19] == "987654321"
    # The fixture must also DISCRIMINATE: every naive parse has to miss. If any
    # of these ever equals the sentinel, the fixture stopped testing the defect.
    assert raw.split()[19] != "987654321"
    assert raw.split()[21] != "987654321"
    assert raw[raw.index(")") + 2:].split()[19] != "987654321"

    assert service._parse_proc_start(raw) == "987654321"


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_when_pid_is_null(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id, path=str(tmp_path / "ws"), leased_item_id=item.id
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    assert service._owner_process_is_alive(workspace) is True


@pytest.mark.asyncio
async def test_owner_process_alive_is_false_for_dead_pid(db, tmp_path, monkeypatch):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=123456,
        leased_owner_proc_start="123",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    def _dead(_pid):
        raise ProcessLookupError()

    monkeypatch.setattr(service, "_read_proc_start", _dead)

    assert service._owner_process_is_alive(workspace) is False


@pytest.mark.asyncio
async def test_owner_process_alive_is_false_when_proc_start_differs(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start="999999999",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    assert service._owner_process_is_alive(workspace) is False


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_for_this_process(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start=service._read_proc_start(os.getpid()),
    )
    db.add(workspace)
    await db.commit()

    assert service._owner_process_is_alive(workspace) is True


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_when_proc_unreadable(db, tmp_path, monkeypatch):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start="123",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    def _boom(_pid):
        raise PermissionError("denied")

    monkeypatch.setattr(service, "_read_proc_start", _boom)

    assert service._owner_process_is_alive(workspace) is True


@pytest.mark.asyncio
async def test_acquire_leases_oldest_available_workspace(db, tmp_path):
    repo_path = tmp_path / "repo"
    scope, _, item = await _context(db, repo_path)
    runner = FakeGitRunner()
    service = GithubWorkspaceService(runner=runner)
    first = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws1"))
    second = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws2"))
    db.add_all([first, second])
    await db.commit()

    acquired = await service.acquire(db, scope, item)

    assert acquired.id == first.id
    assert acquired.leased_item_id == item.id
    assert acquired.leased_at is not None


@pytest.mark.asyncio
async def test_acquire_mints_a_fresh_token_each_acquisition(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()

    first = await service.acquire(db, scope, item)
    first_token = first.lease_token
    await service.release(db, item.id)
    second = await service.acquire(db, scope, item)

    assert first_token is not None
    assert second.lease_token is not None
    assert second.lease_token != first_token


@pytest.mark.asyncio
async def test_acquire_returning_held_lease_does_not_remint(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()

    first = await service.acquire(db, scope, item)
    token = first.lease_token
    again = await service.acquire(db, scope, item)

    assert again.id == first.id
    assert again.lease_token == token


@pytest.mark.asyncio
async def test_acquire_returns_none_when_every_workspace_is_leased(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    other = GithubWorkItem(
        scope_id=scope.id,
        issue_number=305,
        issue_title="Other",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(other)
    await db.flush()
    db.add(GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"), leased_item_id=other.id))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).acquire(db, scope, item) is None


@pytest.mark.asyncio
async def test_acquire_is_idempotent_for_existing_lease(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()
    runner = FakeGitRunner()

    acquired = await GithubWorkspaceService(runner=runner).acquire(db, scope, item)

    assert acquired.id == workspace.id
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["enabled", "dispatchable"])
async def test_acquire_ignores_unavailable_workspace(db, tmp_path, field):
    scope, _, item = await _context(db, tmp_path / "repo")
    values = {"enabled": True, "dispatchable": True}
    values[field] = False
    db.add(GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"), **values))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).acquire(db, scope, item) is None


@pytest.mark.asyncio
async def test_non_dispatchable_primary_never_wins_acquire(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    primary = GithubWorkspace(
        scope_id=scope.id,
        path=scope.repo_path,
        kind="primary",
        dispatchable=False,
    )
    worktree = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add_all([primary, worktree])
    await db.commit()

    acquired = await GithubWorkspaceService(runner=FakeGitRunner()).acquire(db, scope, item)

    assert acquired.id == worktree.id


@pytest.mark.asyncio
async def test_release_is_idempotent(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    await service.release(db, item.id)
    await service.release(db, item.id)

    assert workspace.leased_item_id is None
    assert workspace.released_at is not None


@pytest.fixture
def dead_owner(monkeypatch):
    def _dead(self, pid):
        raise ProcessLookupError()

    monkeypatch.setattr(GithubWorkspaceService, "_read_proc_start", _dead)


def _stale_lease(scope, tmp_path, item, **overrides):
    fields = dict(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_at=datetime.utcnow() - timedelta(seconds=25000),
        lease_token="t1",
        leased_owner_pid=123456,
        leased_owner_proc_start="123",
        lease_last_owner_contact_at=None,
    )
    fields.update(overrides)
    return GithubWorkspace(**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["escalated", "failed", "merged", "completed"])
async def test_reclaim_releases_dead_silent_clean_lease(db, tmp_path, dead_owner, status):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = status
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    count = await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope)

    assert count == 1


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_live_owner_process(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    service = GithubWorkspaceService(runner=FakeGitRunner())
    db.add(
        _stale_lease(
            scope,
            tmp_path,
            item,
            leased_owner_pid=os.getpid(),
            leased_owner_proc_start=service._read_proc_start(os.getpid()),
        )
    )
    await db.commit()

    assert await service.reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_within_threshold(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(
        _stale_lease(
            scope,
            tmp_path,
            item,
            leased_at=datetime.utcnow() - timedelta(seconds=60),
        )
    )
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_dirty_tree(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    runner.statuses[str(tmp_path / "ws")] = " M src/foo.c\n"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_unpushed_commits(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    runner.statuses[str(tmp_path / "ws")] = ""
    runner.rev_counts[str(tmp_path / "ws")] = "3"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_command", ["status", "rev-list"])
async def test_reclaim_retains_lease_when_quiescence_cannot_be_determined(
    db, tmp_path, dead_owner, failing_command
):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    runner.failures[failing_command] = "fatal: not a git repository"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_checks_unpushed_commits_against_the_scope_base_ref(
    db, tmp_path, dead_owner
):
    scope, _, item = await _context(db, tmp_path / "repo")
    scope.base_ref = "origin/feature/integration"
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope)

    rev_list = [call for call in runner.calls if len(call) > 2 and call[2] == "rev-list"]
    assert rev_list
    assert "origin/feature/integration..HEAD" in rev_list[0]


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_recent_owner_contact(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(
        _stale_lease(
            scope,
            tmp_path,
            item,
            lease_last_owner_contact_at=datetime.utcnow() - timedelta(seconds=60),
        )
    )
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_releases_when_owner_contact_has_aged_out(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(
        _stale_lease(
            scope,
            tmp_path,
            item,
            lease_last_owner_contact_at=datetime.utcnow() - timedelta(seconds=25000),
        )
    )
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 1


@pytest.mark.asyncio
async def test_reclaim_never_touches_a_leased_primary_workspace(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(scope, tmp_path, item, kind="primary"))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_ready_for_review_is_not_reclaimable(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "ready_for_review"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_register_provisions_fresh_worktree(db, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    _set_identity(runner, repo_path, repo_path / ".git", linked=False)
    workspace_path = tmp_path / "ws"

    workspace = await GithubWorkspaceService(runner=runner).register_workspace(
        db, scope, str(workspace_path), kind="worktree"
    )

    assert workspace.path == str(workspace_path)
    assert [
        "-C", str(repo_path), "worktree", "add", "--detach",
        str(workspace_path), "origin/HEAD",
    ] in runner.calls


@pytest.mark.asyncio
async def test_register_empty_directory_takes_provisioning_path(db, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    workspace_path = tmp_path / "ws"
    workspace_path.mkdir()
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    _set_identity(runner, repo_path, repo_path / ".git", linked=False)

    await GithubWorkspaceService(runner=runner).register_workspace(
        db, scope, str(workspace_path), kind="worktree"
    )

    assert any(call[2:4] == ["worktree", "add"] for call in runner.calls)


@pytest.mark.asyncio
async def test_register_adopts_existing_linked_worktree(db, tmp_path):
    repo_path = tmp_path / "repo"
    workspace_path = tmp_path / "ws"
    repo_path.mkdir()
    workspace_path.mkdir()
    (workspace_path / "tracked").write_text("clean")
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    common_dir = repo_path / ".git"
    _set_identity(runner, repo_path, common_dir, linked=False)
    _set_identity(runner, workspace_path, common_dir, linked=True)

    workspace = await GithubWorkspaceService(runner=runner).register_workspace(
        db, scope, str(workspace_path), kind="worktree"
    )

    assert workspace.kind == "worktree"
    assert not any(call[2:4] == ["worktree", "add"] for call in runner.calls)
    assert all("--path-format=absolute" in call for call in runner.calls if "rev-parse" in call)


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_kind", ["foreign", "nested", "plain"])
async def test_register_rejects_invalid_existing_worktree(db, tmp_path, candidate_kind):
    repo_path = tmp_path / "repo"
    workspace_path = tmp_path / "ws"
    repo_path.mkdir()
    workspace_path.mkdir()
    (workspace_path / "content").write_text("x")
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    common_dir = repo_path / ".git"
    _set_identity(runner, repo_path, common_dir, linked=False)
    if candidate_kind == "foreign":
        _set_identity(runner, workspace_path, tmp_path / "other" / ".git", linked=True)
    elif candidate_kind == "nested":
        runner.identities[str(workspace_path)] = (
            str(common_dir / "worktrees" / "real"),
            str(common_dir),
            str(tmp_path / "real-root"),
        )

    with pytest.raises(GithubWorkspaceError) as exc_info:
        await GithubWorkspaceService(runner=runner).register_workspace(
            db, scope, str(workspace_path), kind="worktree"
        )

    assert exc_info.value.block_code == "workspace_not_a_worktree"


@pytest.mark.asyncio
async def test_register_rejects_primary_as_worktree(db, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "content").write_text("x")
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    _set_identity(runner, repo_path, repo_path / ".git", linked=False)

    with pytest.raises(GithubWorkspaceError) as exc_info:
        await GithubWorkspaceService(runner=runner).register_workspace(
            db, scope, str(repo_path), kind="worktree"
        )

    assert exc_info.value.block_code == "workspace_is_primary"


@pytest.mark.asyncio
async def test_register_rejects_linked_worktree_as_primary(db, tmp_path):
    repo_path = tmp_path / "repo"
    workspace_path = tmp_path / "ws"
    repo_path.mkdir()
    workspace_path.mkdir()
    (workspace_path / "content").write_text("x")
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    common_dir = repo_path / ".git"
    _set_identity(runner, repo_path, common_dir, linked=False)
    _set_identity(runner, workspace_path, common_dir, linked=True)

    with pytest.raises(GithubWorkspaceError) as exc_info:
        await GithubWorkspaceService(runner=runner).register_workspace(
            db, scope, str(workspace_path), kind="primary"
        )

    assert exc_info.value.block_code == "workspace_not_a_worktree"


@pytest.mark.asyncio
async def test_register_primary_validates_repository_identity(db, tmp_path):
    repo_path = tmp_path / "repo"
    other_path = tmp_path / "other"
    repo_path.mkdir()
    other_path.mkdir()
    (other_path / "content").write_text("x")
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    _set_identity(runner, repo_path, repo_path / ".git", linked=False)
    _set_identity(runner, other_path, other_path / ".git", linked=False)

    with pytest.raises(GithubWorkspaceError) as exc_info:
        await GithubWorkspaceService(runner=runner).register_workspace(
            db, scope, str(other_path), kind="primary"
        )

    assert exc_info.value.block_code == "workspace_not_a_worktree"


@pytest.mark.asyncio
async def test_register_rejects_dirty_adopted_worktree(db, tmp_path):
    repo_path = tmp_path / "repo"
    workspace_path = tmp_path / "ws"
    repo_path.mkdir()
    workspace_path.mkdir()
    (workspace_path / "content").write_text("x")
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    common_dir = repo_path / ".git"
    _set_identity(runner, repo_path, common_dir, linked=False)
    _set_identity(runner, workspace_path, common_dir, linked=True)
    runner.statuses[str(workspace_path)] = "?? untracked.txt\n"

    with pytest.raises(GithubWorkspaceError) as exc_info:
        await GithubWorkspaceService(runner=runner).register_workspace(
            db, scope, str(workspace_path), kind="worktree"
        )

    assert exc_info.value.block_code == "workspace_dirty"
    assert "untracked.txt" in str(exc_info.value)


@pytest.mark.asyncio
async def test_register_rejects_occupied_adopted_worktree(db, tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    workspace_path = tmp_path / "ws"
    repo_path.mkdir()
    workspace_path.mkdir()
    (workspace_path / "content").write_text("x")
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    common_dir = repo_path / ".git"
    _set_identity(runner, repo_path, common_dir, linked=False)
    _set_identity(runner, workspace_path, common_dir, linked=True)
    monkeypatch.setattr(
        "app.services.github_workspace_service.discover_agent_sessions",
        lambda: [{"cwd": str(workspace_path / ".." / "ws")}],
    )

    with pytest.raises(GithubWorkspaceError) as exc_info:
        await GithubWorkspaceService(runner=runner).register_workspace(
            db, scope, str(workspace_path), kind="worktree"
        )

    assert exc_info.value.block_code == "workspace_occupied"


@pytest.mark.asyncio
async def test_register_honors_explicit_workspace_flags(db, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    scope, _, _ = await _context(db, repo_path)
    runner = FakeGitRunner()
    _set_identity(runner, repo_path, repo_path / ".git", linked=False)

    workspace = await GithubWorkspaceService(runner=runner).register_workspace(
        db,
        scope,
        str(tmp_path / "ws"),
        kind="worktree",
        dispatchable=False,
        enabled=False,
    )

    assert workspace.dispatchable is False
    assert workspace.enabled is False


@pytest.mark.asyncio
async def test_reset_uses_safe_commands_and_preserves_ignored_files(db, tmp_path):
    scope, _, _ = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    runner = FakeGitRunner()

    await GithubWorkspaceService(runner=runner).reset_workspace(db, scope, workspace)

    assert ["-C", workspace.path, "switch", "--detach", "--force", "origin/HEAD"] in runner.calls
    assert ["-C", workspace.path, "reset", "--hard", "origin/HEAD"] in runner.calls
    assert ["-C", workspace.path, "clean", "-fd"] in runner.calls
    assert not any("-fdx" in call or "-x" in call for call in runner.calls)


@pytest.mark.asyncio
async def test_reset_primary_runs_no_git_commands(db, tmp_path):
    scope, _, _ = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=scope.repo_path,
        kind="primary",
    )
    runner = FakeGitRunner()

    await GithubWorkspaceService(runner=runner).reset_workspace(db, scope, workspace)

    assert runner.calls == []


@pytest.mark.asyncio
async def test_fetch_failure_is_transient_and_releases_lease(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()
    runner = FakeGitRunner()
    runner.failures["fetch"] = "network down"

    acquired = await GithubWorkspaceService(runner=runner).acquire(db, scope, item)

    assert acquired is None
    assert workspace.enabled is True
    assert workspace.provision_error == "network down"
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_local_reset_failure_disables_workspace(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()
    runner = FakeGitRunner()
    runner.failures["switch"] = "broken tree"

    acquired = await GithubWorkspaceService(runner=runner).acquire(db, scope, item)

    assert acquired is None
    assert workspace.enabled is False
    assert workspace.provision_error == "broken tree"
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_successful_reset_clears_provision_error(db, tmp_path):
    scope, _, _ = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        provision_error="old failure",
    )

    await GithubWorkspaceService(runner=FakeGitRunner()).reset_workspace(db, scope, workspace)

    assert workspace.provision_error is None


@pytest.mark.asyncio
async def test_reset_error_reports_transient_classification(db, tmp_path):
    scope, _, _ = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    runner = FakeGitRunner()
    runner.failures["fetch"] = "offline"

    with pytest.raises(GithubWorkspaceResetError) as exc_info:
        await GithubWorkspaceService(runner=runner).reset_workspace(db, scope, workspace)

    assert exc_info.value.transient is True


@pytest.mark.asyncio
async def test_git_runner_is_noninteractive_and_timed(monkeypatch):
    captured = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def create_process(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        return Process()

    real_wait_for = __import__("asyncio").wait_for

    async def timed(awaitable, *, timeout):
        captured["timeout"] = timeout
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(
        "app.services.github_workspace_service.asyncio.create_subprocess_exec",
        create_process,
    )
    monkeypatch.setattr(
        "app.services.github_workspace_service.asyncio.wait_for",
        timed,
    )

    result = await GithubWorkspaceService()._run_git(["status"])

    assert result == (0, "ok")
    assert captured["args"] == ("git", "status")
    assert captured["timeout"] == GIT_TIMEOUT_SECONDS
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["env"]["GIT_ASKPASS"] == ""
    assert captured["env"]["SSH_ASKPASS"] == ""
