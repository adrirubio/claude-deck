"""GitHub PR verification and merge pipeline tests."""
from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.github_verification_service import github_verification_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _scope(db, **kwargs):
    preset = AgentTeamPreset(name="T", description="", created_by="t")
    db.add(preset)
    await db.flush()
    values = {
        "preset_id": preset.id,
        "repo_owner": "o",
        "repo_name": "r",
        "repo_path": "/tmp/r",
    }
    values.update(kwargs)
    scope = TeamGithubScope(
        **values,
    )
    db.add(scope)
    await db.flush()
    return scope


async def _item(db, scope, **kwargs):
    values = {
        "scope_id": scope.id,
        "issue_number": 1,
        "issue_title": "x",
        "issue_url": "u",
        "github_updated_at": datetime.utcnow(),
        "dispatch_status": "dispatched",
    }
    values.update(kwargs)
    item = GithubWorkItem(
        **values,
    )
    db.add(item)
    await db.commit()
    return item


async def _owner(db, scope):
    slot = AgentTeamSlot(
        preset_id=scope.preset_id,
        position=0,
        display_name="Owner",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
    )
    db.add(slot)
    await db.flush()
    member = MailTeamMember(
        identity_key=f"slot:{slot.id}",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=scope.preset_id,
        team_slot_id=slot.id,
    )
    db.add(member)
    await db.flush()
    return slot, member


class _Client:
    def __init__(
        self,
        *,
        pull=None,
        check_runs=None,
        combined_status=None,
        merge_result=None,
        merge_error: httpx.HTTPStatusError | None = None,
        ready_error: httpx.HTTPStatusError | None = None,
    ):
        self.pull = pull or {
            "number": 5,
            "node_id": "node",
            "draft": True,
            "merged": False,
            "mergeable_state": "clean",
            "head": {"sha": "sha"},
        }
        self.check_runs = check_runs if check_runs is not None else []
        self.combined_status = (
            combined_status
            if combined_status is not None
            else {"state": "pending", "statuses": []}
        )
        self.merge_result = merge_result or {"merged": True}
        self.merge_error = merge_error
        self.ready_error = ready_error
        self.ready_calls = 0
        self.merge_calls = 0
        self.pull_calls = 0

    async def get_pull(self, owner, repo, pr_number):
        self.pull_calls += 1
        return dict(self.pull)

    async def list_check_runs_for_ref(self, owner, repo, ref):
        return list(self.check_runs)

    async def get_combined_status_for_ref(self, owner, repo, ref):
        return dict(self.combined_status)

    async def mark_pull_ready_for_review(self, pull_node_id):
        self.ready_calls += 1
        if self.ready_error is not None:
            raise self.ready_error
        return {"ok": True}

    async def merge_pull(self, owner, repo, pr_number):
        self.merge_calls += 1
        if self.merge_error is not None:
            raise self.merge_error
        return self.merge_result


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("PUT", "https://api.github.com/repos/o/r/pulls/5/merge")
    response = httpx.Response(status_code, request=request, json={"message": "blocked"})
    return httpx.HTTPStatusError("blocked", request=request, response=response)


@pytest.mark.asyncio
async def test_report_pr_opened_routes_code_and_design(db):
    code_scope = await _scope(db)
    design_scope = await _scope(db, repo_name="design")
    code_item = await _item(db, code_scope, issue_type="code")
    design_item = await _item(db, design_scope, issue_type="design")

    await github_verification_service.report_pr_opened(db, code_item, code_scope, 10)
    await github_verification_service.report_pr_opened(db, design_item, design_scope, 11)

    await db.refresh(code_item)
    await db.refresh(design_item)
    assert code_item.pr_number == 10
    assert code_item.dispatch_status == "verifying"
    assert design_item.pr_number == 11
    assert design_item.dispatch_status == "awaiting_human_review"


@pytest.mark.asyncio
async def test_verify_green_code_pr_marks_ready_for_review(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}])

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert client.ready_calls == 1
    assert client.pull_calls == 2


@pytest.mark.asyncio
async def test_draft_ready_failure_keeps_item_verifying_for_retry(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}],
        ready_error=_http_error(403),
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert item.last_verified_sha is None
    assert "GitHub verification failed; will retry" in item.status_note
    assert client.ready_calls == 1
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not any(message.subject == "Code PR ready for review" for message in messages)


@pytest.mark.asyncio
async def test_verify_zero_check_runs_escalates(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="verifying",
        pr_number=5,
        updated_at=datetime.utcnow() - timedelta(minutes=5),
    )

    await github_verification_service.process_scope(db, scope, client=_Client(check_runs=[]))

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert "No GitHub check-runs or commit statuses" in item.status_note


@pytest.mark.asyncio
async def test_zero_check_runs_waits_during_grace_window(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)

    await github_verification_service.process_scope(db, scope, client=_Client(check_runs=[]))

    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert "Waiting for GitHub check-runs" in item.status_note


@pytest.mark.asyncio
async def test_combined_status_success_verifies_without_check_runs(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[],
        combined_status={"state": "success", "statuses": [{"context": "ci"}]},
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert client.ready_calls == 1
    assert client.pull_calls == 2


@pytest.mark.asyncio
async def test_unrecognized_check_conclusion_counts_as_failed(db):
    scope = await _scope(db, max_verification_retries=0)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "startup_failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"


@pytest.mark.asyncio
async def test_failed_check_returns_to_dispatched_until_budget_exhausted(db):
    scope = await _scope(db, max_verification_retries=2)
    slot, member = await _owner(db, scope)
    item = await _item(
        db,
        scope,
        dispatch_status="verifying",
        pr_number=5,
        retry_count=0,
        owner_slot_id=slot.id,
    )
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 1
    assert item.last_verified_sha == "sha"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert any(
        message.kind == "message"
        and message.recipient_member_id == member.id
        and "GitHub checks failed" in (message.subject or "")
        for message in messages
    )

    client.pull["head"]["sha"] = "sha-2"
    item.dispatch_status = "verifying"
    await db.commit()
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 2
    assert item.last_verified_sha == "sha-2"

    client.pull["head"]["sha"] = "sha-3"
    item.dispatch_status = "verifying"
    await db.commit()
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert item.retry_count == 3
    assert item.last_verified_sha == "sha-3"


@pytest.mark.asyncio
async def test_failed_check_counts_same_head_once_until_new_sha(db):
    scope = await _scope(db, max_verification_retries=2)
    slot, member = await _owner(db, scope)
    item = await _item(
        db,
        scope,
        dispatch_status="verifying",
        pr_number=5,
        owner_slot_id=slot.id,
    )
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)

    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 1
    assert item.escalation_reason is None
    assert item.last_verified_sha == "sha"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    failure_messages = [
        message
        for message in messages
        if message.kind == "message"
        and message.recipient_member_id == member.id
        and "GitHub checks failed" in (message.subject or "")
    ]
    assert len(failure_messages) == 1

    client.pull["head"]["sha"] = "sha-2"
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)

    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 2
    assert item.escalation_reason is None
    assert item.last_verified_sha == "sha-2"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    failure_messages = [
        message
        for message in messages
        if message.kind == "message"
        and message.recipient_member_id == member.id
        and "GitHub checks failed" in (message.subject or "")
    ]
    assert len(failure_messages) == 2


@pytest.mark.asyncio
async def test_failed_check_dispatched_item_with_pr_is_reverified(db):
    scope = await _scope(db, max_verification_retries=2)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"

    client.check_runs = [{"name": "ci", "status": "completed", "conclusion": "success"}]
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"


@pytest.mark.asyncio
async def test_auto_merge_success_sets_merged_and_budget_timestamp(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5)
    client = _Client()

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert item.auto_merged_at is not None
    assert client.merge_calls == 1


@pytest.mark.asyncio
async def test_auto_merge_cap_falls_back_to_human_review(db):
    scope = await _scope(db, merge_policy="auto", max_auto_merges_per_day=1)
    await _item(
        db,
        scope,
        issue_number=2,
        dispatch_status="merged",
        pr_number=4,
        auto_merged_at=datetime.utcnow() - timedelta(minutes=5),
    )
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5)
    client = _Client()

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert item.escalation_reason is None
    assert "Auto-merge budget exhausted" in item.status_note
    assert client.merge_calls == 0


@pytest.mark.asyncio
async def test_durable_merge_failure_falls_back_to_human_without_escalation(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5)
    client = _Client(merge_error=_http_error(403))

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert item.escalation_reason is None
    assert "requires human merge" in item.status_note
    assert client.merge_calls == 1


@pytest.mark.asyncio
async def test_unexpected_merge_status_is_transient_and_does_not_abort_batch(db):
    scope = await _scope(db, merge_policy="auto", max_verification_retries=2)
    first = await _item(db, scope, issue_number=1, dispatch_status="ready_for_review", pr_number=5)
    second = await _item(db, scope, issue_number=2, dispatch_status="ready_for_review", pr_number=6)

    class _BatchClient(_Client):
        async def get_pull(self, owner, repo, pr_number):
            return {
                "number": pr_number,
                "merged": False,
                "mergeable_state": "clean",
                "head": {"sha": f"sha-{pr_number}"},
            }

        async def merge_pull(self, owner, repo, pr_number):
            self.merge_calls += 1
            if pr_number == 5:
                raise _http_error(422)
            return {"merged": True}

    client = _BatchClient()

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(first)
    await db.refresh(second)
    assert first.dispatch_status == "ready_for_review"
    assert first.retry_count == 1
    assert "Transient merge failure" in first.status_note
    assert second.dispatch_status == "merged"


@pytest.mark.asyncio
async def test_draft_pr_is_refetched_before_auto_merge_decision(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)

    class _DraftClient(_Client):
        async def get_pull(self, owner, repo, pr_number):
            self.pull_calls += 1
            if self.pull_calls == 1:
                return {
                    "number": 5,
                    "node_id": "node",
                    "draft": True,
                    "merged": False,
                    "mergeable_state": "unknown",
                    "head": {"sha": "sha"},
                }
            return {
                "number": 5,
                "node_id": "node",
                "draft": False,
                "merged": False,
                "mergeable_state": "clean",
                "head": {"sha": "sha"},
            }

    client = _DraftClient(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert client.ready_calls == 1
    assert client.pull_calls == 2


@pytest.mark.asyncio
async def test_transient_merge_failure_falls_back_to_human_after_budget(db):
    scope = await _scope(db, merge_policy="auto", max_verification_retries=1)
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5)
    client = _Client(pull={"number": 5, "merged": False, "mergeable_state": "blocked"})

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert item.escalation_reason is None
    assert "Auto-merge retry budget exhausted" in item.status_note
    assert client.merge_calls == 0
