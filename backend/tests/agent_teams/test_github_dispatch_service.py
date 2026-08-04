"""Dispatch routing + concurrency tests."""
from datetime import datetime, timedelta
from io import StringIO

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.config import settings
from app.database import Base
from app.models.database import (
    AgentTeamLaunch,
    AgentTeamLaunchItem,
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.github_dispatch_service import GithubDispatchService, github_dispatch_service
from app.services.github_workspace_service import github_workspace_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def host_has_enough_memory(monkeypatch):
    monkeypatch.setattr(
        github_dispatch_service,
        "_available_memory_mb",
        lambda: 999_999,
        raising=False,
    )

    async def reset_succeeds(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_workspace_service, "reset_workspace", reset_succeeds)


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
    await db.flush()
    db.add_all(
        [
            GithubWorkspace(scope_id=scope.id, path=f"/tmp/r-ws-{index}")
            for index in range(1, 6)
        ]
    )
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


async def _create_registered_slot_member(db, slot: AgentTeamSlot) -> MailTeamMember:
    for index in range(2):
        db.add(
            MailTeamMember(
                identity_key=f"repo:offset:{slot.id}:{index}",
                repo_id="offset",
                repo_path="/tmp/offset",
                repo_name="offset",
                display_name=f"Offset {index}",
                participant_kind="repo",
            )
        )
    await db.flush()
    member = MailTeamMember(
        identity_key=f"slot:test:{slot.id}",
        repo_id=slot.repo_id,
        repo_path=slot.repo_path,
        repo_name=slot.repo_name,
        display_name=slot.display_name,
        participant_kind="team_slot",
        team_preset_id=slot.preset_id,
        team_slot_id=slot.id,
        role=slot.role,
        charter=slot.charter,
    )
    db.add(member)
    await db.commit()
    assert member.id != slot.id
    return member


async def _create_live_slot_launch_session(
    db,
    preset: AgentTeamPreset,
    slot: AgentTeamSlot,
    *,
    target: str,
) -> tuple[AgentTeamLaunch, MailAgentSession]:
    launch = AgentTeamLaunch(
        preset_id=preset.id,
        plan_hash=f"plan:{target}",
        status="running",
    )
    db.add(launch)
    await db.flush()
    db.add(
        AgentTeamLaunchItem(
            launch_id=launch.id,
            slot_id=slot.id,
            action="spawn",
            status="started",
            provider=slot.provider,
            repo_path=slot.repo_path,
            tmux_target=target,
        )
    )
    member = await _create_registered_slot_member(db, slot)
    session = MailAgentSession(
        member_id=member.id,
        provider=slot.provider,
        source="observed",
        session_key=f"tmux:{target}",
        cwd=slot.repo_path,
        tmux_target=target,
        team_preset_id=preset.id,
        team_slot_id=slot.id,
        mailbox_status="observed",
        last_seen_at=datetime.utcnow(),
    )
    db.add(session)
    await db.commit()
    return launch, session


def test_leader_unblock_instructions_text():
    text = github_dispatch_service._leader_unblock_instructions()
    assert "dependency map" in text.lower()
    assert "deck_retry_work_item" in text
    assert "github_dispatch_blocker_merged" in text
    assert "all" in text.lower()
    assert "deck_list_work_items" in text
    assert "start" in text.lower()


@pytest.mark.asyncio
async def test_bootstrap_prompt_appends_unblock_only_for_leader(db):
    from app.services.agent_team_service import agent_team_service

    preset, slots, scope = await _team(db)
    leader, non_leader = slots[0], slots[1]

    leader_text = await agent_team_service._bootstrap_prompt(db, preset, leader)
    non_leader_text = await agent_team_service._bootstrap_prompt(db, preset, non_leader)

    assert "deck_retry_work_item" in leader_text
    assert "dependency map" in leader_text.lower()
    assert "deck_retry_work_item" not in non_leader_text


@pytest.mark.asyncio
async def test_bootstrap_prompt_appends_unblock_even_with_custom_prompt(db):
    from app.services.agent_team_service import agent_team_service

    preset, slots, scope = await _team(db)
    leader = slots[0]
    leader.bootstrap_prompt = "CUSTOM standing prompt."
    await db.commit()

    text = await agent_team_service._bootstrap_prompt(db, preset, leader)

    assert text.startswith("CUSTOM standing prompt.")
    assert "deck_retry_work_item" in text


@pytest.mark.asyncio
async def test_notify_blocker_merged_sends_leader_message_with_escalated_items(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    from app.services.agent_mail_service import agent_mail_service

    leader_member = await agent_mail_service.get_or_create_slot_member(db, architect)
    await db.commit()
    merged = GithubWorkItem(
        scope_id=scope.id,
        issue_number=816,
        issue_title="baseline",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    dep1 = GithubWorkItem(
        scope_id=scope.id,
        issue_number=817,
        issue_title="build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        status_note="Blocked by #816",
    )
    dep2 = GithubWorkItem(
        scope_id=scope.id,
        issue_number=818,
        issue_title="gmusic",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        status_note="Blocked by #817",
    )
    other = GithubWorkItem(
        scope_id=scope.id,
        issue_number=828,
        issue_title="docs",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
    )
    db.add_all([merged, dep1, dep2, other])
    await db.commit()

    await github_dispatch_service.notify_blocker_merged(db, scope, merged, slots)

    messages = (await db.execute(select(MailMessage))).scalars().all()
    hit = [
        message
        for message in messages
        if (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
    ]
    assert len(hit) == 1
    message = hit[0]
    assert message.recipient_member_id == leader_member.id
    assert "816" in (message.subject or "")
    escalated = {entry["issue_number"] for entry in message.payload["escalated_items"]}
    assert escalated == {817, 818}
    work_item_ids = {
        entry["work_item_id"] for entry in message.payload["escalated_items"]
    }
    assert dep1.id in work_item_ids and dep2.id in work_item_ids
    assert message.payload["issue_number"] == 816


@pytest.mark.asyncio
async def test_notify_blocker_merged_noop_when_no_leader_registered(db):
    preset, slots, scope = await _team(db)
    merged = GithubWorkItem(
        scope_id=scope.id,
        issue_number=816,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(merged)
    await db.commit()

    await github_dispatch_service.notify_blocker_merged(db, scope, merged, slots)

    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not [
        message
        for message in messages
        if (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
    ]


@pytest.mark.asyncio
async def test_work_item_has_lifecycle_columns(db):
    preset, slots, scope = await _team(db)
    now = datetime.utcnow()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=900,
        issue_title="x",
        issue_url="u",
        github_updated_at=now,
        dispatch_status="dispatched",
        dispatched_at=now,
        ack_received_at=now,
        last_nudge_at=now,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    assert item.dispatched_at is not None
    assert item.ack_received_at is not None
    assert item.last_nudge_at is not None


def test_ack_lifecycle_settings_present():
    assert settings.github_leader_ack_timeout_seconds > 0
    assert settings.github_design_ack_multiplier >= 1
    assert settings.github_owner_idle_timeout_seconds > 0
    assert settings.github_nudge_grace_seconds > 0


def test_reset_for_retry_clears_ack_received_at():
    item = GithubWorkItem(
        scope_id=1,
        issue_number=819,
        issue_type="code",
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 17, 12, 0),
    )

    github_dispatch_service.reset_for_retry(item)

    assert item.ack_received_at is None


@pytest.mark.asyncio
async def test_reset_for_retry_does_not_release_workspace(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=909,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope.id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    await db.commit()

    github_dispatch_service.reset_for_retry(item)
    await db.commit()

    assert item.dispatch_status == "pending"
    assert workspace.leased_item_id == item.id


def test_ack_not_satisfied_by_ack_older_than_current_dispatch():
    item = GithubWorkItem(
        scope_id=1,
        issue_number=819,
        issue_type="code",
        dispatch_status="dispatched",
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
    )

    assert github_dispatch_service._ack_satisfied(item) is False


def test_ack_satisfied_when_ack_follows_dispatch():
    item = GithubWorkItem(
        scope_id=1,
        issue_number=819,
        issue_type="code",
        dispatch_status="dispatched",
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
        ack_received_at=datetime(2026, 7, 24, 18, 40, 0),
    )

    assert github_dispatch_service._ack_satisfied(item) is True


def test_pr_number_satisfies_ack_regardless_of_stale_ack():
    item = GithubWorkItem(
        scope_id=1,
        issue_number=819,
        issue_type="code",
        dispatch_status="dispatched",
        pr_number=865,
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
    )

    assert github_dispatch_service._ack_satisfied(item) is True


@pytest.mark.asyncio
async def test_dispatch_pending_stamps_dispatched_at(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=910,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Result:
        launch_id = 910
        items = []

    async def fake_launcher(db_, preset_id, request):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={910: ["area:backend"]},
        issue_details_by_number={910: {"body": "do the thing"}},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.dispatched_at is not None


@pytest.mark.asyncio
async def test_ack_prompt_has_no_owner_side_timeout(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    leader_member = await _create_registered_slot_member(db, architect)
    instruction = github_dispatch_service._leader_ack_instruction(
        architect, leader_member, before="editing files"
    )
    assert "ack_received" in instruction
    assert "minute" not in instruction.lower()
    assert "give up" not in instruction.lower()


@pytest.mark.asyncio
async def test_report_ack_received_records_timestamp_and_clears_nudge(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=911,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=datetime.utcnow(),
        last_nudge_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.record_ack_received(db, item)

    await db.refresh(item)
    assert item.ack_received_at is not None
    assert item.last_nudge_at is None
    assert item.dispatch_status == "dispatched"


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
    assert launched["override"] == "/tmp/r-ws-1"


@pytest.mark.asyncio
async def test_dispatch_captures_pane_pid_from_launch_result(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=201,
        issue_title="Capture pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:1.0"
        pane_pid = 4242

    class _Result:
        launch_id = 201
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(github_workspace_service, "_read_proc_start", lambda _pid: "9001")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={201: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert item.dispatch_status == "dispatched"
    assert workspace.leased_owner_pid == 4242
    assert workspace.leased_owner_proc_start == "9001"


@pytest.mark.asyncio
async def test_dispatch_resolves_pane_pid_from_tmux_target(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=202,
        issue_title="Resolve pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:2.0"
        pane_pid = None

    class _Result:
        launch_id = 202
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(github_dispatch_service, "_resolve_pane_pid", lambda _target: 5252)
    monkeypatch.setattr(github_workspace_service, "_read_proc_start", lambda _pid: "9002")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={202: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert workspace.leased_owner_pid == 5252
    assert workspace.leased_owner_proc_start == "9002"


@pytest.mark.asyncio
async def test_dispatch_without_resolvable_pane_pid_still_dispatches(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=203,
        issue_title="Missing pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:3.0"
        pane_pid = None

    class _Result:
        launch_id = 203
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(github_dispatch_service, "_resolve_pane_pid", lambda _target: None)

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={203: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert item.dispatch_status == "dispatched"
    assert workspace.leased_owner_pid is None
    assert workspace.leased_owner_proc_start is None


@pytest.mark.asyncio
async def test_dispatch_keeps_pid_pair_null_when_proc_start_is_unreadable(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=204,
        issue_title="Unreadable pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:4.0"
        pane_pid = 6262

    class _Result:
        launch_id = 204
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    def unreadable(_pid):
        raise PermissionError("denied")

    monkeypatch.setattr(github_workspace_service, "_read_proc_start", unreadable)

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={204: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert item.dispatch_status == "dispatched"
    assert workspace.leased_owner_pid is None
    assert workspace.leased_owner_proc_start is None


@pytest.mark.asyncio
async def test_dispatch_pending_passes_issue_specific_owner_brief(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    leader_member = await _create_registered_slot_member(db, architect)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=833,
        issue_title="Add agent docs",
        issue_url="https://github.com/o/r/issues/833",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 833

    async def fake_launcher(db_, preset_id, request):
        launched["request"] = request
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={833: ["area:backend"]},
        issue_details_by_number={
            833: {
                "body": "Acceptance criteria and verification steps.",
                "labels": [{"name": "area:backend"}, {"name": "agent-ready"}],
            }
        },
    )

    prompt = launched["request"].slot_prompt_overrides[backend.id]
    assert "autonomous GitHub dispatch" in prompt
    assert "Work item ID:" in prompt
    assert "Issue: #833 — Add agent docs" in prompt
    assert "https://github.com/o/r/issues/833" in prompt
    assert "Acceptance criteria and verification steps." in prompt
    assert "deck_report_dispatch_status" in prompt
    assert "deck_request_context" in prompt
    assert f"Agent Mail member_id={leader_member.id}" in prompt
    assert f"to_member_id={leader_member.id}" in prompt
    assert f"slot_id={architect.id}" not in prompt
    assert f"to_member_id={architect.id}" not in prompt
    assert "wait for acknowledgment before starting implementation" in prompt
    assert "open a draft PR" in prompt
    assert "Workspace: /tmp/r-ws-1" in prompt
    assert "leased exclusively" in prompt
    assert "Do NOT create, move or remove git worktrees" in prompt

    member = (
        await db.execute(select(MailTeamMember).where(MailTeamMember.team_slot_id == backend.id))
    ).scalar_one()
    message = (
        await db.execute(
            select(MailMessage).where(MailMessage.recipient_member_id == member.id)
        )
    ).scalar_one()
    assert message.subject == "Autonomous dispatch: issue #833"
    assert "Issue: #833 — Add agent docs" in message.body_markdown
    assert "Acceptance criteria and verification steps." in message.body_markdown
    assert f"Agent Mail member_id={leader_member.id}" in message.body_markdown
    assert f"to_member_id={leader_member.id}" in message.body_markdown
    assert f"slot_id={architect.id}" not in message.body_markdown
    assert "wait for acknowledgment before starting implementation" in message.body_markdown


@pytest.mark.asyncio
async def test_design_dispatch_brief_uses_design_pipeline_language(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    leader_member = await _create_registered_slot_member(db, architect)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=835,
        issue_title="Write design note",
        issue_url="https://github.com/o/r/issues/835",
        github_updated_at=datetime.utcnow(),
        issue_type="design",
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 835

    async def fake_launcher(db_, preset_id, request):
        launched["request"] = request
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={835: ["area:backend"]},
        issue_details_by_number={835: {"body": "Capture design rationale."}},
    )

    prompt = launched["request"].slot_prompt_overrides[backend.id]
    assert "Pipeline: design" in prompt
    assert "Design pipeline instructions" in prompt
    assert "do not rely on CI or auto-merge" in prompt
    assert "human-reviewed PR" in prompt
    assert f"Agent Mail member_id={leader_member.id}" in prompt
    assert f"to_member_id={leader_member.id}" in prompt
    assert f"slot_id={architect.id}" not in prompt


@pytest.mark.asyncio
async def test_dispatch_brief_uses_discovery_when_leader_member_missing(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=837,
        issue_title="Small docs follow-up",
        issue_url="https://github.com/o/r/issues/837",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 837

    async def fake_launcher(db_, preset_id, request):
        launched["request"] = request
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={837: ["area:backend"]},
        issue_details_by_number={837: {"body": "Tiny docs follow-up."}},
    )

    prompt = launched["request"].slot_prompt_overrides[backend.id]
    assert "Team leader / approver: Architect" in prompt
    assert "Leader Agent Mail member id is not registered yet" in prompt
    assert "deck_list_team" in prompt
    assert "resolve the Agent Mail member id for `Architect`" in prompt
    assert f"slot_id={architect.id}" not in prompt
    assert f"to_member_id={architect.id}" not in prompt


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
    assert launched["override"] == "/tmp/r-ws-1"


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
async def test_escalate_sets_reason_for_active_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=62,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.escalate(db, item, "plan_blocked", "needs a human plan")

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "plan_blocked"
    assert item.status_note == "needs a human plan"


@pytest.mark.asyncio
async def test_escalation_broadcast_flags_active_owner(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=65,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.escalate(db, item, "owner_idle_timeout")

    message = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.kind == "broadcast",
                MailMessage.payload["kind"].as_string() == "github_dispatch_escalation",
            )
        )
    ).scalar_one()
    assert message.payload["owner_may_be_active"] is True
    assert "Do NOT retry" in message.body_markdown


@pytest.mark.asyncio
async def test_escalation_broadcast_no_active_owner_for_pending_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=66,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.escalate(db, item, "plan_blocked")

    message = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.kind == "broadcast",
                MailMessage.payload["kind"].as_string() == "github_dispatch_escalation",
            )
        )
    ).scalar_one()
    assert message.payload["owner_may_be_active"] is False


@pytest.mark.asyncio
async def test_escalate_preserves_first_reason_for_already_escalated_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=63,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="dispatch_label_removed",
        status_note="The dispatch label was removed.",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    message_count = len((await db.execute(select(MailMessage))).scalars().all())

    await github_dispatch_service.escalate(db, item, "plan_blocked", "owner also blocked")

    await db.refresh(item)
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"
    assert item.status_note == "The dispatch label was removed."
    assert len(messages) == message_count


@pytest.mark.asyncio
async def test_escalate_same_reason_is_idempotent_for_already_escalated_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=64,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="owner_offline",
        status_note="Owner heartbeat expired.",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    message_count = len((await db.execute(select(MailMessage))).scalars().all())

    await github_dispatch_service.escalate(db, item, "owner_offline", "duplicate poll")

    await db.refresh(item)
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_offline"
    assert item.status_note == "Owner heartbeat expired."
    assert len(messages) == message_count


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
async def test_dispatch_proceeds_with_only_standing_session(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    await _create_live_slot_launch_session(
        db,
        preset,
        backend,
        target="standing:0.0",
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=42,
        issue_title="new work",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    launches = []

    class _Result:
        launch_id = 104

    async def fake_launcher(db_, preset_id, request):
        launches.append(request)
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={42: ["area:backend"]},
    )

    await db.refresh(item)
    assert len(launches) == 1
    assert item.dispatch_status == "dispatched"
    assert item.owner_slot_id == backend.id
    assert item.pending_reason is None


@pytest.mark.asyncio
async def test_dispatch_pending_queues_when_scope_concurrency_cap_reached(db):
    preset, slots, scope = await _team(db)
    scope.max_concurrent_dispatched = 1
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=29,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=slots[0].id,
        )
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=31,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(db_, preset_id, request):
        raise AssertionError("repo cap should queue before launch")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={31: ["area:backend"]},
    )
    await db.refresh(item)
    assert backend.id != slots[0].id
    assert item.owner_slot_id is None
    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_repo_cap"


def test_available_memory_mb_reads_memavailable(monkeypatch):
    meminfo = "MemTotal:       16384000 kB\nMemAvailable:    6144000 kB\n"
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: StringIO(meminfo))

    assert GithubDispatchService()._available_memory_mb() == 6000


@pytest.mark.asyncio
async def test_dispatch_queues_when_available_memory_below_floor(db, monkeypatch):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=45,
        issue_title="memory-heavy work",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 2999)

    async def fake_launcher(db_, preset_id, request):
        raise AssertionError("should not launch below the memory floor")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={45: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_low_memory"


@pytest.mark.asyncio
async def test_dispatch_proceeds_when_available_memory_above_floor(db, monkeypatch):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=46,
        issue_title="memory-safe work",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 3001)
    launches = []

    class _Result:
        launch_id = 106

    async def fake_launcher(db_, preset_id, request):
        launches.append(request)
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={46: ["area:backend"]},
    )

    await db.refresh(item)
    assert len(launches) == 1
    assert item.dispatch_status == "dispatched"
    assert item.pending_reason is None


@pytest.mark.asyncio
async def test_dispatch_fails_open_when_available_memory_unknown(db, monkeypatch):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=47,
        issue_title="portable dispatch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: None)
    launches = []

    class _Result:
        launch_id = 107

    async def fake_launcher(db_, preset_id, request):
        launches.append(request)
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={47: ["area:backend"]},
    )

    await db.refresh(item)
    assert len(launches) == 1
    assert item.dispatch_status == "dispatched"
    assert item.pending_reason is None


@pytest.mark.asyncio
async def test_scope_concurrency_ignores_human_review_and_escalated_items(db):
    preset, slots, scope = await _team(db)
    scope.max_concurrent_dispatched = 1
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add_all(
        [
            GithubWorkItem(
                scope_id=scope.id,
                issue_number=32,
                issue_title="x",
                issue_url="u",
                github_updated_at=datetime.utcnow(),
                dispatch_status="awaiting_human_review",
                owner_slot_id=backend.id,
            ),
            GithubWorkItem(
                scope_id=scope.id,
                issue_number=33,
                issue_title="x",
                issue_url="u",
                github_updated_at=datetime.utcnow(),
                dispatch_status="ready_for_review",
                owner_slot_id=backend.id,
            ),
            GithubWorkItem(
                scope_id=scope.id,
                issue_number=34,
                issue_title="x",
                issue_url="u",
                github_updated_at=datetime.utcnow(),
                dispatch_status="escalated",
                owner_slot_id=backend.id,
            ),
        ]
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=35,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Result:
        launch_id = 104

    async def fake_launcher(db_, preset_id, request):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={35: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.owner_slot_id == backend.id


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
async def test_escalation_creates_agent_mail_broadcast(db):
    preset, slots, scope = await _team(db)
    scope.max_approval_rounds = 1
    db.add(
        MailTeamMember(
            identity_key="slot:1",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Architect",
            participant_kind="team_slot",
            team_preset_id=preset.id,
            team_slot_id=slots[0].id,
        )
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=36,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.record_approval_round(db, item, scope)

    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert any(message.kind == "broadcast" for message in messages)
    assert any("approval_rounds_exhausted" in (message.subject or "") for message in messages)


@pytest.mark.asyncio
async def test_escalation_state_persists_when_notification_fails(db, monkeypatch):
    preset, slots, scope = await _team(db)
    scope.max_approval_rounds = 1
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=37,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
    )
    db.add(item)
    await db.commit()

    async def fail_broadcast(db_, item_, reason, note):
        raise RuntimeError("mail down")

    monkeypatch.setattr(
        github_dispatch_service,
        "_send_escalation_broadcast",
        fail_broadcast,
    )

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
    past_registration_grace = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_registration_grace_seconds + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=50,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        updated_at=past_registration_grace,
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
async def test_monitor_leaves_newly_dispatched_item_when_leader_offline(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=53,
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
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_when_owner_offline(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    past_registration_grace = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_registration_grace_seconds + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=51,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        updated_at=past_registration_grace,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "offline"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_offline"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert any("owner_offline" in (message.subject or "") for message in messages)


@pytest.mark.asyncio
async def test_monitor_leaves_newly_dispatched_item_when_owner_offline(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=54,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "offline"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_does_not_escalate_slow_live_owner(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    for wake_state in ("wakeable", "delivered_waiting"):
        item = GithubWorkItem(
            scope_id=scope.id,
            issue_number=60 if wake_state == "wakeable" else 61,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=backend.id,
        )
        db.add(item)
        await db.commit()

        await github_dispatch_service.monitor_dispatched(
            db,
            scope,
            preset_slots=slots,
            wake_state_by_slot={architect.id: "wakeable", backend.id: wake_state},
        )

        await db.refresh(item)
        assert item.dispatch_status == "dispatched"
        assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_nudges_leader_on_ack_timeout(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=920,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_retried_item_still_nudged_when_leader_never_acks_again(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    dispatched_at = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=819,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=dispatched_at,
        ack_received_at=dispatched_at - timedelta(hours=1),
        updated_at=dispatched_at,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={
            architect.id: "wakeable",
            backend.id: "wakeable",
        },
    )

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_leader_ack_after_nudge_grace(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    nudged = datetime.utcnow() - timedelta(seconds=settings.github_nudge_grace_seconds + 5)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=921,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
        last_nudge_at=nudged,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "leader_ack_timeout"


@pytest.mark.asyncio
async def test_monitor_design_item_uses_ack_multiplier(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    age = (
        settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    assert age < settings.github_leader_ack_timeout_seconds * settings.github_design_ack_multiplier
    old = datetime.utcnow() - timedelta(seconds=age)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=922,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        issue_type="design",
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is None


@pytest.mark.asyncio
async def test_monitor_no_ack_action_when_ack_received(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=923,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=datetime.utcnow(),
        ack_received_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_ack_timeout_uses_dispatched_at_not_recent_activity(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=924,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_nudges_idle_owner_after_ack(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 30
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=930,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
        ack_received_at=old,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_idle_owner_activity_resets_clock(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 30
    )
    nudged = old + timedelta(seconds=1)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=931,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        ack_received_at=old,
        last_nudge_at=nudged,
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_idle_owner_after_nudge_grace(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 60
    )
    nudged = datetime.utcnow() - timedelta(seconds=settings.github_nudge_grace_seconds + 5)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=932,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        ack_received_at=old,
        updated_at=old,
        last_nudge_at=nudged,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_idle_timeout"


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


@pytest.mark.asyncio
async def test_dispatch_pending_queues_when_no_workspace_is_available(db):
    preset, slots, scope = await _team(db)
    await db.execute(delete(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id))
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=950,
        issue_title="No workspace",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(*_args, **_kwargs):
        raise AssertionError("launcher must not run without a workspace")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={950: ["area:backend"]},
    )

    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_no_workspace"
    assert item.owner_slot_id == slots[1].id
    assert item.routing_method == "label"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "launch_status",
    [
        "failed",
        "blocked",
        "blocked_provider_unavailable",
        "blocked_agent_mail_not_configured",
    ],
)
async def test_known_launch_failure_releases_workspace(db, launch_status):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=951,
        issue_title="Launch failure",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = launch_status
        tmux_target = None

    class _Result:
        launch_id = 951
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={951: ["area:backend"]},
    )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    assert item.dispatch_status == "failed"
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("launch_status", ["pending_registration", "reused", "spawned"])
async def test_success_or_unknown_launch_status_retains_workspace(db, launch_status):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=952,
        issue_title="Launch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = launch_status
        tmux_target = "deck:0.0" if launch_status != "spawned" else None

    class _Result:
        launch_id = 952
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={952: ["area:backend"]},
    )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalar_one()
    assert workspace.path == "/tmp/r-ws-1"


@pytest.mark.asyncio
async def test_tmux_target_vetoes_release_for_failure_status(db):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=953,
        issue_title="Ambiguous launch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "failed"
        tmux_target = "deck:0.0"

    class _Result:
        launch_id = 953
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={953: ["area:backend"]},
    )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalar_one()
    assert workspace.path == "/tmp/r-ws-1"


@pytest.mark.asyncio
async def test_value_error_releases_lease_immediately(db):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=954,
        issue_title="Plan blocked",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(*_args, **_kwargs):
        raise ValueError("blocked plan")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={954: ["area:backend"]},
    )

    workspaces = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id)
        )
    ).scalars().all()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "plan_blocked"
    assert all(workspace.leased_item_id != item.id for workspace in workspaces)
    assert await github_workspace_service.reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_unexpected_launch_exception_retains_lease_and_escalates(db):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=955,
        issue_title="Unknown launch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(*_args, **_kwargs):
        raise RuntimeError("commit failed after spawn")

    with pytest.raises(RuntimeError, match="commit failed after spawn"):
        await github_dispatch_service.dispatch_pending(
            db,
            scope,
            slots,
            launcher=fake_launcher,
            issue_labels_by_number={955: ["area:backend"]},
        )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalar_one()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "launch_outcome_unknown"
    assert workspace.leased_item_id == item.id


@pytest.mark.asyncio
async def test_dispatch_brief_renders_out_of_tree_build_hints(db):
    _, slots, scope = await _team(db)
    scope.builds_out_of_tree = True
    scope.build_dir_template = "build-{issue_number}"
    scope.build_command_hint = "meson compile -C {build_dir} -j{parallelism}"
    scope.max_build_parallelism = 4
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=956,
        issue_title="Build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=slots[1].id,
        preset_slots=slots,
    )

    assert "build-956" in brief
    assert "meson compile -C build-956 -j4" in brief
    assert "Cap build parallelism at -j4" in brief


@pytest.mark.asyncio
async def test_dispatch_brief_describes_in_tree_build_limit(db):
    _, slots, scope = await _team(db)
    scope.builds_out_of_tree = False
    scope.build_command_hint = "make -C {build_dir} -j{parallelism}"
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=957,
        issue_title="Build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=slots[1].id,
        preset_slots=slots,
    )

    assert "Only one build may run in this workspace at a time" in brief
    assert "build-957" not in brief


@pytest.mark.asyncio
async def test_dispatch_brief_contains_malformed_build_template(db):
    _, slots, scope = await _team(db)
    scope.builds_out_of_tree = True
    scope.build_dir_template = "build-{issue_number"
    scope.build_command_hint = "make -C {build_dir} -j{parallelism}"
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=958,
        issue_title="Build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=slots[1].id,
        preset_slots=slots,
    )

    assert "Issue: #958" in brief
    assert "make -C" not in brief
