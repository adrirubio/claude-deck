"""#931: a positively settled revision no longer leaves its item 'verifying' and skipped by verification.

Positive settlement completes the revision but leaves the item on it. Verification used to read a completed
revision as 'inconsistent': it logged once a minute, never read the PR and never recorded the merge.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select, update

from app.api.v1.agent_teams import _RELEASABLE_STATUSES
from app.models.database import FactoryAuditEvent, GithubAttemptScopeRevision, GithubHeadReview, GithubWorkItem
from app.services.github_verification_service import github_verification_service as service
from tests.agent_teams.test_github_verification_service import db  # noqa: F401  (fixture)
from tests.agent_teams.test_head_acceptance import twin  # noqa: F401  (fixture)
from tests.agent_teams.test_merged_item_settlement import MERGED, _submitted, _tick

LOGGER = "app.services.github_verification_service"
SETTLED_AT = datetime(2026, 11, 14, 8, 51, 0)


async def _settled(db, **kwargs):
    """A verifying item on a positively settled revision: completed, submitted head 'sha', item still on it."""
    scope, item, revision, workspace, client = await _submitted(db, unacknowledged_amendment=False, **kwargs)
    await db.execute(update(GithubAttemptScopeRevision).where(GithubAttemptScopeRevision.id == revision.id)
                     .values(status="completed", completed_at=SETTLED_AT))
    await db.commit()
    await db.refresh(revision)
    assert item.dispatch_status == "verifying" and item.active_scope_revision == revision.revision
    return scope, item, revision, client


async def _outcome_events(db, revision_id):
    return await db.scalar(select(func.count()).select_from(FactoryAuditEvent).where(
        FactoryAuditEvent.event_kind == "revision_outcome", FactoryAuditEvent.revision_id == revision_id))


@pytest.fixture
def fresh_log_memory(monkeypatch):
    """The once-per-state log memory is per process: start every log test from an empty one."""
    monkeypatch.setattr(service, "_logged_inconsistent", set())


def _skips(caplog):
    return [r for r in caplog.records if r.name == LOGGER and "inconsistent" in r.getMessage()]


@pytest.mark.asyncio
async def test_a_pr_merged_at_the_settled_head_records_the_merge_and_the_item_is_releasable(db):
    scope, item, revision, client = await _settled(db)
    events_before = await _outcome_events(db, revision.id)
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status == "merged"
    assert item.dispatch_status in _RELEASABLE_STATUSES
    # The settlement already decided this revision: it keeps its status, its time and its one outcome record.
    assert revision.status == "completed" and revision.completed_at == SETTLED_AT
    assert await _outcome_events(db, revision.id) == events_before


@pytest.mark.asyncio
async def test_a_pr_merged_at_a_different_head_escalates_and_records_no_merge(db):
    scope, item, revision, client = await _settled(db, pull_head="other-head")
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status == "escalated" and item.escalation_reason == "continuation_invalid_state"
    assert "other-head" in item.status_note and "sha" in item.status_note and "no merge was recorded" in item.status_note
    assert revision.status == "completed" and revision.completed_at == SETTLED_AT


@pytest.mark.asyncio
async def test_a_pr_merged_at_an_accepted_head_settles_even_when_it_is_not_the_settled_head(db):
    scope, item, revision, client = await _settled(db, pull_head="accepted-head")
    db.add(GithubHeadReview(work_item_id=item.id, dispatch_nonce="attempt-1", pr_number=5, head_sha="accepted-head",
                            scope_revision=1, reviewer_member_id=1, verdict="accepted", summary="ok",
                            evidence_url="https://github.com/o/r/pull/5#pullrequestreview-1"))
    await db.commit()
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status == "merged" and revision.status == "completed"


@pytest.mark.asyncio
async def test_an_open_pr_changes_nothing_and_logs_nothing_over_several_polls(db, caplog, fresh_log_memory):
    scope, item, revision, client = await _settled(db, pull=dict(state="open", merged=False, merged_at=None))
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        for _ in range(3):
            await _tick(db, scope, client, item, revision)
    assert (item.dispatch_status, revision.status) == ("verifying", "completed")
    assert [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.INFO] == []


@pytest.mark.asyncio
async def test_a_pr_closed_without_merge_escalates_and_leaves_the_settled_revision(db):
    scope, item, revision, client = await _settled(db, pull=dict(state="closed", merged=False, merged_at=None))
    await _tick(db, scope, client, item, revision)
    assert item.dispatch_status == "escalated" and item.escalation_reason == "pr_closed_unmerged"
    assert revision.status == "completed" and revision.completed_at == SETTLED_AT


@pytest.mark.asyncio
async def test_a_genuinely_inconsistent_item_logs_one_warning_not_one_per_poll(db, caplog, fresh_log_memory):
    scope, item, revision, client = await _settled(db, pull=dict(state="open", merged=False, merged_at=None))
    await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(active_scope_revision=3))
    await db.commit()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for _ in range(4):
            await _tick(db, scope, client, item)
    skips = _skips(caplog)
    assert len(skips) == 1 and skips[0].levelno == logging.WARNING and str(item.id) in skips[0].getMessage()


@pytest.mark.asyncio
async def test_a_changed_inconsistent_state_logs_again(db, caplog, fresh_log_memory):
    scope, item, revision, client = await _settled(db, pull=dict(state="open", merged=False, merged_at=None))
    await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(active_scope_revision=3))
    await db.commit()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await _tick(db, scope, client, item)
        await _tick(db, scope, client, item)
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(active_scope_revision=4))
        await db.commit()
        await _tick(db, scope, client, item)
        await _tick(db, scope, client, item)
    assert len(_skips(caplog)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "item"])
async def test_a_change_during_the_awaited_pr_read_settles_nothing(twin, change):
    db, maker = twin
    scope, item, revision, client = await _settled(db)
    original = client.get_pull
    revision_id, item_id = revision.id, item.id

    async def racing(owner, repo, number):
        if not racing.done:
            racing.done = True
            async with maker() as other:  # another connection changes the attempt while GitHub is awaited
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
    assert await _outcome_events(db, revision_id) == 0


# --- V1 review 5903551697: identity, fences, unreadable reads and poll isolation ---

OPEN = dict(state="open", merged=False, merged_at=None)
CLOSED = dict(state="closed", merged=False, merged_at=None)


def _quiet(caplog):
    return [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.INFO]


async def _unchanged(db, item, revision):
    await db.refresh(item)
    await db.refresh(revision)
    return (item.dispatch_status, item.status_note, item.updated_at, item.escalation_reason, revision.status,
            revision.completed_at)


@pytest.mark.asyncio
async def test_a_closed_response_cannot_escalate_an_attempt_that_replaced_the_settled_one_during_the_read(twin):
    db, maker = twin
    scope, item, revision, client = await _settled(db, pull=CLOSED)
    item_id, original = item.id, client.get_pull

    async def racing(*args):
        async with maker() as other:  # a new attempt replaces the settled one while GitHub is awaited
            await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == item_id).values(
                dispatch_nonce="new-attempt", dispatch_status="dispatched", status_note="new attempt healthy"))
            await other.commit()
        return await original(*args)

    client.get_pull = racing
    await _tick(db, scope, client, item, revision)
    assert (item.dispatch_nonce, item.dispatch_status, item.status_note) == ("new-attempt", "dispatched", "new attempt healthy")


@pytest.mark.asyncio
async def test_a_closed_response_for_another_pr_cannot_escalate_the_item(db):
    scope, item, revision, client = await _settled(db, pull=CLOSED)
    client.pull["number"] = 999
    before = await _unchanged(db, item, revision)
    await _tick(db, scope, client, item, revision)
    assert await _unchanged(db, item, revision) == before and item.dispatch_status == "verifying"


@pytest.mark.asyncio
async def test_a_closed_pr_that_reads_open_on_the_second_read_escalates_nothing(db):
    scope, item, revision, client = await _settled(db, pull=CLOSED)
    original, calls = client.get_pull, []

    async def flipping(*args):
        calls.append(1)
        pull = await original(*args)
        return pull if len(calls) == 1 else dict(pull, **OPEN)

    client.get_pull = flipping
    before = await _unchanged(db, item, revision)
    await _tick(db, scope, client, item, revision)
    assert len(calls) == 2 and await _unchanged(db, item, revision) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("pull", [OPEN, MERGED, CLOSED])
@pytest.mark.parametrize("failing_read", [1, 2])
async def test_an_unreadable_pr_changes_nothing_and_logs_nothing_then_recovers_without_a_stale_note(
        db, caplog, pull, failing_read):
    scope, item, revision, client = await _settled(db, pull=pull)
    original, calls = client.get_pull, []

    async def failing(*args):
        calls.append(1)
        if len(calls) == failing_read:
            raise httpx.ConnectError("isolated unavailable")
        return await original(*args)

    client.get_pull = failing
    before = await _unchanged(db, item, revision)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await _tick(db, scope, client, item, revision)
        if pull is OPEN or failing_read == 1:  # a failed first read leaves nothing to compare
            assert await _unchanged(db, item, revision) == before
        client.get_pull = original
        for _ in range(2):
            await _tick(db, scope, client, item, revision)
    assert _quiet(caplog) == []
    assert item.status_note is None or "failed" not in (item.status_note or "")
    if pull is OPEN:
        assert await _unchanged(db, item, revision) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("pull", [MERGED, CLOSED])
async def test_a_foreign_or_malformed_first_response_is_contained_and_logged_once(db, caplog, fresh_log_memory, pull):
    scope, item, revision, client = await _settled(db, pull=pull)
    client.pull["base"] = dict(client.pull["base"], repo={"full_name": "foreign/repo"})
    before = await _unchanged(db, item, revision)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for _ in range(3):
            await _tick(db, scope, client, item, revision)  # must not raise out of process_scope
    assert await _unchanged(db, item, revision) == before and item.dispatch_status == "verifying"
    assert len([r for r in _quiet(caplog) if r.levelno == logging.WARNING]) == 1


@pytest.mark.asyncio
async def test_a_failing_settled_item_does_not_stop_the_other_items_of_the_poll(db, fresh_log_memory):
    scope, item, revision, client = await _settled(db, pull=MERGED)
    client.pull["base"] = dict(client.pull["base"], repo={"full_name": "foreign/repo"})
    other = GithubWorkItem(scope_id=scope.id, issue_number=77, issue_title="other", issue_url="u",
                           github_updated_at=datetime.utcnow(), dispatch_status="verifying", pr_number=77,
                           dispatch_nonce="attempt-77", dispatch_head_ref="deck/other", dispatch_base_ref="release/v4.1",
                           owner_slot_id=item.owner_slot_id)
    db.add(other)
    await db.commit()
    seen, original = [], client.get_pull

    async def spying(owner, repo, number):
        seen.append(number)
        return await original(owner, repo, number)

    client.get_pull = spying
    await _tick(db, scope, client, item, revision)
    assert 77 in seen, "the poll stopped at the failing settled item"


@pytest.mark.asyncio
async def test_the_settlement_event_and_time_survive_the_merge_and_a_repeat_poll(db):
    scope, item, revision, client = await _settled(db)
    event = FactoryAuditEvent(event_kind="revision_outcome", source="settlement-fixture", occurred_at=SETTLED_AT,
                              actor_kind="system", revision_id=revision.id, item_id=item.id,
                              after_values={"outcome": "completed"})
    db.add(event)
    await db.commit()
    event_id = event.id
    await _tick(db, scope, client, item, revision)
    await _tick(db, scope, client, item, revision)  # the item is terminal now: a repeat poll must not touch anything
    assert item.dispatch_status == "merged" and revision.completed_at == SETTLED_AT
    assert await _outcome_events(db, revision.id) == 1
    await db.refresh(event)
    assert (event.id, event.occurred_at, event.after_values) == (event_id, SETTLED_AT, {"outcome": "completed"})


# --- V1 review 5903639166: the response boundary (real client errors and malformed nested shapes) ---


def _malformed_response(shape, base_payload):
    """The HTTP response a real GitHub client would parse for the given malformed shape."""
    def response(request):
        if shape == "invalid_json":
            return httpx.Response(200, text="{not-json", request=request)
        if shape == "array":
            return httpx.Response(200, json=[], request=request)
        payload = dict(base_payload)
        if shape == "base_repo_string":
            payload["base"] = dict(payload["base"], repo="invalid nested object")
        elif shape == "head_string":
            payload["head"] = "invalid head"
        elif shape == "head_repo_list":
            payload["head"] = dict(payload["head"], repo=["not", "an", "object"])
        return httpx.Response(200, json=payload, request=request)
    return response


SHAPES = ["invalid_json", "array", "base_repo_string", "head_string", "head_repo_list"]


async def _with_healthy_second_item(db, scope, item, client):
    other = GithubWorkItem(scope_id=scope.id, issue_number=77, issue_title="other", issue_url="u",
                           github_updated_at=datetime.utcnow(), dispatch_status="verifying", pr_number=77,
                           dispatch_nonce="attempt-77", dispatch_head_ref="deck/other", dispatch_base_ref="release/v4.1",
                           owner_slot_id=item.owner_slot_id)
    db.add(other)
    await db.commit()
    return other


@pytest.mark.asyncio
@pytest.mark.parametrize("pull", [MERGED, CLOSED])
@pytest.mark.parametrize("shape", SHAPES)
async def test_a_malformed_real_client_response_is_contained_and_the_poll_goes_on(db, shape, pull):
    from app.services.github_client import GithubClient
    scope, item, revision, client = await _settled(db, pull=pull)
    await _with_healthy_second_item(db, scope, item, client)
    healthy, settled_pr = client.get_pull, item.pr_number  # plain values: a rollback expires the item
    seen = []
    before = await _unchanged(db, item, revision)
    async with httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(
            _malformed_response(shape, dict(client.pull)))) as http:
        real = GithubClient(http=http, token="")

        async def routed(owner, repo, number):
            seen.append(number)
            return await (real.get_pull(owner, repo, number) if number == settled_pr else healthy(owner, repo, number))

        client.get_pull = routed
        await _tick(db, scope, client, item, revision)  # must not raise out of process_scope
    assert 77 in seen, "the poll stopped at the malformed settled item"
    assert await _unchanged(db, item, revision) == before and item.dispatch_status == "verifying"


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["base_repo_string", "head_string"])
async def test_a_malformed_final_reread_of_the_merge_is_contained(db, shape):
    scope, item, revision, client = await _settled(db)
    original, calls = client.get_pull, []

    async def second_read_malformed(*args):
        calls.append(1)
        pull = dict(await original(*args))
        if len(calls) >= 2:
            pull["base"] = dict(pull["base"], repo="invalid nested object") if shape == "base_repo_string" else pull["base"]
            if shape == "head_string":
                pull["head"] = "invalid head"
        return pull

    client.get_pull = second_read_malformed
    before = await _unchanged(db, item, revision)
    await _tick(db, scope, client, item, revision)
    assert len(calls) >= 2
    assert await _unchanged(db, item, revision) == before and item.dispatch_status == "verifying"


@pytest.mark.asyncio
async def test_an_implementation_error_inside_the_settled_path_is_not_swallowed(db, monkeypatch):
    scope, item, revision, client = await _settled(db)

    async def broken(*args, **kwargs):
        raise AttributeError("a programming error in the merge settlement")

    monkeypatch.setattr(service, "_settle_merged_submitted", broken)
    with pytest.raises(AttributeError):
        await service.process_scope(db, scope, client=client)
