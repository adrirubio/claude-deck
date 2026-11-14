"""#920: one failing item never discards another item's poll work, and a merged PR settles its item."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update

from app.config import settings
from app.database import get_db
from app.models.database import GithubAttemptScopeRevision, GithubHeadReview, GithubMaintenanceEvent, GithubWorkItem
from app.services.github_terminal_revision_service import TERMINAL_ITEMS, finalize_merged_item, finalize_merged_preview
from app.services.github_verification_service import github_verification_service
from app.services.github_watcher_service import github_watcher_service
from tests.agent_teams.test_github_verification_service import (  # noqa: F401  (fixtures and helpers shared with the verification tests)
    _Client, _implementation_revision, _item, _owner, _scope, db,
)
from tests.agent_teams.test_github_watcher_service import _FakeClient, _issue, _make_scope
from tests.agent_teams.test_head_acceptance import twin  # noqa: F401

LABEL = "claude-deck-ready"


def _closed(number):
    return dict(_issue(number, [LABEL]), state="closed")


async def _active_item(db, scope, number, **values):
    item = GithubWorkItem(scope_id=scope.id, issue_number=number, issue_title=f"issue {number}", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="dispatched", dispatch_nonce=f"n{number}",
                          **values)
    db.add(item)
    await db.commit()
    return item


async def _numbers(db):
    return sorted(row.issue_number for row in (await db.execute(select(GithubWorkItem))).scalars().all())


@pytest.mark.asyncio
async def test_a_closed_issue_that_loses_its_claim_does_not_discard_a_newly_admitted_issue(db):
    scope = await _make_scope(db)
    await _active_item(db, scope, 1, retry_requested_at=datetime.utcnow())  # a live retry: the guarded claim is lost
    client = _FakeClient(labeled=[_issue(2, [LABEL])], by_number={1: _closed(1)})
    await github_watcher_service.poll_scope(db, scope, client)
    assert await _numbers(db) == [1, 2]


@pytest.mark.asyncio
async def test_an_exception_in_one_completion_is_logged_with_the_item_id_and_isolated(db, monkeypatch, caplog):
    scope = await _make_scope(db)
    failing = await _active_item(db, scope, 1)
    healthy = await _active_item(db, scope, 3)
    failing_id, healthy_id = failing.id, healthy.id  # plain ints: the isolated rollback expires the rows
    original = github_watcher_service._complete_and_notify

    async def explode_for_one(db_, scope_, item, **kwargs):
        if item.id == failing_id:
            raise RuntimeError("completion exploded")
        return await original(db_, scope_, item, **kwargs)

    monkeypatch.setattr(github_watcher_service, "_complete_and_notify", explode_for_one)
    client = _FakeClient(labeled=[_issue(2, [LABEL])], by_number={1: _closed(1), 3: _closed(3)})
    with caplog.at_level(logging.WARNING):
        await github_watcher_service.poll_scope(db, scope, client)
    assert await _numbers(db) == [1, 2, 3]
    assert (await db.get(GithubWorkItem, healthy_id, populate_existing=True)).dispatch_status == "completed"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(f"work item {failing_id}" in message for message in warnings)
    assert not any(f"work item {healthy_id}" in message for message in warnings)  # the healthy item did not fail


@pytest.mark.asyncio
async def test_the_poll_time_is_never_advanced_over_discarded_upserts(db, monkeypatch):
    scope = await _make_scope(db)

    async def recheck_that_rolls_back(db_, scope_, client_):
        await db_.rollback()
        await db_.refresh(scope_)  # as every rollback path in the watcher does

    monkeypatch.setattr(github_watcher_service, "_recheck_active_items", recheck_that_rolls_back)
    await github_watcher_service.poll_scope(db, scope, _FakeClient(labeled=[_issue(2, [LABEL])]))
    await db.refresh(scope)
    assert await _numbers(db) == [2] or scope.last_polled_at is None


MERGED = dict(state="closed", merged=True, merged_at="2026-11-14T04:12:07Z")


async def _submitted(db, *, unacknowledged_amendment, pull_head="sha", pull=None):
    """A verifying item with a submitted revision (submitted head 'sha') and a PR that GitHub reports as given."""
    scope = await _scope(db)
    slot, member = await _owner(db, scope)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5, owner_slot_id=slot.id,
                       dispatch_nonce="attempt-1", active_scope_revision=1, attempt_phase="implementation",
                       ack_received_at=None if unacknowledged_amendment else datetime.utcnow())
    revision, workspace = await _implementation_revision(db, scope, item, slot, member)
    if unacknowledged_amendment:  # the owner has not acknowledged an amendment: process_scope used to skip the item
        await db.execute(update(GithubAttemptScopeRevision).where(GithubAttemptScopeRevision.id == revision.id)
                         .values(origin_kind="scope_amendment"))
        await db.commit()
    client = _Client()
    client.pull.update(pull or MERGED)
    client.pull["head"] = dict(client.pull["head"], sha=pull_head)
    return scope, item, revision, workspace, client


async def _tick(db, scope, client, *rows):
    await github_verification_service.process_scope(db, scope, client=client)
    for row in rows:
        await db.refresh(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("unacknowledged_amendment", [False, True])
async def test_a_pr_merged_at_the_submitted_head_settles_the_item_and_its_revision(db, unacknowledged_amendment):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=unacknowledged_amendment)
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status == "merged" and item.dispatch_status in TERMINAL_ITEMS  # releasable
    assert revision.status == "completed" and revision.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("unacknowledged_amendment", [False, True])
async def test_a_pr_merged_at_a_different_head_escalates_with_both_heads_named(db, unacknowledged_amendment):
    scope, item, revision, workspace, client = await _submitted(
        db, unacknowledged_amendment=unacknowledged_amendment, pull_head="other-head")
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status == "escalated" and item.escalation_reason == "continuation_invalid_state"
    assert "other-head" in item.status_note and "sha" in item.status_note and "no merge was recorded" in item.status_note
    assert revision.status == "superseded"


@pytest.mark.asyncio
async def test_a_pr_merged_at_an_accepted_head_settles_even_when_it_is_not_the_submitted_head(db):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True, pull_head="accepted-head")
    db.add(GithubHeadReview(work_item_id=item.id, dispatch_nonce="attempt-1", pr_number=5, head_sha="accepted-head",
                            scope_revision=1, reviewer_member_id=1, verdict="accepted", summary="ok",
                            evidence_url="https://github.com/o/r/pull/5#pullrequestreview-1"))
    await db.commit()
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status == "merged" and revision.status == "completed"


@pytest.mark.asyncio
async def test_a_merged_pr_with_no_revision_keeps_its_existing_settlement_at_any_head(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5, dispatch_nonce="attempt-1")
    client = _Client()
    client.pull.update(MERGED)
    client.pull["head"] = dict(client.pull["head"], sha="some-other-head")
    await _tick(db, scope, client, item)
    assert item.dispatch_status == "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("unacknowledged_amendment,state,merged,merged_at,item_status,revision_status", [
    (True, "open", False, None, "verifying", "submitted"),            # the skip still holds for a live PR
    (True, "closed", False, None, "verifying", "submitted"),          # and for a closed-unmerged one: only merges settle here
    (False, "closed", False, None, "escalated", "superseded"),        # the existing closed-unmerged behavior
])
async def test_open_and_closed_unmerged_pulls_are_unchanged(db, unacknowledged_amendment, state, merged, merged_at,
                                                           item_status, revision_status):
    scope, item, revision, workspace, client = await _submitted(
        db, unacknowledged_amendment=unacknowledged_amendment, pull=dict(state=state, merged=merged, merged_at=merged_at))
    await _tick(db, scope, client, item, revision)
    assert (item.dispatch_status, revision.status) == (item_status, revision_status)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "item"])
async def test_a_change_during_the_awaited_pr_read_stops_the_settlement(twin, change):
    db, maker = twin
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    original = client.get_pull
    revision_id, item_id = revision.id, item.id

    async def racing(owner, repo, number):
        if not racing.done:
            racing.done = True
            async with maker() as other:  # another connection settles the attempt while GitHub is awaited
                if change == "revision":
                    await other.execute(update(GithubAttemptScopeRevision)
                                        .where(GithubAttemptScopeRevision.id == revision_id).values(status="superseded"))
                else:
                    await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == item_id)
                                        .values(dispatch_nonce="a-newer-attempt"))
                await other.commit()
        return await original(owner, repo, number)

    racing.done = False
    client.get_pull = racing
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status != "merged"
    assert revision.status != "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("unacknowledged_amendment", [False, True])
async def test_a_pr_that_is_no_longer_merged_at_the_second_read_settles_nothing(db, unacknowledged_amendment):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=unacknowledged_amendment)
    original = client.get_pull
    calls = []

    async def second_read_differs(owner, repo, number):
        # the poll reads the merged PR once; the settlement reads it again right before its claim
        calls.append(number)
        pull = await original(owner, repo, number)
        return pull if len(calls) == 1 else dict(pull, state="open", merged=False, merged_at=None)

    client.get_pull = second_read_differs
    await _tick(db, scope, client, item, revision)
    assert len(calls) >= 2  # the second read happened
    assert item.dispatch_status != "merged" and revision.status != "completed"


# --- the operator finalizes a merged item that the poll cannot settle -------------------------------------------

MERGE_SHA = "c" * 40
REASON = "Merged by hand at the accepted head; the poll cannot settle it."


def _reader(client, **extra):
    async def read_pull():
        return dict(client.pull, merge_commit_sha=MERGE_SHA, **extra)
    return read_pull


async def _finalize(db, scope, item, client, *, digest=None, operation="op-1", reason=REASON):
    if digest is None:
        digest = (await finalize_merged_preview(db, item, scope, _reader(client)))["context_sha256"]
    return await finalize_merged_item(db, item, scope, _reader(client), expected_context_sha256=digest,
                                      operation_id=operation, reason=reason)


@pytest.mark.asyncio
async def test_the_preview_gives_fresh_merge_evidence_and_a_context_digest_without_private_values(db):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    preview = await finalize_merged_preview(db, item, scope, _reader(client))
    assert preview["pr_number"] == 5 and preview["merged_head_sha"] == "sha" and preview["merge_commit_sha"] == MERGE_SHA
    assert len(preview["context_sha256"]) == 64
    assert f"lease-{item.id}" not in str(preview) and "attempt-1" not in str(preview)  # the lease token and nonce


@pytest.mark.asyncio
async def test_finalize_settles_the_item_and_revision_and_records_the_operation(db):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    result = await _finalize(db, scope, item, client)
    await db.refresh(item); await db.refresh(revision)
    assert result["status"] == "finalized"
    assert item.dispatch_status == "merged" and item.dispatch_status in TERMINAL_ITEMS  # releasable
    assert revision.status == "completed"
    assert "operator" in item.status_note and "Merged by hand" in item.status_note
    event = (await db.execute(select(GithubMaintenanceEvent))).scalars().one()
    assert event.operation_id == "finalize_merged:op-1" and event.work_item_id == item.id
    assert workspace.leased_item_id == item.id  # the finalize releases nothing; the owner releases normally


@pytest.mark.asyncio
@pytest.mark.parametrize("pull,code", [
    (dict(state="open", merged=False, merged_at=None), "finalize_merged_not_merged"),
    (dict(state="closed", merged=False, merged_at=None), "finalize_merged_not_merged"),
])
async def test_finalize_refuses_a_pr_that_is_not_merged(db, pull, code):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True, pull=pull)
    with pytest.raises(ValueError, match=code):
        await _finalize(db, scope, item, client, digest="a" * 64)
    await db.refresh(item)
    assert item.dispatch_status == "verifying"


@pytest.mark.asyncio
async def test_finalize_refuses_a_missing_reason_a_stale_digest_and_a_terminal_item(db):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    with pytest.raises(ValueError, match="finalize_merged_reason_required"):
        await _finalize(db, scope, item, client, reason="   ")
    with pytest.raises(ValueError, match="finalize_merged_context_changed"):
        await _finalize(db, scope, item, client, digest="b" * 64)
    await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(dispatch_status="merged"))
    await db.commit(); await db.refresh(item)
    with pytest.raises(ValueError, match="finalize_merged_item_terminal"):
        await _finalize(db, scope, item, client, digest="a" * 64)


@pytest.mark.asyncio
async def test_finalize_refuses_when_the_pr_changes_between_the_preview_and_the_write(db):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    digest = (await finalize_merged_preview(db, item, scope, _reader(client)))["context_sha256"]
    client.pull["head"] = dict(client.pull["head"], sha="a-different-head")  # the fresh read now shows another head
    with pytest.raises(ValueError, match="finalize_merged_context_changed"):
        await finalize_merged_item(db, item, scope, _reader(client), expected_context_sha256=digest,
                                   operation_id="op-2", reason=REASON)
    await db.refresh(item)
    assert item.dispatch_status == "verifying"


@pytest.mark.asyncio
async def test_an_exact_replay_is_idempotent_and_a_changed_replay_conflicts(db):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    digest = (await finalize_merged_preview(db, item, scope, _reader(client)))["context_sha256"]
    first = await _finalize(db, scope, item, client, digest=digest)
    await db.refresh(item)
    again = await _finalize(db, scope, item, client, digest=digest)
    assert first["status"] == "finalized" and again["status"] == "already_finalized"
    assert await db.scalar(select(func.count()).select_from(GithubMaintenanceEvent)) == 1
    with pytest.raises(ValueError, match="finalize_merged_replay_conflict"):
        await _finalize(db, scope, item, client, digest=digest, reason="A different reason for the same operation.")


async def _route(db, monkeypatch, client):
    """The maintenance router over one finalize-merged URL, with the PR read replaced by the fake client's pull."""
    from app.api.v1 import factory_maintenance
    reads = []

    async def merged_pull(db_, scope_, item_):
        reads.append(1)
        return dict(client.pull, merge_commit_sha=MERGE_SHA)

    monkeypatch.setattr(factory_maintenance, "read_merged_pull", merged_pull)
    monkeypatch.setattr(settings, "operator_token", "synthetic-operator")
    app = FastAPI()
    app.include_router(factory_maintenance.router, prefix="/api/v1/agent-teams")

    async def database():
        yield db
    app.dependency_overrides[get_db] = database
    return app, reads


OPERATOR = {"X-Synth-City-Operator-Token": "synthetic-operator"}


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "wrong", "synthetic-operator"])
@pytest.mark.parametrize("dry_run", [True, False])
async def test_the_finalize_route_requires_the_operator_in_both_modes(db, monkeypatch, header, dry_run):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    app, reads = await _route(db, monkeypatch, client)
    digest = (await finalize_merged_preview(db, item, scope, _reader(client)))["context_sha256"]
    headers = {"X-Synth-City-Operator-Token": header} if header else {}
    body = {"dry_run": True} if dry_run else {"operation_id": "route-1", "expected_context_sha256": digest, "reason": REASON}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(f"/api/v1/agent-teams/presets/{scope.preset_id}/work-items/{item.id}/finalize-merged",
                                   headers=headers, json=body)
    expected = 200 if header == "synthetic-operator" else 401
    assert response.status_code == expected
    if expected == 200:
        assert response.headers["cache-control"] == "no-store"
    await db.refresh(item)
    assert item.dispatch_status == ("merged" if expected == 200 and not dry_run else "verifying")


@pytest.mark.asyncio
async def test_a_dry_run_returns_evidence_and_the_digest_and_changes_and_consumes_nothing(db, monkeypatch):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    app, reads = await _route(db, monkeypatch, client)
    url = f"/api/v1/agent-teams/presets/{scope.preset_id}/work-items/{item.id}/finalize-merged"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        preview = await http.post(url, headers=OPERATOR, json={"dry_run": True})
        assert preview.status_code == 200
        evidence = preview.json()
        assert evidence["merged_head_sha"] == "sha" and evidence["merge_commit_sha"] == MERGE_SHA
        await db.refresh(item); await db.refresh(revision)
        assert (item.dispatch_status, revision.status) == ("verifying", "submitted")  # nothing settled
        assert await db.scalar(select(func.count()).select_from(GithubMaintenanceEvent)) == 0  # no event recorded
        assert workspace.leased_item_id == item.id  # no lease released
        # the operation id is still unused: the same id now finalizes with the digest the preview returned
        real = await http.post(url, headers=OPERATOR, json={
            "operation_id": "same-id", "expected_context_sha256": evidence["context_sha256"], "reason": REASON})
        assert real.status_code == 200 and real.json()["status"] == "finalized"
    await db.refresh(item)
    assert item.dispatch_status == "merged"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["operation_id", "expected_context_sha256", "reason"])
async def test_a_real_finalize_missing_a_value_is_refused_before_any_read_or_mutation(db, monkeypatch, missing):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    app, reads = await _route(db, monkeypatch, client)
    body = {"operation_id": "op-9", "expected_context_sha256": "a" * 64, "reason": REASON}
    del body[missing]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(f"/api/v1/agent-teams/presets/{scope.preset_id}/work-items/{item.id}/finalize-merged",
                                   headers=OPERATOR, json=body)
    assert response.status_code == 422
    assert reads == []  # not even the PR was read
    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert await db.scalar(select(func.count()).select_from(GithubMaintenanceEvent)) == 0


@pytest.mark.asyncio
async def test_the_route_reports_a_stale_digest_as_a_plain_409_code(db, monkeypatch):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    app, reads = await _route(db, monkeypatch, client)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(f"/api/v1/agent-teams/presets/{scope.preset_id}/work-items/{item.id}/finalize-merged",
                                   headers=OPERATOR, json={"operation_id": "op-5", "expected_context_sha256": "b" * 64,
                                                           "reason": REASON})
    assert response.status_code == 409 and response.json()["detail"] == "finalize_merged_context_changed"


@pytest.mark.asyncio
async def test_finalize_refuses_when_only_the_second_read_differs(db):
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=True)
    digest = (await finalize_merged_preview(db, item, scope, _reader(client)))["context_sha256"]
    reads = []

    async def changes_on_the_second_read():
        reads.append(1)
        head = "sha" if len(reads) == 1 else "pushed-after-the-first-read"
        return dict(client.pull, head=dict(client.pull["head"], sha=head), merge_commit_sha=MERGE_SHA)

    with pytest.raises(ValueError, match="finalize_merged_context_changed"):
        await finalize_merged_item(db, item, scope, changes_on_the_second_read, expected_context_sha256=digest,
                                   operation_id="op-3", reason=REASON)
    assert len(reads) == 2
    await db.refresh(item)
    assert item.dispatch_status == "verifying"
