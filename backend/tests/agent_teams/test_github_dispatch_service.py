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


class _LabelsClient:
    def __init__(self, labels):
        self._labels = labels

    async def list_repo_labels(self, owner, repo):
        return list(self._labels)


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
    owner_id, method = await github_dispatch_service.route_item(db, item, slots, ["nothing"])
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


@pytest.mark.asyncio
async def test_dispatch_pending_launches_and_marks_dispatched(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=20,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 99

    async def fake_launcher(db_, preset_id, request):
        launched["preset_id"] = preset_id
        launched["override"] = request.repo_path_override
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        classify=None,
        launcher=fake_launcher,
        issue_labels_by_number={20: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.owner_slot_id == backend.id
    assert item.routing_method == "label"
    assert item.launch_id == 99
    assert item.pending_reason is None
    assert launched["override"] == scope.repo_path


@pytest.mark.asyncio
async def test_dispatch_pending_disables_reuse_for_repo_override(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=23,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 100

    async def fake_launcher(db_, preset_id, request):
        launched["reuse_existing"] = request.reuse_existing
        launched["override"] = request.repo_path_override
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient([]),
        launcher=fake_launcher,
        issue_labels_by_number={23: []},
    )

    assert launched["reuse_existing"] is False
    assert launched["override"] == scope.repo_path


@pytest.mark.asyncio
async def test_dispatch_pending_queues_same_batch_items_for_same_slot(db):
    preset, slots, scope = await _team(db)
    first = GithubWorkItem(
        scope_id=scope.id,
        issue_number=24,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    second = GithubWorkItem(
        scope_id=scope.id,
        issue_number=25,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add_all([first, second])
    await db.commit()
    launches = []

    class _Result:
        launch_id = 101

    async def fake_launcher(db_, preset_id, request):
        launches.append(request.slot_ids[0])
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        launcher=fake_launcher,
        issue_labels_by_number={24: ["area:backend"], 25: ["area:backend"]},
    )
    await db.refresh(first)
    await db.refresh(second)
    assert len(launches) == 1
    assert first.dispatch_status == "dispatched"
    assert second.dispatch_status == "pending"
    assert second.pending_reason == "queued_slot_busy"


@pytest.mark.asyncio
async def test_dispatch_pending_commits_success_before_later_plan_block(db):
    preset, slots, scope = await _team(db)
    first = GithubWorkItem(
        scope_id=scope.id,
        issue_number=26,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    second = GithubWorkItem(
        scope_id=scope.id,
        issue_number=27,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add_all([first, second])
    await db.commit()
    calls = 0

    class _Result:
        launch_id = 102

    async def fake_launcher(db_, preset_id, request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("plan is blocked")
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        launcher=fake_launcher,
        issue_labels_by_number={26: [], 27: ["area:backend"]},
    )
    await db.refresh(first)
    await db.refresh(second)
    assert first.dispatch_status == "dispatched"
    assert second.dispatch_status == "escalated"
    assert second.escalation_reason == "plan_blocked"


@pytest.mark.asyncio
async def test_dispatch_pending_marks_failed_launch_result_failed(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=28,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Item:
        status = "failed"
        error = "spawn failed"

    class _Result:
        launch_id = 103
        status = "completed_with_errors"
        items = [_Item()]

    async def fake_launcher(db_, preset_id, request):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient([]),
        launcher=fake_launcher,
        issue_labels_by_number={28: []},
    )
    await db.refresh(item)
    assert item.dispatch_status == "failed"
    assert item.launch_id == 103


@pytest.mark.asyncio
async def test_dispatch_pending_queues_when_slot_busy(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=21,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=backend.id,
        )
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=22,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(db_, preset_id, request):
        raise AssertionError("should not launch a busy slot")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        launcher=fake_launcher,
        issue_labels_by_number={22: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_slot_busy"


@pytest.mark.asyncio
async def test_approval_round_cap_escalates(db):
    preset, slots, scope = await _team(db)
    scope.max_approval_rounds = 2
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=30,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        approval_round_count=0,
    )
    db.add(item)
    await db.commit()
    await github_dispatch_service.record_approval_round(db, item, scope)
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    await github_dispatch_service.record_approval_round(db, item, scope)
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "approval_rounds_exhausted"


@pytest.mark.asyncio
async def test_two_phase_handoff(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=40,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=architect.id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.initiate_handoff(db, item, backend.id)
    await db.refresh(item)
    assert item.handoff_state == "pending"
    assert item.handoff_target_slot_id == backend.id
    assert item.owner_slot_id == architect.id

    with pytest.raises(ValueError):
        await github_dispatch_service.accept_handoff(db, item, architect.id)

    await github_dispatch_service.accept_handoff(db, item, backend.id)
    await db.refresh(item)
    assert item.owner_slot_id == backend.id
    assert item.handoff_state == "accepted"
    assert item.handoff_target_slot_id is None
    assert item.routing_method == "reassigned"


@pytest.mark.asyncio
async def test_monitor_escalates_when_leader_offline(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=50,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "offline", slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "leader_offline"


@pytest.mark.asyncio
async def test_monitor_leaves_item_when_leader_reachable(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=51,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"


@pytest.mark.asyncio
async def test_monitor_leaves_item_when_leader_not_registered_yet(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=52,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
