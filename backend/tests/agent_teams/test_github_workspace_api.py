"""HTTP contract tests for GitHub workspace operations."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.api.v1.deps import mail_session
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import (
    AgentPaneBinding,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.github_app_auth_service import (
    GithubAppMintError,
    GithubAppMintRejected,
    GithubAppNotInstalled,
    GithubAppUnconfigured,
    github_app_auth_service,
)
from app.services.github_approval_service import (
    GithubApprovalError,
    github_approval_service,
)
from app.services.github_client import (
    GithubCommitSnapshot,
    GithubTreeEntry,
    github_client,
)
from app.services.github_workspace_service import (
    GithubWorkspaceCredentialRevokeError,
    GithubWorkspaceError,
    GithubWorkspaceResetError,
    github_workspace_service,
)
from app.utils.peer_process import PeerPane, PeerPaneResolution

OPERATOR_TOKEN = "test-operator-token-for-workspace-api"


@pytest.fixture(autouse=True)
def operator_token(monkeypatch):
    """Every guarded call in this file authenticates as the operator."""
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)


OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN}


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


@pytest.mark.asyncio
async def test_continuation_policy_is_operator_only_and_updates_all_fields(
    client, db, tmp_path
):
    _, scope = await _scope(db, tmp_path / "policy-repo")
    payload = {
        "continuation_enabled": True,
        "max_continuation_revisions": 4,
        "max_continuation_failed_heads": 6,
        "max_failed_heads_per_revision": 2,
        "max_scope_paths": 24,
        "max_scope_commands": 12,
    }

    refused = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/continuation-policy",
        json=payload,
    )
    updated = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/continuation-policy",
        headers=OPERATOR_HEADERS,
        json=payload,
    )

    assert refused.status_code == 401
    assert refused.json()["detail"] == "operator_token_required"
    assert updated.status_code == 200
    assert {
        key: updated.json()[key]
        for key in payload
    } == payload
    await db.refresh(scope)
    assert scope.continuation_enabled is True


@pytest.mark.asyncio
async def test_generic_scope_patch_cannot_enable_continuation(client, db, tmp_path):
    _, scope = await _scope(db, tmp_path / "generic-policy-repo")

    response = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope.id}",
        json={"continuation_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["continuation_enabled"] is False
    await db.refresh(scope)
    assert scope.continuation_enabled is False


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
    leased_at = datetime.utcnow() - timedelta(seconds=90)
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(path),
        leased_item_id=item.id,
        leased_at=leased_at,
        lease_token=token,
    )
    db.add(workspace)
    await db.commit()
    return item, workspace, leased_at


async def _slot(db, preset, position, *, enabled=True):
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=position,
        display_name=f"Slot {position}",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        launch_mode="plain",
        launch_options={},
        enabled=enabled,
    )
    db.add(slot)
    await db.flush()
    return slot


async def _continuation_proposal_context(db, tmp_path):
    preset, scope = await _scope(db, tmp_path / "continuation-proposal-repo")
    scope.continuation_enabled = True
    scope.github_auth_mode = "ambient"
    leader_slot = await _slot(db, preset, 0)
    owner_slot = await _slot(db, preset, 1)
    leader = MailTeamMember(
        identity_key=f"leader:{leader_slot.id}",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Leader",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=leader_slot.id,
    )
    owner = MailTeamMember(
        identity_key=f"owner:{owner_slot.id}",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=owner_slot.id,
    )
    db.add_all([leader, owner])
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=73,
        issue_title="Continue safely",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        issue_type="code",
        dispatch_status="escalated",
        escalation_reason="retry_count_exhausted",
        owner_slot_id=owner_slot.id,
        dispatch_nonce="continuation-nonce",
        approval_round_count=2,
        pr_number=42,
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "continuation-proposal-worktree"),
        leased_item_id=item.id,
        leased_at=datetime.utcnow(),
        lease_token="lease-secret",
    )
    db.add(workspace)
    await db.commit()
    return scope, item, workspace, owner_slot, owner


def _continuation_proposal_kwargs(item, owner_slot, owner):
    return {
        "authenticated_owner_member_id": owner.id,
        "authenticated_owner_slot_id": owner_slot.id,
        "dispatch_nonce": item.dispatch_nonce,
        "phase": "implementation",
        "execution_target": "workspace",
        "summary": " Apply one bounded correction ",
        "allowed_paths": ["src/z.py", "src/a.py", "src/z.py"],
        "allowed_actions": [
            "request_verification",
            "edit_production",
            "edit_production",
        ],
        "allowed_commands": ["pytest -q", "git diff --check", "pytest -q"],
        "prohibited_actions": ["Do not edit CI", "Do not edit CI"],
        "max_failed_heads": 2,
        "tool_fallbacks": {},
        "lease_token": "lease-secret",
    }


def _stub_continuation_github(monkeypatch):
    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "head": {"sha": "a" * 40}}

    async def get_commit_snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="a" * 40, tree_sha="b" * 40)

    async def get_recursive_tree(*_args, **_kwargs):
        return [
            GithubTreeEntry(
                path="src/a.py",
                mode="100644",
                object_type="blob",
                sha="c" * 40,
            )
        ]

    monkeypatch.setattr(github_client, "get_pull", get_pull)
    monkeypatch.setattr(github_client, "get_commit_snapshot", get_commit_snapshot)
    monkeypatch.setattr(github_client, "get_recursive_tree", get_recursive_tree)


@pytest.mark.asyncio
async def test_continuation_proposal_persists_canonical_server_authority(
    db, tmp_path, monkeypatch
):
    scope, item, workspace, owner_slot, owner = await _continuation_proposal_context(
        db, tmp_path
    )
    _stub_continuation_github(monkeypatch)

    revision, approval, created = await github_approval_service.create_continuation_request(
        db,
        item,
        scope,
        **_continuation_proposal_kwargs(item, owner_slot, owner),
    )
    replay_revision, replay_approval, replay_created = (
        await github_approval_service.create_continuation_request(
            db,
            item,
            scope,
            **_continuation_proposal_kwargs(item, owner_slot, owner),
        )
    )

    assert created is True
    assert replay_created is False
    assert replay_revision.id == revision.id
    assert replay_approval.id == approval.id
    assert revision.revision == 1
    assert revision.allowed_paths == ["src/a.py", "src/z.py"]
    assert revision.allowed_actions == ["edit_production", "request_verification"]
    assert revision.allowed_commands == ["git diff --check", "pytest -q"]
    assert revision.summary == "Apply one bounded correction"
    assert revision.baseline_head_sha == "a" * 40
    assert revision.baseline_tree_sha == "b" * 40
    assert revision.expected_workspace_id == workspace.id
    assert revision.expected_lease_token_hash != workspace.lease_token
    assert github_approval_service.lease_token_matches(
        "lease-secret", revision.expected_lease_token_hash
    )
    assert approval.request_kind == "continuation"
    assert approval.scope_revision_id == revision.id
    assert revision.approval_request_id == approval.id
    assert (
        await db.scalar(select(func.count()).select_from(GithubAttemptScopeRevision))
    ) == 1
    assert (
        await db.scalar(select(func.count()).select_from(GithubApprovalRequest))
    ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "detail"),
    [
        ({"phase": "diagnostic"}, "diagnostic_continuation_not_available"),
        ({"allowed_paths": ["src/**"]}, "allowed_paths_invalid"),
        ({"allowed_actions": ["run_anything"]}, "allowed_actions_invalid"),
        ({"lease_token": "wrong"}, "lease_token_mismatch"),
    ],
)
async def test_continuation_proposal_rejects_unbounded_or_stale_authority(
    db, tmp_path, monkeypatch, override, detail
):
    scope, item, _workspace, owner_slot, owner = await _continuation_proposal_context(
        db, tmp_path
    )
    _stub_continuation_github(monkeypatch)
    payload = _continuation_proposal_kwargs(item, owner_slot, owner)
    payload.update(override)

    with pytest.raises(GithubApprovalError, match=detail) as exc_info:
        await github_approval_service.create_continuation_request(
            db,
            item,
            scope,
            **payload,
        )

    assert exc_info.value.detail == detail
    assert (
        await db.scalar(select(func.count()).select_from(GithubAttemptScopeRevision))
    ) == 0


@pytest.mark.asyncio
async def test_continuation_proposal_guard_rejects_database_current_non_escalated_item(
    db, tmp_path, monkeypatch
):
    scope, item, _workspace, owner_slot, owner = await _continuation_proposal_context(
        db, tmp_path
    )
    _stub_continuation_github(monkeypatch)

    async def transition_during_snapshot(*_args, **_kwargs):
        await db.execute(
            update(GithubWorkItem)
            .where(GithubWorkItem.id == item.id)
            .values(dispatch_status="ready_for_review")
            .execution_options(synchronize_session=False)
        )
        return []

    monkeypatch.setattr(github_client, "get_recursive_tree", transition_during_snapshot)

    with pytest.raises(GithubApprovalError, match="stale_continuation_context"):
        await github_approval_service.create_continuation_request(
            db,
            item,
            scope,
            **_continuation_proposal_kwargs(item, owner_slot, owner),
        )

    assert (
        await db.scalar(select(func.count()).select_from(GithubAttemptScopeRevision))
    ) == 0
    assert (
        await db.scalar(select(func.count()).select_from(GithubApprovalRequest))
    ) == 0


@pytest.mark.asyncio
async def test_operator_lists_and_cancels_continuation_without_secret_projection(
    client, db, tmp_path, monkeypatch
):
    scope, item, _workspace, owner_slot, owner = await _continuation_proposal_context(
        db, tmp_path
    )
    _stub_continuation_github(monkeypatch)
    revision, approval, _created = (
        await github_approval_service.create_continuation_request(
            db,
            item,
            scope,
            **_continuation_proposal_kwargs(item, owner_slot, owner),
        )
    )
    root = MailMessage(
        kind="context_request",
        sender_member_id=approval.owner_member_id,
        recipient_member_id=approval.leader_member_id,
        subject="Continuation",
        body_markdown=revision.summary,
        payload=github_approval_service.continuation_request_payload(
            approval,
            revision,
        ),
        request_status="pending",
        delivery_key=f"github-approval:{approval.id}:request",
    )
    db.add(root)
    await db.flush()
    approval.request_message_id = root.id
    await db.commit()

    unauthenticated = await client.get(
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions"
    )
    listed = await client.get(
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions",
        headers=OPERATOR_HEADERS,
    )
    cancelled = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests/"
        f"{approval.id}/cancel",
        headers=OPERATOR_HEADERS,
    )

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"] == "operator_token_required"
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "expected_lease_token_hash" not in listed.text
    assert "lease-secret" not in listed.text
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "superseded"
    await db.refresh(revision)
    await db.refresh(root)
    assert revision.status == "superseded"
    assert root.request_status == "superseded"


async def _credential_context(db, tmp_path):
    preset, scope = await _scope(db, tmp_path / "credential-repo")
    slot = await _slot(db, preset, 0)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=99,
        issue_title="credential",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slot.id,
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "credential-worktree"),
        leased_item_id=item.id,
        leased_at=datetime.utcnow(),
        lease_token="workspace-secret",
    )
    scope.github_auth_mode = "app"
    scope.github_app_installation_id = 55
    binding = AgentPaneBinding(
        pane_pid=4321,
        pane_proc_start="proc-start",
        slot_id=slot.id,
        preset_id=preset.id,
        tmux_target="team:0.0",
    )
    db.add_all([workspace, binding])
    await db.commit()
    return preset, scope, slot, item, workspace


def _credential_resolution(start="proc-start"):
    pane = PeerPane(
        pane_pid=4321,
        pane_proc_start=start,
        tmux_target="team:0.0",
        peer_pid=5000,
    )
    return PeerPaneResolution(pane, (5000, 4321), "resolved", 16)


@pytest.mark.asyncio
async def test_git_credential_mints_only_for_kernel_derived_owner(
    client, db, tmp_path, monkeypatch
):
    _, scope, _, _, workspace = await _credential_context(db, tmp_path)
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution(),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )
    calls = []

    async def mint(installation_id, owner, repo, **kwargs):
        calls.append((installation_id, owner, repo, kwargs))
        return "installation-secret"

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", mint)
    monkeypatch.setattr(
        github_app_auth_service,
        "cached_repository_token_expiry",
        lambda *_args, **_kwargs: datetime.now(timezone.utc) + timedelta(hours=1),
    )

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "workspace_token": "workspace-secret",
            "protocol": "https",
            "host": "github.com",
            "path": f"owner/{scope.repo_name}.git",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "username": "x-access-token",
        "password": "installation-secret",
    }
    assert calls == [
        (
            55,
            "owner",
            scope.repo_name,
            {
                "purpose": "push",
                "cache_subject": "workspace:1:lease:workspace-secret:slot:1",
            },
        )
    ]
    assert response.headers["cache-control"] == "no-store"
    await db.refresh(workspace)
    assert workspace.push_token_expires_at is not None
    assert workspace.push_token_expires_at > datetime.utcnow()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "status", "detail"),
    [
        ({"path": None}, 400, "credential_path_required"),
        ({"protocol": "ssh"}, 403, "credential_target_refused"),
        ({"host": "example.com"}, 403, "credential_target_refused"),
        ({"workspace_token": "stale"}, 403, "workspace_lease_not_current"),
    ],
)
async def test_git_credential_refuses_invalid_target_before_mint(
    client, db, tmp_path, monkeypatch, updates, status, detail
):
    _, scope, _, _, _ = await _credential_context(db, tmp_path)
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution(),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def unexpected_mint(*_args):
        raise AssertionError("mint must not run")

    monkeypatch.setattr(
        github_app_auth_service, "mint_repository_token", unexpected_mint
    )
    payload = {
        "workspace_token": "workspace-secret",
        "protocol": "https",
        "host": "github.com",
        "path": f"owner/{scope.repo_name}.git",
    }
    payload.update(updates)

    response = await client.post(
        "/api/v1/agent-teams/git-credential", json=payload
    )

    assert response.status_code == status
    assert response.json()["detail"] == detail


@pytest.mark.asyncio
async def test_git_credential_repo_mismatch_names_both_repositories(
    client, db, tmp_path, monkeypatch
):
    _, scope, _, _, _ = await _credential_context(db, tmp_path)
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pane resolution must follow repo authorization")
        ),
    )

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "workspace_token": "workspace-secret",
            "protocol": "https",
            "host": "github.com",
            "path": "other/repository.git",
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "credential_repo_mismatch"
    assert "other/repository" in detail["message"]
    assert f"owner/{scope.repo_name}" in detail["message"]


@pytest.mark.asyncio
async def test_git_credential_missing_token_refuses_before_pane_walk(
    client, db, tmp_path, monkeypatch
):
    _, scope, _, _, _ = await _credential_context(db, tmp_path)
    called = False

    def resolve(*_args, **_kwargs):
        nonlocal called
        called = True
        return _credential_resolution()

    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed", resolve
    )

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "protocol": "https",
            "host": "github.com",
            "path": f"owner/{scope.repo_name}.git",
        },
    )

    assert response.status_code == 422
    assert called is False


@pytest.mark.asyncio
async def test_git_credential_non_loopback_refuses_before_database_or_mint(
    db, tmp_path, monkeypatch
):
    _, scope, _, _, _ = await _credential_context(db, tmp_path)
    calls = []

    async def _override():
        calls.append("db")
        yield db

    app.dependency_overrides[get_db] = _override
    monkeypatch.setattr(
        github_app_auth_service,
        "mint_repository_token",
        lambda *_args: (_ for _ in ()).throw(AssertionError("mint must not run")),
    )
    transport = httpx.ASGITransport(app=app, client=("10.0.0.2", 32100))
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as remote:
            response = await remote.post(
                "/api/v1/agent-teams/git-credential",
                json={
                    "workspace_token": "workspace-secret",
                    "protocol": "https",
                    "host": "github.com",
                    "path": f"owner/{scope.repo_name}.git",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "loopback_required"
    assert calls == ["db"]


@pytest.mark.asyncio
async def test_git_credential_requires_full_pane_identity(
    client, db, tmp_path, monkeypatch
):
    _, scope, _, _, _ = await _credential_context(db, tmp_path)
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution("reused-pid"),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "workspace_token": "workspace-secret",
            "protocol": "https",
            "host": "github.com",
            "path": f"owner/{scope.repo_name}.git",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_item_owner"


@pytest.mark.asyncio
async def test_git_credential_rechecks_owner_after_mint(
    client, db, tmp_path, monkeypatch
):
    preset, scope, _, item, _ = await _credential_context(db, tmp_path)
    replacement = await _slot(db, preset, 1)
    await db.commit()
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution(),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def mint(*_args, **_kwargs):
        item.owner_slot_id = replacement.id
        await db.commit()
        return "must-not-escape"

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", mint)

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "workspace_token": "workspace-secret",
            "protocol": "https",
            "host": "github.com",
            "path": f"owner/{scope.repo_name}.git",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_item_owner"
    assert "must-not-escape" not in response.text


@pytest.mark.asyncio
async def test_git_credential_distinguishes_stale_app_and_missing_config(
    client, db, tmp_path, monkeypatch
):
    _, scope, _, item, workspace = await _credential_context(db, tmp_path)
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution(),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: (_ for _ in ()).throw(GithubAppUnconfigured()),
    )
    payload = {
        "workspace_token": "workspace-secret",
        "protocol": "https",
        "host": "github.com",
        "path": f"owner/{scope.repo_name}.git",
    }

    unconfigured = await client.post(
        "/api/v1/agent-teams/git-credential", json=payload
    )
    assert unconfigured.status_code == 503
    assert unconfigured.json()["detail"] == "app_auth_unconfigured"

    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def gone(*_args, **_kwargs):
        raise GithubAppNotInstalled("owner", scope.repo_name, 55)

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", gone)
    not_installed = await client.post(
        "/api/v1/agent-teams/git-credential", json=payload
    )
    assert not_installed.status_code == 409
    assert not_installed.json()["detail"] == "app_not_installed"
    await db.refresh(scope)
    assert scope.github_auth_mode == "app"
    assert scope.github_app_installation_id == 55
    await db.refresh(workspace)
    assert workspace.push_token_expires_at is None

    async def config_runner(_args):
        return 0, ""

    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    assert await github_workspace_service.release(db, item.id) is True


@pytest.mark.asyncio
async def test_failed_credential_refresh_preserves_an_existing_token_quarantine(
    client, db, tmp_path, monkeypatch
):
    _, scope, _, item, workspace = await _credential_context(db, tmp_path)
    previous_expiry = datetime.utcnow() + timedelta(minutes=20)
    workspace.push_token_expires_at = previous_expiry
    await db.commit()
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution(),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "cached_repository_token_expiry",
        lambda *_args, **_kwargs: previous_expiry.replace(tzinfo=timezone.utc),
    )

    async def gone(*_args, **_kwargs):
        raise GithubAppNotInstalled("owner", scope.repo_name, 55)

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", gone)

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "workspace_token": "workspace-secret",
            "protocol": "https",
            "host": "github.com",
            "path": f"owner/{scope.repo_name}.git",
        },
    )

    assert response.status_code == 409
    await db.refresh(workspace)
    assert workspace.push_token_expires_at >= previous_expiry

    async def cache_miss(*_args, **_kwargs):
        return False

    async def config_runner(_args):
        return 0, ""

    monkeypatch.setattr(
        github_app_auth_service,
        "revoke_cached_repository_token",
        cache_miss,
    )
    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    with pytest.raises(GithubWorkspaceCredentialRevokeError):
        await github_workspace_service.release(db, item.id)


@pytest.mark.asyncio
async def test_definitive_mint_rejection_does_not_quarantine_a_first_request(
    client, db, tmp_path, monkeypatch
):
    _, scope, _, item, workspace = await _credential_context(db, tmp_path)
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution(),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def rejected(*_args, **_kwargs):
        raise GithubAppMintRejected("owner", scope.repo_name)

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", rejected)

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "workspace_token": "workspace-secret",
            "protocol": "https",
            "host": "github.com",
            "path": f"owner/{scope.repo_name}.git",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "app_token_mint_failed"
    await db.refresh(workspace)
    assert workspace.push_token_expires_at is None

    async def config_runner(_args):
        return 0, ""

    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    assert await github_workspace_service.release(db, item.id) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("with_previous_token", [False, True])
async def test_ambiguous_mint_failure_keeps_the_workspace_quarantined(
    client, db, tmp_path, monkeypatch, with_previous_token
):
    _, scope, _, item, workspace = await _credential_context(db, tmp_path)
    if with_previous_token:
        workspace.push_token_expires_at = datetime.utcnow() + timedelta(minutes=20)
        await db.commit()
    monkeypatch.setattr(
        "app.api.v1.agent_teams.resolve_request_pane_detailed",
        lambda *_args, **_kwargs: _credential_resolution(),
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def ambiguous(*_args, **_kwargs):
        raise GithubAppMintError("owner", scope.repo_name)

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", ambiguous)

    response = await client.post(
        "/api/v1/agent-teams/git-credential",
        json={
            "workspace_token": "workspace-secret",
            "protocol": "https",
            "host": "github.com",
            "path": f"owner/{scope.repo_name}.git",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "app_token_mint_failed"
    await db.refresh(workspace)
    assert workspace.push_token_expires_at > datetime.utcnow()

    async def cache_miss(*_args, **_kwargs):
        return False

    async def config_runner(_args):
        return 0, ""

    monkeypatch.setattr(
        github_app_auth_service,
        "revoke_cached_repository_token",
        cache_miss,
    )
    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    with pytest.raises(GithubWorkspaceCredentialRevokeError):
        await github_workspace_service.release(db, item.id)


@pytest.mark.asyncio
async def test_resume_prepared_attempt_requires_operator_and_preserves_identity(
    client, db, tmp_path
):
    preset, scope = await _scope(db, tmp_path / "resume-repo")
    owner = await _slot(db, preset, 0)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=70,
        issue_title="resume",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="prepared_owner_unavailable",
        owner_slot_id=owner.id,
        routing_method="label",
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref=f"deck/slot-{owner.id}/issue-70-0123456789abcdef",
        dispatch_base_ref="origin/master",
        approval_round_count=2,
        last_verified_sha="abc123",
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "resume-worktree"),
        leased_item_id=item.id,
        lease_token="lease-kept",
    )
    db.add(workspace)
    await db.commit()
    url = (
        f"/api/v1/agent-teams/presets/{preset.id}/work-items/"
        f"{item.id}/resume-attempt"
    )

    unauthorized = await client.post(url, json={"resume": True})
    assert unauthorized.status_code == 401
    response = await client.post(
        url,
        json={"resume": True},
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    await db.refresh(item)
    await db.refresh(workspace)
    assert item.dispatch_status == "pending"
    assert item.escalation_reason is None
    assert item.owner_slot_id == owner.id
    assert item.routing_method == "label"
    assert item.dispatch_nonce == "0123456789abcdef"
    assert item.dispatch_head_ref.endswith("0123456789abcdef")
    assert item.approval_round_count == 2
    assert item.last_verified_sha == "abc123"
    assert workspace.lease_token == "lease-kept"


@pytest.mark.asyncio
async def test_resume_reassignment_refuses_unknown_previous_owner_liveness(
    client, db, tmp_path
):
    preset, scope = await _scope(db, tmp_path / "reassign-repo")
    owner = await _slot(db, preset, 0, enabled=False)
    target = await _slot(db, preset, 1)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=71,
        issue_title="reassign",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="prepared_owner_unavailable",
        owner_slot_id=owner.id,
        routing_method="label",
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref=f"deck/slot-{owner.id}/issue-71-0123456789abcdef",
        dispatch_base_ref="origin/master",
        approval_round_count=1,
    )
    db.add(item)
    await db.flush()
    db.add(
        GithubWorkspace(
            scope_id=scope.id,
            path=str(tmp_path / "reassign-worktree"),
            leased_item_id=item.id,
            lease_token="lease-kept",
        )
    )
    await db.commit()

    response = await client.post(
        f"/api/v1/agent-teams/presets/{preset.id}/work-items/"
        f"{item.id}/resume-attempt",
        json={"resume": True, "reassign_to_slot_id": target.id},
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == (
        "previous_owner_liveness_unknown"
    )
    assert item.dispatch_status == "escalated"
    assert item.owner_slot_id == owner.id


@pytest.mark.asyncio
async def test_owner_claims_persisted_continuation_with_no_store(
    client, db, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    preset, scope = await _scope(db, tmp_path / "continuation-repo")
    leader = await _slot(db, preset, 0)
    owner = await _slot(db, preset, 1)
    leader_member = MailTeamMember(
        identity_key=f"leader:{leader.id}",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Leader",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=leader.id,
    )
    owner_member = MailTeamMember(
        identity_key=f"owner:{owner.id}",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=owner.id,
    )
    db.add_all([leader_member, owner_member])
    await db.flush()
    session = MailAgentSession(
        member_id=owner_member.id,
        provider="codex-cli",
        source="mcp",
        session_key="mcp:continuation",
        cwd="/tmp/r",
        team_preset_id=preset.id,
        team_slot_id=owner.id,
        mailbox_status="connected",
        last_seen_at=datetime.utcnow(),
        bound_pane_pid=4321,
        bound_pane_proc_start="9876",
    )
    db.add(session)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=72,
        issue_title="continue",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        issue_type="code",
        dispatch_status="dispatched",
        owner_slot_id=owner.id,
        routing_method="reassigned",
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref=f"deck/slot-{owner.id}/issue-72-0123456789abcdef",
        approval_round_count=2,
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "continuation-worktree"),
        leased_item_id=item.id,
        lease_token="lease-secret",
    )
    db.add(workspace)
    await db.commit()

    async def authenticated_session():
        return session

    app.dependency_overrides[mail_session] = authenticated_session
    response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/claim-continuation"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["dispatch_nonce"] == item.dispatch_nonce
    assert body["dispatch_head_ref"] == item.dispatch_head_ref
    assert body["approval_round_count"] == 2
    assert body["workspace_path"] == workspace.path
    assert body["lease_token"] == "lease-secret"
    assert body["leader_member_id"] == leader_member.id
    assert "lease-secret" not in item.status_note if item.status_note else True
    await db.refresh(workspace)
    assert workspace.leased_owner_pid == 4321
    assert workspace.leased_owner_proc_start == "9876"
    assert workspace.lease_last_owner_contact_at is not None


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
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    rows = response.json()["workspaces"]
    assert [row["lease_state"] for row in rows] == [
        "available",
        "leased",
        "disabled",
        "disabled_for_dispatch",
    ]
    assert all("lease_token" not in row for row in rows)
    assert rows[0]["lease_last_owner_contact_at"] is None
    assert rows[0]["lease_release_reminded_at"] is None
    assert rows[0]["lease_age_seconds"] is None
    assert rows[1]["lease_last_owner_contact_at"] is not None
    assert rows[1]["lease_release_reminded_at"] is not None
    assert 89 <= rows[1]["lease_age_seconds"] < 120
    missing = await client.get(
        "/api/v1/agent-teams/github-scopes/999999/workspaces",
        headers=OPERATOR_HEADERS,
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_force_release_with_matching_acquisition(client, db, tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    item, workspace, leased_at = await _leased_workspace(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", ApiGitRunner(repo_path))

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "force": True,
            "expected_leased_at": leased_at.isoformat(),
            "reason": "owner is unavailable",
            "requested_by": "operator",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["released_item_id"] == item.id
    assert body["workspace"]["leased_item_id"] is None
    assert "lease_token" not in body["workspace"]
    await db.refresh(workspace)
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_force_release_refusal_names_no_lease_token(
    client, db, tmp_path, monkeypatch
):
    """The old version asserted the 409 echoed both tokens; that was the leak."""
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    item, workspace, _ = await _leased_workspace(db, scope, tmp_path / "ws")
    item_id = item.id
    monkeypatch.setattr(github_workspace_service, "_runner", ApiGitRunner(repo_path))

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "force": True,
            "expected_leased_at": "2020-01-01T00:00:00",
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert "lease-current" not in response.text
    await db.refresh(workspace)
    assert workspace.leased_item_id == item_id


@pytest.mark.asyncio
async def test_force_release_reports_dirty_paths_and_proceeds(
    client, db, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    _, workspace, leased_at = await _leased_workspace(db, scope, tmp_path / "ws")
    runner = ApiGitRunner(repo_path)
    runner.status_output = " M src/foo.c\n?? scratch.txt\n"
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "force": True,
            "expected_leased_at": leased_at.isoformat(),
            "reason": "discard abandoned changes",
        },
        headers=OPERATOR_HEADERS,
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
            "force": True,
            "expected_leased_at": "2026-08-08T12:00:00",
            "reason": "nothing owns it",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "workspace_not_leased"


@pytest.mark.asyncio
async def test_force_release_reports_clean_unpushed_commits(
    client, db, tmp_path, monkeypatch
):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    _, workspace, leased_at = await _leased_workspace(db, scope, tmp_path / "ws")
    runner = ApiGitRunner(repo_path)
    runner.rev_count = "3"
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "force": True,
            "expected_leased_at": leased_at.isoformat(),
            "reason": "discard abandoned commits",
        },
        headers=OPERATOR_HEADERS,
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
        {"force": True, "expected_leased_at": "2026-08-08T12:00:00"},
        {"force": True, "reason": "missing the acquisition"},
    ],
    ids=["no_reason", "no_expected_leased_at"],
)
async def test_force_release_requires_reason_and_acquisition(client, db, tmp_path, body):
    _, scope = await _scope(db, tmp_path / "repo")
    _, workspace, _ = await _leased_workspace(db, scope, tmp_path / "ws")

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json=body,
        headers=OPERATOR_HEADERS,
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
async def test_create_workspace_rejects_path_outside_scope_checkout_parent(
    client, db, tmp_path, monkeypatch
):
    repo_path = tmp_path / "pool" / "repo"
    repo_path.parent.mkdir()
    _, scope = await _scope(db, repo_path)
    runner = ApiGitRunner(repo_path)
    monkeypatch.setattr(github_workspace_service, "_runner", runner)

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces",
        json={"path": str(tmp_path / "outside"), "kind": "worktree"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "workspace_path_outside_root"
    assert runner.calls == []


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
