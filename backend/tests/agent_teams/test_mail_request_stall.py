"""Unanswered explicit requests are visible on the team summary and the Supervisor check-in (#752).

The signal is a pending context_request or handoff, addressed to an idle member of the team, older
than a configurable threshold. A view that was truncated or could not be proven is never complete.
Native activity is faked in every test; none reads /proc or depends on a host PID.
"""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    MailExternalActor,
    MailMessage,
    MailReceipt,
    MailTeamMember,
)
from app.models.schemas import MailMessageCreate
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
async def test_a_reply_with_broken_ancestry_does_not_clear_and_is_not_proven(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    await add_reply(db, people[1], 999999)       # thread id of a message that does not exist
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.reason == "reply_scan_limit" and not view.complete
    assert request.id


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
async def test_legacy_reply_scan_cap_is_a_sentinel_not_a_no_reply(db):
    team, people = await make_team(db)
    request = await add_request(db, people[0], people[1])
    unrelated = await add_reply(db, people[2], None)
    await db.flush()
    for _ in range(33):
        await add_reply(db, people[1], unrelated.id)       # by the recipient, in another thread
    await db.commit()
    view = await observe(db, team, states(people))
    assert view.items == [] and view.reason == "reply_scan_limit" and not view.complete
    assert request.id


@pytest.mark.asyncio
async def test_total_reply_budget_stops_before_claiming_no_reply(db):
    team, people = await make_team(db)
    unrelated = await add_reply(db, people[2], None)
    await db.flush()
    for index in range(60):
        await add_request(db, people[0], people[1], age=THRESHOLD + 1000 - index)
    for _ in range(5):
        await add_reply(db, people[1], unrelated.id)
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

def fake_native(monkeypatch, people, by_index=None, boom=False):
    by_index = by_index or {}

    async def observe_team(db, preset_id, **kwargs):
        if kwargs.get("input_fence") is not None:
            kwargs["input_fence"].clear()
        return SimpleNamespace(
            slots=[SimpleNamespace(slot_id=person.slot.id, state=by_index.get(index, "idle"), waiting_input=None)
                   for index, person in enumerate(people)],
            valid_until=datetime.now(timezone.utc) + timedelta(seconds=60))

    async def team_inputs(db, preset_id, max_rows=None):
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
