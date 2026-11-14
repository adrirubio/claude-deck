"""#917: the Leader-approval merge gate must read its inputs fresh, at the first call and at the merge boundary."""
from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, MailTeamMember
from app.services.github_verification_service import github_verification_service
from tests.agent_teams.test_head_acceptance import (  # noqa: F401  (fixtures and helpers shared with #904's tests)
    HEAD_A, enforcement, hold_loaded_authority, make_case, slot_member, twin,
)
from tests.agent_teams.test_github_verification_service import db  # noqa: F401

CHANGES = ["approver", "round", "epoch", "leader", "owner_is_approver", "round_bump"]


async def leader_slot_id(db, case):
    return (await db.get(AgentTeamPreset, case.scope.preset_id)).leader_slot_id


async def apply_change(maker, case, kind, slots):
    """Commit one approval-input change through a second connection."""
    async with maker() as other:
        item = update(GithubWorkItem).where(GithubWorkItem.id == case.item.id)
        if kind == "approver":      # the recorded approver is no longer the designated Leader
            await other.execute(item.values(ack_approver_member_id=case.verifier.id))
        elif kind == "round":       # the approval belongs to a different round than the item's
            await other.execute(item.values(ack_approval_round=0))
        elif kind == "epoch":       # the approval was not recorded under enforced identity
            await other.execute(item.values(ack_enforcement_epoch=0))
        elif kind == "leader":      # the preset now designates another slot as Leader
            await other.execute(update(AgentTeamPreset).where(AgentTeamPreset.id == case.scope.preset_id)
                                .values(leader_slot_id=slots["other"]))
        elif kind == "owner_is_approver":  # the owner slot becomes the Leader's slot
            await other.execute(item.values(owner_slot_id=slots["leader"]))
        elif kind == "round_bump":  # a newer approval round opened
            await other.execute(item.values(approval_round_count=GithubWorkItem.approval_round_count + 1))
        await other.commit()


async def merge_case(db, monkeypatch):
    case = await make_case(db, monkeypatch)
    await case.record(HEAD_A)  # the acceptance gate is satisfied; only the approval gate is under test
    # Another coordinator slot a rebinding can designate as Leader, so the acceptance gate (which refuses a
    # verifier who is the Leader) does not pre-empt the approval gate.
    other_slot, _ = await slot_member(db, case.scope, role="coordinator", name="L9")
    return case, {"leader": await leader_slot_id(db, case), "other": other_slot.id}


@pytest.mark.asyncio
async def test_an_unchanged_approval_still_merges_across_two_connections(twin, monkeypatch):
    db, maker = twin
    case, _ = await merge_case(db, monkeypatch)
    await case.tick()
    assert case.item.dispatch_status == "merged" and case.client.merge_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", CHANGES)
async def test_an_approval_change_committed_before_the_poll_stops_the_merge(twin, monkeypatch, kind):
    db, maker = twin
    case, slots = await merge_case(db, monkeypatch)
    held = await hold_loaded_authority(db, case)  # noqa: F841 - a long-lived session keeps these rows cached
    await apply_change(maker, case, kind, slots)
    await case.tick()
    assert case.client.merge_calls == 0 and case.item.dispatch_status != "merged"
    assert "distinct current-round leader approval" in case.item.status_note


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", CHANGES)
async def test_an_approval_change_that_lands_during_the_check_read_stops_the_merge_boundary(twin, monkeypatch, kind):
    db, maker = twin
    case, slots = await merge_case(db, monkeypatch)
    held = await hold_loaded_authority(db, case)  # noqa: F841
    original = case.client.list_check_runs_for_ref

    async def racing(owner, repo, ref):
        if not racing.done:
            racing.done = True
            await apply_change(maker, case, kind, slots)  # committed while GitHub is awaited
        return await original(owner, repo, ref)

    racing.done = False
    case.client.list_check_runs_for_ref = racing
    await case.tick()
    assert case.client.merge_calls == 0 and case.item.dispatch_status != "merged"
    assert "distinct current-round leader approval" in case.item.status_note


@pytest.mark.asyncio
@pytest.mark.parametrize("identity,note", [((5, "nonce-1", None), None), ((6, "nonce-1", None), "changed during verification"),
                                           ((5, "other", None), "changed during verification")])
async def test_the_approval_gate_is_bound_to_the_operation_identity(twin, monkeypatch, identity, note):
    db, maker = twin
    case, _ = await merge_case(db, monkeypatch)
    expected = (identity[0], identity[1], case.scope.id)
    reason = await github_verification_service._approval_gate_reason(db, case.scope, case.item, expected)
    if note is None:
        assert reason is None
    else:
        assert note in (reason or "").lower()
    wrong_scope = await github_verification_service._approval_gate_reason(db, case.scope, case.item, (5, "nonce-1", case.scope.id + 1))
    assert "changed during verification" in (wrong_scope or "").lower()
