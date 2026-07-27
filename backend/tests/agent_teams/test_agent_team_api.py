"""HTTP contract tests for Agent Team presets."""
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.database import AgentTeamPreset, GithubWorkItem, TeamGithubScope
from app.models.schemas import AgentTeamPresetCreate, AgentTeamSlotCreate
from app.services.agent_team_service import agent_team_service


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
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
async def test_github_scope_crud_endpoints(client, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sync_calls = 0

    async def fake_sync(_db):
        nonlocal sync_calls
        sync_calls += 1

    monkeypatch.setattr("app.api.v1.agent_teams._sync_github_jobs", fake_sync)

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
            "enabled": True,
        },
    )
    assert create_response.status_code == 200
    scope = create_response.json()
    assert scope["repo_owner"] == "adrirubio"
    assert scope["merge_policy"] == "auto"
    assert scope["max_verification_retries"] == 3

    list_response = await client.get(
        f"/api/v1/agent-teams/presets/{preset_id}/github-scopes"
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["scopes"]] == [scope["id"]]

    update_response = await client.patch(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}",
        json={"merge_policy": "human", "enabled": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["merge_policy"] == "human"
    assert update_response.json()["enabled"] is False

    delete_response = await client.delete(
        f"/api/v1/agent-teams/github-scopes/{scope['id']}"
    )
    assert delete_response.status_code == 204
    assert sync_calls == 3


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
    assert "865" in response.json()["detail"]
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
    await db.refresh(item)
    assert item.dispatch_status == "pending"
