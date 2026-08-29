"""Schema tests for the autonomous GitHub dispatch tables."""
import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base, _run_sqlite_compat_migrations
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    TeamGithubScope,
    GithubWorkItem,
    GithubWorkspace,
)
from app.models.schemas import TeamGithubContinuationPolicyUpdate


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
    assert scope.max_concurrent_dispatched == 3
    assert scope.max_verification_retries == 2
    assert scope.max_auto_merges_per_day == 5
    assert scope.base_ref == "origin/HEAD"
    assert scope.builds_out_of_tree is False
    assert scope.build_dir_template == "build"
    assert scope.build_command_hint is None
    assert scope.max_build_parallelism == 4
    assert scope.continuation_enabled is False
    assert scope.max_continuation_revisions == 6
    assert scope.max_continuation_failed_heads == 8
    assert scope.max_failed_heads_per_revision == 2
    assert scope.max_scope_paths == 32
    assert scope.max_scope_commands == 16
    assert scope.enabled is True


def test_continuation_policy_rejects_invalid_caps():
    with pytest.raises(ValidationError):
        TeamGithubContinuationPolicyUpdate(
            continuation_enabled=True,
            max_continuation_revisions=6,
            max_continuation_failed_heads=2,
            max_failed_heads_per_revision=3,
            max_scope_paths=32,
            max_scope_commands=16,
        )
    for field in ("max_scope_paths", "max_scope_commands"):
        values = {
            "continuation_enabled": True,
            "max_continuation_revisions": 6,
            "max_continuation_failed_heads": 8,
            "max_failed_heads_per_revision": 2,
            "max_scope_paths": 32,
            "max_scope_commands": 16,
        }
        values[field] = 0
        with pytest.raises(ValidationError):
            TeamGithubContinuationPolicyUpdate(**values)


@pytest.mark.asyncio
async def test_github_workspace_defaults(db):
    preset = AgentTeamPreset(name="Workspace", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo",
        repo_path="/tmp/repo",
    )
    db.add(scope)
    await db.flush()
    workspace = GithubWorkspace(scope_id=scope.id, path="/tmp/repo-ws1")
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    assert workspace.kind == "worktree"
    assert workspace.enabled is True
    assert workspace.dispatchable is True
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_github_workspace_leased_item_is_unique(db):
    preset = AgentTeamPreset(name="Lease", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo",
        repo_path="/tmp/repo",
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="Issue",
        issue_url="https://github.com/owner/repo/issues/1",
        github_updated_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    db.add_all([
        GithubWorkspace(scope_id=scope.id, path="/tmp/repo-ws1", leased_item_id=item.id),
        GithubWorkspace(scope_id=scope.id, path="/tmp/repo-ws2", leased_item_id=item.id),
    ])
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_github_workspace_path_is_globally_unique(db):
    preset = AgentTeamPreset(name="Path", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scopes = [
        TeamGithubScope(
            preset_id=preset.id,
            repo_owner="owner",
            repo_name=repo_name,
            repo_path=f"/tmp/{repo_name}",
        )
        for repo_name in ("repo-a", "repo-b")
    ]
    db.add_all(scopes)
    await db.flush()
    db.add_all([
        GithubWorkspace(scope_id=scopes[0].id, path="/tmp/shared-ws"),
        GithubWorkspace(scope_id=scopes[1].id, path="/tmp/shared-ws"),
    ])
    with pytest.raises(IntegrityError):
        await db.commit()


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
    assert item.auto_merged_at is None
    assert item.active_scope_revision == 0
    assert item.attempt_phase == "implementation"
    assert item.diagnostic_retry_count == 0
    assert item.diagnostic_last_verified_sha is None
    assert item.continuation_nudged_at is None
    assert item.continuation_activated_at is None


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
        await conn.execute(text("CREATE TABLE team_github_scopes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    async with engine.connect() as conn:
        await _run_sqlite_compat_migrations(conn)
    async with engine.connect() as conn:
        preset_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_presets)"))).fetchall()}
        slot_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_slots)"))).fetchall()}
        work_item_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(github_work_items)"))).fetchall()}
        scope_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(team_github_scopes)"))).fetchall()}
    assert "autonomy_enabled" in preset_cols
    assert "area_labels" in slot_cols
    assert "expertise" in slot_cols
    assert "status_note" in work_item_cols
    assert "auto_merged_at" in work_item_cols
    assert "last_verified_sha" in work_item_cols
    assert "max_concurrent_dispatched" in scope_cols
    assert "max_verification_retries" in scope_cols
    assert "max_auto_merges_per_day" in scope_cols
    assert "base_ref" in scope_cols
    assert "builds_out_of_tree" in scope_cols
    assert "build_dir_template" in scope_cols
    assert "build_command_hint" in scope_cols
    assert "max_build_parallelism" in scope_cols
    assert {
        "continuation_enabled",
        "max_continuation_revisions",
        "max_continuation_failed_heads",
        "max_failed_heads_per_revision",
        "max_scope_paths",
        "max_scope_commands",
    } <= scope_cols
    assert {
        "active_scope_revision",
        "attempt_phase",
        "diagnostic_retry_count",
        "diagnostic_last_verified_sha",
        "continuation_nudged_at",
        "continuation_activated_at",
    } <= work_item_cols
    await engine.dispose()
