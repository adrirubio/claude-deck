"""Workspace lease, provisioning, adoption, and reset tests."""
from datetime import datetime
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
from app.services.github_dispatch_service import github_dispatch_service
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
        self.failures: dict[str, str] = {}

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        path = args[1] if len(args) > 1 and args[0] == "-C" else ""
        command = args[2] if len(args) > 2 else ""
        if command == "rev-parse":
            identity = self.identities.get(path)
            if identity is None:
                return 128, "fatal: not a git repository"
            return 0, "\n".join(identity) + "\n"
        if command == "status":
            return 0, self.statuses.get(path, "")
        failure = self.failures.get(command)
        if failure is not None:
            return 1, failure
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


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["escalated", "failed", "merged", "completed"])
async def test_reclaim_releases_non_working_item_without_live_owner(
    db, tmp_path, monkeypatch, status
):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = status
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()
    monkeypatch.setattr(
        github_dispatch_service,
        "slot_has_live_owner_session",
        lambda *_args, **_kwargs: _async_value(False),
    )

    count = await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope)

    assert count == 1
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_reclaim_retains_non_working_item_with_live_owner(db, tmp_path, monkeypatch):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()
    monkeypatch.setattr(
        github_dispatch_service,
        "slot_has_live_owner_session",
        lambda *_args, **_kwargs: _async_value(True),
    )

    count = await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope)

    assert count == 0
    assert workspace.leased_item_id == item.id


async def _async_value(value):
    return value


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
