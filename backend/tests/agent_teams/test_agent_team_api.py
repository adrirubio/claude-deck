"""HTTP contract tests for Agent Team presets."""
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database import get_db
from app.api.v1.agent_teams import _scope_auth_configured
from app.config import settings
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.models.schemas import AgentTeamPresetCreate, AgentTeamSlotCreate
from app.services.agent_team_service import agent_team_service
from app.services.github_app_auth_service import github_app_auth_service


@pytest.mark.parametrize(
    ("mode", "token", "app_id", "key_path", "bot_login", "expected"),
    [
        ("unknown", "", "", "", "", False),
        ("unknown", "token", "", "", "", True),
        ("unknown", "token", "123", "", "", False),
        ("unknown", "token", "", "", "bot", True),
        ("unknown", "", "123", "/tmp/key.pem", "bot", True),
        ("ambient", "", "123", "/tmp/key.pem", "bot", False),
        ("ambient", "token", "", "", "", True),
        ("app", "token", "", "", "", False),
        ("app", "", "123", "/tmp/key.pem", "bot", True),
    ],
)
def test_scope_auth_configuration_is_truthful_for_selected_mode(
    monkeypatch, mode, token, app_id, key_path, bot_login, expected
):
    monkeypatch.setattr(settings, "github_token", token)
    monkeypatch.setattr(settings, "github_app_id", app_id)
    monkeypatch.setattr(settings, "github_app_private_key_path", key_path)
    monkeypatch.setattr(settings, "github_app_bot_login", bot_login)
    assert _scope_auth_configured(SimpleNamespace(github_auth_mode=mode)) is expected


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "agent-team-api-test-operator-token")
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Deck-Operator-Token": "agent-team-api-test-operator-token"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_real_process_boundaries(monkeypatch):
    async def fake_install_status():
        return SimpleNamespace(
            claude_code_mcp_installed=True,
            claude_code_hooks_missing=[],
            codex_cli_available=True,
            codex_mcp_installed=True,
            codex_hooks_missing=[],
        )

    async def fake_sync_observed_sessions(_db):
        return None

    provider = SimpleNamespace(
        display_name="Codex",
        get_status=lambda: {"installed": True},
        build_spawn_command=lambda options: ["codex", "--cd", options.directory],
    )
    monkeypatch.setattr("app.services.agent_team_service.get_provider", lambda _provider_id: provider)
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_install_service.get_install_status",
        fake_install_status,
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_service.sync_observed_sessions",
        fake_sync_observed_sessions,
    )
    monkeypatch.setattr("app.services.agent_team_service.discover_agent_sessions", lambda: [])


@pytest.mark.asyncio
async def test_launch_conflict_returns_updated_plan(client, db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="API team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Dev agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    plan_response = await client.post(f"/api/v1/agent-teams/presets/{preset.id}/plan-launch", json={})
    assert plan_response.status_code == 200
    old_hash = plan_response.json()["plan_hash"]

    await agent_team_service.update_preset(db, preset.id, name="API team updated")
    launch_response = await client.post(
        f"/api/v1/agent-teams/presets/{preset.id}/launch",
        json={"confirm_plan_hash": old_hash},
    )

    assert launch_response.status_code == 409
    detail = launch_response.json()["detail"]
    assert detail["message"] == "Launch plan changed; review the latest plan before launching"
    assert detail["plan"]["plan_hash"] != old_hash


@pytest.mark.asyncio
async def test_create_preset_validation_error_includes_block_code(client, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    response = await client.post(
        "/api/v1/agent-teams/presets",
        json={
            "name": "Invalid effort team",
            "slots": [
                {
                    "display_name": "Architect",
                    "provider": "opencode-cli",
                    "repo_path": str(repo),
                    "launch_options": {"reasoning_effort": "xhigh"},
                }
            ],
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == "opencode-cli does not support reasoning_effort"
    assert detail["block_code"] == "reasoning_effort_unsupported"


@pytest.mark.asyncio
async def test_preset_autonomy_and_slot_routing_fields_round_trip(client, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sync_calls = 0

    async def fake_sync(_db):
        nonlocal sync_calls
        sync_calls += 1

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)

    response = await client.post(
        "/api/v1/agent-teams/presets",
        json={
            "name": "Autonomy team",
            "slots": [
                {
                    "display_name": "Backend SME",
                    "provider": "codex-cli",
                    "repo_path": str(repo),
                    "area_labels": ["area:backend", "area:api", "area:backend"],
                    "expertise": "Owns the API",
                }
            ],
        },
    )
    assert response.status_code == 200
    preset = response.json()
    assert preset["autonomy_enabled"] is False
    slot = preset["slots"][0]
    assert slot["area_labels"] == ["area:backend", "area:api"]
    assert slot["expertise"] == "Owns the API"

    leader = await client.put(
        f"/api/v1/agent-teams/presets/{preset['id']}/leader",
        json={
            "leader_slot_id": slot["id"],
            "expected_leader_slot_id": None,
            "expected_updated_at": preset["updated_at"],
            "reason": "Assign the fixture Leader before activation.",
        },
    )
    assert leader.status_code == 200

    response = await client.patch(
        f"/api/v1/agent-teams/presets/{preset['id']}",
        json={"autonomy_enabled": True},
    )
    assert response.status_code == 200
    assert response.json()["autonomy_enabled"] is True
    assert sync_calls == 1

    response = await client.patch(
        f"/api/v1/agent-teams/slots/{slot['id']}",
        json={"area_labels": ["area:frontend"], "expertise": "Owns UI"},
    )
    assert response.status_code == 200
    updated_slot = response.json()["slots"][0]
    assert updated_slot["area_labels"] == ["area:frontend"]
    assert updated_slot["expertise"] == "Owns UI"


@pytest.mark.asyncio
async def test_github_scope_crud_endpoints(client, db, monkeypatch, tmp_path):
    await db.execute(text("PRAGMA foreign_keys=ON"))
    assert (await db.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    repo = tmp_path / "repo"
    repo.mkdir()
    sync_calls = 0

    async def fake_sync(_db):
        nonlocal sync_calls
        sync_calls += 1

    async def resolve_installation(_owner, _repo):
        return 73

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    monkeypatch.setattr(github_app_auth_service, "require_configuration", lambda **_kwargs: None)
    monkeypatch.setattr(github_app_auth_service, "resolve_installation", resolve_installation)

    preset_response = await client.post(
        "/api/v1/agent-teams/presets",
        json={"name": "Scope team", "slots": []},
    )
    preset_id = preset_response.json()["id"]

    create_response = await client.post(
        f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
        json={
            "repo_owner": "adrirubio",
            "repo_name": "snazzyemail",
            "repo_path": str(repo),
            "dispatch_label": "deck-ready",
            "design_label": "deck-design",
            "merge_policy": "auto",
            "max_approval_rounds": 4,
            "max_concurrent_dispatched": 2,
            "max_verification_retries": 3,
            "max_auto_merges_per_day": 1,
            "base_ref": "origin/main",
            "github_auth_mode": "app",
            "builds_out_of_tree": True,
            "build_dir_template": "build-{issue_number}",
            "build_command_hint": "meson compile -C {build_dir} -j{parallelism}",
            "max_build_parallelism": 3,
            "enabled": True,
        },
    )
    assert create_response.status_code == 200
    scope = create_response.json()
    assert scope["repo_owner"] == "adrirubio"
    assert scope["merge_policy"] == "auto"
    assert scope["github_auth_mode"] == "app"
    assert (await db.get(TeamGithubScope, scope["id"])).github_app_installation_id == 73
    assert isinstance(scope["github_poll_token_configured"], bool)
    assert scope["max_verification_retries"] == 3
    assert scope["base_ref"] == "origin/main"
    assert scope["builds_out_of_tree"] is True
    assert scope["build_dir_template"] == "build-{issue_number}"
    assert scope["max_build_parallelism"] == 3

    list_response = await client.get(
        f"/api/v1/agent-teams/presets/{preset_id}/github-scopes"
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["scopes"]] == [scope["id"]]
    assert list_response.json()["scopes"][0]["github_auth_mode"] == "app"

    update_response = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}",
        json={
            "merge_policy": "human",
            "build_dir_template": "build",
            "max_build_parallelism": 4,
            "github_auth_mode": "ambient",
            "enabled": False,
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["merge_policy"] == "human"
    assert update_response.json()["build_dir_template"] == "build"
    assert update_response.json()["max_build_parallelism"] == 4
    assert update_response.json()["github_auth_mode"] == "ambient"
    assert update_response.json()["enabled"] is False
    assert (await db.get(TeamGithubScope, scope["id"])).github_app_installation_id is None

    item = GithubWorkItem(
        scope_id=scope["id"],
        issue_number=1,
        issue_title="leased",
        issue_url="https://github.com/adrirubio/snazzyemail/issues/1",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope["id"],
        path=str(tmp_path / "leased-worktree"),
        leased_item_id=item.id,
        lease_token="lease",
    )
    db.add(workspace)
    await db.commit()

    blocked_update = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}",
        json={"repo_name": "renamed-while-leased"},
    )
    assert blocked_update.status_code == 409
    assert blocked_update.json()["detail"] == "scope_identity_in_use"

    blocked_auth_update = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}",
        json={"github_auth_mode": "app"},
    )
    assert blocked_auth_update.status_code == 409
    assert blocked_auth_update.json()["detail"] == "scope_auth_in_use"

    blocked_delete = await client.delete(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}"
    )
    assert blocked_delete.status_code == 409
    assert blocked_delete.json()["detail"] == "scope_identity_in_use"

    workspace.leased_item_id = None
    workspace.lease_token = None
    await db.commit()

    blocked_pending = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}",
        json={"repo_owner": "other-owner"},
    )
    assert blocked_pending.status_code == 409
    assert blocked_pending.json()["detail"] == "scope_identity_in_use"

    item.dispatch_status = "verifying"
    item.dispatch_nonce = "nonce"
    item.dispatch_head_ref = "deck/slot-1/issue-1-nonce"
    item.dispatch_base_ref = "origin/master"
    await db.commit()

    blocked_without_lease = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}",
        json={"base_ref": "origin/release"},
    )
    assert blocked_without_lease.status_code == 409
    assert blocked_without_lease.json()["detail"] == "scope_identity_in_use"

    item.dispatch_status = "completed"
    await db.commit()

    # Capture identity before the delete; a route rollback can expire shared rows.
    await db.refresh(item)
    await db.refresh(workspace)
    item_id = item.id
    workspace_id = workspace.id
    delete_response = await client.delete(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}"
    )
    assert delete_response.status_code == 204
    db.expire_all()
    assert await db.get(GithubWorkItem, item_id) is None
    assert await db.get(GithubWorkspace, workspace_id) is None
    assert sync_calls == 3


@pytest.mark.asyncio
async def test_disabled_app_scope_saves_without_installation_discovery(client, db, monkeypatch, tmp_path):
    repo = tmp_path / "disabled-app-repo"
    repo.mkdir()
    calls = []

    async def fake_sync(_db):
        return None

    def require_configuration(**_kwargs):
        calls.append("require_configuration")

    async def resolve_installation(_owner, _repo):
        calls.append("resolve_installation")
        return 73

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    monkeypatch.setattr(github_app_auth_service, "require_configuration", require_configuration)
    monkeypatch.setattr(github_app_auth_service, "resolve_installation", resolve_installation)

    preset_response = await client.post(
        "/api/v1/agent-teams/presets",
        json={"name": "Disabled app team", "slots": []},
    )
    preset_id = preset_response.json()["id"]

    # A disabled configuration save keeps its App dispatch preference with gaps.
    create_response = await client.post(
        f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
        json={
            "repo_owner": "example",
            "repo_name": "disabled-app-repo",
            "repo_path": str(repo),
            "dispatch_label": "deck-ready",
            "design_label": "deck-design",
            "base_ref": "origin/main",
            "github_auth_mode": "app",
            "enabled": False,
        },
    )
    assert create_response.status_code == 200
    scope = create_response.json()
    assert scope["github_auth_mode"] == "app"
    assert scope["enabled"] is False
    assert calls == []
    assert (await db.get(TeamGithubScope, scope["id"])).github_app_installation_id is None

    # Enabling the saved scope resolves the installation and keeps the preference.
    enabled = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert calls == ["require_configuration", "resolve_installation"]
    assert enabled.json()["github_auth_mode"] == "app"
    assert (await db.get(TeamGithubScope, scope["id"])).github_app_installation_id == 73


@pytest.mark.asyncio
async def test_app_installation_lookup_refuses_changed_configuration(client, db, monkeypatch, tmp_path):
    repo = tmp_path / "raced-app-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    monkeypatch.setattr(github_app_auth_service, "require_configuration", lambda **_kwargs: None)

    preset_response = await client.post(
        "/api/v1/agent-teams/presets",
        json={"name": "Raced app team", "slots": []},
    )
    preset_id = preset_response.json()["id"]
    create_response = await client.post(
        f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
        json={
            "repo_owner": "example",
            "repo_name": "raced-app-repo",
            "repo_path": str(repo),
            "dispatch_label": "deck-ready",
            "design_label": "deck-design",
            "base_ref": "origin/main",
            "github_auth_mode": "app",
            "enabled": False,
        },
    )
    scope_id = create_response.json()["id"]

    async def resolve_installation(_owner, _repo):
        # A same-mode request changes scope configuration during remote discovery.
        await db.execute(
            text("UPDATE team_github_scopes SET dispatch_label = :label WHERE id = :scope_id"),
            {"label": "changed-during-lookup", "scope_id": scope_id},
        )
        await db.commit()
        return 73

    monkeypatch.setattr(github_app_auth_service, "resolve_installation", resolve_installation)

    response = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope_id}",
        json={"enabled": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "scope_changed_during_app_lookup"
    stored = await db.get(TeamGithubScope, scope_id)
    assert stored.enabled is False
    assert stored.github_app_installation_id is None


@pytest.mark.asyncio
async def test_github_scope_build_hint_can_be_cleared(client, monkeypatch, tmp_path):
    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await client.post(
        "/api/v1/agent-teams/presets", json={"name": "Scope team", "slots": []}
    )
    created = await client.post(
        f"/api/v1/agent-teams/presets/{preset.json()['id']}/github-scopes",
        json={
            "repo_owner": "adrirubio",
            "repo_name": "snazzyemail",
            "repo_path": str(repo),
            "build_command_hint": "meson compile -C {build_dir}",
        },
    )
    assert created.status_code == 200
    url = f"/api/v1/agent-teams/github-scopes/{created.json()['id']}"

    unchanged = await client.patch(url, json={"max_approval_rounds": 4})
    assert unchanged.status_code == 200
    assert unchanged.json()["build_command_hint"] == "meson compile -C {build_dir}"

    cleared = await client.patch(url, json={"build_command_hint": None})
    assert cleared.status_code == 200
    assert cleared.json()["build_command_hint"] is None

    restored = await client.patch(url, json={"build_command_hint": "make -j{parallelism}"})
    assert restored.status_code == 200
    cleared_empty = await client.patch(url, json={"build_command_hint": ""})
    assert cleared_empty.status_code == 200
    assert cleared_empty.json()["build_command_hint"] is None


@pytest.mark.asyncio
async def test_github_scope_noop_identity_edit_allowed_while_active(client, db, monkeypatch, tmp_path):
    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await client.post(
        "/api/v1/agent-teams/presets", json={"name": "Scope team", "slots": []}
    )
    created = await client.post(
        f"/api/v1/agent-teams/presets/{preset.json()['id']}/github-scopes",
        json={"repo_owner": "adrirubio", "repo_name": "snazzyemail", "repo_path": str(repo), "base_ref": "origin/main"},
    )
    assert created.status_code == 200
    scope_id = created.json()["id"]
    db.add(GithubWorkItem(
        scope_id=scope_id,
        issue_number=1,
        issue_title="active",
        issue_url="https://github.com/adrirubio/snazzyemail/issues/1",
        github_updated_at=datetime.utcnow(),
    ))
    await db.commit()
    url = f"/api/v1/agent-teams/github-scopes/{scope_id}"

    updated = await client.patch(url, json={
        "repo_owner": "adrirubio",
        "repo_name": "snazzyemail",
        "repo_path": str(repo),
        "base_ref": "origin/main",
        "max_approval_rounds": 5,
    })
    assert updated.status_code == 200
    assert updated.json()["max_approval_rounds"] == 5
    assert updated.json()["base_ref"] == "origin/main"

    blocked = await client.patch(url, json={"base_ref": "origin/release"})
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "scope_identity_in_use"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("build_dir_template", "build-{issue_number"),
        ("build_dir_template", "build-{unknown}"),
        ("build_command_hint", "make -C {unknown}"),
    ],
)
async def test_github_scope_rejects_invalid_build_templates(
    client, monkeypatch, tmp_path, field, value
):
    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    repo = tmp_path / f"repo-{field}-{len(value)}"
    repo.mkdir()
    preset_response = await client.post(
        "/api/v1/agent-teams/presets",
        json={"name": f"Template team {field} {len(value)}", "slots": []},
    )

    response = await client.post(
        f"/api/v1/agent-teams/presets/{preset_response.json()['id']}/github-scopes",
        json={
            "repo_owner": "owner",
            "repo_name": repo.name,
            "repo_path": str(repo),
            field: value,
        },
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_github_scope_rejects_invalid_repo_path(client, tmp_path):
    preset_response = await client.post(
        "/api/v1/agent-teams/presets",
        json={"name": "Invalid scope team", "slots": []},
    )
    preset_id = preset_response.json()["id"]

    response = await client.post(
        f"/api/v1/agent-teams/presets/{preset_id}/github-scopes",
        json={
            "repo_owner": "adrirubio",
            "repo_name": "snazzyemail",
            "repo_path": "relative/path",
        },
    )
    assert response.status_code == 400
    assert "Repo path must be absolute" in response.json()["detail"]


@pytest.mark.asyncio
async def test_github_scope_create_missing_preset_returns_404(client, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    response = await client.post(
        "/api/v1/agent-teams/presets/999999/github-scopes",
        json={
            "repo_owner": "adrirubio",
            "repo_name": "snazzyemail",
            "repo_path": str(repo),
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_github_work_item_feed_and_retry_guard(client, db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Feed team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Backend SME",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="adrirubio",
        repo_name="snazzyemail",
        repo_path=str(repo),
    )
    db.add(scope)
    await db.flush()
    escalated = GithubWorkItem(
        scope_id=scope.id,
        issue_number=10,
        issue_title="Fix CI",
        issue_url="https://github.com/adrirubio/snazzyemail/issues/10",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="retry_count_exhausted",
        pending_reason="queued_repo_cap",
        handoff_state="pending",
        handoff_target_slot_id=1,
        pr_number=None,
        retry_count=2,
        last_verified_sha="abc123",
        approval_round_count=3,
    )
    active = GithubWorkItem(
        scope_id=scope.id,
        issue_number=11,
        issue_title="Still running",
        issue_url="https://github.com/adrirubio/snazzyemail/issues/11",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
    )
    db.add_all([escalated, active])
    await db.commit()

    feed_response = await client.get(
        f"/api/v1/agent-teams/presets/{preset.id}/github-work-items"
    )
    assert feed_response.status_code == 200
    rows = feed_response.json()["items"]
    assert {row["issue_number"] for row in rows} == {10, 11}
    row = next(item for item in rows if item["issue_number"] == 10)
    assert row["repo_owner"] == "adrirubio"
    assert row["escalation_reason"] == "retry_count_exhausted"

    guard_response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{active.id}/retry",
        json={"reason": "should remain guarded"},
    )
    assert guard_response.status_code == 409

    retry_response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{escalated.id}/retry",
        json={"reason": "prerequisite #816 merged"},
    )
    assert retry_response.status_code == 200
    body = retry_response.json()
    assert body["dispatch_status"] == "pending"
    assert body["escalation_reason"] is None
    assert body["pending_reason"] == "retry requested: prerequisite #816 merged"
    assert body["handoff_state"] is None
    assert body["handoff_target_slot_id"] is None
    assert body["pr_number"] is None
    assert body["retry_count"] == 0
    assert body["last_verified_sha"] is None
    assert body["approval_round_count"] == 0


async def _create_retry_work_item(db, *, pr_number: int | None) -> GithubWorkItem:
    preset = AgentTeamPreset(name="Retry team")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="adrirubio",
        repo_name="snazzyemail",
        repo_path="/tmp/snazzyemail",
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=865,
        issue_title="Preserve open PR",
        issue_url="https://github.com/adrirubio/snazzyemail/issues/865",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        pr_number=pr_number,
    )
    db.add(item)
    await db.commit()
    return item


@pytest.mark.asyncio
async def test_retry_rejected_when_pr_open(client, db):
    item = await _create_retry_work_item(db, pr_number=865)

    response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/retry",
        json={"reason": "try again"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["block_code"] == "pr_preserved"
    assert "865" in detail["message"]
    await db.refresh(item)
    assert item.pr_number == 865
    assert item.dispatch_status == "escalated"


@pytest.mark.asyncio
async def test_retry_allowed_when_no_pr(client, db):
    item = await _create_retry_work_item(db, pr_number=None)

    response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/retry",
        json={"reason": "try again"},
    )

    assert response.status_code == 200
    assert response.json()["retry_allowed"] is False
    assert response.json()["retry_block_code"] == "not_escalated"
    await db.refresh(item)
    assert item.dispatch_status == "pending"


@pytest.mark.asyncio
async def test_retry_endpoint_defers_while_workspace_is_leased(client, db):
    item = await _create_retry_work_item(db, pr_number=None)
    workspace = GithubWorkspace(
        scope_id=item.scope_id,
        path="/tmp/snazzyemail-retry",
        leased_item_id=item.id,
        lease_token="api-token",
    )
    db.add(workspace)
    await db.commit()

    response = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/retry",
        json={"reason": "try again"},
    )

    assert response.status_code == 200
    body = response.json()
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.retry_requested_at is not None
    assert body["retry_requested_at"] is not None
    assert body["retry_allowed"] is True
    assert body["retry_block_code"] is None
    assert workspace.leased_item_id == item.id


@pytest.mark.asyncio
async def test_leader_assignment_is_explicit_and_survives_reorder(client, db, tmp_path):
    repo = tmp_path / "leader-repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Explicit Leader fixture",
            slots=[
                AgentTeamSlotCreate(display_name="Worker", repo_path=str(repo)),
                AgentTeamSlotCreate(display_name="Leader", repo_path=str(repo)),
            ],
        ),
    )
    assert preset.leader_slot_id is None
    leader_slot = preset.slots[1]
    response = await client.put(
        f"/api/v1/agent-teams/presets/{preset.id}/leader",
        json={
            "leader_slot_id": leader_slot.id,
            "expected_leader_slot_id": None,
            "expected_updated_at": preset.updated_at.isoformat(),
            "reason": "Select the approved fixture Leader.",
        },
    )
    assert response.status_code == 200
    assert response.json()["leader_slot_id"] == leader_slot.id

    reordered = await agent_team_service.reorder_slots(
        db, preset.id, [leader_slot.id, preset.slots[0].id]
    )
    assert reordered.leader_slot_id == leader_slot.id

    missing = await client.put(
        "/api/v1/agent-teams/presets/999999/leader",
        json={
            "leader_slot_id": leader_slot.id,
            "expected_leader_slot_id": None,
            "expected_updated_at": preset.updated_at.isoformat(),
            "reason": "Check a missing team safely.",
        },
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "team_not_found"

    stale = await client.put(
        f"/api/v1/agent-teams/presets/{preset.id}/leader",
        json={
            "leader_slot_id": preset.slots[0].id,
            "expected_leader_slot_id": None,
            "expected_updated_at": "2000-01-01T00:00:00",
            "reason": "Reject a stale assignment safely.",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "leader_assignment_changed"
    unchanged = await agent_team_service.get_preset(db, preset.id)
    assert unchanged.leader_slot_id == leader_slot.id


@pytest.mark.asyncio
async def test_team_creation_requires_operator(client):
    response = await client.post(
        "/api/v1/agent-teams/presets",
        headers={"X-Deck-Operator-Token": ""},
        json={"name": "Denied creation", "slots": []},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "operator_token_required"


@pytest.mark.asyncio
async def test_v18_leader_update_invalid_change_matrix(client, db, tmp_path):
    """V18: invalid-change matrix for the protected Leader update route."""
    repo = tmp_path / "v18-repo"
    repo.mkdir()
    other = tmp_path / "v18-other"
    other.mkdir()
    team_a = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V18 team A", slots=[
        AgentTeamSlotCreate(display_name="A1", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="A2", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="A3", repo_path=str(repo), enabled=False),
    ]))
    team_b = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V18 team B", slots=[
        AgentTeamSlotCreate(display_name="B1", repo_path=str(other)),
    ]))
    a1, _a2, a3_disabled = team_a.slots[0], team_a.slots[1], team_a.slots[2]
    b1_cross = team_b.slots[0]
    endpoint = f"/api/v1/agent-teams/presets/{team_a.id}/leader"
    stamp = team_a.updated_at.isoformat()

    def payload(slot_id, expected=None, updated_at=None, reason="V18 matrix check"):
        return {"leader_slot_id": slot_id, "expected_leader_slot_id": expected,
                "expected_updated_at": updated_at or stamp, "reason": reason}

    # Unauthorized: missing and wrong operator credentials are refused.
    missing_auth = await client.put(endpoint, headers={"X-Deck-Operator-Token": ""},
                                    json=payload(a1.id))
    assert missing_auth.status_code == 401
    wrong_auth = await client.put(endpoint, headers={"X-Deck-Operator-Token": "v18-wrong"},
                                  json=payload(a1.id))
    assert wrong_auth.status_code == 401

    # Missing slot: refused without any assignment change.
    missing_slot = await client.put(endpoint, json=payload(999999))
    assert missing_slot.status_code == 409
    assert missing_slot.json()["detail"]["code"] == "leader_slot_unavailable"

    # Disabled slot: refused.
    disabled_slot = await client.put(endpoint, json=payload(a3_disabled.id))
    assert disabled_slot.status_code == 409
    assert disabled_slot.json()["detail"]["code"] == "leader_slot_unavailable"

    # Cross-team slot: refused.
    cross_team = await client.put(endpoint, json=payload(b1_cross.id))
    assert cross_team.status_code == 409
    assert cross_team.json()["detail"]["code"] == "leader_slot_unavailable"

    # Stale expected assignment and stale update stamp: refused.
    stale = await client.put(endpoint, json=payload(a1.id, expected=999999))
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "leader_assignment_changed"
    stale_stamp = await client.put(endpoint, json=payload(a1.id, updated_at="2000-01-01T00:00:00"))
    assert stale_stamp.status_code == 409
    assert stale_stamp.json()["detail"]["code"] == "leader_assignment_changed"

    # Empty reason: refused.
    no_reason = await client.put(endpoint, json=payload(a1.id, reason=" "))
    assert no_reason.status_code == 409
    assert no_reason.json()["detail"]["code"] == "leader_assignment_reason_required"

    # Positive control: a valid explicit assignment succeeds.
    accepted = await client.put(endpoint, json=payload(a1.id))
    assert accepted.status_code == 200
    assert accepted.json()["leader_slot_id"] == a1.id

    # Active team automation: refused and the assignment is preserved.
    async def current(slot_id, reason="V18 matrix check"):
        preset = await agent_team_service.get_preset(db, team_a.id)
        return {"leader_slot_id": slot_id, "expected_leader_slot_id": preset.leader_slot_id,
                "expected_updated_at": preset.updated_at.isoformat(), "reason": reason}

    team_a.autonomy_enabled = True
    await db.execute(text("UPDATE agent_team_presets SET autonomy_enabled = 1 WHERE id = :id"), {"id": team_a.id})
    await db.commit()
    db.expire_all()
    active_team = await client.put(endpoint, json=await current(_a2.id))
    assert active_team.status_code == 409
    assert active_team.json()["detail"]["code"] == "leader_assignment_team_active"
    await db.execute(text("UPDATE agent_team_presets SET autonomy_enabled = 0 WHERE id = :id"), {"id": team_a.id})
    await db.commit()
    db.expire_all()

    # Non-quiescent team with an active item and lease: refused.
    scope = TeamGithubScope(preset_id=team_a.id, repo_owner="example", repo_name="v18",
                            repo_path=str(repo))
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="v18",
                          issue_url="https://example.invalid/1", github_updated_at=datetime.utcnow(),
                          dispatch_status="dispatched")
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "v18-work"),
                                leased_item_id=item.id, lease_token="v18-lease")
    db.add(workspace)
    await db.commit()
    busy_team = await client.put(endpoint, json=await current(_a2.id))
    assert busy_team.status_code == 409
    assert busy_team.json()["detail"]["code"] == "leader_assignment_team_not_quiescent"

    # Concurrent acquisition is covered by
    # test_leader_mutation_rechecks_assignment_after_waiting_for_sqlite_writer.
    unchanged = await agent_team_service.get_preset(db, team_a.id)
    assert unchanged.leader_slot_id == a1.id


@pytest.mark.asyncio
async def test_v18_leader_update_quiescence_blockers_and_competing_updates(client, db, tmp_path):
    """V18: each quiescence blocker and competing protected updates refuse safely."""
    repo = tmp_path / "v18b-repo"
    repo.mkdir()
    team = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V18B team", slots=[
        AgentTeamSlotCreate(display_name="Q1", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="Q2", repo_path=str(repo)),
    ]))
    q1, q2 = team.slots[0], team.slots[1]
    scope = TeamGithubScope(preset_id=team.id, repo_owner="example", repo_name="v18b",
                            repo_path=str(repo))
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=2, issue_title="v18b",
                          issue_url="https://example.invalid/2", github_updated_at=datetime.utcnow(),
                          dispatch_status="completed")
    db.add(item)
    await db.commit()
    # Capture identities before later commits can expire the shared session rows.
    team_id, q1_id, q2_id, scope_id, item_id = team.id, q1.id, q2.id, scope.id, item.id
    endpoint = f"/api/v1/agent-teams/presets/{team_id}/leader"

    async def attempt(slot_id, reason="V18 quiescence blockers"):
        preset = await agent_team_service.get_preset(db, team_id)
        return await client.put(endpoint, json={
            "leader_slot_id": slot_id,
            "expected_leader_slot_id": preset.leader_slot_id,
            "expected_updated_at": preset.updated_at.isoformat(),
            "reason": reason,
        })

    async def refused_unchanged(response, slot_id):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "leader_assignment_team_not_quiescent"
        preset = await agent_team_service.get_preset(db, team_id)
        assert preset.leader_slot_id is None

    # Blocker: a verifying attempt alone.
    item.dispatch_status = "verifying"
    await db.commit()
    await refused_unchanged(await attempt(q1_id), q1_id)
    item.dispatch_status = "completed"
    await db.commit()

    # Blocker: a pending approval request alone.
    approval = GithubApprovalRequest(
        work_item_id=item_id, request_kind="initial", dispatch_nonce="v18b-nonce",
        approval_round=1, owner_member_id=1, leader_member_id=2,
        request_fingerprint="v18b-fingerprint", status="pending")
    db.add(approval)
    await db.commit()
    await refused_unchanged(await attempt(q1_id), q1_id)
    approval.status = "approved"
    await db.commit()

    # Blocker: a nonterminal attempt scope revision alone.
    revision = GithubAttemptScopeRevision(
        work_item_id=item_id, dispatch_nonce="v18b-nonce", revision=0, owner_slot_id=q1_id,
        owner_member_id=1, phase="implementation", execution_target="/work", summary="v18b",
        allowed_paths="[]", allowed_actions="[]", allowed_commands="[]", prohibited_actions="[]",
        tool_fallbacks="{}", baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
        originating_escalation_reason="fixture", expected_workspace_id=0,
        expected_lease_token_hash="fixture-hash", max_failed_heads=2, failed_head_count=0,
        status="active", delivery_attempt_count=0)
    db.add(revision)
    await db.commit()
    await refused_unchanged(await attempt(q1_id), q1_id)
    revision.status = "superseded"
    await db.commit()

    # Blocker: residual workspace lease fields after release.
    workspace = GithubWorkspace(scope_id=scope_id, path=str(tmp_path / "v18b-work"),
                                lease_token="residual-lease-token")
    db.add(workspace)
    await db.commit()
    await refused_unchanged(await attempt(q1_id), q1_id)
    workspace.lease_token = None
    await db.commit()

    # Quiescent team: a valid explicit assignment succeeds.
    accepted = await attempt(q1_id)
    assert accepted.status_code == 200
    assert accepted.json()["leader_slot_id"] == q1_id

    # Competing protected updates: the second stale request is refused and the
    # first assignment is preserved.
    preset = await agent_team_service.get_preset(db, team_id)
    stale_snapshot = {
        "leader_slot_id": q2_id,
        "expected_leader_slot_id": preset.leader_slot_id,
        "expected_updated_at": preset.updated_at.isoformat(),
        "reason": "V18 competing update",
    }
    first = await client.put(endpoint, json=dict(stale_snapshot))
    assert first.status_code == 200
    second = await client.put(endpoint, json=dict(stale_snapshot))
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "leader_assignment_changed"
    after = await agent_team_service.get_preset(db, team_id)
    assert after.leader_slot_id == q2_id

    # A blocker created after a refusal is visible to the next fresh read.
    late = GithubWorkspace(scope_id=scope_id, path=str(tmp_path / "v18b-late"),
                           leased_item_id=item_id, lease_token="late-lease")
    db.add(late)
    await db.commit()
    late_blocked = await attempt(q1_id)
    assert late_blocked.status_code == 409
    assert late_blocked.json()["detail"]["code"] == "leader_assignment_team_not_quiescent"

    # Concurrent writer acquisition is covered by
    # test_leader_mutation_rechecks_assignment_after_waiting_for_sqlite_writer.
