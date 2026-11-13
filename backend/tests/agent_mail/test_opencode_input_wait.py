"""OpenCode 2 open-question detection and Supervisor escalation through the plugin (#732).

The plugin reports one wait per member: ``open`` when its first question or permission
prompt appears and ``clear`` when the last one closes, both with the same generation.
Identity is kernel-derived (peer chain, OpenCode 2 gate, bound pane and authenticated
session); the payload never chooses the slot. Clears are a database compare-and-set on the
generation, so a stale clear cannot erase a newer wait, even across backend workers.
"""
import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base, get_db
from app.main import app
from app.utils.peer_process import PeerPane

PANE = PeerPane(pane_pid=41000, pane_proc_start="27", tmux_target="%8", peer_pid=41010)
ROUTE = "/api/v1/agent-mail/hooks/input-wait"


@pytest_asyncio.fixture
async def maker(tmp_path):
    # A file-backed database: separate sessions behave like separate backend workers.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wait.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _team(maker, *, supervised=True):
    from app.models.database import (
        AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, MailAgentSession, MailExternalActor, MailTeamMember,
    )
    async with maker() as db:
        team = AgentTeamPreset(name="OpenCode wait fixture")
        actor = MailExternalActor(actor_key="oc-wait-actor", display_name="Supervisor", kind="external_tool",
                                  token_hash="synthetic-hash")
        db.add_all([team, actor]); await db.flush()
        slot = AgentTeamSlot(preset_id=team.id, display_name="Worker", provider="opencode-cli",
                             repo_path="/synthetic/project", repo_id="fixture", repo_name="fixture")
        leader = AgentTeamSlot(preset_id=team.id, display_name="Leader", provider="codex-cli",
                               repo_path="/synthetic/project", repo_id="fixture", repo_name="fixture")
        db.add_all([slot, leader]); await db.flush()
        team.leader_slot_id = leader.id
        team.supervisor_actor_id = actor.id if supervised else None
        members = [MailTeamMember(identity_key=f"oc-wait-{s.id}", repo_id="fixture", repo_name="fixture",
                                  repo_path="/synthetic/project", display_name=s.display_name,
                                  team_preset_id=team.id, team_slot_id=s.id) for s in (slot, leader)]
        db.add_all(members); await db.flush()
        binding = AgentPaneBinding(pane_pid=PANE.pane_pid, pane_proc_start=PANE.pane_proc_start, slot_id=slot.id,
                                   preset_id=team.id, tmux_target="%8")
        session = MailAgentSession(member_id=members[0].id, provider="opencode-cli", source="mcp",
                                   session_key="oc-wait-session", team_slot_id=slot.id, team_preset_id=team.id,
                                   bound_pane_pid=PANE.pane_pid, bound_pane_proc_start=PANE.pane_proc_start,
                                   cwd="/synthetic/project", capability_token_hash="synthetic-hash",
                                   mailbox_status="connected")
        db.add_all([binding, session]); await db.commit()
        return SimpleNamespace(team_id=team.id, actor_id=actor.id, slot_id=slot.id, binding_id=binding.id,
                               session_id=session.id, leader_member_id=members[1].id)


@pytest_asyncio.fixture
async def team(maker, monkeypatch):
    from app.services import opencode_version

    async def override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override
    gate = {"ready": True, "pane": PANE}
    monkeypatch.setattr("app.api.v1.agent_mail.resolve_request_pane_detailed",
                        lambda _request: SimpleNamespace(pane=gate["pane"], walked_pids=(41010, PANE.pane_pid)),
                        raising=False)
    monkeypatch.setattr(opencode_version, "member_gate_for_peer", lambda pane, walked: opencode_version.VersionGate(
        "ok" if gate["ready"] else "unsupported", "2.2.7" if gate["ready"] else "1.17.11", None))
    fixture = await _team(maker)
    fixture.gate = gate
    yield fixture
    app.dependency_overrides.pop(get_db, None)


def _gen(offset=0):
    return int(time.time() * 1000) + offset


async def _post(state, generation, **extra):
    body = {"provider": "opencode-cli", "session_id": "ses_member", "cwd": "/synthetic/project", "pid": 41010,
            "state": state, "kind": "question", "generation": generation, **extra}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(ROUTE, json=body)


async def _binding(maker, fixture):
    from app.models.database import AgentPaneBinding
    async with maker() as db:
        return await db.get(AgentPaneBinding, fixture.binding_id)


async def _notices(maker):
    from app.models.database import MailMessage
    async with maker() as db:
        return (await db.scalars(select(MailMessage).where(MailMessage.subject == "Waiting for input"))).all()


@pytest.mark.asyncio
async def test_an_open_question_is_recorded_once_and_escalated_to_the_supervisor(maker, team):
    from app.models.database import MailExternalActor
    from app.services.agent_team_supervisor_service import require_supervisor_thread, supervisor_inbox

    generation = _gen()
    assert (await _post("open", generation)).status_code == 200
    assert (await _post("open", generation)).status_code == 200  # duplicate: no second notice

    binding = await _binding(maker, team)
    assert binding.waiting_input_reason == "question"
    notices = await _notices(maker)
    assert len(notices) == 1
    notice = notices[0]
    # The exact four-key notice that Supervisor routing accepts; no question text or private context.
    assert notice.payload == {"notice": "native_input_wait", "slot_id": team.slot_id, "reason": "question",
                              "supervisor_actor_id": team.actor_id}
    assert "/synthetic/project" not in notice.body_markdown and "ses_member" not in notice.body_markdown
    async with maker() as db:
        actor = await db.get(MailExternalActor, team.actor_id)
        assert len(await supervisor_inbox(db, actor)) == 1
        await require_supervisor_thread(db, actor, notice)


@pytest.mark.asyncio
async def test_only_the_matching_generation_clears_the_wait(maker, team):
    first, second = _gen(), _gen(5000)
    await _post("open", first)
    await _post("open", second)  # a newer wait after a lost clear replaces the generation, no new notice
    await _post("clear", first)  # stale
    assert (await _binding(maker, team)).waiting_input_reason == "question"
    assert len(await _notices(maker)) == 1
    await _post("clear", second)
    binding = await _binding(maker, team)
    assert binding.waiting_input_reason is None and binding.waiting_input_notice_id is None


@pytest.mark.asyncio
async def test_a_clear_before_its_open_is_a_no_op_and_the_late_open_is_retained(maker, team):
    generation = _gen()
    await _post("clear", generation)
    assert (await _binding(maker, team)).waiting_input_reason is None
    await _post("open", generation)
    assert (await _binding(maker, team)).waiting_input_reason == "question"


@pytest.mark.asyncio
async def test_a_stale_clear_cannot_erase_a_newer_wait_across_workers(maker, team):
    old, new = _gen(), _gen(5000)
    await _post("open", old)
    for _ in range(5):
        # Two concurrent requests, each with its own database session (as two workers would have).
        await asyncio.gather(_post("open", new), _post("clear", old))
        binding = await _binding(maker, team)
        assert binding.waiting_input_reason == "question"
    assert len(await _notices(maker)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["gate", "no_pane", "other_pane", "session_closed", "slot_disabled", "generation"])
async def test_unverified_or_stale_identity_records_nothing(maker, team, change):
    from sqlalchemy import update
    from app.models.database import AgentTeamSlot, MailAgentSession

    generation = _gen()
    if change == "gate":
        team.gate["ready"] = False
    elif change == "no_pane":
        team.gate["pane"] = None
    elif change == "other_pane":
        team.gate["pane"] = PeerPane(pane_pid=42000, pane_proc_start="99", tmux_target="%9", peer_pid=42010)
    elif change in {"session_closed", "slot_disabled"}:
        async with maker() as db:
            if change == "session_closed":
                await db.execute(update(MailAgentSession).where(MailAgentSession.id == team.session_id)
                                 .values(mailbox_status="offline"))
            else:
                await db.execute(update(AgentTeamSlot).where(AgentTeamSlot.id == team.slot_id).values(enabled=False))
            await db.commit()
    elif change == "generation":
        generation = -1
    assert (await _post("open", generation)).status_code == 200  # hooks never fail the member
    assert (await _binding(maker, team)).waiting_input_reason is None
    assert await _notices(maker) == []


@pytest.mark.asyncio
async def test_the_payload_cannot_choose_a_slot(maker, team):
    await _post("open", _gen(), team_slot_id=999999, team_preset_id=999999)
    notices = await _notices(maker)
    assert [n.payload["slot_id"] for n in notices] == [team.slot_id]


@pytest.mark.asyncio
async def test_an_unsupervised_team_notifies_the_current_leader(maker, monkeypatch):
    from sqlalchemy import update
    from app.models.database import AgentTeamPreset, MailReceipt
    from app.services import opencode_version

    async def override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr("app.api.v1.agent_mail.resolve_request_pane_detailed",
                        lambda _request: SimpleNamespace(pane=PANE, walked_pids=(41010, PANE.pane_pid)), raising=False)
    monkeypatch.setattr(opencode_version, "member_gate_for_peer",
                        lambda pane, walked: opencode_version.VersionGate("ok", "2.2.7", None))
    try:
        fixture = await _team(maker, supervised=False)
        await _post("open", _gen())
        notices = await _notices(maker)
        assert len(notices) == 1 and notices[0].recipient_member_id == fixture.leader_member_id
        async with maker() as db:
            assert await db.scalar(select(MailReceipt.id).where(MailReceipt.message_id == notices[0].id,
                                                                MailReceipt.member_id == fixture.leader_member_id))
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_a_delayed_older_open_never_replaces_a_newer_wait(maker, team):
    old, new = _gen(), _gen(5000)
    await _post("open", new)
    await _post("open", old)  # delayed: arrives after the newer one
    await _post("clear", old)
    assert (await _binding(maker, team)).waiting_input_reason == "question"
    await _post("clear", new)
    assert (await _binding(maker, team)).waiting_input_reason is None


@pytest.mark.asyncio
async def test_an_equal_generation_collision_is_retained_not_cleared(maker, team):
    # Two plugin processes for the same pane can pick the same millisecond. Ordering cannot be
    # proved, so the wait is kept: the old process's clear must not erase the new one's wait.
    generation = _gen()
    await _post("open", generation)
    await _post("open", generation)  # the colliding open from another process
    await _post("clear", generation)
    assert (await _binding(maker, team)).waiting_input_reason == "question"
    assert len(await _notices(maker)) == 1
    later = _gen(5000)
    await _post("open", later)  # a newer open takes the generation but cannot prove the order
    await _post("clear", later)
    binding = await _binding(maker, team)
    assert binding.waiting_input_reason == "question" and binding.opencode_wait_uncertain is True


async def _record(maker, state, generation):
    from app.services import opencode_input_wait
    async with maker() as db:
        return await opencode_input_wait.record(db, pane_pid=PANE.pane_pid, pane_proc_start=PANE.pane_proc_start,
                                                state=state, generation=generation)


@pytest.mark.asyncio
@pytest.mark.parametrize("schedule", ["clear_first", "open_first"])
async def test_forced_worker_schedules_never_lose_the_newer_wait(maker, team, schedule):
    old, new = _gen(), _gen(5000)
    await _record(maker, "open", old)
    if schedule == "clear_first":
        # The old interval legitimately ends, then a new one starts: two intervals, two notices.
        assert await _record(maker, "clear", old) is True
        assert await _record(maker, "open", new) is True
        assert len(await _notices(maker)) == 2
    else:
        assert await _record(maker, "open", new) is True  # takes over the continuous interval
        assert await _record(maker, "clear", old) is False
        assert len(await _notices(maker)) == 1
    assert (await _binding(maker, team)).waiting_input_reason == "question"


@pytest.mark.asyncio
async def test_a_backend_restart_keeps_the_wait_and_its_generation(maker, team, tmp_path):
    generation = _gen()
    await _record(maker, "open", generation)
    # Reopen the same database with a fresh engine, as a restarted backend would.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wait.db'}")
    reopened = async_sessionmaker(engine, expire_on_commit=False)
    try:
        assert (await _binding(reopened, team)).waiting_input_reason == "question"
        assert await _record(reopened, "clear", generation) is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_generation_round_trips_exactly_and_started_at_is_server_time(maker, team):
    from datetime import datetime, timedelta
    generation = _gen(-3_600_000)  # the plugin's clock reads one hour behind
    before = datetime.utcnow()
    await _record(maker, "open", generation)
    binding = await _binding(maker, team)
    assert binding.opencode_wait_generation == generation and binding.opencode_wait_uncertain is False
    assert before - timedelta(seconds=1) <= binding.waiting_input_started_at <= datetime.utcnow()
    await _record(maker, "open", generation)  # collision: unprovable, kept exact, no marker
    binding = await _binding(maker, team)
    assert binding.opencode_wait_generation == generation and binding.opencode_wait_uncertain is True
    assert await _record(maker, "clear", generation) is False


@pytest.mark.parametrize("value", [True, False, 1.5, "1700000000000", None, 0, -5, float("inf"), 10**20])
def test_only_a_bounded_integer_millisecond_generation_is_accepted(value):
    from app.services import opencode_input_wait
    now = opencode_input_wait.datetime.utcnow()
    assert opencode_input_wait.generation_time(value, now) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["closed_at", "retired", "replaced_member", "rebound_pane"])
async def test_closed_retired_replaced_or_rebound_identity_records_nothing(maker, team, change):
    from datetime import datetime
    from sqlalchemy import update
    from app.models.database import MailAgentSession, MailPaneLifecycle, MailTeamMember

    async with maker() as db:
        if change == "closed_at":
            await db.execute(update(MailAgentSession).where(MailAgentSession.id == team.session_id)
                             .values(closed_at=datetime.utcnow()))
        elif change == "retired":
            db.add(MailPaneLifecycle(pane_pid=PANE.pane_pid, pane_proc_start=PANE.pane_proc_start,
                                     retired_at=datetime.utcnow()))
        elif change == "replaced_member":
            db.add(MailTeamMember(identity_key="oc-wait-replacement", repo_id="fixture", repo_name="fixture",
                                  repo_path="/synthetic/project", display_name="Replacement",
                                  team_preset_id=team.team_id, team_slot_id=team.slot_id,
                                  updated_at=datetime(2100, 1, 1)))
        else:
            await db.execute(update(MailAgentSession).where(MailAgentSession.id == team.session_id)
                             .values(bound_pane_pid=PANE.pane_pid + 1))
        await db.commit()
    assert await _record(maker, "open", _gen()) is False
    assert (await _binding(maker, team)).waiting_input_reason is None
    assert await _notices(maker) == []


@pytest.mark.asyncio
async def test_replayed_clear_after_a_new_wait_with_the_same_generation_keeps_it(maker, team):
    # V1 counterexample: open A(T), clear A(T), open B(T), delayed duplicate clear A(T).
    generation = _gen()
    await _record(maker, "open", generation)
    await _record(maker, "clear", generation)
    await _record(maker, "open", generation)
    await _record(maker, "clear", generation)
    assert (await _binding(maker, team)).waiting_input_reason == "question"


async def _set(maker, team, **values):
    from sqlalchemy import update
    from app.models.database import AgentPaneBinding
    async with maker() as db:
        await db.execute(update(AgentPaneBinding).where(AgentPaneBinding.id == team.binding_id).values(**values))
        await db.commit()


@pytest.mark.asyncio
async def test_an_equal_generation_marks_the_wait_uncertain_and_keeps_it(maker, team):
    generation = _gen()
    assert await _record(maker, "open", generation) is True
    assert await _record(maker, "open", generation) is True  # changed: now uncertain
    binding = await _binding(maker, team)
    assert (binding.opencode_wait_generation, binding.opencode_wait_uncertain) == (generation, True)
    assert await _record(maker, "clear", generation) is False
    assert (await _binding(maker, team)).waiting_input_reason == "question"
    assert len(await _notices(maker)) == 1


@pytest.mark.asyncio
async def test_an_older_open_after_a_clear_starts_an_uncertain_wait(maker, team):
    old, new = _gen(), _gen(5000)
    await _record(maker, "open", new)
    assert await _record(maker, "clear", new) is True
    assert (await _binding(maker, team)).opencode_wait_generation == new  # the fence survives the clear
    assert await _record(maker, "open", old) is True  # a real but unprovable new interval
    binding = await _binding(maker, team)
    assert binding.waiting_input_reason == "question"
    assert (binding.opencode_wait_generation, binding.opencode_wait_uncertain) == (new, True)
    assert len(await _notices(maker)) == 2
    assert await _record(maker, "clear", old) is False
    assert await _record(maker, "clear", new) is False
    assert (await _binding(maker, team)).waiting_input_reason == "question"


@pytest.mark.asyncio
async def test_an_older_open_during_a_wait_is_a_no_op(maker, team):
    old, new = _gen(), _gen(5000)
    await _record(maker, "open", new)
    assert await _record(maker, "open", old) is False
    binding = await _binding(maker, team)
    assert (binding.opencode_wait_generation, binding.opencode_wait_uncertain) == (new, False)


@pytest.mark.asyncio
async def test_a_duplicate_clear_is_a_no_op_and_keeps_the_fence(maker, team):
    generation = _gen()
    await _record(maker, "open", generation)
    assert await _record(maker, "clear", generation) is True
    assert await _record(maker, "clear", generation) is False
    binding = await _binding(maker, team)
    assert binding.waiting_input_reason is None and binding.waiting_input_started_at is None
    assert binding.waiting_input_notice_id is None
    assert (binding.opencode_wait_generation, binding.opencode_wait_uncertain) == (generation, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [None, False])
async def test_a_legacy_wait_without_a_generation_gives_no_clear_authority(maker, team, uncertain):
    from datetime import datetime
    generation = _gen()
    await _set(maker, team, waiting_input_reason="question", waiting_input_started_at=datetime.utcnow(),
               opencode_wait_generation=None, opencode_wait_uncertain=uncertain)
    assert await _record(maker, "clear", generation) is False
    assert (await _binding(maker, team)).waiting_input_reason == "question"


@pytest.mark.asyncio
async def test_uncertainty_survives_a_newer_open_and_a_backend_restart(maker, team, tmp_path):
    generation, newer = _gen(), _gen(5000)
    await _record(maker, "open", generation)
    await _record(maker, "open", generation)  # uncertain
    assert await _record(maker, "open", newer) is True
    binding = await _binding(maker, team)
    assert (binding.opencode_wait_generation, binding.opencode_wait_uncertain) == (newer, True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wait.db'}")
    reopened = async_sessionmaker(engine, expire_on_commit=False)
    try:
        assert await _record(reopened, "clear", newer) is False
        binding = await _binding(reopened, team)
        assert binding.waiting_input_reason == "question" and binding.opencode_wait_uncertain is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_one_notice_per_continuous_wait(maker, team):
    first = _gen()
    await _record(maker, "open", first)
    await _record(maker, "open", first + 1)  # the same continuous wait: no new notice
    assert len(await _notices(maker)) == 1
    await _record(maker, "clear", first + 1)
    await _record(maker, "open", first + 2)  # a new wait: one new notice
    notices = await _notices(maker)
    assert len(notices) == 2
    assert all(n.payload == {"notice": "native_input_wait", "slot_id": team.slot_id, "reason": "question",
                             "supervisor_actor_id": team.actor_id} for n in notices)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["closed_at", "retired", "replaced_member", "rebound_pane"])
async def test_a_clear_after_an_authority_change_is_a_no_op(maker, team, change):
    from datetime import datetime
    from sqlalchemy import update
    from app.models.database import MailAgentSession, MailPaneLifecycle, MailTeamMember

    generation = _gen()
    await _record(maker, "open", generation)
    async with maker() as db:
        if change == "closed_at":
            await db.execute(update(MailAgentSession).where(MailAgentSession.id == team.session_id)
                             .values(closed_at=datetime.utcnow()))
        elif change == "retired":
            db.add(MailPaneLifecycle(pane_pid=PANE.pane_pid, pane_proc_start=PANE.pane_proc_start,
                                     retired_at=datetime.utcnow()))
        elif change == "replaced_member":
            db.add(MailTeamMember(identity_key="oc-wait-replacement", repo_id="fixture", repo_name="fixture",
                                  repo_path="/synthetic/project", display_name="Replacement",
                                  team_preset_id=team.team_id, team_slot_id=team.slot_id,
                                  updated_at=datetime(2100, 1, 1)))
        else:
            await db.execute(update(MailAgentSession).where(MailAgentSession.id == team.session_id)
                             .values(bound_pane_pid=PANE.pane_pid + 1))
        await db.commit()
    assert await _record(maker, "clear", generation) is False
    binding = await _binding(maker, team)
    assert binding.waiting_input_reason == "question" and binding.opencode_wait_generation == generation


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["clear", "question"])
async def test_the_native_wait_recorder_leaves_the_opencode_fence_alone(maker, team, reason):
    from datetime import datetime
    from app.services import agent_activity_service

    await _set(maker, team, opencode_wait_generation=1_763_020_800_000, opencode_wait_uncertain=True)
    pane = SimpleNamespace(binding_id=team.binding_id, pane_pid=PANE.pane_pid, pane_start=PANE.pane_proc_start,
                           tmux_target="%8", cwd="/synthetic/project")
    entry = (team.slot_id, "opencode-cli", None, [pane])
    details = {"input_wait_known": True, "input_wait_reason": reason, "input_wait_binding_id": team.binding_id}
    async with maker() as db:
        await agent_activity_service._record_input_waits(db, team.team_id, [entry], [details],
                                                         {team.slot_id: entry}, now=datetime.utcnow())
        await db.commit()
    binding = await _binding(maker, team)
    assert (binding.opencode_wait_generation, binding.opencode_wait_uncertain) == (1_763_020_800_000, True)
