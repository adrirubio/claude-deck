"""Schema tests for the autonomous GitHub dispatch tables."""
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base, _run_sqlite_compat_migrations
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    TeamGithubScope,
    GithubWorkItem,
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


@pytest.mark.asyncio
async def test_team_github_scope_round_trips(db):
    preset = AgentTeamPreset(name="SnazzyEmail", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="adrirubio",
        repo_name="snazzyemail",
        repo_path="/tmp/snazzyemail",
    )
    db.add(scope)
    await db.commit()
    await db.refresh(scope)
    assert scope.dispatch_label == "claude-deck-ready"
    assert scope.design_label == "claude-deck-design"
    assert scope.merge_policy == "human"
    assert scope.max_approval_rounds == 3
    assert scope.enabled is True


@pytest.mark.asyncio
async def test_github_work_item_defaults(db):
    preset = AgentTeamPreset(name="T", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id, repo_owner="o", repo_name="r", repo_path="/tmp/r"
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=42,
        issue_title="bug",
        issue_url="https://github.com/o/r/issues/42",
        github_updated_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    assert item.issue_type == "code"
    assert item.dispatch_status == "pending"
    assert item.pending_reason is None
    assert item.approval_round_count == 0
    assert item.retry_count == 0
    assert item.handoff_state is None
    assert item.status_note is None


@pytest.mark.asyncio
async def test_new_columns_on_existing_tables(db):
    preset = AgentTeamPreset(name="T2", description="", created_by="test", autonomy_enabled=True)
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id, position=0, display_name="Backend SME",
        provider="codex-cli", repo_id="r", repo_path="/tmp/r", repo_name="r",
        launch_mode="plain", launch_options={}, enabled=True,
        area_labels=["area:backend"], expertise="owns the backend",
    )
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    await db.refresh(preset)
    assert preset.autonomy_enabled is True
    assert slot.area_labels == ["area:backend"]
    assert slot.expertise == "owns the backend"


@pytest.mark.asyncio
async def test_compat_migration_adds_new_columns_to_legacy_db():
    """Simulate a pre-existing db missing the new columns, then migrate."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Legacy agent_team_presets WITHOUT autonomy_enabled
        await conn.execute(text(
            "CREATE TABLE agent_team_presets (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name VARCHAR NOT NULL, description VARCHAR, created_by VARCHAR, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        # Legacy agent_team_slots WITHOUT area_labels/expertise
        await conn.execute(text(
            "CREATE TABLE agent_team_slots (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "preset_id INTEGER NOT NULL, position INTEGER NOT NULL, display_name VARCHAR NOT NULL, "
            "provider VARCHAR NOT NULL, repo_id VARCHAR NOT NULL, repo_path VARCHAR NOT NULL, "
            "repo_name VARCHAR NOT NULL, role VARCHAR, charter VARCHAR, bootstrap_prompt VARCHAR, "
            "ui_color VARCHAR, launch_mode VARCHAR NOT NULL, launch_options JSON, "
            "enabled BOOLEAN NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        await conn.execute(text("CREATE TABLE github_work_items (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    async with engine.connect() as conn:
        await _run_sqlite_compat_migrations(conn)
    async with engine.connect() as conn:
        preset_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_presets)"))).fetchall()}
        slot_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_slots)"))).fetchall()}
        work_item_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(github_work_items)"))).fetchall()}
    assert "autonomy_enabled" in preset_cols
    assert "area_labels" in slot_cols
    assert "expertise" in slot_cols
    assert "status_note" in work_item_cols
    await engine.dispose()
