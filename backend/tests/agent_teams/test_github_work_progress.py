"""Source-bound publication facts. These tests use disposable repos and DBs."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, GithubWorkspace, TeamGithubScope
from app.models.github_work_progress import GithubWorkProgressSnapshot
from app.services.github_work_progress_observation import (
    LocalProgressObservation, ProgressObservationError, WorkspaceProgressContext, WorkspaceProgressObserver,
)
from app.services.github_work_progress_service import GithubWorkProgressService, _next_step
from app.api.v1 import github_work_progress as api

SHA = "a" * 40
REMOTE = "b" * 40


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "task")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "Test")
    (path / "file").write_text("first")
    git(path, "add", "file")
    git(path, "commit", "-m", "first")
    return path


def context(repo):
    return WorkspaceProgressContext(str(repo), str(repo), "primary")


@pytest.mark.asyncio
async def test_exact_local_gap_and_matching_head(repo):
    observer = WorkspaceProgressObserver()
    published = git(repo, "rev-parse", "HEAD")
    (repo / "file").write_text("second")
    git(repo, "commit", "-am", "second")
    local = await observer.read(context(repo))
    assert await observer.compare(context(repo), local.sha, published) == ("ahead", 1)
    assert await observer.compare(context(repo), local.sha, local.sha) == ("synchronized", 0)
    assert await observer.compare(context(repo), published, local.sha) == ("behind", 0)
    assert local.tracked_changes is None and local.untracked_files is None
    assert await observer.confirm(context(repo), local)
    git(repo, "checkout", "--detach")
    assert (await observer.read(context(repo))).branch is None
    assert not await observer.confirm(context(repo), local)


@pytest.mark.asyncio
async def test_diverged_history_and_missing_object(repo):
    observer = WorkspaceProgressObserver()
    git(repo, "checkout", "-b", "other")
    (repo / "other").write_text("remote")
    git(repo, "add", "other"); git(repo, "commit", "-m", "other")
    published = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "task")
    (repo / "local").write_text("local")
    git(repo, "add", "local"); git(repo, "commit", "-m", "local")
    local = await observer.read(context(repo))
    assert await observer.compare(context(repo), local.sha, published) == ("diverged", 1)
    with pytest.raises(ProgressObservationError, match="published_object_unavailable"):
        await observer.compare(context(repo), local.sha, REMOTE)
    (repo / ".git/shallow").write_text(local.sha + "\n")
    with pytest.raises(ProgressObservationError, match="ancestry_unavailable"):
        await observer.compare(context(repo), local.sha, published)


@pytest.mark.asyncio
async def test_filters_dirty_untracked_and_promisor_never_execute(repo, tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    git(repo, "config", "filter.test.clean", f"touch {marker}; cat")
    git(repo, "config", "filter.test.process", f"touch {marker}")
    (repo / ".git/info/attributes").write_text("* filter=test\n")
    (repo / "file").write_text("dirty")
    (repo / "private.env").write_text("private-file-name")
    git(repo, "config", "remote.evil.promisor", "true")
    git(repo, "config", "remote.evil.url", f"ext::touch {marker}")
    git(repo, "config", "protocol.ext.allow", "always")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", f"touch {marker}")
    monkeypatch.setenv("SECRET_PROGRESS_TEST", "must-not-enter-child")
    before = (repo / ".git/index").read_bytes()
    observer = WorkspaceProgressObserver()
    local = await observer.read(context(repo))
    assert local.tracked_changes is None and local.untracked_files is None
    with pytest.raises(ProgressObservationError, match="published_object_unavailable"):
        await observer.compare(context(repo), local.sha, REMOTE)
    assert await observer.confirm(context(repo), local)
    assert not marker.exists()
    assert (repo / ".git/index").read_bytes() == before
    assert (repo / "file").read_text() == "dirty"
    assert (repo / "private.env").read_text() == "private-file-name"


@pytest.mark.asyncio
async def test_registered_linked_worktree_and_invalid_paths(repo, tmp_path):
    workspace = tmp_path / "owner"
    git(repo, "worktree", "add", "-b", "owner", str(workspace))
    observer = WorkspaceProgressObserver()
    linked = WorkspaceProgressContext(str(repo), str(workspace), "worktree")
    assert (await observer.read(linked)).branch == "owner"
    other = tmp_path / "other"; other.mkdir()
    git(other, "init")
    with pytest.raises(ProgressObservationError, match="workspace_identity_unavailable"):
        await observer.read(WorkspaceProgressContext(str(repo), str(other), "worktree"))
    alias = tmp_path / "alias"; alias.symlink_to(repo)
    with pytest.raises(ProgressObservationError, match="workspace_identity_unavailable"):
        await observer.read(context(alias))
    with pytest.raises(ProgressObservationError, match="workspace_identity_unavailable"):
        await observer.read(context(tmp_path / "missing"))


@pytest_asyncio.fixture
async def db(monkeypatch):
    monkeypatch.setattr("app.services.github_work_progress_service.hold_code", lambda: None)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", hide_parameters=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def seed(db):
    preset = AgentTeamPreset(name="Progress", created_by="test", autonomy_enabled=True)
    db.add(preset); await db.flush()
    slot = AgentTeamSlot(preset_id=preset.id, position=0, display_name="Owner", provider="codex-cli",
                         repo_id="repo", repo_path="/safe/repo", repo_name="repo", launch_mode="plain", launch_options={})
    db.add(slot); await db.flush()
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="owner", repo_name="repo", repo_path="/safe/repo",
                            merge_policy="human", enabled=True)
    db.add(scope); await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="Progress", issue_url="https://github.com/owner/repo/issues/1",
                          github_updated_at=datetime.utcnow(), owner_slot_id=slot.id, dispatch_status="dispatched",
                          dispatch_nonce="public-dispatch-id", dispatch_head_ref="task", ack_received_at=datetime.utcnow())
    db.add(item); await db.flush()
    workspace = GithubWorkspace(scope_id=scope.id, kind="primary", path=scope.repo_path,
                                leased_item_id=item.id, lease_token="private-lease-value", leased_at=datetime.utcnow())
    db.add(workspace); await db.commit()
    return item, scope, preset, workspace


class Observer:
    calls = 0
    changed = False
    async def read(self, context):
        self.calls += 1
        return LocalProgressObservation(SHA, "task")
    async def confirm(self, context, local):
        return not self.changed
    async def compare(self, context, local, remote):
        return ("synchronized", 0) if local == remote else ("ahead", 2)


class Client:
    calls = 0
    sha = REMOTE
    missing = False
    async def get_ref(self, *args, **kwargs):
        self.calls += 1
        return None if self.missing else {"ref": "refs/heads/task", "object": {"sha": self.sha, "type": "commit"}}


@pytest.mark.asyncio
async def test_cache_reuse_release_and_private_fields(db):
    item, scope, preset, workspace = await seed(db)
    observer, client = Observer(), Client()
    service = GithubWorkProgressService(observer, client)
    first = await service.summary(db, item.id)
    assert first.publication.unpublished_commits == 2
    assert first.publication.publication_time_source == "github_head_observation"
    assert first.publication.tracked_changes is None
    assert (first.phase, first.next_actor) == ("implementation", "owner")
    assert first.last_check_head is None
    saved = await db.get(GithubWorkProgressSnapshot, item.id)
    assert "private-lease-value" not in str(saved.identity) + str(saved.observation)
    assert "/safe/repo" not in first.model_dump_json()
    assert "private-lease-value" not in first.model_dump_json()
    second = await service.summary(db, item.id)
    assert observer.calls == 1 and client.calls == 1
    assert second.publication.publication_first_observed_at == first.publication.publication_first_observed_at
    workspace.leased_item_id = None; workspace.lease_token = None
    item.dispatch_status = "merged"
    await db.commit()
    released = await service.summary(db, item.id)
    assert released.publication.state == "historical" and released.publication.local_sha == SHA
    assert observer.calls == 1
    assert (released.phase, released.next_actor) == ("complete", "none")
    assert item.retry_count == 0 and item.approval_round_count == 0 and preset.autonomy_enabled


@pytest.mark.asyncio
async def test_new_read_keeps_first_observation_time_and_handles_missing_remote(db):
    item, *_ = await seed(db)
    observer, client = Observer(), Client()
    service = GithubWorkProgressService(observer, client)
    first = await service.summary(db, item.id)
    await db.execute(update(GithubWorkProgressSnapshot).values(observed_at=datetime.utcnow() - timedelta(seconds=30)))
    await db.commit()
    refreshed = await service.summary(db, item.id)
    assert observer.calls == 2
    assert refreshed.publication.publication_first_observed_at == first.publication.publication_first_observed_at
    client.missing = True
    await db.execute(update(GithubWorkProgressSnapshot).values(observed_at=datetime.utcnow() - timedelta(seconds=30)))
    await db.commit()
    missing = await service.summary(db, item.id)
    assert missing.publication.state == "historical" and missing.publication.reason == "remote_unavailable"
    assert missing.publication.observed_at == refreshed.publication.observed_at


@pytest.mark.asyncio
async def test_changed_source_and_dispatch_do_not_publish_current_facts(db):
    item, *_ = await seed(db)
    observer = Observer(); observer.changed = True
    service = GithubWorkProgressService(observer, Client())
    changed = await service.summary(db, item.id)
    assert changed.publication.state == "unavailable" and changed.publication.reason == "changed_during_read"
    assert await db.get(GithubWorkProgressSnapshot, item.id) is None
    observer.changed = False
    class RaceClient(Client):
        async def get_ref(self, *args, **kwargs):
            await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(dispatch_nonce="new-dispatch"))
            await db.commit()
            return await super().get_ref(*args, **kwargs)
    service.client = RaceClient()
    raced = await service.summary(db, item.id)
    assert raced.dispatch_nonce == "new-dispatch"
    assert raced.publication.state == "unavailable" and raced.publication.local_sha is None
    assert await db.get(GithubWorkProgressSnapshot, item.id) is None


@pytest.mark.asyncio
async def test_route_is_safe_read_no_store_and_missing_item_404(db, monkeypatch):
    item, *_ = await seed(db)
    app = FastAPI(); app.include_router(api.router, prefix="/agent-teams")
    async def session(): yield db
    app.dependency_overrides[get_db] = session
    monkeypatch.setattr(api, "github_work_progress_service", GithubWorkProgressService(Observer(), Client()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/agent-teams/github-work-items/{item.id}/progress")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["publication"]["file_counts_reason"] == "safe_metadata_read"
        assert (await client.get("/agent-teams/github-work-items/999/progress")).status_code == 404


@pytest.mark.parametrize("status, pending, hold, phase, actor", [
    ("dispatched", None, None, "implementation", "owner"),
    ("dispatched", 1, None, "plan_review", "leader"),
    ("ready_for_review", None, None, "review", "operator"),
    ("verifying", None, None, "ci", "controller"),
    ("escalated", None, None, "intervention", "operator"),
    ("dispatched", None, "hold", "paused", "operator"),
    ("merged", None, "hold", "complete", "none"),
])
def test_phase_actors_do_not_grant_authority(status, pending, hold, phase, actor):
    item = SimpleNamespace(dispatch_status=status, attempt_phase="implementation", status_note=None,
                           handoff_state=None, ack_received_at=datetime.now(timezone.utc))
    scope = SimpleNamespace(enabled=True, merge_policy="human")
    preset = SimpleNamespace(autonomy_enabled=True)
    assert _next_step(item, scope, preset, pending, hold)[:2] == (phase, actor)


@pytest.mark.asyncio
async def test_git_child_is_bounded_and_has_no_inherited_secrets(repo, monkeypatch):
    import app.services.github_work_progress_observation as module
    monkeypatch.setenv("SECRET_PROGRESS_TEST", "private-value")
    captured, killed, finished = {}, [], []
    class Stream:
        async def read(self, size): return b"x" * 64
    class Process:
        pid = 123456789
        returncode = None
        stdout = Stream()
        async def wait(self): self.returncode = 0; finished.append(True); return 0
    async def spawn(*args, **kwargs): captured.update(args=args, **kwargs); return Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "_MAX_OUTPUT", 32)
    monkeypatch.setattr(module.os, "killpg", lambda pid, signal: killed.append(pid))
    with pytest.raises(ProgressObservationError, match="observation_limit"):
        await module.WorkspaceProgressObserver._run_git(str(repo), ["rev-parse", "HEAD"])
    assert "SECRET_PROGRESS_TEST" not in captured["env"]
    assert Path(captured["args"][0]).is_absolute()
    assert captured["start_new_session"] and killed == [123456789] and finished == [True]
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    class HangingStream:
        async def read(self, size): await asyncio.Event().wait()
    Process.stdout = HangingStream()
    monkeypatch.setattr(module, "_COMMAND_SECONDS", 0.01)
    with pytest.raises(ProgressObservationError, match="observation_timeout"):
        await module.WorkspaceProgressObserver._run_git(str(repo), ["rev-parse", "HEAD"])
    assert finished == [True, True]


@pytest.mark.asyncio
async def test_private_object_view_is_removed_after_limit(repo):
    paths = []
    async def runner(path, args):
        if args[0] == "cat-file": return 0, b"commit\n"
        if args[0] == "rev-list":
            view = Path(path); paths.append(view)
            assert "remote" not in (view / "config").read_text()
            assert "commitGraph = false" in (view / "config").read_text()
            assert (view / "objects").is_symlink()
            return 0, b"0 10001\n"
        return await WorkspaceProgressObserver._run_git(path, args)
    with pytest.raises(ProgressObservationError, match="observation_limit"):
        await WorkspaceProgressObserver(runner).compare(context(repo), git(repo, "rev-parse", "HEAD"), REMOTE)
    assert len(paths) == 1 and not paths[0].exists()


@pytest.mark.asyncio
async def test_tag_pointer_is_not_peeled_for_commit_counts(repo):
    git(repo, "tag", "-a", "tag", "-m", "annotated")
    tag = git(repo, "rev-parse", "refs/tags/tag")
    with pytest.raises(ProgressObservationError, match="published_object_unavailable"):
        await WorkspaceProgressObserver().compare(context(repo), tag, git(repo, "rev-parse", "HEAD"))


@pytest.mark.asyncio
async def test_lease_revocation_during_remote_read_grants_no_authority(db):
    item, scope, preset, workspace = await seed(db)
    class RevokeClient(Client):
        async def get_ref(self, *args, **kwargs):
            await db.execute(update(GithubWorkspace).where(GithubWorkspace.id == workspace.id).values(lease_token=None, leased_item_id=None))
            await db.commit()
            return await super().get_ref(*args, **kwargs)
    value = await GithubWorkProgressService(Observer(), RevokeClient()).summary(db, item.id)
    assert value.publication.state == "unavailable" and value.publication.reason == "changed_during_read"
    assert await db.get(GithubWorkProgressSnapshot, item.id) is None
    await db.refresh(item); await db.refresh(preset); await db.refresh(workspace)
    assert item.retry_count == 0 and item.dispatch_status == "dispatched"
    assert workspace.lease_token is None and preset.autonomy_enabled


@pytest.mark.asyncio
async def test_missing_remote_without_prior_snapshot_is_not_zero(db):
    item, *_ = await seed(db)
    client = Client(); client.missing = True
    value = await GithubWorkProgressService(Observer(), client).summary(db, item.id)
    assert value.publication.reason == "remote_unavailable" and value.publication.state == "unavailable"
    assert value.publication.published_sha is None and value.publication.unpublished_commits is None


@pytest.mark.asyncio
async def test_route_timeout_and_disposable_database_startup(db, monkeypatch):
    from app import database
    original_wait = asyncio.wait_for
    async def short_wait(operation, timeout): return await original_wait(operation, timeout=0.01)
    class Hanging:
        async def summary(self, *args): await asyncio.Event().wait()
    monkeypatch.setattr(api.asyncio, "wait_for", short_wait)
    monkeypatch.setattr(api, "github_work_progress_service", Hanging())
    app = FastAPI(); app.include_router(api.router)
    async def session(): yield db
    app.dependency_overrides[get_db] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/github-work-items/1/progress")
        assert response.status_code == 409 and response.json()["detail"] == "progress_observation_unavailable"
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(database, "engine", engine)
    await database.init_db()
    from sqlalchemy import inspect
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        assert "github_work_progress_snapshots" in tables
    await engine.dispose()
