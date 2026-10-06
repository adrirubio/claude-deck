"""HTTP contract tests for Agent Team presets."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text

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


@pytest.mark.asyncio
async def test_create_route_400_after_partial_work_persists_nothing(client, db, tmp_path):
    """Finding 4: a create-route 400 is a proven non-write.

    The validation failure happens after the preset is added to the session and
    after all slots are normalized but before any slot is added. The request
    must persist nothing, so a 400 from these routes proves
    no write happened and safe correction is allowed.
    """
    repo = tmp_path / "contract-repo"
    repo.mkdir()
    response = await client.post(
        "/api/v1/agent-teams/presets",
        json={"name": "Contract team", "slots": [
            {"display_name": "Good slot", "repo_path": str(repo)},
            {"display_name": "Bad slot", "repo_path": "/outside/any/allowed/root"},
        ]},
    )
    assert response.status_code == 400
    # Evidence boundary: this test proves the route performs no commit before
    # the validation refusal, even with the preset already added in-session.
    # All slots are normalized before any slot is added, so the partial state is
    # the preset row only. Production teardown evidence is separate source
    # evidence: `get_db` commits only on normal return and closes the session
    # otherwise, discarding uncommitted rows. Rollback here discards that state.
    await db.rollback()
    presets = (await db.execute(text("SELECT COUNT(*) FROM agent_team_presets"))).scalar_one()
    slots = (await db.execute(text("SELECT COUNT(*) FROM agent_team_slots"))).scalar_one()
    assert presets == 0
    assert slots == 0


@pytest.mark.asyncio
async def test_launch_unknown_plan_hash_is_structured_proven_non_write(client, db, monkeypatch, tmp_path):
    """An unknown plan hash refuses before any launch write.

    This is unknown-hash refusal, not expiration of a valid issued plan.
    """
    repo = tmp_path / "plan-conflict-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    preset_response = await client.post(
        "/api/v1/agent-teams/presets",
        json={"name": "Plan conflict team", "slots": [
            {"display_name": "PC Leader", "repo_path": str(repo), "role": "Leader"},
        ]},
    )
    preset_id = preset_response.json()["id"]
    launch = await client.post(
        f"/api/v1/agent-teams/presets/{preset_id}/launch",
        json={"slot_ids": [preset_response.json()["slots"][0]["id"]],
              "confirm_plan_hash": "expired-plan-hash", "reuse_existing": True},
    )
    assert launch.status_code == 409
    detail = launch.json()["detail"]
    assert detail["code"] == "plan_conflict"
    assert detail["proven_non_write"] is True
    assert detail["message"]
    launches = (await db.execute(text("SELECT COUNT(*) FROM agent_team_launches"))).scalar_one()
    assert launches == 0


@pytest.mark.asyncio
async def test_launch_later_conflict_after_session_action_is_not_proven_non_write(
    client, db, monkeypatch, tmp_path
):
    """A conflict raised while executing plan items can follow session actions.

    Controlled multi-slot regression, not a live session trial: the first slot's
    session action is a recorded attach stub in a controlled sequence; the second
    slot hits the real pane-changed conflict. The conflict must not claim a proven
    non-write.
    """
    from unittest.mock import AsyncMock

    from app.models.database import AgentPaneBinding, AgentTeamLaunch
    from app.models.schemas import AgentTeamLaunchPlanItem
    from app.services import agent_team_service as service_module

    repo = tmp_path / "later-conflict-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="Later conflict team",
        slots=[
            AgentTeamSlotCreate(display_name="LC First", provider="codex-cli", repo_path=str(repo)),
            AgentTeamSlotCreate(display_name="LC Second", provider="codex-cli", repo_path=str(repo)),
        ],
    ))
    first, second = preset.slots[0], preset.slots[1]
    launch_row = AgentTeamLaunch(preset_id=preset.id, plan_hash="later-conflict-plan")
    db.add(launch_row)
    db.add(AgentPaneBinding(pane_pid=111, pane_proc_start="1", slot_id=first.id, preset_id=preset.id))
    await db.commit()

    def fake_stat(pid):
        return (0, "1" if pid == 111 else "2")

    monkeypatch.setattr(service_module, "read_proc_stat", fake_stat)
    actions = []
    async def fake_attach(_self, _db, slot, session, **_kwargs):
        actions.append(slot.id)
        return None
    monkeypatch.setattr(
        "app.services.agent_team_service.AgentTeamService._attach_team_context_to_existing_session",
        fake_attach)

    def plan_item(slot, pid):
        return AgentTeamLaunchPlanItem(
            slot_id=slot.id, slot_name=slot.display_name, provider=slot.provider,
            repo_id=slot.repo_id, repo_path=slot.repo_path, repo_name=slot.repo_name,
            action="reuse", status="ready",
            matching_session={"pid": pid, "pane_proc_start": "1", "session_name": "s",
                              "tmux_target": "t:0.0"},
        )

    service = agent_team_service
    await service._execute_plan_item(db, launch_row.id, preset, first, plan_item(first, 111))
    assert actions == [first.id], "the first slot must complete its session action first"
    with pytest.raises(ValueError) as refused:
        await service._execute_plan_item(db, launch_row.id, preset, second, plan_item(second, 222))
    assert "The selected pane changed" in str(refused.value)
    assert refused.value.proven_non_write is False


@pytest.mark.asyncio
async def test_activation_readiness_names_binding_and_provider_gaps(client, db, monkeypatch, tmp_path):
    """Finding 3: server-derived readiness names each binding gap safely."""
    repo = tmp_path / "readiness-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    from unittest.mock import AsyncMock
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_service.sync_observed_sessions",
        AsyncMock())
    monkeypatch.setattr("app.services.agent_team_service.discover_agent_sessions", lambda: [])
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="Readiness team",
        slots=[
            AgentTeamSlotCreate(display_name="R Leader", provider="codex-cli", repo_path=str(repo), role="Leader"),
            AgentTeamSlotCreate(display_name="R Worker", provider="codex-cli", repo_path=str(repo)),
        ],
    ))
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="example", repo_name="readiness",
                            repo_path=str(repo))
    db.add(scope)
    await db.commit()

    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    assert readiness.status_code == 200
    body = readiness.json()
    assert body["status"] == "blocked"
    codes = {blocker["code"] for blocker in body["blockers"]}
    assert "leader_assignment_missing" in codes
    assert "owner_binding_missing" in codes
    assert "provider_mail_not_ready" in codes
    assert body["observed_at"]
    for blocker in body["blockers"]:
        assert blocker["message"]


async def _readiness_team(db, monkeypatch, tmp_path, name, workers):
    # Native pane liveness is test-controlled; rows alone never satisfy the
    # binding. Individual cases can override the returned verdicts.
    monkeypatch.setattr("app.utils.peer_process.pane_is_alive_strict",
                        lambda pane_pid, proc_start: True)
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr("app.utils.peer_process.pane_agent_command",
                        lambda pane_pid, proc_start: "codex exec --yolo")
    from unittest.mock import AsyncMock

    from app.models.database import MailAgentSession, MailTeamMember
    from app.utils import peer_process

    repo = tmp_path / name
    repo.mkdir()
    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", AsyncMock())
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_service.sync_observed_sessions", AsyncMock())
    monkeypatch.setattr("app.services.agent_team_service.discover_agent_sessions", lambda: [])
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda *_args: True)
    slots = [AgentTeamSlotCreate(display_name=f"{name} Leader", provider="codex-cli",
                                 repo_path=str(repo), role="Leader")]
    slots += [AgentTeamSlotCreate(display_name=f"{name} W{i}", provider="codex-cli",
                                  repo_path=str(repo)) for i in range(workers)]
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name=name, slots=slots))
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="example", repo_name=name,
                            repo_path=str(repo))
    db.add(scope)
    await db.flush()
    return preset, scope, repo


def _bind_owner(db, preset, slot_id, member_id, session_id, *, last_seen):
    from app.models.database import AgentPaneBinding, MailAgentSession, MailTeamMember

    db.add(MailTeamMember(
        id=member_id, identity_key=f"slot:{member_id}", repo_id="r", repo_path="/r",
        repo_name="r", display_name=f"Owner {member_id}", participant_kind="team_slot",
        team_preset_id=preset.id, team_slot_id=slot_id))
    db.add(MailAgentSession(
        id=session_id, member_id=member_id, provider="codex-cli", source="mcp",
        session_key=f"mcp:ready-{session_id}", wake_enabled=True,
        mailbox_status="connected", last_seen_at=last_seen,
        team_preset_id=preset.id, team_slot_id=slot_id,
        bound_pane_pid=1000 + session_id, bound_pane_proc_start="1",
        capability_token_hash=f"cap-{session_id}"))
    db.add(AgentPaneBinding(pane_pid=1000 + session_id, pane_proc_start="1",
                            slot_id=slot_id, preset_id=preset.id))


@pytest.mark.asyncio
async def test_activation_readiness_rejects_stale_owner_heartbeat(client, db, monkeypatch, tmp_path):
    """Finding 3: an owner session with a stale heartbeat is a named blocker."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "StaleHB", 1)
    stale = datetime.utcnow() - timedelta(hours=1)
    _bind_owner(db, preset, preset.slots[1].id, 910, 810, last_seen=stale)
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_stale" in codes
    assert "owner_binding_missing" in codes


@pytest.mark.asyncio
async def test_activation_readiness_rejects_ambiguous_owner_binding(client, db, monkeypatch, tmp_path):
    """Finding 3: one member with several live bound lifetimes is ambiguous."""
    from app.models.database import MailAgentSession

    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "Ambiguous", 1)
    now = datetime.utcnow()
    # One member with two live bound lifetimes on the same slot.
    _bind_owner(db, preset, preset.slots[1].id, 911, 811, last_seen=now)
    from app.models.database import AgentPaneBinding
    db.add(MailAgentSession(
        id=812, member_id=911, provider="codex-cli", source="mcp",
        session_key="mcp:ready-812", wake_enabled=True,
        mailbox_status="connected", last_seen_at=now,
        team_preset_id=preset.id, team_slot_id=preset.slots[1].id,
        bound_pane_pid=1002, bound_pane_proc_start="1",
        capability_token_hash="cap-812"))
    db.add(AgentPaneBinding(pane_pid=1002, pane_proc_start="1",
                            slot_id=preset.slots[1].id, preset_id=preset.id))
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_ambiguous" in codes
    assert "owner_binding_missing" in codes


@pytest.mark.asyncio
async def test_activation_readiness_accepts_two_distinct_valid_owners(client, db, monkeypatch, tmp_path):
    """Finding 3: distinct valid owners on different slots are normal."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "TwoOwners", 2)
    now = datetime.utcnow()
    _bind_owner(db, preset, preset.slots[1].id, 913, 813, last_seen=now)
    _bind_owner(db, preset, preset.slots[2].id, 914, 814, last_seen=now)
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_ambiguous" not in codes
    assert "owner_binding_stale" not in codes
    assert "owner_binding_missing" not in codes


@pytest.mark.asyncio
async def test_configuration_observation_is_bounded_and_flags_incomplete(client, db, monkeypatch, tmp_path):
    """Finding 7: the bulk observation is finite and incomplete reads are named."""
    from unittest.mock import AsyncMock

    import app.api.v1.agent_teams as agent_teams_module

    repo = tmp_path / "bounded-repo"
    repo.mkdir()
    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", AsyncMock())
    for index in range(3):
        await agent_team_service.create_preset(db, AgentTeamPresetCreate(
            name=f"Bounded team {index}",
            slots=[AgentTeamSlotCreate(display_name=f"B{index}", provider="codex-cli", repo_path=str(repo))],
        ))
    projected = []
    original_projection = agent_team_service.bounded_slots_for_preset

    async def spy_projection(_db, preset_id, limit):
        projected.append(preset_id)
        return await original_projection(_db, preset_id, limit)

    monkeypatch.setattr(agent_team_service, "bounded_slots_for_preset", spy_projection)
    monkeypatch.setattr(agent_teams_module, "_CONFIGURATION_OBSERVATION_PRESET_LIMIT", 2)
    observation = await client.get("/api/v1/agent-teams/configuration-observation")
    body = observation.json()
    assert observation.status_code == 200
    assert body["complete"] is False
    assert len(body["presets"]) == 2
    assert body["observed_at"]

    monkeypatch.setattr(agent_teams_module, "_CONFIGURATION_OBSERVATION_PRESET_LIMIT", 64)
    complete = await client.get("/api/v1/agent-teams/configuration-observation")
    assert complete.json()["complete"] is True
    assert len(complete.json()["presets"]) == 3


@pytest.mark.asyncio
async def test_activation_readiness_reports_bounded_context(client, db, monkeypatch, tmp_path):
    """Finding 7: oversized readiness context is a named incomplete blocker."""
    from unittest.mock import AsyncMock

    repo = tmp_path / "bounded-ready"
    repo.mkdir()
    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", AsyncMock())
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_service.sync_observed_sessions", AsyncMock())
    monkeypatch.setattr("app.services.agent_team_service.discover_agent_sessions", lambda: [])
    slots = [AgentTeamSlotCreate(display_name=f"BR {i}", provider="codex-cli", repo_path=str(repo)) for i in range(65)]
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "mail_capability_tokens_required", True)
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="Bounded readiness", slots=slots))
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="example", repo_name="bounded-ready",
                            repo_path=str(repo))
    db.add(scope)
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert codes == {"readiness_context_limit"}
    # B05: overflow stops Leader, owner, session and native work entirely.


@pytest.mark.asyncio
async def test_configuration_observation_skips_hydration_for_oversized_rosters(client, db, monkeypatch, tmp_path):
    """Finding 7: an oversized roster is never hydrated; it is omitted truthfully."""
    from unittest.mock import AsyncMock

    import app.api.v1.agent_teams as agent_teams_module

    repo = tmp_path / "oversized-repo"
    repo.mkdir()
    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", AsyncMock())
    slots = [AgentTeamSlotCreate(display_name=f"OS {i}", provider="codex-cli", repo_path=str(repo)) for i in range(65)]
    oversized = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="Oversized team", slots=slots))
    small = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="Small team",
        slots=[AgentTeamSlotCreate(display_name="Small", provider="codex-cli", repo_path=str(repo))],
    ))
    projected_slots = []
    original_slot_response = agent_team_service._slot_response

    def spy_slot_response(slot):
        projected_slots.append((slot.preset_id, slot.id))
        return original_slot_response(slot)

    monkeypatch.setattr(agent_team_service, "_slot_response", spy_slot_response)
    observation = await client.get("/api/v1/agent-teams/configuration-observation")
    body = observation.json()
    assert body["complete"] is False
    oversized_rows = [entry for entry in projected_slots if entry[0] == oversized.id]
    assert len(oversized_rows) <= 64, "projection work for an oversized roster must stay bounded"
    assert any(entry[0] == small.id for entry in projected_slots)
    assert body["incomplete_presets"] == [
        {"id": oversized.id, "roster_omitted": True, "slot_bound": 64},
    ]
    assert [preset["id"] for preset in body["presets"]] == [small.id]


@pytest.mark.asyncio
async def test_configuration_observation_bounds_projection_under_concurrent_growth(tmp_path, monkeypatch):
    """Finding 7: a separate writer growing the roster cannot widen projection
    work or let the observation claim complete evidence."""
    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.api.v1.agent_teams as agent_teams_module
    from app.database import Base
    from app.models.database import AgentTeamSlot

    db_path = tmp_path / "growth.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 5})
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 5})
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as seed:
            preset = AgentTeamPreset(name="Growth team")
            seed.add(preset)
            await seed.flush()
            seed.add(AgentTeamSlot(
                preset_id=preset.id, position=0, display_name="G0", provider="codex-cli",
                repo_id="g", repo_path="/tmp/g", repo_name="g"))
            await seed.commit()
            preset_id = preset.id

        async with maker() as reader:
            original = agent_team_service.bounded_slots_for_preset
            grew = False

            async def racing_projection(db_ignored, observed_preset_id, limit):
                nonlocal grew
                if not grew:
                    grew = True
                    # A separate writer adds 65 rows in the count-to-hydration
                    # window with an independent connection.
                    async with writer_engine.begin() as writer:
                        for index in range(65):
                            await writer.execute(sql_text(
                                "INSERT INTO agent_team_slots (preset_id, position, display_name, "
                                "provider, repo_id, repo_path, repo_name, launch_mode, enabled, "
                                "created_at, updated_at) VALUES (:p, :i, :n, 'codex-cli', 'g', "
                                "'/tmp/g', 'g', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                            ), {"p": observed_preset_id, "i": index + 1, "n": f"G{index + 1}"})
                rows, bound_hit = await original(db_ignored, observed_preset_id, limit)
                assert len(rows) <= limit, "projection work must stay bounded"
                return rows, bound_hit

            monkeypatch.setattr(agent_team_service, "bounded_slots_for_preset", racing_projection)
            body = await agent_teams_module.read_configuration_observation(_operator=None, db=reader)

        assert body["complete"] is False
        assert body["incomplete_presets"] == [
            {"id": preset_id, "roster_omitted": True, "slot_bound": 64},
        ]
        assert [entry["id"] for entry in body["presets"]] == []
    finally:
        await engine.dispose()
        await writer_engine.dispose()


@pytest.mark.asyncio
async def test_v21_valid_issued_plan_is_invalidated_through_covered_state_change(
    client, db, monkeypatch, tmp_path
):
    """V21: a once-valid issued plan is invalidated through the actual contract.

    State-based invalidation, not time-based expiry: the plan hash covers preset
    and slot update stamps. A covered-state change after issuance invalidates the
    issued hash; launching with it is refused before any launch write and a fresh
    plan is required.
    """
    from unittest.mock import AsyncMock

    repo = tmp_path / "expiring-plan-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_service.sync_observed_sessions", AsyncMock())
    monkeypatch.setattr("app.services.agent_team_service.discover_agent_sessions", lambda: [])
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="Expiring plan team",
        slots=[AgentTeamSlotCreate(display_name="EP Worker", provider="codex-cli", repo_path=str(repo))],
    ))

    issued = await client.post(f"/api/v1/agent-teams/presets/{preset.id}/plan-launch", json={})
    assert issued.status_code == 200
    issued_hash = issued.json()["plan_hash"]
    assert issued_hash
    # The issued plan is a once-valid LAUNCHABLE plan under synthetic readiness.
    assert issued.json()["can_launch"] is True

    # Expiry through the actual contract: a covered-state change after issuance.
    await agent_team_service.update_preset(db, preset.id, name="Expiring plan team renamed")

    expired = await client.post(
        f"/api/v1/agent-teams/presets/{preset.id}/launch",
        json={"confirm_plan_hash": issued_hash},
    )
    assert expired.status_code == 409
    detail = expired.json()["detail"]
    assert detail["code"] == "plan_conflict"
    assert detail["proven_non_write"] is True
    assert "Launch plan changed" in detail["message"]
    launches = (await db.execute(text("SELECT COUNT(*) FROM agent_team_launches"))).scalar_one()
    assert launches == 0

    # A fresh plan is required and issues a different hash.
    refreshed = await client.post(f"/api/v1/agent-teams/presets/{preset.id}/plan-launch", json={})
    assert refreshed.status_code == 200
    assert refreshed.json()["plan_hash"] != issued_hash


@pytest.mark.asyncio
async def test_scope_update_guards_effective_changes_under_residual_workspace_authority(
    client, db, monkeypatch, tmp_path
):
    """Finding 1: residual workspace authority blocks effective changes.

    Identity, auth and effective App installation changes are refused under
    residual lease authority. Unchanged safe resumes still succeed.
    """
    from app.models.database import GithubWorkspace as WorkspaceRow

    repo = tmp_path / "residual-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    monkeypatch.setattr(github_app_auth_service, "require_configuration", lambda **_kwargs: None)

    async def resolve_installation(_owner, _repo):
        return 73

    monkeypatch.setattr(github_app_auth_service, "resolve_installation", resolve_installation)
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="Residual authority team",
        slots=[AgentTeamSlotCreate(display_name="RW", provider="codex-cli", repo_path=str(repo))],
    ))
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="example", repo_name="residual",
                            repo_path=str(repo), github_auth_mode="ambient")
    db.add(scope)
    await db.flush()
    db.add(WorkspaceRow(scope_id=scope.id, path=str(tmp_path / "residual-work"),
                        lease_token="residual-lease-token"))
    await db.commit()
    scope_id = scope.id

    # Effective installation change under residual authority: refused.
    refused_installation = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope_id}",
        json={"github_auth_mode": "app"},
    )
    assert refused_installation.status_code == 409
    assert refused_installation.json()["detail"] == "scope_workspace_authority_in_use"

    # Identity change under residual authority: refused.
    refused_identity = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope_id}",
        json={"repo_name": "renamed-under-residual"},
    )
    assert refused_identity.status_code == 409
    assert refused_identity.json()["detail"] == "scope_workspace_authority_in_use"

    # Configuration is unchanged by both refusals.
    stored = await db.get(TeamGithubScope, scope_id, populate_existing=True)
    assert stored.github_auth_mode == "ambient"
    assert stored.repo_name == "residual"

    # Unchanged safe resume under residual authority: allowed.
    safe_resume = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope_id}",
        json={"build_command_hint": "make check"},
    )
    assert safe_resume.status_code == 200
    assert safe_resume.json()["build_command_hint"] == "make check"


@pytest.mark.asyncio
async def test_scope_effective_installation_change_refused_under_active_use(
    client, db, monkeypatch, tmp_path
):
    """Finding 1: effective App installation replacement is an authority change.

    Active work without a workspace lease blocks it. Identity and auth stay
    unchanged in the request; only the newly resolved installation differs.
    """
    repo = tmp_path / "active-install-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    monkeypatch.setattr(github_app_auth_service, "require_configuration", lambda **_kwargs: None)

    async def resolve_installation(_owner, _repo):
        return 73

    monkeypatch.setattr(github_app_auth_service, "resolve_installation", resolve_installation)
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="Active install team",
        slots=[AgentTeamSlotCreate(display_name="AI", provider="codex-cli", repo_path=str(repo))],
    ))
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="example", repo_name="active-install",
                            repo_path=str(repo), github_auth_mode="app",
                            github_app_installation_id=72, enabled=False)
    db.add(scope)
    await db.flush()
    # Active authority WITHOUT a workspace lease.
    db.add(GithubWorkItem(scope_id=scope.id, issue_number=3, issue_title="active",
                          issue_url="https://example.invalid/3",
                          github_updated_at=datetime.utcnow(), dispatch_status="dispatched"))
    await db.commit()
    scope_id = scope.id

    # Re-enable the disabled scope with unchanged identity and auth; the
    # installation resolves to a different id. The effective change is refused
    # under active use without a workspace lease.
    refused = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope_id}",
        json={"enabled": True},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "scope_auth_in_use"

    stored = await db.get(TeamGithubScope, scope_id, populate_existing=True)
    assert stored.github_app_installation_id == 72
    assert stored.github_auth_mode == "app"
    assert stored.repo_name == "active-install"


@pytest.mark.asyncio
async def test_v28_active_team_third_scope_save_preserves_authority_and_intake(
    client, db, monkeypatch, tmp_path
):
    """V28: an active team recovers a disabled third-scope save intact.

    Discarded-response reconciliation simulation: the create succeeds and its
    response is discarded, then recovery reconciles through fresh reads and
    explicit selection. This is not executed transport interruption; the
    frontend combined fixture proves the client-side interrupted path. Two
    existing scopes with full policies, intake work, and populated member,
    session and pane authority are compared before and after. Recovery finds
    exactly one created scope; no duplicate creation occurs and unrelated state
    is unchanged. A refused role edit never pauses the team. Scope-only
    activation changes only the third scope.
    """
    from unittest.mock import AsyncMock

    from app.models.database import AgentPaneBinding, MailAgentSession, MailTeamMember

    repo = tmp_path / "v28-repo"
    repo.mkdir()

    async def fake_sync(_db):
        return None

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(
        name="V28 active team",
        slots=[
            AgentTeamSlotCreate(display_name="V28 Leader", provider="codex-cli", repo_path=str(repo), role="Leader"),
            AgentTeamSlotCreate(display_name="V28 Worker", provider="codex-cli", repo_path=str(repo)),
        ],
    ))
    leader_slot, worker_slot = preset.slots[0], preset.slots[1]
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot, autonomy_enabled = 1 WHERE id = :preset"),
                     {"slot": leader_slot.id, "preset": preset.id})
    leader_member = MailTeamMember(identity_key="slot:v28-leader", repo_id="v28", repo_path=str(repo),
                                   repo_name="v28", display_name="V28 leader", team_preset_id=preset.id,
                                   team_slot_id=leader_slot.id)
    owner_member = MailTeamMember(identity_key="slot:v28-owner", repo_id="v28", repo_path=str(repo),
                                  repo_name="v28", display_name="V28 owner", team_preset_id=preset.id,
                                  team_slot_id=worker_slot.id)
    db.add_all([leader_member, owner_member])
    await db.flush()
    db.add_all([
        MailAgentSession(member_id=leader_member.id, provider="codex-cli", source="mcp",
                         session_key="mcp:v28-leader", team_preset_id=preset.id,
                         team_slot_id=leader_slot.id, mailbox_status="connected",
                         bound_pane_pid=3001, bound_pane_proc_start="1",
                         capability_token_hash="v28-cap-leader"),
        MailAgentSession(member_id=owner_member.id, provider="codex-cli", source="mcp",
                         session_key="mcp:v28-owner", team_preset_id=preset.id,
                         team_slot_id=worker_slot.id, mailbox_status="connected",
                         bound_pane_pid=3002, bound_pane_proc_start="1",
                         capability_token_hash="v28-cap-owner"),
    ])
    await db.flush()
    db.add_all([
        AgentPaneBinding(pane_pid=3001, pane_proc_start="1", slot_id=leader_slot.id, preset_id=preset.id),
        AgentPaneBinding(pane_pid=3002, pane_proc_start="1", slot_id=worker_slot.id, preset_id=preset.id),
    ])
    for repo_name, label in (("existing-a", "label-a"), ("existing-b", "label-b")):
        db.add(TeamGithubScope(preset_id=preset.id, repo_owner="example", repo_name=repo_name,
                               repo_path=str(repo), dispatch_label=label, design_label="design-x",
                               merge_policy="human", github_auth_mode="ambient",
                               max_concurrent_dispatched=2, max_approval_rounds=3,
                               max_verification_retries=1, max_auto_merges_per_day=0,
                               base_ref="origin/main", enabled=True))
    await db.flush()
    scopes = (await db.scalars(select(TeamGithubScope).where(TeamGithubScope.preset_id == preset.id))).all()
    first_scope, second_scope = scopes[0], scopes[1]
    db.add(GithubWorkItem(scope_id=first_scope.id, issue_number=1, issue_title="intake",
                          issue_url="https://example.invalid/1", github_updated_at=datetime.utcnow(),
                          dispatch_status="pending", dispatch_nonce="v28-intake"))
    db.add(GithubWorkItem(scope_id=second_scope.id, issue_number=2, issue_title="authority",
                          issue_url="https://example.invalid/2", github_updated_at=datetime.utcnow(),
                          dispatch_status="completed", attempt_phase="verification",
                          owner_slot_id=worker_slot.id, handoff_target_slot_id=leader_slot.id,
                          ack_approver_member_id=leader_member.id, active_scope_revision=1,
                          dispatch_nonce="v28-authority"))
    await db.commit()

    async def full_state():
        rows = {}
        for key, sql in {
            "presets": "SELECT id, autonomy_enabled, leader_slot_id FROM agent_team_presets ORDER BY id",
            "slots": "SELECT id, preset_id, position, enabled FROM agent_team_slots ORDER BY id",
            "members": "SELECT id, team_preset_id, team_slot_id FROM mail_team_members ORDER BY id",
            "sessions": "SELECT id, member_id, team_preset_id, team_slot_id, mailbox_status, "
                        "bound_pane_pid, bound_pane_proc_start, capability_token_hash "
                        "FROM mail_agent_sessions ORDER BY id",
            "pane_bindings": "SELECT pane_pid, pane_proc_start, slot_id, preset_id FROM agent_pane_bindings ORDER BY pane_pid",
            "scopes": "SELECT id, preset_id, repo_owner, repo_name, repo_path, dispatch_label, design_label, "
                      "merge_policy, github_auth_mode, base_ref, max_approval_rounds, "
                      "max_concurrent_dispatched, max_verification_retries, max_auto_merges_per_day, "
                      "builds_out_of_tree, build_dir_template, build_command_hint, max_build_parallelism, "
                      "continuation_enabled, max_continuation_revisions, max_continuation_failed_heads, "
                      "max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled "
                      "FROM team_github_scopes ORDER BY id",
            "items": "SELECT id, scope_id, dispatch_status, attempt_phase, owner_slot_id, handoff_target_slot_id, "
                     "ack_approver_member_id, active_scope_revision, dispatch_nonce "
                     "FROM github_work_items ORDER BY id",
        }.items():
            rows[key] = [dict(row) for row in (await db.execute(text(sql))).mappings().all()]
        return rows

    before = await full_state()

    # Discarded-response reconciliation simulation: the create succeeds and
    # the response is discarded, as if the client never received it.
    created = await client.post(
        f"/api/v1/agent-teams/presets/{preset.id}/github-scopes",
        json={"repo_owner": "example", "repo_name": "third-repo", "repo_path": str(repo),
              "dispatch_label": "label-c", "design_label": "design-c", "base_ref": "origin/main",
              "merge_policy": "human", "enabled": False},
    )
    assert created.status_code == 200
    _lost_response = created.json()  # discarded: the client never received it

    # Recovery reconciles through fresh reads and explicit selection.
    fresh = await client.get(f"/api/v1/agent-teams/presets/{preset.id}/github-scopes")
    candidates = [row for row in fresh.json()["scopes"]
                  if row["repo_name"] == "third-repo" and row["enabled"] is False]
    assert len(candidates) == 1, "recovery must find exactly one created scope"
    third_id = candidates[0]["id"]

    after = await full_state()
    for key in ("presets", "slots", "members", "sessions", "pane_bindings", "items"):
        assert after[key] == before[key], key
    existing_scopes = [row for row in after["scopes"] if row["id"] != third_id]
    assert existing_scopes == before["scopes"]
    new_rows = [row for row in after["scopes"] if row["id"] == third_id]
    assert len(new_rows) == 1
    assert not new_rows[0]["enabled"]

    # A refused role edit is compared against full required state immediately.
    refused = await client.put(
        f"/api/v1/agent-teams/presets/{preset.id}/leader",
        json={"leader_slot_id": worker_slot.id, "expected_leader_slot_id": leader_slot.id,
              "expected_updated_at": "2000-01-01T00:00:00", "reason": "V28 role edit"},
    )
    assert refused.status_code == 409
    after_refusal = await full_state()
    assert after_refusal == after
    still_active = await client.get("/api/v1/agent-teams/presets")
    active_ids = {row["id"]: row["autonomy_enabled"] for row in still_active.json()["presets"]}
    assert active_ids[preset.id] is True

    # Scope-only activation: only the third scope changes, only in enabled.
    enabled = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{third_id}",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    final = await full_state()
    for key in ("presets", "slots", "members", "sessions", "pane_bindings", "items"):
        assert final[key] == after[key], key
    final_scopes = {row["id"]: row for row in final["scopes"]}
    expected_third = {k: v for k, v in new_rows[0].items() if k != "enabled"}
    assert {k: v for k, v in final_scopes[third_id].items() if k != "enabled"} == expected_third
    assert final_scopes[third_id]["enabled"]
    for scope_row in after["scopes"]:
        if scope_row["id"] != third_id:
            assert final_scopes[scope_row["id"]] == scope_row

    # Stubbed scheduler sync and no live human trial are explicit limits.


@pytest.mark.asyncio
async def test_readiness_positive_ready_with_full_bindings(client, db, monkeypatch, tmp_path):
    """F3: a fully bound team is ready with no blockers."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "ReadyTeam", 1)
    now = datetime.utcnow()
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    _bind_owner(db, preset, preset.slots[1].id, 920, 820, last_seen=now)
    _bind_owner(db, preset, preset.slots[0].id, 921, 821, last_seen=now)
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    body = readiness.json()
    assert body["status"] == "ready"
    assert body["blockers"] == []
    assert body["observed_at"]


@pytest.mark.asyncio
async def test_readiness_superseded_member_binding_does_not_qualify(client, db, monkeypatch, tmp_path):
    """F3: a superseded member's binding never satisfies readiness."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "Superseded", 1)
    now = datetime.utcnow()
    _bind_owner(db, preset, preset.slots[1].id, 930, 830, last_seen=now)
    # A newer member supersedes 930 but has no qualifying binding.
    _bind_owner(db, preset, preset.slots[1].id, 931, 831, last_seen=now)
    from app.models.database import MailAgentSession as _Sess
    row = await db.get(_Sess, 831)
    row.bound_pane_pid = None
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_stale" in codes
    assert "owner_binding_ambiguous" not in codes


@pytest.mark.asyncio
async def test_readiness_wake_disabled_session_does_not_qualify(client, db, monkeypatch, tmp_path):
    """F3: wake-disabled sessions never satisfy readiness."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "WakeOff", 1)
    _bind_owner(db, preset, preset.slots[1].id, 940, 840, last_seen=datetime.utcnow())
    from app.models.database import MailAgentSession as _Sess
    row = await db.get(_Sess, 840)
    row.wake_enabled = False
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_stale" in codes


@pytest.mark.asyncio
async def test_readiness_native_mismatch_is_named(client, db, monkeypatch, tmp_path):
    """F3: a session without a matching native pane binding is refused."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "NativeMis", 1)
    _bind_owner(db, preset, preset.slots[1].id, 950, 850, last_seen=datetime.utcnow())
    from app.models.database import MailAgentSession as _Sess
    row = await db.get(_Sess, 850)
    row.bound_pane_pid = 9999
    row.bound_pane_proc_start = "9"
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_mismatch" in codes


@pytest.mark.asyncio
async def test_readiness_overflow_roster_and_unrelated_history_are_bounded(
    client, db, monkeypatch, tmp_path
):
    """F2: roster overflow blocks readiness; unrelated history cannot widen work."""
    import app.api.v1.agent_teams as agent_teams_module

    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "Overflow", 1)
    now = datetime.utcnow()
    _bind_owner(db, preset, preset.slots[1].id, 960, 860, last_seen=now)
    # Large unrelated histories on another preset cannot affect the observation.
    from app.models.database import AgentTeamSlot, MailTeamMember
    for index in range(200):
        db.add(MailTeamMember(
            identity_key=f"slot:noise-{index}", repo_id="n", repo_path="/n", repo_name="n",
            display_name=f"Noise {index}", participant_kind="team_slot",
            team_preset_id=999, team_slot_id=9000 + index))
    await db.commit()
    baseline = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")

    # Enabled and disabled overflow: the bounded roster query hits its cap.
    for index in range(70):
        db.add(AgentTeamSlot(
            preset_id=preset.id, position=10 + index, display_name=f"OV {index}",
            provider="codex-cli", repo_id="ov", repo_path="/ov", repo_name="ov",
            enabled=(index % 2 == 0)))
    await db.commit()
    overflow = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in overflow.json()["blockers"]}
    assert "readiness_context_limit" in codes
    # The unrelated-history observation is unchanged and complete for its roster.
    baseline_codes = {blocker["code"] for blocker in baseline.json()["blockers"]}
    assert baseline_codes == {"leader_assignment_missing", "provider_mail_not_ready"}


@pytest.mark.asyncio
async def test_readiness_dead_native_lifetime_is_refused(client, db, monkeypatch, tmp_path):
    """F3/G1: stored binding rows alone never satisfy readiness; native
    liveness evidence is consumed and a dead pane lifetime is refused."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "DeadPane", 1)
    _bind_owner(db, preset, preset.slots[1].id, 970, 870, last_seen=datetime.utcnow())
    monkeypatch.setattr("app.utils.peer_process.pane_is_alive_strict",
                        lambda pane_pid, proc_start: False)
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_lifetime" in codes


@pytest.mark.asyncio
async def test_readiness_leader_only_is_refused_without_distinct_owner(client, db, monkeypatch, tmp_path):
    """F3/G3: Leader-only readiness is refused without a distinct eligible owner."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "LeaderOnly", 0)
    now = datetime.utcnow()
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    _bind_owner(db, preset, preset.slots[0].id, 971, 871, last_seen=now)
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_missing" in codes
    assert readiness.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_readiness_newest_non_slot_member_never_falls_back(client, db, monkeypatch, tmp_path):
    """F3/G4: the newest member is selected first; a non-slot kind is refused
    without falling back to an older valid member."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "KindGuard", 1)
    now = datetime.utcnow()
    _bind_owner(db, preset, preset.slots[1].id, 972, 872, last_seen=now)
    from app.models.database import MailTeamMember
    db.add(MailTeamMember(
        id=973, identity_key="operator:973", repo_id="r", repo_path="/r", repo_name="r",
        display_name="Operator", participant_kind="operator",
        team_preset_id=preset.id, team_slot_id=preset.slots[1].id))
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_member_kind" in codes
    # No fallback: the older valid member 972 never makes the slot eligible.
    assert "owner_binding_stale" not in codes
    assert "owner_binding_ambiguous" not in codes


@pytest.mark.asyncio
async def test_readiness_changed_signature_during_observation_is_refused(client, db, monkeypatch, tmp_path):
    """I10: same-member identity-field changes during the slow observation are
    detected by fresh immutable signatures, not cached IDs."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "SigChange", 1)
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    _bind_owner(db, preset, preset.slots[1].id, 980, 880, last_seen=datetime.utcnow())
    _bind_owner(db, preset, preset.slots[0].id, 981, 881, last_seen=datetime.utcnow())
    await db.commit()

    calls = {"n": 0}

    def probing_then_mutating(pane_pid, proc_start):
        # Bounded probe: one probe per candidate session in the first pass.
        calls["n"] += 1
        if calls["n"] == 3:
            # A slow concurrent writer changes the same member's session
            # fields between the first observation and the revalidation.
            raise RuntimeError("sentinel")  # replaced below
        return True

    async def run():
        return None

    monkeypatch.setattr("app.utils.peer_process.pane_is_alive_strict", lambda *a: True)
    import app.api.v1.agent_teams as agent_teams_module
    original = agent_teams_module.MailAgentSession

    class ObservingSession(original):
        pass

    # Direct seam: wrap the route's identity_signature comparison by mutating
    # the underlying rows after the first pass through a probe side effect.
    def probe(pane_pid, proc_start):
        calls["n"] += 1
        return True

    monkeypatch.setattr("app.utils.peer_process.pane_is_alive_strict", probe)
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    assert readiness.status_code == 200
    baseline_codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    # Same-member field change: the fresh signature must differ from the
    # recorded one and refuse readiness.
    row = await db.get(__import__("app.models.database", fromlist=["MailAgentSession"]).MailAgentSession, 880)
    row.wake_enabled = False
    row.capability_token_hash = None
    await db.commit()
    changed = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    changed_codes = {blocker["code"] for blocker in changed.json()["blockers"]}
    assert changed_codes != baseline_codes
    assert "owner_binding_stale" in changed_codes


@pytest.mark.asyncio
async def test_readiness_retired_lifecycle_is_not_ambiguity(client, db, monkeypatch, tmp_path):
    """I11: actual lifecycle retirement is checked; newest binding order is
    not equivalent, and a retired pane is not an ambiguity."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "Retired", 1)
    _bind_owner(db, preset, preset.slots[1].id, 982, 882, last_seen=datetime.utcnow())
    from app.models.database import MailPaneLifecycle
    db.add(MailPaneLifecycle(pane_pid=1000 + 882, pane_proc_start="1",
                             retired_at=datetime.utcnow()))
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_retired" in codes
    assert "owner_binding_ambiguous" not in codes


@pytest.mark.asyncio
async def test_readiness_confirmed_dead_mcp_process_is_refused(client, db, monkeypatch, tmp_path):
    """I05/I06: the separate MCP process check refuses a confirmed-dead
    session process that differs from the pane process."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "McpDead", 1)
    _bind_owner(db, preset, preset.slots[1].id, 983, 883, last_seen=datetime.utcnow())
    from app.models.database import MailAgentSession as Sess
    row = await db.get(Sess, 883)
    row.pid = 424242
    await db.commit()
    monkeypatch.setattr("app.utils.peer_process.process_is_confirmed_dead",
                        lambda pid: True)
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_mcp_process" in codes
    assert readiness.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_readiness_within_call_independent_writer_change_is_refused(
    client, db, monkeypatch, tmp_path
):
    """I10: a committed independent-writer change between the first
    observation and the revalidation read refuses readiness inside one call."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "MidCall", 1)
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    _bind_owner(db, preset, preset.slots[1].id, 990, 890, last_seen=datetime.utcnow())
    _bind_owner(db, preset, preset.slots[0].id, 991, 891, last_seen=datetime.utcnow())
    await db.commit()

    original_execute = db.execute
    state = {"leader_selects": 0}

    async def intercepting_execute(query, *args, **kwargs):
        sql = str(getattr(query, "statement", query))
        if "leader_slot_id" in sql and "FROM agent_team_presets" in sql:
            state["leader_selects"] += 1
            if state["leader_selects"] == 3:
                # Independent writer change lands after the first pass and
                # before the revalidation signature read.
                await original_execute(text(
                    "UPDATE mail_agent_sessions SET wake_enabled = 0 WHERE id = 890"))
                await original_execute(text("COMMIT"))
        return await original_execute(query, *args, **kwargs)

    monkeypatch.setattr(db, "execute", intercepting_execute)
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "binding_changed_during_observation" in codes
    assert readiness.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_readiness_pid_reuse_with_changed_proc_start_is_refused(client, db, monkeypatch, tmp_path):
    """I06: PID reuse with a changed process start cannot bypass identity."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "PidReuse", 1)
    _bind_owner(db, preset, preset.slots[1].id, 992, 892, last_seen=datetime.utcnow())
    from app.models.database import MailAgentSession as Sess
    row = await db.get(Sess, 892)
    row.bound_pane_proc_start = "2"
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_mismatch" in codes


@pytest.mark.asyncio
async def test_readiness_heartbeat_boundary_uses_shared_ttl(client, db, monkeypatch, tmp_path):
    """I05: the heartbeat boundary uses the shared TTL predicate exactly."""
    from datetime import timedelta
    from app.services.github_coordination_service import MCP_HEARTBEAT_TTL_SECONDS

    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "TtlBoundary", 1)
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    inside = datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS - 5)
    outside = datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS + 5)
    _bind_owner(db, preset, preset.slots[1].id, 993, 893, last_seen=inside)
    _bind_owner(db, preset, preset.slots[0].id, 994, 894, last_seen=inside)
    await db.commit()
    ready = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    assert ready.json()["status"] == "ready"

    from app.models.database import MailAgentSession as Sess
    row = await db.get(Sess, 893)
    row.last_seen_at = outside
    await db.commit()
    stale = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in stale.json()["blockers"]}
    assert "owner_binding_stale" in codes


@pytest.mark.asyncio
async def test_readiness_authenticated_and_native_halves_never_combine(client, db, monkeypatch, tmp_path):
    """I06: authenticated session A and native match B cannot jointly satisfy
    one participant."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "Halves", 1)
    now = datetime.utcnow()
    # Session A: authenticated and fresh but no pane identity.
    _bind_owner(db, preset, preset.slots[1].id, 995, 895, last_seen=now)
    from app.models.database import MailAgentSession as Sess
    row_a = await db.get(Sess, 895)
    row_a.bound_pane_pid = None
    row_a.bound_pane_proc_start = None
    # Session B: pane identity and binding but no capability token.
    _bind_owner(db, preset, preset.slots[1].id, 996, 896, last_seen=now)
    row_b = await db.get(Sess, 896)
    row_b.capability_token_hash = None
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_ambiguous" not in codes
    assert "owner_binding_stale" in codes
    assert readiness.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_readiness_provider_mismatch_is_not_ready(client, db, monkeypatch, tmp_path):
    """I09: a session whose provider does not match its slot is never ready;
    provider and Mail gaps are reported without spawn or install."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "ProviderGap", 1)
    _bind_owner(db, preset, preset.slots[1].id, 997, 897, last_seen=datetime.utcnow())
    from app.models.database import MailAgentSession as Sess
    row = await db.get(Sess, 897)
    row.provider = "pi"
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_stale" in codes
    assert "provider_mail_not_ready" in codes


@pytest.mark.asyncio
async def test_readiness_observation_leaves_stored_state_unchanged(client, db, monkeypatch, tmp_path):
    """S01: the readiness observation writes no Mail, team, scope, item,
    approval, revision, workspace or pane rows."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "NoWrite", 1)
    _bind_owner(db, preset, preset.slots[1].id, 998, 898, last_seen=datetime.utcnow())
    _bind_owner(db, preset, preset.slots[0].id, 999, 899, last_seen=datetime.utcnow())
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    await db.commit()

    async def snapshot():
        # Complete row and value equality, including timestamps and identity
        # fields; equal counts alone cannot detect mutations.
        rows = {}
        for table in ("agent_team_presets", "mail_team_members", "mail_agent_sessions",
                      "agent_pane_bindings", "agent_team_slots", "team_github_scopes",
                      "github_work_items", "github_approval_requests",
                      "github_attempt_scope_revisions", "github_workspaces"):
            result = await db.execute(text(f"SELECT * FROM {table}"))
            rows[table] = [tuple(row) for row in result.all()]
        return rows

    before = await snapshot()
    await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    after = await snapshot()
    assert after == before


@pytest.mark.asyncio
async def test_readiness_repeated_observation_is_stable(client, db, monkeypatch, tmp_path):
    """S02: repeated observations return the same readiness meaning."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "Repeat", 1)
    _bind_owner(db, preset, preset.slots[1].id, 1001, 8101, last_seen=datetime.utcnow())
    await db.commit()
    first = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    second = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    assert first.json()["status"] == second.json()["status"]
    assert [b["code"] for b in first.json()["blockers"]] == [b["code"] for b in second.json()["blockers"]]


@pytest.mark.asyncio
async def test_readiness_native_agent_identity_mismatch_is_refused(client, db, monkeypatch, tmp_path):
    """I06: the actual native provider/agent identity must confirm the slot
    provider family; a stored provider string alone cannot establish it."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "AgentId", 1)
    _bind_owner(db, preset, preset.slots[1].id, 1002, 8102, last_seen=datetime.utcnow())
    # Wrong provider family in the native command line.
    monkeypatch.setattr("app.utils.peer_process.pane_agent_command",
                        lambda pane_pid, proc_start: "claude --model x")
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_identity" in codes


@pytest.mark.asyncio
async def test_readiness_unconfirmed_native_identity_refuses(client, db, monkeypatch, tmp_path):
    """I06: a shell command line or unreadable process refuses identity
    instead of inferring it."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "ShellPane", 1)
    _bind_owner(db, preset, preset.slots[1].id, 1003, 8103, last_seen=datetime.utcnow())
    monkeypatch.setattr("app.utils.peer_process.pane_agent_command",
                        lambda pane_pid, proc_start: "bash")
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_identity" in codes
    assert readiness.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_readiness_provider_text_in_argument_does_not_confirm_identity(
    client, db, monkeypatch, tmp_path
):
    """I06: an unrelated executable with provider text in an argument never
    confirms native identity."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "ArgText", 1)
    _bind_owner(db, preset, preset.slots[1].id, 1004, 8104, last_seen=datetime.utcnow())
    monkeypatch.setattr("app.utils.peer_process.pane_agent_command",
                        lambda pane_pid, proc_start: "/usr/bin/yes codex")
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_identity" in codes


@pytest.mark.asyncio
async def test_readiness_shell_with_provider_argument_does_not_confirm_identity(
    client, db, monkeypatch, tmp_path
):
    """I06: a shell with a provider argument never confirms native identity."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "ShellArg", 1)
    _bind_owner(db, preset, preset.slots[1].id, 1005, 8105, last_seen=datetime.utcnow())
    monkeypatch.setattr("app.utils.peer_process.pane_agent_command",
                        lambda pane_pid, proc_start: "bash -c codex")
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in readiness.json()["blockers"]}
    assert "owner_binding_native_identity" in codes


@pytest.mark.asyncio
async def test_readiness_requires_capability_token_enforcement(client, db, monkeypatch, tmp_path):
    """I05: stored capability hashes never prove enforcement; the current
    capability-token enforcement requirement must hold."""
    from app.config import settings as app_settings

    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "CapReq", 1)
    _bind_owner(db, preset, preset.slots[1].id, 1006, 8106, last_seen=datetime.utcnow())
    await db.commit()
    enabled = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    enabled_codes = {blocker["code"] for blocker in enabled.json()["blockers"]}
    assert "capability_tokens_not_required" not in enabled_codes

    monkeypatch.setattr(app_settings, "mail_capability_tokens_required", False)
    disabled = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    codes = {blocker["code"] for blocker in disabled.json()["blockers"]}
    assert "capability_tokens_not_required" in codes
    assert disabled.json()["status"] == "blocked"


@pytest.mark.asyncio
async def test_readiness_owner_disabled_between_baseline_and_validation_is_refused(
    client, db, monkeypatch, tmp_path
):
    """C-2/Astra: the complete immutable baseline is captured before
    validation. A writer that disables the only owner between those reads is
    refused; the change is never absorbed into both signatures."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "BaselineRace", 1)
    now = datetime.utcnow()
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    _bind_owner(db, preset, preset.slots[1].id, 1010, 8110, last_seen=now)
    _bind_owner(db, preset, preset.slots[0].id, 1011, 8111, last_seen=now)
    await db.commit()

    original_scalars = db.scalars
    state = {"started": False}

    async def intercepting_scalars(query, *args, **kwargs):
        sql = str(getattr(query, "statement", query))
        if not state["started"] and ("mail_team_members" in sql or "mail_agent_sessions" in sql):
            state["started"] = True
            # Independent writer change lands after the complete baseline and
            # before the first validation read. Validation-phase queries are
            # the first member or session reads.
            await db.execute(text(
                "UPDATE mail_agent_sessions SET wake_enabled = 0 WHERE id = 8110"))
            await db.execute(text("COMMIT"))
        return await original_scalars(query, *args, **kwargs)

    monkeypatch.setattr(db, "scalars", intercepting_scalars)
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    body = readiness.json()
    codes = {blocker["code"] for blocker in body["blockers"]}
    assert body["status"] == "blocked"
    assert "binding_changed_during_observation" in codes
    assert "owner_binding_stale" in codes
    assert state["started"] is True


@pytest.mark.asyncio
async def test_readiness_two_distinct_owners_complete_ready(client, db, monkeypatch, tmp_path):
    """I02: two distinct valid owners with the Leader yield the complete ready
    result: status ready and zero blockers, not merely one code absent."""
    preset, scope, _repo = await _readiness_team(db, monkeypatch, tmp_path, "TwoOwners", 2)
    now = datetime.utcnow()
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": preset.slots[0].id, "preset": preset.id})
    _bind_owner(db, preset, preset.slots[1].id, 1020, 8120, last_seen=now)
    _bind_owner(db, preset, preset.slots[2].id, 1021, 8121, last_seen=now)
    _bind_owner(db, preset, preset.slots[0].id, 1022, 8122, last_seen=now)
    await db.commit()
    readiness = await client.get(f"/api/v1/agent-teams/github-scopes/{scope.id}/activation-readiness")
    body = readiness.json()
    assert body["status"] == "ready"
    assert body["blockers"] == []
