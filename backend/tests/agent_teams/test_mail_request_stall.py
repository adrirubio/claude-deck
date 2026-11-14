"""Unanswered explicit requests are visible on the team summary and the Supervisor check-in (#752).

The signal is a pending context_request or handoff, addressed to an idle member of the team, older
than a configurable threshold. A view that was truncated or could not be proven is never complete.
Native activity is faked in every test; none reads /proc or depends on a host PID.
"""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
import sqlite3

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentPaneBinding,
    AgentTeamPreset,
    AgentTeamSlot,
    MailAgentSession,
    MailExternalActor,
    MailMessage,
    MailReceipt,
    MailTeamMember,
)
from app.models.schemas import AgentActivityObservation, MailMessageCreate
from app.services.agent_mail_service import agent_mail_service
from app.services.mail_request_stall_service import MailRequestStallService

THRESHOLD = 1200


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stall.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def threshold(monkeypatch):
    monkeypatch.setattr(settings, "mail_request_unanswered_seconds", THRESHOLD)


async def make_team(db, name="Stall", members=3):
    """A preset with one slot and one member per name L1, C1, R1, ..."""
    team = AgentTeamPreset(name=name, description="Stall visibility.")
    db.add(team)
    await db.flush()
    people = []
    for index in range(members):
        slot = AgentTeamSlot(preset_id=team.id, display_name=f"{name}-S{index}", provider="codex-cli",
                             repo_path="/private/repo", repo_id="private", repo_name="repo")
        db.add(slot)
        await db.flush()
        member = MailTeamMember(identity_key=f"slot:{name}:{index}", repo_id="r", repo_path="/r", repo_name="r",
                                display_name=f"{name}-M{index}", participant_kind="team_slot",
                                team_preset_id=team.id, team_slot_id=slot.id)
        db.add(member)
        await db.flush()
        people.append(SimpleNamespace(member=member, slot=slot, id=member.id, name=member.display_name))
    await db.commit()
    return team, people


async def add_request(db, sender, recipient, *, age=THRESHOLD, kind="context_request", status="pending",
                      payload=None, thread=None, actor=None, subject="PRIVATE-SUBJECT", base=None):
    row = MailMessage(
        kind=kind, sender_member_id=None if actor else sender.id, sender_actor_id=actor.id if actor else None,
        recipient_member_id=recipient.id, thread_root_id=thread, request_status=status, payload=payload,
        subject=subject, body_markdown="PRIVATE-BODY", audience_type="member", audience_id=str(recipient.id),
        created_at=(base or datetime.utcnow()) - timedelta(seconds=age))
    db.add(row)
    await db.flush()
    db.add(MailReceipt(message_id=row.id, member_id=recipient.id))
    await db.flush()
    return row


async def add_reply(db, sender, thread, *, kind="message", after=None):
    row = MailMessage(kind=kind, sender_member_id=sender.id, thread_root_id=thread, body_markdown="reply",
                      audience_type="member", audience_id=str(sender.id))
    db.add(row)
    await db.flush()
    return row


def states(people, **by_index):
    return {person.slot.id: by_index.get(f"p{index}", "idle") for index, person in enumerate(people)}


async def observe(db, team, native_states, *, ok=True, service=None, now=None):
    stall = service or MailRequestStallService()
    return await stall.observe(db, team.id, now=now or datetime.now(timezone.utc), native_states=native_states,
                               native_ok=ok)


def ids(view):
    return [item.request_id for item in view.items]


# --- threshold and recipient state -----------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("age,reported", [(THRESHOLD - 1, False), (THRESHOLD, True), (THRESHOLD + 1, True)])
async def test_threshold_edges(db, age, reported):
    # A fixed clock, so the age is exact: one second below does not count, equal counts.
    now = datetime.now(timezone.utc)
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1], age=age, base=now.replace(tzinfo=None))
    await db.commit()
    view = await observe(db, team, states(people), now=now)
    assert (ids(view) == [request.id]) is reported
    assert view.complete is True and view.reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds,age,reported", [(60, 61, True), (60, 59, False), (3600, 1300, False), (3600, 3601, True)])
async def test_threshold_follows_the_setting(db, monkeypatch, seconds, age, reported):
    monkeypatch.setattr(settings, "mail_request_unanswered_seconds", seconds)
    now = datetime.now(timezone.utc)
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1], age=age, base=now.replace(tzinfo=None))
    await db.commit()
    view = await observe(db, team, states(people), now=now)
    assert (ids(view) == [request.id]) is reported


@pytest.mark.asyncio
async def test_the_setting_defaults_to_twenty_minutes_and_is_bounded():
    from app.config import Settings

    assert Settings.model_fields["mail_request_unanswered_seconds"].default == 1200
    with pytest.raises(ValueError):
        Settings(mail_request_unanswered_seconds=59)
    with pytest.raises(ValueError):
        Settings(mail_request_unanswered_seconds=86401)


@pytest.mark.asyncio
@pytest.mark.parametrize("state,reported,reason", [
    ("idle", True, None), ("working", False, None), ("stopped", False, "native_unknown"),
    ("unknown", False, "native_unknown")])
async def test_recipient_native_state(db, state, reported, reason):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    view = await observe(db, team, states(people, p1=state))
    assert (ids(view) == [request.id]) is reported
    assert view.reason == reason and view.complete is (reason is None)


@pytest.mark.asyncio
async def test_a_missing_slot_binding_and_a_failed_native_read_are_unknown(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    missing = states(people)
    missing.pop(people[1].slot.id)
    view = await observe(db, team, missing)
    assert view.items == [] and view.reason == "native_unknown" and not view.complete
    view = await observe(db, team, states(people), ok=False)
    assert view.items == [] and view.reason == "native_unknown" and not view.complete
    people[1].member.team_slot_id = None
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.reason == "native_unknown"
    assert request.id


@pytest.mark.asyncio
async def test_a_binding_that_changes_during_the_reads_is_not_a_stable_observation(db):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    service = MailRequestStallService()
    real = service._signatures
    calls = []

    async def drifting(db_, member_ids):
        calls.append(1)
        result = await real(db_, member_ids)
        if len(calls) > 1:
            result = {key: (None, *value[1:]) for key, value in result.items()}
        return result

    service._signatures = drifting
    view = await observe(db, team, states(people), service=service)
    assert view.items == [] and view.reason == "native_unknown" and not view.complete


# --- who and what counts ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_requests_addressed_to_this_team_count(db):
    team, people = await make_team(db, "Mine")
    other, strangers = await make_team(db, "Other")
    mine = await add_request(db, people[0], people[1])
    await add_request(db, people[0], strangers[1])
    await add_request(db, strangers[0], strangers[1])
    from_other_team = await add_request(db, strangers[0], people[2])
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [mine.id, from_other_team.id]
    assert {item.requester for item in view.items} == {people[0].name, strangers[0].name}
    assert other.id != team.id


@pytest.mark.asyncio
async def test_status_kind_and_approval_flow_rules(db):
    team, people = await make_team(db)
    pending = await add_request(db, people[0], people[1])
    handoff = await add_request(db, people[0], people[2], kind="handoff")
    await add_request(db, people[0], people[1], status="answered")
    await add_request(db, people[0], people[1], status="superseded")
    await add_request(db, people[0], people[1], kind="handoff", status="acknowledged")
    await add_request(db, people[0], people[1], payload={"approval_request_id": 7, "work_item_id": 3})
    await add_request(db, people[0], people[1], kind="message", status=None)
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [pending.id, handoff.id]
    assert {item.kind for item in view.items} == {"context_request", "handoff"}


@pytest.mark.asyncio
async def test_a_request_pending_for_thirty_days_is_still_reported(db):
    team, people = await make_team(db)
    old = await add_request(db, people[0], people[1], age=30 * 24 * 3600)
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [old.id] and view.items[0].unanswered_seconds >= 30 * 24 * 3600 - 5


# --- clearing ---------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_the_addressed_recipients_plain_reply_clears_a_root_request(db):
    team, people = await make_team(db)
    asked, followed_up, third = (await add_request(db, people[0], people[1]),
                                 await add_request(db, people[0], people[1]),
                                 await add_request(db, people[0], people[1]))
    await db.commit()
    await add_reply(db, people[1], asked.id)         # the addressed recipient: clears
    await add_reply(db, people[0], followed_up.id)   # the requester following up: does not clear
    await add_reply(db, people[2], third.id)         # a third member: does not clear
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [followed_up.id, third.id]


@pytest.mark.asyncio
async def test_an_explicit_answer_leaves_pending_and_clears(db):
    team, people = await make_team(db)
    request = await agent_mail_service.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=people[0].id, recipient_member_id=people[1].id,
        body_markdown="PRIVATE-BODY"), auto_nudge=False)
    row = await db.get(MailMessage, request.id)
    row.created_at = datetime.utcnow() - timedelta(seconds=THRESHOLD + 5)
    await db.commit()
    assert ids(await observe(db, team, states(people))) == [request.id]
    await agent_mail_service.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=people[1].id, thread_root_id=request.id, body_markdown="Done."),
        auto_nudge=False)
    assert (await observe(db, team, states(people))).items == []


@pytest.mark.asyncio
async def test_a_legacy_nested_reply_by_the_recipient_clears_the_root_request(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.flush()
    nested_follow_up = await add_reply(db, people[0], request.id)       # requester's reply under the request
    await add_reply(db, people[1], nested_follow_up.id)                 # recipient replies under that reply
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.complete is True


@pytest.mark.asyncio
async def test_a_reply_that_is_not_part_of_the_requests_thread_neither_clears_nor_blocks_the_proof(db):
    # Adapted for the indexed descent: a reply by the addressee under a missing parent cannot belong to
    # the request's thread, so the request is provably unanswered (it used to be unprovable).
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await add_reply(db, people[1], 999999)       # thread id of a message that does not exist
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [request.id] and view.complete is True and view.reason is None


# --- legacy nested requests -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nested_pending_requests_are_never_entries_and_make_the_view_ambiguous(db):
    team, people = await make_team(db)
    root = await add_request(db, people[0], people[1], kind="message", status=None, age=10)
    first = await add_request(db, people[0], people[1], thread=root.id)
    second = await add_request(db, people[0], people[1], thread=root.id)
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == []
    assert view.reason == "ambiguous_legacy_request" and view.complete is False
    # A plain reply by the addressed member cannot prove which nested request it answers.
    await add_reply(db, people[1], root.id)
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.reason == "ambiguous_legacy_request"
    # An explicit answer naming one request resolves only that request.
    await agent_mail_service.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=people[1].id, thread_root_id=first.id, body_markdown="First."),
        auto_nudge=False)
    assert (await db.get(MailMessage, first.id)).request_status == "answered"
    assert (await db.get(MailMessage, second.id)).request_status == "pending"
    view = await observe(db, team, states(people))
    assert view.reason == "ambiguous_legacy_request"
    await agent_mail_service.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=people[1].id, thread_root_id=second.id, body_markdown="Second."),
        auto_nudge=False)
    view = await observe(db, team, states(people))
    assert view.complete is True and view.reason is None


@pytest.mark.asyncio
async def test_a_root_request_with_a_nested_one_clears_the_root_only(db):
    team, people = await make_team(db)
    root = await add_request(db, people[0], people[1])
    nested = await add_request(db, people[0], people[1], thread=root.id)
    await db.commit()
    await add_reply(db, people[1], root.id)
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.reason == "ambiguous_legacy_request"
    assert (await db.get(MailMessage, nested.id)).request_status == "pending"


# --- bounds and coverage ----------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("count,complete,reason", [(64, True, None), (65, False, "candidate_limit")])
async def test_candidate_bound(db, count, complete, reason):
    team, people = await make_team(db)
    for index in range(count):
        # Not yet stalled: they are candidates but never entries, so only the bound matters.
        await add_request(db, people[0], people[1], age=10 + index)
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.complete is complete and view.reason == reason and view.items == []


@pytest.mark.asyncio
async def test_entry_cap_reports_the_oldest_sixteen_and_counts_the_omitted(db):
    team, people = await make_team(db)
    made = [await add_request(db, people[0], people[1], age=THRESHOLD + 100 - index) for index in range(17)]
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [row.id for row in made[:16]]
    assert view.reason == "entry_limit" and view.omitted_count == 1 and not view.complete


@pytest.mark.asyncio
async def test_old_plain_answered_requests_never_hide_a_newer_unanswered_one(db):
    team, people = await make_team(db)
    for index in range(64):
        old = await add_request(db, people[0], people[1], age=THRESHOLD + 5000 + index)
        await db.flush()
        await add_reply(db, people[1], old.id)
    newer = await add_request(db, people[0], people[2], age=THRESHOLD + 1)
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [newer.id] and view.complete is True


@pytest.mark.asyncio
async def test_a_parent_with_the_probe_cap_of_children_is_unproven_not_a_no_reply(db):
    # Adapted: the sentinel is now the 33-row cap of one probe of the request's own thread.
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.flush()
    first = await add_reply(db, people[0], request.id)
    for _ in range(32):
        await add_reply(db, people[0], request.id)         # 33 children by the requester under the request
    await add_reply(db, people[1], first.id)               # the addressee's reply sits one level deeper
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.reason == "reply_scan_limit" and not view.complete


@pytest.mark.asyncio
async def test_total_reply_budget_stops_before_claiming_no_reply(db):
    # Adapted: the shared 256 rows / 512 reads are spent by descents of the requests' own threads.
    team, people = await make_team(db)
    for index in range(30):
        request = await add_request(db, people[0], people[1], age=THRESHOLD + 1000 - index)
        await db.flush()
        parent = request.id
        for _ in range(20):
            parent = (await add_reply(db, people[0], parent)).id
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.reason == "reply_scan_limit" and not view.complete
    assert len(view.items) <= 16


@pytest.mark.asyncio
async def test_reason_priority_is_fixed(db):
    team, people = await make_team(db)
    for index in range(65):
        await add_request(db, people[0], people[1], age=THRESHOLD + index)
    await db.commit()
    # candidate_limit beats native_unknown, which beats entry_limit.
    assert (await observe(db, team, states(people, p1="unknown"))).reason == "candidate_limit"
    team2, people2 = await make_team(db, "Second")
    for index in range(17):
        await add_request(db, people2[0], people2[1], age=THRESHOLD + 100 + index)
    await add_request(db, people2[0], people2[2], age=THRESHOLD + 5)
    await db.commit()
    assert (await observe(db, team2, states(people2, p2="stopped"))).reason == "native_unknown"
    assert (await observe(db, team2, states(people2))).reason == "entry_limit"


@pytest.mark.asyncio
async def test_a_slow_observation_times_out_into_an_incomplete_view(db):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    service = MailRequestStallService()
    service.deadline_seconds = 0.05

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(5)

    service._candidates = hang
    view = await observe(db, team, states(people), service=service)
    assert view.items == [] and view.reason == "native_unknown" and not view.complete


def slow_phases(service, states_by_slot, native=0.0, mail=0.0):
    """Only the two phases are slow; everything else is the real projection."""
    async def native_phase(db, preset_id):
        await asyncio.sleep(native)
        return states_by_slot, True, None

    original = service._observe

    async def mail_phase(*args):
        await asyncio.sleep(mail)
        return await original(*args)

    service._native_states = native_phase
    service._observe = mail_phase


@pytest.mark.asyncio
async def test_native_and_mail_phases_share_one_deadline(db):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    service = MailRequestStallService()
    service.deadline_seconds = 0.2
    slow_phases(service, states(people), native=0.15, mail=0.15)
    view = await service.projection(db, team.id)
    assert view.items == [] and view.reason == "native_unknown" and not view.complete


@pytest.mark.asyncio
async def test_two_phases_inside_the_budget_are_complete_and_listed(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    service = MailRequestStallService()
    service.deadline_seconds = 2.0
    slow_phases(service, states(people), native=0.05, mail=0.05)
    view = await service.projection(db, team.id)
    assert ids(view) == [request.id] and view.complete is True


@pytest.mark.asyncio
async def test_an_exhausted_budget_before_the_mail_phase_is_incomplete_and_leaves_no_transaction(db):
    from sqlalchemy import select

    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    await db.execute(select(MailMessage.id).limit(1))
    assert db.in_transaction()
    service = MailRequestStallService()
    service.deadline_seconds = 0.05
    slow_phases(service, states(people), native=0.3, mail=0.0)
    view = await service.projection(db, team.id)
    assert view.items == [] and view.reason == "native_unknown" and not view.complete
    assert not db.in_transaction()


@pytest.mark.asyncio
async def test_an_absolute_deadline_that_has_already_passed_is_the_incomplete_view(db):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    past = asyncio.get_running_loop().time() - 1
    view = await MailRequestStallService().observe(
        db, team.id, now=datetime.now(timezone.utc), native_states=states(people), native_ok=True, deadline=past)
    assert view.items == [] and view.reason == "native_unknown" and not view.complete


# --- native provenance: the idle evidence belongs to the current addressee and is revalidated (F2) ----

async def bind_session(db, team, person, *, pid, cwd, member=None):
    """A real pane binding and authenticated session row; only the native observation leaf is faked."""
    owner = member or person.member
    db.add(AgentPaneBinding(pane_pid=pid, pane_proc_start="fixture-start", slot_id=person.slot.id,
                            preset_id=team.id))
    db.add(MailAgentSession(member_id=owner.id, provider="codex-cli", source="mcp", session_key=f"session-{pid}",
                            cwd=cwd, team_preset_id=team.id, team_slot_id=person.slot.id,
                            capability_token_hash="synthetic-hash", bound_pane_pid=pid,
                            bound_pane_proc_start="fixture-start"))
    await db.commit()


def idle_when_bound(monkeypatch):
    def native(slot_id, provider, session_id, bindings, ambiguous, now, **kwargs):
        return AgentActivityObservation(slot_id=slot_id, state="idle" if bindings else "unknown",
                                        reason="synthetic-native-observation", observed_at=now)

    monkeypatch.setattr("app.services.agent_activity_service._observe", native)


def after_legacy_scan(monkeypatch, service, action):
    """Run ``action`` once the mail reads of the view are under way."""
    original = service._legacy_reply_clears

    async def wrapped(*args):
        result = await original(*args)
        await action()
        return result

    monkeypatch.setattr(service, "_legacy_reply_clears", wrapped)


async def replace_member(db, team, person, *, key="replacement"):
    """A newer member row for the same slot: the slot's current member from now on."""
    replacement = MailTeamMember(identity_key=f"slot:{key}", repo_id="r", repo_path="/r", repo_name="r",
                                 display_name=key, participant_kind="team_slot", team_preset_id=team.id,
                                 team_slot_id=person.slot.id,
                                 updated_at=person.member.updated_at + timedelta(seconds=10))
    db.add(replacement)
    await db.commit()
    return replacement


async def change_slot_session(db, person):
    person.slot.launch_options = {"session_id": "changed-native-conversation"}
    await db.commit()


@pytest.mark.asyncio
async def test_a_stable_bound_addressee_is_listed_and_complete(db, monkeypatch):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    await bind_session(db, team, people[1], pid=19000, cwd="/current-workspace")
    idle_when_bound(monkeypatch)
    view = await MailRequestStallService().projection(db, team.id)
    assert ids(view) == [request.id] and view.complete is True


@pytest.mark.asyncio
async def test_native_inputs_that_change_during_the_mail_reads_are_not_idle_evidence(db, monkeypatch):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    await bind_session(db, team, people[1], pid=19002, cwd="/current-workspace")
    idle_when_bound(monkeypatch)
    service = MailRequestStallService()
    after_legacy_scan(monkeypatch, service, lambda: change_slot_session(db, people[1]))
    view = await service.projection(db, team.id)
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_the_summary_also_revalidates_the_native_inputs_after_the_mail_reads(db, monkeypatch):
    from app.services.mail_request_stall_service import mail_request_stall_service

    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    await bind_session(db, team, people[1], pid=19003, cwd="/current-workspace")
    idle_when_bound(monkeypatch)
    after_legacy_scan(monkeypatch, mail_request_stall_service, lambda: change_slot_session(db, people[1]))
    summary, _elapsed = await summary_for(db, monkeypatch, people, team)
    view = summary.supervisor_observation.unanswered_requests
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"
    assert not [item for item in summary.attention if item.code == "unanswered_request"]


@pytest.mark.asyncio
async def test_the_summary_lists_a_stable_bound_addressee(db, monkeypatch):
    team, people = await make_team(db)
    request_id = (await add_request(db, people[0], people[1])).id
    await db.commit()
    await bind_session(db, team, people[1], pid=19004, cwd="/current-workspace")
    idle_when_bound(monkeypatch)
    summary, _elapsed = await summary_for(db, monkeypatch, people, team)
    view = summary.supervisor_observation.unanswered_requests
    assert [item.request_id for item in view.items] == [request_id] and view.complete is True


@pytest.mark.asyncio
async def test_an_old_addressee_does_not_borrow_the_replacement_members_idle_session(db, monkeypatch):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    replacement = await replace_member(db, team, people[1])
    await bind_session(db, team, people[1], pid=19001, cwd="/replacement-workspace", member=replacement)
    idle_when_bound(monkeypatch)
    view = await MailRequestStallService().projection(db, team.id)
    assert request.id not in ids(view) and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_a_replaced_addressee_is_native_unknown_even_without_a_fence(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await replace_member(db, team, people[1])
    view = await observe(db, team, states(people))
    assert request.id not in ids(view) and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_a_replaced_addressee_is_not_reply_scanned_as_if_it_were_proven_idle(db, monkeypatch):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await replace_member(db, team, people[1])
    service = MailRequestStallService()
    scans = []
    original = service._legacy_reply_clears

    async def spy(*args):
        scans.append(args[1].id)
        return await original(*args)

    monkeypatch.setattr(service, "_legacy_reply_clears", spy)
    view = await observe(db, team, states(people), service=service)
    assert scans == [] and view.reason == "native_unknown" and view.items == []


@pytest.mark.asyncio
async def test_a_replacement_that_appears_during_the_mail_reads_is_caught_by_the_final_recheck(db, monkeypatch):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    service = MailRequestStallService()
    after_legacy_scan(monkeypatch, service, lambda: replace_member(db, team, people[1]))
    view = await observe(db, team, states(people), service=service)
    assert request.id not in ids(view) and view.complete is False and view.reason == "native_unknown"


# --- one coherent, fresh and identity-bound native observation (F2, revision C2a) --------------------
# Concurrent changes come from a SECOND connection: only another connection moves SQLite's data version.

def second_session(db):
    return async_sessionmaker(db.bind, expire_on_commit=False)()


def raw_update_launch_options(db, slot_id, value):
    """A change committed by a separate raw sqlite connection (synchronous, usable inside a sync builder)."""
    connection = sqlite3.connect(db.bind.url.database)
    try:
        connection.execute(f"UPDATE {AgentTeamSlot.__tablename__} SET launch_options = ? WHERE id = ?",
                           (json.dumps({"session_id": value}), slot_id))
        connection.commit()
    finally:
        connection.close()


async def commit_new_current_member(db, team, person, *, pid, cwd):
    """A newer member row plus a NEW authenticated session for the same provider, pane, start and cwd."""
    async with second_session(db) as other:
        member = MailTeamMember(identity_key=f"slot:final-{pid}", repo_id="r", repo_path="/r", repo_name="r",
                                display_name="final", participant_kind="team_slot", team_preset_id=team.id,
                                team_slot_id=person.slot.id,
                                updated_at=person.member.updated_at + timedelta(seconds=30))
        other.add(member)
        await other.flush()
        other.add(MailAgentSession(member_id=member.id, provider="codex-cli", source="mcp",
                                   session_key=f"session-final-{pid}", cwd=cwd, team_preset_id=team.id,
                                   team_slot_id=person.slot.id, capability_token_hash="synthetic-hash",
                                   bound_pane_pid=pid, bound_pane_proc_start="fixture-start"))
        await other.commit()


async def commit_new_session_same_member(db, team, person, *, pid, cwd):
    """The old session is closed and a new authenticated session of the SAME member takes the binding."""
    async with second_session(db) as other:
        await other.execute(update(MailAgentSession).where(MailAgentSession.member_id == person.member.id)
                            .values(closed_at=datetime.utcnow()))
        other.add(MailAgentSession(member_id=person.member.id, provider="codex-cli", source="mcp",
                                   session_key=f"session-new-{pid}", cwd=cwd, team_preset_id=team.id,
                                   team_slot_id=person.slot.id, capability_token_hash="synthetic-hash",
                                   bound_pane_pid=pid, bound_pane_proc_start="fixture-start"))
        await other.commit()


class Gate:
    def __init__(self):
        self.armed = False
        self.fired = 0


def arm_after_names(monkeypatch, service, gate):
    original = service._names

    async def wrapped(*args):
        result = await original(*args)
        gate.armed = True
        return result

    monkeypatch.setattr(service, "_names", wrapped)


def act_before_first_input_read(monkeypatch, gate, action):
    """Run ``action`` once, just before the first native input read after the names were read."""
    from app.services import agent_activity_service as activity

    original = activity._team_inputs

    async def wrapped(*args, **kwargs):
        if gate.armed and not gate.fired:
            gate.fired = 1
            await action()
        return await original(*args, **kwargs)

    monkeypatch.setattr(activity, "_team_inputs", wrapped)


async def inputs_of(db, team):
    from app.services import agent_activity_service as activity

    return await activity._team_inputs(db, team.id, 256)


async def bound_fixture(db, monkeypatch, *, pid):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    await bind_session(db, team, people[1], pid=pid, cwd="/same-workspace")
    idle_when_bound(monkeypatch)
    return team, people


@pytest.mark.asyncio
async def test_a_newer_member_with_a_new_matching_session_after_the_names_read_is_not_old_evidence(db, monkeypatch):
    team, people = await bound_fixture(db, monkeypatch, pid=19501)
    service = MailRequestStallService()
    gate, before = Gate(), await inputs_of(db, team)

    async def act():
        await commit_new_current_member(db, team, people[1], pid=19501, cwd="/same-workspace")
        assert await inputs_of(db, team) == before     # the native input tuple cannot see the change

    arm_after_names(monkeypatch, service, gate)
    act_before_first_input_read(monkeypatch, gate, act)
    view = await service.projection(db, team.id)
    assert gate.fired == 1
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_a_new_session_of_the_same_member_after_the_names_read_is_not_old_evidence(db, monkeypatch):
    team, people = await bound_fixture(db, monkeypatch, pid=19502)
    service = MailRequestStallService()
    gate, before = Gate(), await inputs_of(db, team)

    async def act():
        await commit_new_session_same_member(db, team, people[1], pid=19502, cwd="/same-workspace")
        assert await inputs_of(db, team) == before

    arm_after_names(monkeypatch, service, gate)
    act_before_first_input_read(monkeypatch, gate, act)
    view = await service.projection(db, team.id)
    assert gate.fired == 1
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_an_input_change_committed_by_another_connection_before_the_final_read_is_native_unknown(db, monkeypatch):
    team, people = await bound_fixture(db, monkeypatch, pid=19503)
    service = MailRequestStallService()
    gate = Gate()
    arm_after_names(monkeypatch, service, gate)
    act_before_first_input_read(monkeypatch, gate,
                                lambda: asyncio.sleep(0, raw_update_launch_options(db, people[1].slot.id, "changed-1")))
    view = await service.projection(db, team.id)
    assert gate.fired == 1
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_a_change_between_the_builders_component_reads_discards_the_attempt(db, monkeypatch):
    from app.services import agent_activity_service as activity

    team, people = await bound_fixture(db, monkeypatch, pid=19504)
    service = MailRequestStallService()
    gate, calls = Gate(), []
    arm_after_names(monkeypatch, service, gate)
    original = activity._inputs_from_rows

    def mid_read(*args, **kwargs):
        if gate.armed:
            calls.append(1)
            if len(calls) == 1:     # the rows were read; another connection commits before they are used
                raw_update_launch_options(db, people[1].slot.id, "changed-between-reads")
        return original(*args, **kwargs)

    monkeypatch.setattr(activity, "_inputs_from_rows", mid_read)
    view = await service.projection(db, team.id)
    assert len(calls) >= 2                      # the first attempt was discarded and read again
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_three_incoherent_attempts_fail_closed(db, monkeypatch):
    from app.services import agent_activity_service as activity

    team, people = await bound_fixture(db, monkeypatch, pid=19505)
    service = MailRequestStallService()
    gate, calls = Gate(), []
    arm_after_names(monkeypatch, service, gate)
    original = activity._inputs_from_rows

    def always_changing(*args, **kwargs):
        if gate.armed:
            calls.append(1)
            raw_update_launch_options(db, people[1].slot.id, f"changed-{len(calls)}")
        return original(*args, **kwargs)

    monkeypatch.setattr(activity, "_inputs_from_rows", always_changing)
    view = await service.projection(db, team.id)
    assert len(calls) == 3
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError("activity_context_limit"), OSError("read failed"), "timeout"])
async def test_a_failed_early_projection_capture_is_untrusted_and_never_replaced(db, monkeypatch, failure):
    team, people = await bound_fixture(db, monkeypatch, pid=19506)
    service = MailRequestStallService()
    service.deadline_seconds = 0.5
    original, calls = service._coherent_snapshot, []

    async def failing(*args):
        calls.append(1)
        if len(calls) == 1:
            if failure == "timeout":
                await asyncio.sleep(2)
            raise failure
        return await original(*args)

    monkeypatch.setattr(service, "_coherent_snapshot", failing)
    view = await service.projection(db, team.id)
    assert len(calls) == 1                       # no replacement baseline was ever taken
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
async def test_the_identity_argument_does_not_change_the_native_inputs(db, monkeypatch):
    from app.services import agent_activity_service as activity

    team, people = await bound_fixture(db, monkeypatch, pid=19507)
    identity = {}
    with_identity = await activity._team_inputs(db, team.id, 256, identity=identity)
    assert with_identity == await activity._team_inputs(db, team.id, 256)
    session_ids = (await db.execute(select_session_ids(people[1]))).scalars().all()
    assert identity[people[1].slot.id] == (people[1].member.id, tuple(sorted(session_ids)))
    assert identity[people[0].slot.id] == (people[0].member.id, ())


def select_session_ids(person):
    from sqlalchemy import select

    return select(MailAgentSession.id).where(MailAgentSession.member_id == person.member.id)


@pytest.mark.asyncio
async def test_a_commit_by_the_same_connection_does_not_discard_a_snapshot(db, monkeypatch):
    from app.services import agent_activity_service as activity

    team, people = await bound_fixture(db, monkeypatch, pid=19508)
    service = MailRequestStallService()
    original, calls = activity._team_inputs, []

    async def own_commit(*args, **kwargs):
        calls.append(1)
        result = await original(*args, **kwargs)
        await db.execute(update(AgentTeamSlot).where(AgentTeamSlot.id == people[0].slot.id)
                         .values(display_name="renamed by this connection"))
        await db.commit()
        return result

    monkeypatch.setattr(activity, "_team_inputs", own_commit)
    inputs, identity = await service._coherent_snapshot(db, team.id)
    assert len(calls) == 1 and identity[people[1].slot.id][0] == people[1].member.id


@pytest.mark.asyncio
async def test_the_snapshot_attempt_is_pinned_to_one_physical_connection(db, monkeypatch):
    team, people = await bound_fixture(db, monkeypatch, pid=19509)
    service = MailRequestStallService()
    seen = []
    original = service._pinned_driver

    async def spy(session):
        driver = await original(session)
        seen.append(driver)
        return driver

    monkeypatch.setattr(service, "_pinned_driver", spy)
    await service._coherent_snapshot(db, team.id)
    assert len(seen) >= 2 and all(driver is seen[0] for driver in seen)

    # A different physical connection at the end of an attempt is never accepted.
    calls = []

    async def swapping(session):
        driver = await original(session)
        calls.append(1)
        return driver if len(calls) % 2 == 1 else object()

    monkeypatch.setattr(service, "_pinned_driver", swapping)
    with pytest.raises(ValueError):
        await service._coherent_snapshot(db, team.id)


@pytest.mark.asyncio
async def test_an_open_transaction_pinning_an_old_snapshot_is_never_certified(db, monkeypatch):
    team, people = await bound_fixture(db, monkeypatch, pid=19510)
    team_id, slot_id = team.id, people[1].slot.id
    await db.execute(text("PRAGMA journal_mode=WAL"))
    service = MailRequestStallService()
    await db.execute(text("BEGIN"))
    await db.execute(text("SELECT count(*) FROM mail_messages"))       # the read transaction pins a snapshot
    raw_update_launch_options(db, slot_id, "committed-by-another-connection")
    with pytest.raises(ValueError):
        await service._coherent_snapshot(db, team_id)
    await db.rollback()
    inputs, identity = await service._coherent_snapshot(db, team_id)    # fresh again after the rollback
    assert slot_id in identity


# --- the summary takes its identity baseline before its native await (F2, revision C2b) -------------

@pytest.mark.asyncio
async def test_a_member_replaced_between_the_summarys_native_await_and_the_stall_view_is_not_old_evidence(db, monkeypatch):
    team, people = await bound_fixture(db, monkeypatch, pid=19601)
    before = await inputs_of(db, team)

    async def replace():
        await commit_new_current_member(db, team, people[1], pid=19601, cwd="/same-workspace")
        assert await inputs_of(db, team) == before         # the native input tuple cannot see it

    summary, _elapsed = await summary_for(db, monkeypatch, people, team, attention=_HookedAttention(replace))
    view = summary.supervisor_observation.unanswered_requests
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"
    assert not [item for item in summary.attention if item.code == "unanswered_request"]


@pytest.mark.asyncio
async def test_a_session_replaced_between_the_summarys_native_await_and_the_stall_view_is_not_old_evidence(db, monkeypatch):
    team, people = await bound_fixture(db, monkeypatch, pid=19602)
    before = await inputs_of(db, team)

    async def replace():
        await commit_new_session_same_member(db, team, people[1], pid=19602, cwd="/same-workspace")
        assert await inputs_of(db, team) == before

    summary, _elapsed = await summary_for(db, monkeypatch, people, team, attention=_HookedAttention(replace))
    view = summary.supervisor_observation.unanswered_requests
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError("activity_context_limit"), OSError("read failed"), "timeout"])
async def test_a_failed_early_summary_capture_is_untrusted_and_never_replaced(db, monkeypatch, failure):
    from app.services.mail_request_stall_service import mail_request_stall_service

    team, people = await bound_fixture(db, monkeypatch, pid=19603)
    monkeypatch.setattr(mail_request_stall_service, "deadline_seconds", 0.5)
    original, calls = mail_request_stall_service._coherent_snapshot, []

    async def failing(*args):
        calls.append(1)
        if len(calls) == 1:
            if failure == "timeout":
                await asyncio.sleep(2)
            raise failure
        return await original(*args)

    monkeypatch.setattr(mail_request_stall_service, "_coherent_snapshot", failing)
    seen = []
    observe_original = mail_request_stall_service.observe

    async def spy(*args, **kwargs):
        seen.append(kwargs.get("native_baseline", "omitted"))
        return await observe_original(*args, **kwargs)

    monkeypatch.setattr(mail_request_stall_service, "observe", spy)
    summary, _elapsed = await summary_for(db, monkeypatch, people, team)
    view = summary.supervisor_observation.unanswered_requests
    assert seen == [None]                          # a FAILED capture is passed as None, not as omitted
    assert len(calls) == 1                         # no replacement baseline was ever taken
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"
    assert not [item for item in summary.attention if item.code == "unanswered_request"]


@pytest.mark.asyncio
async def test_the_summary_passes_the_baseline_it_captured_before_the_native_await(db, monkeypatch):
    from app.services.mail_request_stall_service import _UNSET, mail_request_stall_service

    team, people = await bound_fixture(db, monkeypatch, pid=19604)
    seen = []
    original = mail_request_stall_service.observe

    async def spy(*args, **kwargs):
        seen.append(kwargs.get("native_baseline", _UNSET))
        return await original(*args, **kwargs)

    monkeypatch.setattr(mail_request_stall_service, "observe", spy)
    summary, _elapsed = await summary_for(db, monkeypatch, people, team)
    assert len(seen) == 1 and seen[0] is not _UNSET and seen[0] is not None
    inputs, identity = seen[0]
    assert people[1].slot.id in identity


@pytest.mark.asyncio
async def test_a_failed_early_capture_leaves_the_summarys_other_data_in_place(db, monkeypatch):
    from app.services.mail_request_stall_service import mail_request_stall_service

    team, people = await bound_fixture(db, monkeypatch, pid=19605)

    async def failing(*args):
        raise OSError("read failed")

    monkeypatch.setattr(mail_request_stall_service, "_coherent_snapshot", failing)
    summary, _elapsed = await summary_for(db, monkeypatch, people, team)
    assert summary is not None
    incomplete = [item for item in summary.attention if item.code == "unanswered_request_incomplete"]
    assert len(incomplete) == 1 and incomplete[0].coverage_reason == "native_unknown"
    assert summary.supervisor_observation.unanswered_requests.reason == "native_unknown"


# --- the reply proof descends the request's own thread through an index (F4, revision D) -------------

async def reply_chain(db, request, people, depth, *, bottom=None, keyed=False):
    """``depth`` replies by the requester, each under the previous one, then optionally a reply by ``bottom``."""
    parent = request.id
    for _ in range(depth):
        parent = (await add_reply(db, people[0], parent)).id
    if bottom is None:
        return parent
    row = MailMessage(kind="answer" if keyed else "message", sender_member_id=bottom.id, thread_root_id=parent,
                      payload={"resolves_request_id": 999} if keyed else None, body_markdown="reply",
                      audience_type="member", audience_id=str(bottom.id))
    db.add(row)
    await db.flush()
    return row


def candidate_of(request, person):
    return SimpleNamespace(id=request.id, recipient_member_id=person.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [2, 5, 20])
async def test_a_legacy_reply_at_any_depth_clears_even_when_the_sender_has_many_other_replies(db, depth):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    unrelated = await add_reply(db, people[2], None)
    await db.flush()
    for _ in range(40):
        await add_reply(db, people[1], unrelated.id)       # the addressee's unrelated replies, older than the chain
    await reply_chain(db, request, people, depth, bottom=people[1])
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.complete is True and view.reason is None


@pytest.mark.asyncio
async def test_the_proof_does_not_spend_the_row_budget_on_unrelated_replies(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    unrelated = await add_reply(db, people[2], None)
    await db.flush()
    for _ in range(200):
        await add_reply(db, people[1], unrelated.id)
    await db.commit()
    cleared, proven, used = await MailRequestStallService()._legacy_reply_clears(
        db, candidate_of(request, people[1]), 256, {}, [0])
    assert (cleared, proven) == (False, True) and used <= 2


@pytest.mark.asyncio
async def test_the_proof_work_does_not_grow_with_unrelated_rows(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    other = await add_reply(db, people[2], None)
    await db.flush()
    service = MailRequestStallService()
    candidate = candidate_of(request, people[1])
    await _bulk_unrelated(db, other.id, people[2], 600)
    small = await _vm_operations(db, lambda: service._legacy_reply_clears(db, candidate, 256, {}, [0]))
    await _bulk_unrelated(db, other.id, people[2], 5400)
    large = await _vm_operations(db, lambda: service._legacy_reply_clears(db, candidate, 256, {}, [0]))
    assert large <= small * 1.25 + 200, (small, large)


async def _bulk_unrelated(db, parent, sender, count):
    rows = [{"kind": "message", "sender_member_id": sender.id, "thread_root_id": parent, "body_markdown": "r",
             "audience_type": "member", "audience_id": str(sender.id)} for _ in range(count)]
    await db.execute(MailMessage.__table__.insert(), rows)
    await db.commit()


async def _vm_operations(db, read):
    connection = await (await db.connection()).get_raw_connection()
    driver, ticks = connection.driver_connection, [0]

    def tick():
        ticks[0] += 1
        return 0

    await driver.set_progress_handler(tick, 10)
    try:
        await read()
    finally:
        await driver.set_progress_handler(None, 0)
    return ticks[0] * 10


@pytest.mark.asyncio
async def test_the_reply_probe_uses_the_thread_root_index_without_sorting(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    query = MailRequestStallService._reply_probe(request.id, request.id, 33)
    sql = str(query.compile(compile_kwargs={"literal_binds": True}))
    detail = " ".join(row[3] for row in (await db.execute(text("EXPLAIN QUERY PLAN " + sql))).all())
    assert "SEARCH" in detail and "ix_mail_messages_thread_root_id" in detail
    assert "TEMP B-TREE" not in detail and "SCAN" not in detail


@pytest.mark.asyncio
async def test_a_descent_deeper_than_the_hop_bound_is_unproven(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.flush()
    await reply_chain(db, request, people, 34, bottom=people[1])
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.reason == "reply_scan_limit" and not view.complete


@pytest.mark.asyncio
async def test_thirty_two_children_are_below_the_probe_cap_and_the_deeper_reply_clears(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.flush()
    first = await add_reply(db, people[0], request.id)
    for _ in range(31):
        await add_reply(db, people[0], request.id)         # 32 children: one below the probe cap
    await add_reply(db, people[1], first.id)               # the addressee's reply, one level deeper
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.complete is True


@pytest.mark.asyncio
async def test_a_probe_never_reads_past_the_remaining_row_capacity(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.flush()
    for _ in range(10):
        await add_reply(db, people[0], request.id)
    await db.commit()
    service = MailRequestStallService()
    limits = []
    original = MailRequestStallService._reply_probe

    def spy(parent, request_id, limit):
        limits.append(limit)
        return original(parent, request_id, limit)

    service._reply_probe = spy
    result = await service._legacy_reply_clears(db, candidate_of(request, people[1]), 5, {}, [0])
    assert result == (False, False, 5) and limits == [5]        # capacity 5: limit 5, five rows charged, unproven
    limits.clear()
    result = await service._legacy_reply_clears(db, candidate_of(request, people[1]), 256, {}, [512])
    assert result == (False, False, 0) and limits == []         # no read capacity: fail closed BEFORE any query


@pytest.mark.asyncio
async def test_every_probe_is_charged_one_read_and_the_last_read_is_the_last(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.flush()
    await reply_chain(db, request, people, 3)
    await db.commit()
    counter = [510]
    result = await MailRequestStallService()._legacy_reply_clears(db, candidate_of(request, people[1]), 256, {}, counter)
    assert result == (False, False, 2) and counter[0] == 512      # reads 511 and 512 ran; a third is refused


@pytest.mark.asyncio
async def test_a_keyed_answer_at_depth_never_clears(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.flush()
    await reply_chain(db, request, people, 6, bottom=people[1], keyed=True)
    await db.commit()
    view = await observe(db, team, states(people))
    assert ids(view) == [request.id] and view.complete is True


# --- privacy, order, repetition ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_external_requester_name_is_sanitized_and_nothing_private_is_exposed(db):
    team, people = await make_team(db)
    actor = MailExternalActor(actor_key="stall-actor", display_name="Ops token=SECRETVALUE123 " + "x" * 200,
                              kind="external_tool", token_hash=hashlib.sha256(b"t").hexdigest())
    db.add(actor)
    await db.flush()
    await add_request(db, None, people[1], actor=actor)
    await db.commit()
    view = await observe(db, team, states(people))
    dumped = view.model_dump_json()
    assert len(view.items) == 1 and len(view.items[0].requester) <= 80
    for forbidden in ("SECRETVALUE123", "PRIVATE-SUBJECT", "PRIVATE-BODY", "token_hash", "private"):
        assert forbidden not in dumped


@pytest.mark.asyncio
async def test_order_is_deterministic_and_repeated_observations_are_identical(db):
    team, people = await make_team(db)
    newer = await add_request(db, people[0], people[1], age=THRESHOLD + 10)
    older = await add_request(db, people[2], people[1], age=THRESHOLD + 500)
    same_age_first = await add_request(db, people[0], people[2], age=THRESHOLD + 200)
    await db.commit()
    first = await observe(db, team, states(people))
    second = await observe(db, team, states(people))
    assert ids(first) == [older.id, same_age_first.id, newer.id]
    assert [item.model_dump(exclude={"unanswered_seconds"}) for item in first.items] == [
        item.model_dump(exclude={"unanswered_seconds"}) for item in second.items]
    assert first.items[0].text == f"{people[1].name} has not answered {people[2].name}'s request for {(THRESHOLD + 500) // 60} min."


# --- the real summary and the authenticated check-in ------------------------------------------

def fake_native(monkeypatch, people, by_index=None, boom=False, delay=0.0):
    by_index = by_index or {}
    owners = [(person.slot.id, person.id) for person in people]     # plain ids: ORM rows expire later

    async def observe_team(db, preset_id, **kwargs):
        await asyncio.sleep(delay)
        if kwargs.get("input_fence") is not None:
            kwargs["input_fence"].clear()
        return SimpleNamespace(
            slots=[SimpleNamespace(slot_id=person.slot.id, state=by_index.get(index, "idle"), waiting_input=None)
                   for index, person in enumerate(people)],
            valid_until=datetime.now(timezone.utc) + timedelta(seconds=60))

    async def team_inputs(db, preset_id, max_rows=None, identity=None):
        if identity is not None:
            for slot_id, member_id in owners:
                identity[slot_id] = (member_id, ())
        return []

    monkeypatch.setattr("app.services.agent_activity_service.observe_team", observe_team)
    monkeypatch.setattr("app.services.agent_activity_service._team_inputs", team_inputs)
    if boom:
        # Only this signal's own native read fails; the unrelated team_idle projection is untouched.
        async def failing(self, db, preset_id):
            raise OSError("native read failed")

        monkeypatch.setattr(MailRequestStallService, "_native_states", failing)


class _Attention:
    async def summary(self, db, preset_id):
        return {"coverage_complete": True, "actions": [],
                "observation_expires_at": datetime.now(timezone.utc) + timedelta(seconds=60)}

    async def dispatch_snapshot(self, db, scopes):
        return {"complete": True, "actions": []}


class _HookedAttention(_Attention):
    """The summary calls dispatch_snapshot after its native await and before the stall view starts."""

    def __init__(self, action):
        self.action = action

    async def dispatch_snapshot(self, db, scopes):
        await self.action()
        return await super().dispatch_snapshot(db, scopes)


@pytest.mark.asyncio
async def test_the_team_summary_shows_the_request_on_both_surfaces(db, monkeypatch):
    from app.services.agent_team_summary_service import AgentTeamSummaryService

    monkeypatch.setattr("app.services.agent_team_summary_service.hold_code", lambda: None)

    async def no_supervisor(db, preset_id, now=None):
        return None

    monkeypatch.setattr("app.services.agent_team_summary_service.observe_supervisor", no_supervisor)
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    fake_native(monkeypatch, people)
    summary = await AgentTeamSummaryService(attention=_Attention()).summary(db, team.id)
    entries = [item for item in summary.attention if item.code == "unanswered_request"]
    assert [entry.request_id for entry in entries] == [request.id]
    assert entries[0].requester == people[0].name and entries[0].recipient == people[1].name
    assert entries[0].unanswered_seconds >= THRESHOLD
    assert not [item for item in summary.attention if item.code == "unanswered_request_incomplete"]
    view = summary.supervisor_observation.unanswered_requests
    assert [item.request_id for item in view.items] == [request.id] and view.complete is True
    # team_idle and next-actor authority are untouched by this signal.
    assert not [item for item in summary.attention if item.code == "team_idle"]
    assert summary.next_actors == []


@pytest.mark.asyncio
async def test_the_team_summary_labels_an_incomplete_view_with_its_reason(db, monkeypatch):
    from app.services.agent_team_summary_service import AgentTeamSummaryService

    monkeypatch.setattr("app.services.agent_team_summary_service.hold_code", lambda: None)

    async def no_supervisor(db, preset_id, now=None):
        return None

    monkeypatch.setattr("app.services.agent_team_summary_service.observe_supervisor", no_supervisor)
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    fake_native(monkeypatch, people, {1: "unknown"})
    summary = await AgentTeamSummaryService(attention=_Attention()).summary(db, team.id)
    incomplete = [item for item in summary.attention if item.code == "unanswered_request_incomplete"]
    assert len(incomplete) == 1 and incomplete[0].coverage_reason == "native_unknown"
    assert not [item for item in summary.attention if item.code == "unanswered_request"]
    assert summary.supervisor_observation.unanswered_requests.complete is False


async def summary_for(db, monkeypatch, people, team, attention=None, **service_args):
    from app.services.agent_team_summary_service import AgentTeamSummaryService

    monkeypatch.setattr("app.services.agent_team_summary_service.hold_code", lambda: None)

    async def no_supervisor(db, preset_id, now=None):
        return None

    monkeypatch.setattr("app.services.agent_team_summary_service.observe_supervisor", no_supervisor)
    started = asyncio.get_running_loop().time()
    summary = await AgentTeamSummaryService(attention=attention or _Attention(), **service_args).summary(
        db, team.id)
    return summary, asyncio.get_running_loop().time() - started


def slow_stall_mail_phase(monkeypatch, seconds):
    from app.services.mail_request_stall_service import mail_request_stall_service

    original = mail_request_stall_service._observe

    async def slow(*args):
        await asyncio.sleep(seconds)
        return await original(*args)

    monkeypatch.setattr(mail_request_stall_service, "_observe", slow)
    return mail_request_stall_service


@pytest.mark.asyncio
async def test_the_summary_keeps_the_five_second_stall_budget_inside_its_eight_second_window(db, monkeypatch):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    fake_native(monkeypatch, people, delay=0.15)
    stall = slow_stall_mail_phase(monkeypatch, 0.15)
    monkeypatch.setattr(stall, "deadline_seconds", 0.2)
    summary, _elapsed = await summary_for(db, monkeypatch, people, team)    # the default eight-second window
    # The summary's own window is not exceeded, so it completes; the stall view is bounded by its own budget.
    assert summary.coverage_complete is True
    view = summary.supervisor_observation.unanswered_requests
    assert view.items == [] and view.reason == "native_unknown" and view.complete is False
    assert not [item for item in summary.attention if item.code == "unanswered_request"]


@pytest.mark.asyncio
async def test_the_summary_native_await_itself_stops_at_the_stall_budget(db, monkeypatch):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    fake_native(monkeypatch, people, delay=2.0)          # far longer than the stall budget, shorter than eight seconds
    from app.services.mail_request_stall_service import mail_request_stall_service

    monkeypatch.setattr(mail_request_stall_service, "deadline_seconds", 0.2)
    summary, elapsed = await summary_for(db, monkeypatch, people, team)
    assert elapsed < 1.0
    assert summary.coverage_complete is False
    view = summary.supervisor_observation.unanswered_requests
    assert view.items == [] and view.reason == "native_unknown" and view.complete is False


@pytest.mark.asyncio
async def test_an_earlier_summary_deadline_caps_the_stall_observation(db, monkeypatch):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    fake_native(monkeypatch, people)
    stall = slow_stall_mail_phase(monkeypatch, 2.0)
    monkeypatch.setattr(stall, "deadline_seconds", 5.0)
    summary, elapsed = await summary_for(db, monkeypatch, people, team, observation_seconds=0.5)
    assert elapsed < 1.5
    view = summary.supervisor_observation.unanswered_requests
    assert view.items == [] and view.complete is False and view.reason == "native_unknown"


@pytest_asyncio.fixture
async def supervisor_client(db, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "synthetic-director-token")

    async def database():
        yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


async def bound_supervisor(db, supervisor_client, team):
    actor = MailExternalActor(actor_key="stall-supervisor", display_name="Supervisor", kind="external_tool",
                              token_hash=hashlib.sha256(b"synthetic-actor-token").hexdigest())
    db.add(actor)
    await db.commit()
    await supervisor_client.put(f"/api/v1/agent-teams/presets/{team.id}/supervisor", json={"actor_id": actor.id},
                                headers={"X-Synth-City-Operator-Token": "synthetic-director-token"})
    return {"Authorization": "Bearer synthetic-actor-token"}


def checkin_payload():
    return {"next_check_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}


@pytest.mark.asyncio
async def test_the_authenticated_checkin_returns_the_view_next_to_an_unchanged_team_idle(db, supervisor_client, monkeypatch):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await db.commit()
    auth = await bound_supervisor(db, supervisor_client, team)
    fake_native(monkeypatch, people)
    response = await supervisor_client.post("/api/v1/external/agent-mail/supervisor-checkin",
                                            json={**checkin_payload(), "preset_id": team.id}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "healthy" and body["team_idle"] == []
    assert [item["request_id"] for item in body["unanswered_requests"]["items"]] == [request.id]
    assert body["unanswered_requests"]["complete"] is True
    assert "PRIVATE-BODY" not in response.text and "PRIVATE-SUBJECT" not in response.text


@pytest.mark.asyncio
async def test_the_checkin_promise_is_committed_and_returned_when_the_observation_fails(db, supervisor_client, monkeypatch):
    team, people = await make_team(db)
    await add_request(db, people[0], people[1])
    await db.commit()
    auth = await bound_supervisor(db, supervisor_client, team)
    fake_native(monkeypatch, people, boom=True)
    response = await supervisor_client.post("/api/v1/external/agent-mail/supervisor-checkin",
                                            json={**checkin_payload(), "preset_id": team.id}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "healthy"
    assert body["unanswered_requests"]["complete"] is False
    assert body["unanswered_requests"]["reason"] == "native_unknown"
    assert body["unanswered_requests"]["items"] == []
    await db.refresh(team)
    assert team.supervisor_next_check_at is not None
