"""File-backed SQLite races for normalized approval authority."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.github_approval_service import (
    GithubApprovalError,
    GithubApprovalService,
)


async def _seed_attempt(maker):
    async with maker() as db:
        preset = AgentTeamPreset(name="Race", description="", created_by="test")
        db.add(preset)
        await db.flush()
        slots = []
        members = []
        for position, name in enumerate(("Leader", "Owner")):
            slot = AgentTeamSlot(
                preset_id=preset.id,
                position=position,
                display_name=name,
                provider="codex-cli",
                repo_id="approval-race",
                repo_path="/tmp/approval-race",
                repo_name="approval-race",
                launch_mode="plain",
                launch_options={},
                enabled=True,
            )
            db.add(slot)
            await db.flush()
            member = MailTeamMember(
                identity_key=f"slot:approval-race:{slot.id}",
                repo_id="approval-race",
                repo_path="/tmp/approval-race",
                repo_name="approval-race",
                display_name=name,
                participant_kind="team_slot",
                team_preset_id=preset.id,
                team_slot_id=slot.id,
            )
            db.add(member)
            await db.flush()
            slots.append(slot)
            members.append(member)
        scope = TeamGithubScope(
            preset_id=preset.id,
            repo_owner="o",
            repo_name="approval-race",
            repo_path="/tmp/approval-race",
        )
        db.add(scope)
        await db.flush()
        item = GithubWorkItem(
            scope_id=scope.id,
            issue_number=91,
            issue_title="approval race",
            issue_url="u",
            github_updated_at=members[0].created_at,
            dispatch_status="dispatched",
            owner_slot_id=slots[1].id,
            dispatch_nonce="0123456789abcdef",
            dispatch_head_ref=f"deck/slot-{slots[1].id}/issue-91-race",
            approval_round_count=1,
        )
        db.add(item)
        await db.commit()
        return item.id, members[1].id


async def _race_requests(tmp_path, summaries):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'approval-race.db'}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.exec_driver_sql("PRAGMA busy_timeout=5000")
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    item_id, owner_member_id = await _seed_attempt(maker)
    service = GithubApprovalService()
    original_current_pending = service.current_pending
    both_preflights_complete = asyncio.Event()
    arrivals = 0

    async def synchronized_current_pending(db, work_item_id):
        nonlocal arrivals
        pending = await original_current_pending(db, work_item_id)
        if pending is None and arrivals < 2:
            arrivals += 1
            if arrivals == 2:
                both_preflights_complete.set()
            await asyncio.wait_for(both_preflights_complete.wait(), timeout=5)
        return pending

    service.current_pending = synchronized_current_pending

    async def create(summary):
        async with maker() as db:
            item = await db.get(GithubWorkItem, item_id)
            return await service.create_initial_request(
                db,
                item,
                authenticated_owner_member_id=owner_member_id,
                summary=summary,
            )

    try:
        outcomes = await asyncio.gather(
            *(create(summary) for summary in summaries),
            return_exceptions=True,
        )
        async with maker() as db:
            counts = {
                "approvals": await db.scalar(
                    select(func.count()).select_from(GithubApprovalRequest)
                ),
                "messages": await db.scalar(select(func.count()).select_from(MailMessage)),
                "revisions": await db.scalar(
                    select(func.count()).select_from(GithubAttemptScopeRevision)
                ),
            }
        return outcomes, counts
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_identical_request_creators_converge_on_one_row(tmp_path):
    outcomes, counts = await _race_requests(tmp_path, ["same plan", "same plan"])

    assert all(
        not isinstance(outcome, BaseException) for outcome in outcomes
    ), outcomes
    requests = [outcome[0] for outcome in outcomes]
    created = [outcome[1] for outcome in outcomes]
    assert requests[0].id == requests[1].id
    assert sorted(created) == [False, True]
    assert counts == {"approvals": 1, "messages": 0, "revisions": 0}


@pytest.mark.asyncio
async def test_conflicting_request_creators_leave_no_orphans(tmp_path):
    outcomes, counts = await _race_requests(tmp_path, ["plan A", "plan B"])

    successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(successes) == 1
    assert successes[0][1] is True
    assert len(failures) == 1
    assert isinstance(failures[0], GithubApprovalError), outcomes
    assert failures[0].detail == "approval_request_already_pending"
    assert counts == {"approvals": 1, "messages": 0, "revisions": 0}
