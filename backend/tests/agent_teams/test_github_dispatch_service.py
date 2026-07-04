"""Dispatch routing + concurrency tests."""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    TeamGithubScope,
)
from app.services.github_dispatch_service import github_dispatch_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _team(db):
    preset = AgentTeamPreset(name="T", description="", created_by="t")
    db.add(preset)
    await db.flush()
    architect = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Architect",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        launch_mode="plain",
        launch_options={},
        enabled=True,
        area_labels=None,
        expertise="cross-cutting",
    )
    backend = AgentTeamSlot(
        preset_id=preset.id,
        position=1,
        display_name="Backend SME",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        launch_mode="plain",
        launch_options={},
        enabled=True,
        area_labels=["area:backend"],
        expertise="backend",
    )
    db.add_all([architect, backend])
    await db.flush()
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="o", repo_name="r", repo_path="/tmp/r")
    db.add(scope)
    await db.commit()
    return preset, [architect, backend], scope


def _item(scope_id, number, labels):
    return (
        GithubWorkItem(
            scope_id=scope_id,
            issue_number=number,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="pending",
        ),
        [{"name": name} for name in labels],
    )


@pytest.mark.asyncio
async def test_route_by_label_match(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    owner_id, method = await github_dispatch_service.route_item(
        db,
        item,
        slots,
        repo_labels=["area:backend"],
        issue_labels=["area:backend"],
    )
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    assert owner_id == backend.id
    assert method == "label"


@pytest.mark.asyncio
async def test_route_classification_fallback(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=2,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")

    async def fake_classify(it, candidate_slots):
        return backend.id

    owner_id, method = await github_dispatch_service.route_item(
        db,
        item,
        slots,
        repo_labels=["area:backend"],
        issue_labels=["no-area-label"],
        classify=fake_classify,
    )
    assert owner_id == backend.id
    assert method == "classified"


@pytest.mark.asyncio
async def test_route_leader_fallback_when_no_expertise(db):
    preset, slots, scope = await _team(db)
    for slot in slots:
        slot.expertise = None
    await db.commit()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=3,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    owner_id, method = await github_dispatch_service.route_item(
        db, item, slots, repo_labels=[], issue_labels=["nothing"]
    )
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    assert owner_id == architect.id
    assert method == "leader_fallback"


@pytest.mark.asyncio
async def test_slot_busy_when_dispatched_item_exists(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=10,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=backend.id,
        )
    )
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is True


@pytest.mark.asyncio
async def test_slot_free_when_only_awaiting_human_review(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=11,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="awaiting_human_review",
            owner_slot_id=backend.id,
        )
    )
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is False


@pytest.mark.asyncio
async def test_slot_busy_during_pending_handoff_on_both_sides(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=12,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=architect.id,
            handoff_state="pending",
            handoff_target_slot_id=backend.id,
        )
    )
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, architect.id) is True
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is True
