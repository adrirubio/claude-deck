"""#904: auto-merge only a head that the team's reviewer accepted (explicit, authenticated, exact-head facts)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubHeadReview,
    GithubWorkItem,
    GithubRequiredCheckWatch,
    MailTeamMember,
)
from app.services import github_head_acceptance_service as acceptance
from app.services.github_approval_service import GithubApprovalError, github_approval_service
from app.services.github_client import github_client
from app.services.github_verification_service import github_verification_service
from tests.agent_teams.test_github_verification_service import _HoldClient, _item, _scope, db  # noqa: F401

HEAD_A = "a" * 40
HEAD_B = "b" * 40
CI = [{"name": "ci", "status": "completed", "conclusion": "success"}]
EVIDENCE = "https://github.com/o/r/pull/5#pullrequestreview-77"


@pytest.fixture(autouse=True)
def enforcement(monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(github_approval_service, "github_read_token", AsyncMock(return_value=None))


class Case:
    """An auto-merge item whose PR head can move, with a recorded verifier slot."""

    def __init__(self, db, scope, item, client, verifier, monkeypatch):
        self.db, self.scope, self.item, self.client, self.verifier = db, scope, item, client, verifier
        monkeypatch.setattr(github_client, "get_pull", AsyncMock(side_effect=lambda *a, **k: self.client.pull))

    async def tick(self):
        await github_verification_service.process_scope(self.db, self.scope, client=self.client)
        await self.db.refresh(self.item)

    def move_head(self, head):
        self.client.pull["head"] = dict(self.client.pull["head"], sha=head)
        self.item.last_verified_sha = head

    async def record(self, head, verdict="accepted", member=None, **overrides):
        values = dict(dispatch_nonce=self.item.dispatch_nonce, head_sha=head,
                      reviewer_member_id=(member or self.verifier).id, verdict=verdict,
                      summary="Reviewed the exact head", evidence_url=EVIDENCE)
        values.update(overrides)
        return await acceptance.record_head_review(self.db, self.item, **values)


async def slot_member(db, scope, *, role, name, enabled=True):
    count = len((await db.execute(select(AgentTeamSlot).where(AgentTeamSlot.preset_id == scope.preset_id))).scalars().all())
    slot = AgentTeamSlot(preset_id=scope.preset_id, position=count, display_name=name, role=role, provider="codex-cli",
                         repo_id="r", repo_path="/tmp/r", repo_name="r", enabled=enabled)
    db.add(slot)
    await db.flush()
    member = MailTeamMember(identity_key=f"slot:{slot.id}:{name}", repo_id="r", repo_path="/tmp/r", repo_name="r",
                            display_name=name, participant_kind="team_slot", team_preset_id=scope.preset_id,
                            team_slot_id=slot.id)
    db.add(member)
    await db.commit()
    return slot, member


async def make_case(db, monkeypatch, *, labels=None, **item_values):
    scope = await _scope(db, merge_policy="auto", review_hold_label="review-hold" if labels else None)
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5, last_verified_sha=HEAD_A,
                       dispatch_nonce="nonce-1", **item_values)
    client = _HoldClient(check_runs=CI)
    client.pull["head"] = dict(client.pull["head"], sha=HEAD_A)
    if labels:
        client.pull["labels"] = labels
    _, verifier = await slot_member(db, scope, role="verifier", name="V1")
    return Case(db, scope, item, client, verifier, monkeypatch)


@pytest.mark.asyncio
async def test_green_checks_without_an_acceptance_do_not_auto_merge(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    await case.tick()
    assert case.client.merge_calls == 0 and case.item.dispatch_status != "merged"
    assert "Waiting for reviewer acceptance at aaaaaaa" in case.item.status_note


@pytest.mark.asyncio
async def test_an_acceptance_at_the_current_head_lets_the_configured_merge_proceed(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    fact = await case.record(HEAD_A)
    assert fact.verdict == "accepted" and fact.status == "active" and fact.pr_number == 5
    assert "accepted head aaaaaaa" in case.item.status_note.lower()
    await case.tick()
    assert case.item.dispatch_status == "merged" and case.client.merge_head_shas == [HEAD_A]


@pytest.mark.asyncio
async def test_a_push_after_acceptance_waits_for_a_new_acceptance_at_the_new_head(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    await case.record(HEAD_A)
    case.move_head(HEAD_B)
    await case.tick()
    assert case.client.merge_calls == 0
    assert "Head changed since acceptance (accepted at aaaaaaa, head is bbbbbbb)" in case.item.status_note
    await case.record(HEAD_B)
    await case.tick()
    assert case.item.dispatch_status == "merged" and case.client.merge_head_shas == [HEAD_B]


@pytest.mark.asyncio
async def test_the_gate_does_not_depend_on_a_required_check_watch(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    await case.tick()
    assert case.client.merge_calls == 0  # no watch exists and the merge still waits
    db.add(GithubRequiredCheckWatch(work_item_id=case.item.id, dispatch_nonce="nonce-1", scope_revision=0, pr_number=5,
        head_sha=HEAD_A, owner_slot_id=case.item.owner_slot_id, policy_digest="d", reviewer_member_id=case.verifier.id,
        checks=[], observed_at=case.item.created_at, changed_at=case.item.created_at))
    await db.commit()
    await case.tick()
    assert case.client.merge_calls == 0  # a watch with a reviewer is not an acceptance
    await case.record(HEAD_A)
    await db.execute(GithubRequiredCheckWatch.__table__.delete())  # a cleared watch changes nothing
    await db.commit()
    await case.tick()
    assert case.item.dispatch_status == "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["owner", "leader", "implementer", "disabled_verifier", "other_team", "unknown"])
async def test_only_a_current_enabled_verifier_who_is_not_the_owner_may_record(db, monkeypatch, who):
    case = await make_case(db, monkeypatch)
    preset = await db.get(AgentTeamPreset, case.scope.preset_id)
    if who in {"owner", "leader"}:
        # Give the slot the verifier role so that only the owner and Leader exclusion can refuse it.
        slot_id = case.item.owner_slot_id if who == "owner" else preset.leader_slot_id
        (await db.get(AgentTeamSlot, slot_id)).role = "verifier"
        await db.commit()
        member = (await db.execute(select(MailTeamMember).where(MailTeamMember.team_slot_id == slot_id))).scalars().first()
    elif who == "implementer":
        _, member = await slot_member(db, case.scope, role="implementer", name="B9")
    elif who == "disabled_verifier":
        _, member = await slot_member(db, case.scope, role="verifier", name="V9", enabled=False)
    elif who == "other_team":
        other = await _scope(db, merge_policy="auto", repo_name="other")
        _, member = await slot_member(db, other, role="verifier", name="V8")
    else:
        class Ghost:
            id = 999999
        member = Ghost()
    with pytest.raises(GithubApprovalError, match="current_independent_reviewer_required"):
        await case.record(HEAD_A, member=member)
    await case.tick()
    assert case.client.merge_calls == 0
    assert (await db.execute(select(GithubHeadReview))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["role", "disabled", "replaced_member"])
async def test_an_acceptance_stops_counting_when_the_reviewer_is_rebound_or_loses_the_role(db, monkeypatch, change):
    case = await make_case(db, monkeypatch)
    await case.record(HEAD_A)
    slot = await db.get(AgentTeamSlot, case.verifier.team_slot_id)
    if change == "role":
        slot.role = "implementer"
    elif change == "disabled":
        slot.enabled = False
    else:
        db.add(MailTeamMember(identity_key="slot:new", repo_id="r", repo_path="/tmp/r", repo_name="r", display_name="V2",
            participant_kind="team_slot", team_preset_id=case.scope.preset_id, team_slot_id=slot.id))
    await db.commit()
    await case.tick()
    assert case.client.merge_calls == 0 and "no longer" in case.item.status_note.lower()


@pytest.mark.asyncio
async def test_a_later_negative_review_supersedes_an_acceptance(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    first = await case.record(HEAD_A)
    second = await case.record(HEAD_A, verdict="changes_required")
    await db.refresh(first)
    assert first.status == "superseded" and second.status == "active"
    await case.tick()
    assert case.client.merge_calls == 0 and "requires changes" in case.item.status_note.lower()
    third = await case.record(HEAD_A)
    await db.refresh(second)
    assert second.status == "superseded" and third.status == "active"
    await case.tick()
    assert case.item.dispatch_status == "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["", "maybe", "ACCEPTED", "approve", None])
async def test_the_verdict_is_explicit_and_never_inferred(db, monkeypatch, verdict):
    case = await make_case(db, monkeypatch)
    with pytest.raises(GithubApprovalError, match="structured_review_required"):
        await case.record(HEAD_A, verdict=verdict, summary="Accepted, looks good")
    with pytest.raises(GithubApprovalError, match="structured_review_required"):
        await case.record(HEAD_A, summary="   ")


@pytest.mark.asyncio
async def test_a_replay_is_idempotent_and_leaves_one_active_fact(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    first = await case.record(HEAD_A)
    again = await case.record(HEAD_A)
    assert again.id == first.id
    rows = (await db.execute(select(GithubHeadReview).where(GithubHeadReview.status == "active"))).scalars().all()
    assert [row.id for row in rows] == [first.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["nonce", "stale_head", "malformed_head", "other_pr_evidence", "not_a_review_link", "no_pr"])
async def test_the_fact_is_bound_to_this_nonce_pr_and_exact_current_head(db, monkeypatch, bad):
    case = await make_case(db, monkeypatch)
    overrides = {"nonce": {"dispatch_nonce": "old-nonce"}, "stale_head": {"head_sha": HEAD_B},
                 "malformed_head": {"head_sha": "abc"},
                 "other_pr_evidence": {"evidence_url": "https://github.com/o/r/pull/6#pullrequestreview-1"},
                 "not_a_review_link": {"evidence_url": "https://github.com/o/r/pull/5"}, "no_pr": {}}[bad]
    if bad == "no_pr":
        case.item.pr_number = None
        await db.commit()
    head = overrides.pop("head_sha", HEAD_A)
    with pytest.raises(GithubApprovalError):
        await case.record(head, **overrides)
    assert (await db.execute(select(GithubHeadReview))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_scoped_correction_head_is_covered_and_records_its_revision(db, monkeypatch):
    case = await make_case(db, monkeypatch, active_scope_revision=2)
    fact = await case.record(HEAD_A)
    assert fact.scope_revision == 2
    await case.tick()
    assert case.item.dispatch_status == "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["pull", "issue"])
async def test_the_hold_label_still_blocks_a_valid_acceptance(db, monkeypatch, location):
    case = await make_case(db, monkeypatch, labels=[{"name": "review-hold"}])
    await case.record(HEAD_A)
    if location == "issue":
        case.client.pull["labels"] = []
        case.client.issue["labels"] = [{"name": "review-hold"}]
    await case.tick()
    assert case.client.merge_calls == 0 and "held for independent review" in case.item.status_note.lower()
    case.client.pull["labels"], case.client.issue["labels"] = [], []
    await case.tick()
    assert case.item.dispatch_status == "merged"


@pytest.mark.asyncio
async def test_the_acceptance_is_rechecked_at_the_merge_boundary(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    await case.record(HEAD_A)
    original = case.client.list_check_runs_for_ref

    async def racing(owner, repo, ref):
        await case.record(HEAD_A, verdict="changes_required")  # a negative review lands while checks are read
        return await original(owner, repo, ref)

    case.client.list_check_runs_for_ref = racing
    await case.tick()
    assert case.client.merge_calls == 0 and case.item.dispatch_status != "merged"


@pytest.mark.asyncio
async def test_a_human_merge_policy_is_not_gated_by_acceptance(db, monkeypatch):
    scope = await _scope(db, merge_policy="human")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5, last_verified_sha=HEAD_A,
                       dispatch_nonce="nonce-1")
    assert await acceptance.gate_note(db, scope, item, HEAD_A) is not None  # the helper reports the missing fact
    client = _HoldClient(check_runs=CI)
    client.pull["head"] = dict(client.pull["head"], sha=HEAD_A)
    await github_verification_service.process_scope(db, scope, client=client)
    assert client.merge_calls == 0  # human policy never auto-merges, with or without a fact


class FakeSession:
    """The authenticated Mail session the route receives; identity comes from it, never from the request body."""

    def __init__(self, member):
        self.member_id, self.team_slot_id, self.id = member.id, member.team_slot_id, 4242


def route_request(**overrides):
    from app.models.schemas import GithubHeadReviewCreate
    values = dict(dispatch_nonce="nonce-1", head_sha=HEAD_A, verdict="accepted", summary="Reviewed the exact head",
                  evidence_url=EVIDENCE)
    values.update(overrides)
    return GithubHeadReviewCreate(**values)


@pytest.mark.asyncio
async def test_the_route_binds_the_authenticated_session_and_returns_the_fact(db, monkeypatch):
    from app.api.v1 import agent_teams
    case = await make_case(db, monkeypatch)
    response = await agent_teams.record_github_head_review(case.item.id, route_request(), FakeSession(case.verifier), db)
    assert response.reviewer_member_id == case.verifier.id and response.verdict == "accepted"
    assert response.head_sha == HEAD_A and response.pr_number == 5 and response.status == "active"
    await case.tick()
    assert case.item.dispatch_status == "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("who,status,detail", [("owner", 403, "current_independent_reviewer_required"),
                                               ("stale", 409, "revision_review_head_changed"),
                                               ("anonymous", 401, "session_token_required"),
                                               ("unbound", 403, "session_not_slot_bound"),
                                               ("missing_item", 404, "work_item_not_found")])
async def test_the_route_maps_refusals_without_recording(db, monkeypatch, who, status, detail):
    from fastapi import HTTPException
    from app.api.v1 import agent_teams
    case = await make_case(db, monkeypatch)
    owner = (await db.execute(select(MailTeamMember).where(MailTeamMember.team_slot_id == case.item.owner_slot_id))).scalars().first()
    session = {"owner": FakeSession(owner), "anonymous": None}.get(who, FakeSession(case.verifier))
    if who == "unbound":
        session.team_slot_id = None
    item_id = 999999 if who == "missing_item" else case.item.id
    request = route_request(head_sha=HEAD_B) if who == "stale" else route_request()
    with pytest.raises(HTTPException) as refused:
        await agent_teams.record_github_head_review(item_id, request, session, db)
    assert refused.value.status_code == status and refused.value.detail == detail
    assert (await db.execute(select(GithubHeadReview))).scalars().all() == []


def test_the_request_schema_requires_an_explicit_valid_verdict():
    from pydantic import ValidationError
    from app.models.schemas import GithubHeadReviewCreate
    base = dict(dispatch_nonce="n", head_sha=HEAD_A, summary="s", evidence_url=EVIDENCE)
    for verdict in ("accepted", "changes_required"):
        assert GithubHeadReviewCreate(**base, verdict=verdict).verdict == verdict
    for verdict in ("", "ACCEPTED", "approve", "accepted ", None):
        with pytest.raises(ValidationError):
            GithubHeadReviewCreate(**base, verdict=verdict)
    with pytest.raises(ValidationError):
        GithubHeadReviewCreate(**base)
    with pytest.raises(ValidationError):
        GithubHeadReviewCreate(**{**base, "head_sha": "abc"}, verdict="accepted")


@pytest.mark.asyncio
async def test_the_acceptance_gate_runs_before_the_wait_for_checks(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    case.client.check_runs = [{"name": "ci", "status": "in_progress", "conclusion": None}]
    await case.tick()
    assert case.client.merge_calls == 0
    assert "Waiting for reviewer acceptance at aaaaaaa" in case.item.status_note
    assert case.item.merge_wait_started_at is None  # the check wait never started: the gate came first


# --- Review 5899212047: authority must be read fresh, at recording and at every merge boundary ------------------


@pytest_asyncio.fixture
async def twin(tmp_path):
    """A file-backed database with two real connections: the case session and a second one that commits changes."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'twin.sqlite'}", connect_args={"timeout": 10})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as first:
        yield first, maker
    await engine.dispose()


async def elsewhere(maker, case, kind):
    """Commit one authority change through a second connection."""
    verifier_slot = case.verifier.team_slot_id
    async with maker() as other:
        if kind == "role":
            await other.execute(update(AgentTeamSlot).where(AgentTeamSlot.id == verifier_slot).values(role="implementer"))
        elif kind == "disabled":
            await other.execute(update(AgentTeamSlot).where(AgentTeamSlot.id == verifier_slot).values(enabled=False))
        elif kind == "replaced":
            other.add(MailTeamMember(identity_key=f"slot:replacement:{uuid.uuid4().hex}", repo_id="r", repo_path="/tmp/r", repo_name="r",
                display_name="V2", participant_kind="team_slot", team_preset_id=case.scope.preset_id,
                team_slot_id=verifier_slot))
        elif kind == "owner":
            await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == case.item.id).values(owner_slot_id=verifier_slot))
        elif kind == "leader":
            await other.execute(update(AgentTeamPreset).where(AgentTeamPreset.id == case.scope.preset_id).values(leader_slot_id=verifier_slot))
        elif kind == "nonce":
            await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == case.item.id).values(dispatch_nonce="nonce-2"))
        elif kind == "superseded":
            await other.execute(update(GithubHeadReview).values(status="superseded"))
        await other.commit()


AUTHORITY_CHANGES = ["role", "disabled", "replaced", "owner", "leader", "superseded"]


async def hold_loaded_authority(db, case):
    """A long-lived session keeps these objects in its identity map; hold strong references to them as it would."""
    return [await db.get(AgentTeamSlot, case.verifier.team_slot_id), await db.get(MailTeamMember, case.verifier.id),
            await db.get(AgentTeamPreset, case.scope.preset_id), await db.get(GithubWorkItem, case.item.id),
            *(await db.execute(select(GithubHeadReview))).scalars().all()]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", AUTHORITY_CHANGES)
async def test_a_second_connection_revoking_the_authority_is_seen_by_the_merge_gate(twin, monkeypatch, kind):
    db, maker = twin
    case = await make_case(db, monkeypatch)
    await case.record(HEAD_A)
    held = await hold_loaded_authority(db, case)  # noqa: F841 - strong references keep the loaded rows cached
    await elsewhere(maker, case, kind)
    await case.tick()
    assert case.client.merge_calls == 0 and case.item.dispatch_status != "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", AUTHORITY_CHANGES)
async def test_a_revocation_that_lands_during_the_check_read_stops_the_merge_boundary(twin, monkeypatch, kind):
    db, maker = twin
    case = await make_case(db, monkeypatch)
    await case.record(HEAD_A)
    held = await hold_loaded_authority(db, case)  # noqa: F841
    original = case.client.list_check_runs_for_ref

    async def racing(owner, repo, ref):
        if not racing.done:
            racing.done = True
            await elsewhere(maker, case, kind)  # a second connection commits while the checks are read
        return await original(owner, repo, ref)

    racing.done = False

    case.client.list_check_runs_for_ref = racing
    await case.tick()
    assert case.client.merge_calls == 0 and case.item.dispatch_status != "merged"


@pytest.mark.asyncio
async def test_an_unchanged_authority_still_merges_across_two_connections(twin, monkeypatch):
    db, maker = twin
    case = await make_case(db, monkeypatch)
    await case.record(HEAD_A)
    await case.tick()
    assert case.item.dispatch_status == "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,code", [("role", "current_independent_reviewer_required"),
                                       ("disabled", "current_independent_reviewer_required"),
                                       ("replaced", "current_independent_reviewer_required"),
                                       ("owner", "current_independent_reviewer_required"),
                                       ("nonce", "stale_revision_review")])
async def test_authority_that_changes_during_the_github_read_is_refused_before_a_fact_is_recorded(twin, monkeypatch, kind, code):
    db, maker = twin
    case = await make_case(db, monkeypatch)
    held = await hold_loaded_authority(db, case)  # noqa: F841

    async def racing_pull(*args, **kwargs):
        await elsewhere(maker, case, kind)  # the change lands while get_pull is outstanding
        return case.client.pull

    monkeypatch.setattr(github_client, "get_pull", racing_pull)
    with pytest.raises(GithubApprovalError, match=code):
        await case.record(HEAD_A)
    assert (await db.execute(select(GithubHeadReview))).scalars().all() == []
