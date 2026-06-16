"""HTTP contract tests for Agent Team presets."""
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
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
