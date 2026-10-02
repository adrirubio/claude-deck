"""A human-policy review state must describe the current PR head."""

import pytest
from sqlalchemy import update

from app.models.database import GithubWorkItem, GithubWorkspace, TeamGithubScope
from app.services.github_verification_service import github_verification_service
from tests.agent_teams.test_github_verification_service import (
    _Client, _implementation_revision, _item, _owner, _scope,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ready_for_review", "awaiting_human_review"])
async def test_changed_human_head_reverifies_without_new_authority(db, status):
    scope = await _scope(db, merge_policy="human")
    item = await _item(db, scope, dispatch_status=status, pr_number=5,
                       dispatch_nonce="fixture-attempt", last_verified_sha="old",
                       approval_round_count=1, ack_approval_round=1,
                       ack_evidence_message_id=44, retry_count=1)
    workspace = GithubWorkspace(scope_id=scope.id, path="/tmp/review-workspace",
                                leased_item_id=item.id, lease_token="fixture-lease")
    db.add(workspace)
    await db.commit()
    client = _Client(pull={"number": 5, "head": {"sha": "new"}})
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    await db.refresh(workspace)
    assert item.dispatch_status == "verifying"
    assert item.last_verified_sha == "old"
    assert item.dispatch_nonce == "fixture-attempt"
    assert item.approval_round_count == item.ack_approval_round == 1
    assert item.ack_evidence_message_id == 44
    assert item.retry_count == 1 and item.active_scope_revision == 0
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == "fixture-lease"
    assert client.merge_calls == 0


@pytest.mark.asyncio
async def test_current_head_needs_real_checks_before_new_readiness(db):
    scope = await _scope(db, merge_policy="human")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5,
                       last_verified_sha="old")
    client = _Client(pull={"number": 5, "head": {"sha": "new"}},
                     check_runs=[{"status": "in_progress", "conclusion": None}])
    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "verifying" and item.last_verified_sha == "old"
    client.check_runs = [{"status": "completed", "conclusion": "success"}]
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert item.last_verified_sha == "new"
    assert client.merge_calls == 0


@pytest.mark.asyncio
async def test_unchanged_human_head_remains_ready(db):
    scope = await _scope(db, merge_policy="human")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5,
                       last_verified_sha="same")
    client = _Client(pull={"number": 5, "head": {"sha": "same"}})
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert client.merge_calls == 0


@pytest.mark.asyncio
async def test_missing_head_cannot_retain_readiness(db):
    scope = await _scope(db, merge_policy="human")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5,
                       last_verified_sha="old")
    await github_verification_service.process_scope(
        db, scope, client=_Client(pull={"number": 5, "head": {"sha": None}}))
    await db.refresh(item)
    assert item.dispatch_status == "verifying"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["terminal", "nonce", "owner", "policy"])
async def test_changed_head_claim_preserves_concurrent_changes(db, change):
    scope = await _scope(db, merge_policy="human")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5,
                       dispatch_nonce="fixture-attempt", last_verified_sha="old")
    client = _Client(pull={"number": 5, "head": {"sha": "new"}})
    original_get = client.get_pull

    async def concurrent_change(*args):
        if change == "policy":
            await db.execute(update(TeamGithubScope).where(TeamGithubScope.id == scope.id)
                             .values(merge_policy="auto")
                             .execution_options(synchronize_session=False))
        else:
            values = {"terminal": {"dispatch_status": "merged"},
                      "nonce": {"dispatch_nonce": "next-attempt"},
                      "owner": {"owner_slot_id": 99}}[change]
            await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id)
                             .values(**values).execution_options(synchronize_session=False))
        await db.commit()
        return await original_get(*args)

    client.get_pull = concurrent_change
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == ("merged" if change == "terminal" else "ready_for_review")
    assert item.last_verified_sha == "old" and client.merge_calls == 0


@pytest.mark.asyncio
async def test_completed_scoped_head_requires_recovery_not_implicit_reactivation(db):
    scope = await _scope(db, merge_policy="human", continuation_enabled=True)
    slot, member = await _owner(db, scope)
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5,
                       owner_slot_id=slot.id, dispatch_nonce="fixture-attempt",
                       last_verified_sha="old", active_scope_revision=1)
    revision, workspace = await _implementation_revision(
        db, scope, item, slot, member, status="completed", failed_head_count=1)
    await github_verification_service.process_scope(
        db, scope, client=_Client(pull={"number": 5, "head": {"sha": "new"}}))
    await db.refresh(item)
    await db.refresh(revision)
    await db.refresh(workspace)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "plan_blocked"
    assert revision.status == "completed" and revision.failed_head_count == 1
    assert item.active_scope_revision == 1 and item.last_verified_sha == "old"
    assert workspace.leased_item_id == item.id
