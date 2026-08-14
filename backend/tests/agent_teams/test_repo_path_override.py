"""repo_path_override threads through the launch path to spawn options."""
import pytest
import pytest_asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import AgentTeamPreset, AgentTeamSlot
from app.models.schemas import AgentTeamLaunchRequest
from app.services.agent_team_service import agent_team_service


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_launch_request_accepts_repo_path_override():
    req = AgentTeamLaunchRequest(repo_path_override="/tmp/other-repo", skip_plan_confirmation=True)
    assert req.repo_path_override == "/tmp/other-repo"


@pytest.mark.asyncio
async def test_override_directory_used_in_spawn(db, tmp_path):
    override_dir = tmp_path / "override-repo"
    override_dir.mkdir()
    slot_dir = tmp_path / "slot-repo"
    slot_dir.mkdir()

    preset = AgentTeamPreset(name="T", description="", created_by="t")
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id, position=0, display_name="Dev", provider="claude-code",
        repo_id="r", repo_path=str(slot_dir), repo_name="slot-repo",
        launch_mode="plain", launch_options={}, enabled=True,
    )
    db.add(slot)
    await db.commit()

    captured = {}

    def fake_spawn(provider, options, extra_env=None):
        captured["directory"] = options.directory
        return {"session_name": "s", "tmux_target": "s:0.0"}

    fake_provider = SimpleNamespace(
        display_name="Claude Code",
        get_status=lambda: {"installed": True},
        build_spawn_command=lambda options: ["claude"],
    )
    fake_install_status = SimpleNamespace(
        claude_code_mcp_installed=True,
        claude_code_hooks_missing=[],
    )

    with (
        patch("app.services.agent_team_service.get_provider", return_value=fake_provider),
        patch(
            "app.services.agent_team_service.agent_mail_install_service.get_install_status",
            AsyncMock(return_value=fake_install_status),
        ),
        patch(
            "app.services.agent_team_service.agent_mail_service.sync_observed_sessions",
            AsyncMock(),
        ),
        patch.object(agent_team_service, "_discover_sessions", return_value=[]),
        patch("app.services.agent_team_service.spawn_session", side_effect=fake_spawn),
    ):
        req = AgentTeamLaunchRequest(
            skip_plan_confirmation=True,
            repo_path_override=str(override_dir),
        )
        await agent_team_service.launch(db, preset.id, req)

    assert captured["directory"] == str(override_dir)
