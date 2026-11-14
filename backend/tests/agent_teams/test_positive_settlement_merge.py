"""#931: a positively settled revision no longer leaves its item 'verifying' and skipped by verification.

Positive settlement completes the revision but leaves the item on it. Verification used to read a completed
revision as 'inconsistent': it logged once a minute, never read the PR and never recorded the merge.
"""
from __future__ import annotations

import logging
from datetime import datetime

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
