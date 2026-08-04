"""HTTP contract tests for GitHub workspace operations."""
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_workspace_service import (
    GithubWorkspaceError,
    GithubWorkspaceResetError,
    github_workspace_service,
)


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _scope(db, repo_path: Path):
    repo_path.mkdir(exist_ok=True)
    (repo_path / "tracked").write_text("x")
    preset = AgentTeamPreset(name=f"Workspace {repo_path.name}", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name=repo_path.name,
        repo_path=str(repo_path),
    )
    db.add(scope)
    await db.commit()
    return preset, scope


class ApiGitRunner:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.calls: list[list[str]] = []
        self.status_output = ""
        self.rev_count = "0"
        self.worktree_add_error: str | None = None

    async def __call__(self, args: list[str]):
        self.calls.append(args)
        path = Path(args[1])
        command = args[2]
        common = self.repo_path / ".git"
        if command == "rev-parse":
            linked = path != self.repo_path
            git_dir = common / "worktrees" / path.name if linked else common
            return 0, f"{git_dir}\n{common}\n{path}\n"
        if command == "status":
            return 0, self.status_output
        if command == "rev-list":
            return 0, f"{self.rev_count}\n"
        if command == "worktree" and self.worktree_add_error:
            return 128, self.worktree_add_error
        return 0, ""


@pytest.fixture
def no_live_sessions(monkeypatch):
    monkeypatch.setattr(
        "app.services.github_workspace_service.discover_agent_sessions", lambda: []
    )


async def _leased_workspace(db, scope, path: Path, *, token="lease-current"):
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(path),
        leased_item_id=item.id,
        leased_at=datetime.utcnow() - timedelta(seconds=90),
        lease_token=token,
    )
    db.add(workspace)
    await db.commit()
    return item, workspace


@pytest.mark.asyncio
async def test_list_workspaces_derives_all_lease_states(client, db, tmp_path):
    _, scope = await _scope(db, tmp_path / "repo")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    leased_at = datetime.utcnow() - timedelta(seconds=90)
    owner_contact = datetime.utcnow() - timedelta(seconds=20)
    reminded_at = datetime.utcnow() - timedelta(seconds=10)
    db.add_all(
        [
            GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "available")),
            GithubWorkspace(
                scope_id=scope.id,
                path=str(tmp_path / "leased"),
                leased_item_id=item.id,
                leased_at=leased_at,
                lease_token="lease-visible",
                lease_last_owner_contact_at=owner_contact,
                lease_release_reminded_at=reminded_at,
            ),
            GithubWorkspace(
                scope_id=scope.id,
                path=str(tmp_path / "disabled"),
                enabled=False,
            ),
            GithubWorkspace(
                scope_id=scope.id,
                path=str(tmp_path / "reserved"),
                dispatchable=False,
            ),
        ]
    )
    await db.commit()

    response = await client.get(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces"
    )

    assert response.status_code == 200
    rows = response.json()["workspaces"]
    assert [row["lease_state"] for row in rows] == [
        "available",
        "leased",
        "disabled",
        "disabled_for_dispatch",
    ]
    assert rows[0]["lease_token"] is None
    assert rows[0]["lease_last_owner_contact_at"] is None
    assert rows[0]["lease_release_reminded_at"] is None
    assert rows[0]["lease_age_seconds"] is None
    assert rows[1]["lease_token"] == "lease-visible"
    assert rows[1]["lease_last_owner_contact_at"] is not None
    assert rows[1]["lease_release_reminded_at"] is not None
    assert 89 <= rows[1]["lease_age_seconds"] < 120
    missing = await client.get("/api/v1/agent-teams/github-scopes/999999/workspaces")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_force_release_with_matching_token(client, db, tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    item, workspace = await _leased_workspace(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", ApiGitRunner(repo_path))

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "expected_lease_token": "lease-current",
            "reason": "owner is unavailable",
            "requested_by": "operator",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["released_item_id"] == item.id
    assert body["workspace"]["leased_item_id"] is None
    await db.refresh(workspace)
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_force_release_rejects_stale_token(client, db, tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    item, workspace = await _leased_workspace(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", ApiGitRunner(repo_path))

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "expected_lease_token": "lease-stale",
            "reason": "owner is unavailable",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "lease-stale" in detail["message"]
    assert "lease-current" in detail["message"]
    await db.refresh(workspace)
    assert workspace.leased_item_id == item.id


@pytest.mark.asyncio
async def test_force_release_reports_dirty_paths_and_proceeds(
    client, db, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    _, workspace = await _leased_workspace(db, scope, tmp_path / "ws")
    runner = ApiGitRunner(repo_path)
    runner.status_output = " M src/foo.c\n?? scratch.txt\n"
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "expected_lease_token": "lease-current",
            "reason": "discard abandoned changes",
        },
    )

    assert response.status_code == 200
    assert response.json()["discarded_paths"] == " M src/foo.c\n?? scratch.txt"
    await db.refresh(workspace)
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_force_release_rejects_unleased_workspace(client, db, tmp_path):
    _, scope = await _scope(db, tmp_path / "repo")
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "expected_lease_token": "lease-current",
            "reason": "nothing owns it",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "workspace_not_leased"


@pytest.mark.asyncio
async def test_force_release_reports_clean_unpushed_commits(
    client, db, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    _, workspace = await _leased_workspace(db, scope, tmp_path / "ws")
    runner = ApiGitRunner(repo_path)
    runner.rev_count = "3"
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "expected_lease_token": "lease-current",
            "reason": "discard abandoned commits",
        },
    )

    assert response.status_code == 200
    assert response.json()["discarded_paths"] is None
    assert response.json()["unpushed_commits"] == 3
    await db.refresh(workspace)
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"reason": "missing token"},
        {"expected_lease_token": "lease-current"},
    ],
)
async def test_force_release_requires_token_and_reason(client, db, tmp_path, body):
    _, scope = await _scope(db, tmp_path / "repo")
    _, workspace = await _leased_workspace(db, scope, tmp_path / "ws")

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json=body,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_workspace_provisions_and_honors_explicit_flags(
    client, db, tmp_path, monkeypatch, no_live_sessions
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    runner = ApiGitRunner(repo_path)
    monkeypatch.setattr(github_workspace_service, "_runner", runner)
    workspace_path = tmp_path / "ws"

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        json={
            "path": str(workspace_path),
            "kind": "worktree",
            "dispatchable": False,
            "enabled": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["dispatchable"] is False
    assert body["enabled"] is False
    assert [
        "-C", str(repo_path), "worktree", "add", "--detach",
        str(workspace_path), "origin/HEAD",
    ] in runner.calls


@pytest.mark.asyncio
async def test_create_primary_defaults_non_dispatchable_and_never_mutates_git(
    client, db, tmp_path, monkeypatch, no_live_sessions
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    runner = ApiGitRunner(repo_path)
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        json={"path": str(repo_path), "kind": "primary"},
    )

    assert response.status_code == 201
    assert response.json()["dispatchable"] is False
    assert all(call[2] == "rev-parse" for call in runner.calls)


@pytest.mark.asyncio
async def test_create_workspace_rejects_duplicate_before_git_mutation(
    client, db, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    missing_path = tmp_path / "missing-ws"
    db.add(GithubWorkspace(scope_id=scope.id, path=str(missing_path)))
    await db.commit()
    runner = ApiGitRunner(repo_path)
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        json={"path": str(missing_path), "kind": "worktree"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "workspace_path_registered"
    assert runner.calls == []


@pytest.mark.asyncio
async def test_create_workspace_rejects_invalid_kind(client, db, tmp_path):
    _, scope = await _scope(db, tmp_path / "repo")
    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        json={"path": str(tmp_path / "ws"), "kind": "Primary"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_workspace_failure_persists_no_row(
    client, db, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    runner = ApiGitRunner(repo_path)
    runner.worktree_add_error = "stale worktree registration"
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        json={"path": str(tmp_path / "ws"), "kind": "worktree"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "workspace_not_a_worktree"
    rows = (await db.execute(select(GithubWorkspace))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("block_code", "path_kind", "dispatchable"),
    [
        ("workspace_is_primary", "primary", True),
        ("workspace_dirty", "linked", True),
        ("workspace_occupied", "linked", True),
    ],
)
async def test_create_workspace_conflicts_include_machine_code(
    client,
    db,
    tmp_path,
    monkeypatch,
    block_code,
    path_kind,
    dispatchable,
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    candidate = repo_path if path_kind == "primary" else tmp_path / "ws"
    if candidate != repo_path:
        candidate.mkdir()
        (candidate / "tracked").write_text("x")
    runner = ApiGitRunner(repo_path)
    if block_code == "workspace_dirty":
        runner.status_output = "?? untracked\n"
    monkeypatch.setattr(github_workspace_service, "_runner", runner)
    sessions = (
        [{"cwd": str(candidate), "tmux_target": "deck:0.0"}]
        if block_code == "workspace_occupied"
        else []
    )
    monkeypatch.setattr(
        "app.services.github_workspace_service.discover_agent_sessions",
        lambda: sessions,
    )

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        json={
            "path": str(candidate),
            "kind": "worktree",
            "dispatchable": dispatchable,
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["block_code"] == block_code
    assert isinstance(detail["message"], str)


@pytest.mark.asyncio
async def test_reprobe_reenables_only_after_success(client, db, tmp_path, monkeypatch):
    _, scope = await _scope(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        enabled=False,
        provision_error="old",
    )
    db.add(workspace)
    await db.commit()

    async def succeeds(*_args):
        return None

    monkeypatch.setattr(github_workspace_service, "reset_workspace", succeeds)
    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/{workspace.id}/reprobe"
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["provision_error"] is None


@pytest.mark.asyncio
async def test_reprobe_failure_stays_disabled_with_block_code(
    client, db, tmp_path, monkeypatch
):
    _, scope = await _scope(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        enabled=False,
    )
    db.add(workspace)
    await db.commit()

    async def fails(_db, _scope, target):
        target.enabled = False
        target.provision_error = "still broken"
        raise GithubWorkspaceResetError("still broken", transient=False)

    monkeypatch.setattr(github_workspace_service, "reset_workspace", fails)
    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/{workspace.id}/reprobe"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "workspace_reset_failed"
    assert workspace.enabled is False


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["leased", "primary"])
async def test_reprobe_guard_runs_before_reset(client, db, tmp_path, monkeypatch, guard):
    _, scope = await _scope(db, tmp_path / "repo")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=2,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        kind="primary" if guard == "primary" else "worktree",
        leased_item_id=item.id if guard == "leased" else None,
        enabled=False,
    )
    db.add(workspace)
    await db.commit()
    called = False

    async def should_not_run(*_args):
        nonlocal called
        called = True

    monkeypatch.setattr(github_workspace_service, "reset_workspace", should_not_run)
    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/{workspace.id}/reprobe"
    )

    assert response.status_code == 409
    if guard == "leased":
        assert response.json()["detail"]["block_code"] == "workspace_leased"
    assert called is False


@pytest.mark.asyncio
async def test_abandon_changes_status_but_retains_workspace(client, db, tmp_path, monkeypatch):
    _, scope = await _scope(db, tmp_path / "repo")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=3,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="ready_for_review",
        pr_number=42,
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()
    monkeypatch.setattr(
        "app.services.github_dispatch_service.GithubDispatchService._send_escalation_broadcast",
        lambda *_args, **_kwargs: _async_none(),
    )

    response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/abandon",
        json={"reason": "PR will not proceed"},
    )

    assert response.status_code == 200
    assert response.json()["dispatch_status"] == "escalated"
    assert response.json()["escalation_reason"] == "abandoned_by_operator"
    assert workspace.leased_item_id == item.id


async def _async_none():
    return None


@pytest.mark.asyncio
async def test_abandon_terminal_item_returns_machine_code(client, db, tmp_path):
    _, scope = await _scope(db, tmp_path / "repo")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=4,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/abandon"
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["block_code"] == "work_item_not_abandonable"
    assert "message" in detail


@pytest.mark.asyncio
async def test_work_item_feed_outer_joins_workspace_path(client, db, tmp_path):
    preset, scope = await _scope(db, tmp_path / "repo")
    leased = GithubWorkItem(
        scope_id=scope.id,
        issue_number=5,
        issue_title="leased",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    unleased = GithubWorkItem(
        scope_id=scope.id,
        issue_number=6,
        issue_title="unleased",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add_all([leased, unleased])
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=leased.id,
    )
    db.add(workspace)
    await db.commit()

    response = await client.get(
        f"/api/v1/agent-teams/presets/{preset.id}/github-work-items"
    )

    assert response.status_code == 200
    rows = {row["issue_number"]: row for row in response.json()["items"]}
    assert rows[5]["workspace_path"] == str(tmp_path / "ws")
    assert rows[6]["workspace_path"] is None
