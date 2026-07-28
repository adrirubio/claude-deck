"""GitHub client + watcher service tests."""
from datetime import datetime

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
from app.services.github_client import GithubClient
from app.services.github_watcher_service import github_watcher_service


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return self.handler(request)


@pytest.mark.asyncio
async def test_list_issues_with_label_builds_request():
    def handler(request):
        return httpx.Response(
            200,
            json=[
                {
                    "number": 42,
                    "title": "bug",
                    "html_url": "u",
                    "updated_at": "2026-07-04T00:00:00Z",
                    "labels": [{"name": "claude-deck-ready"}],
                }
            ],
        )

    transport = _RecordingTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http, token="tok")
        issues = await client.list_issues_with_label("o", "r", "claude-deck-ready")

    req = transport.requests[0]
    assert req.url.path == "/repos/o/r/issues"
    assert req.url.params["labels"] == "claude-deck-ready"
    assert req.url.params["state"] == "open"
    assert req.headers["Authorization"] == "Bearer tok"
    assert issues[0]["number"] == 42


@pytest.mark.asyncio
async def test_github_client_pr_check_and_merge_requests():
    def handler(request):
        if request.url.path == "/repos/o/r/pulls/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={"number": 5, "node_id": "PR_node", "head": {"sha": "abc"}, "merged": False},
            )
        if request.url.path == "/repos/o/r/commits/abc/check-runs":
            return httpx.Response(200, json={"check_runs": [{"name": "ci", "conclusion": "success"}]})
        if request.url.path == "/repos/o/r/commits/abc/status":
            return httpx.Response(200, json={"state": "success", "statuses": [{"context": "ci"}]})
        if request.url.path == "/graphql":
            return httpx.Response(200, json={"data": {"markPullRequestReadyForReview": {"pullRequest": {"id": "PR_node"}}}})
        if request.url.path == "/repos/o/r/pulls/5/merge":
            return httpx.Response(200, json={"merged": True})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    transport = _RecordingTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http, token="tok")
        pull = await client.get_pull("o", "r", 5)
        checks = await client.list_check_runs_for_ref("o", "r", "abc")
        status = await client.get_combined_status_for_ref("o", "r", "abc")
        ready = await client.mark_pull_ready_for_review("PR_node")
        merged = await client.merge_pull("o", "r", 5)

    assert pull["head"]["sha"] == "abc"
    assert checks[0]["name"] == "ci"
    assert status["state"] == "success"
    assert ready["data"]["markPullRequestReadyForReview"]["pullRequest"]["id"] == "PR_node"
    assert merged["merged"] is True


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


class _FakeClient:
    def __init__(self, labeled=None, by_number=None):
        self._labeled = labeled or []
        self._by_number = by_number or {}

    async def list_issues_with_label(self, owner, repo, label):
        return list(self._labeled)

    async def get_open_issues_by_number(self, owner, repo, numbers):
        return {
            number: self._by_number[number]
            for number in numbers
            if number in self._by_number and self._by_number[number].get("state", "open") == "open"
        }

    async def get_issues_by_number(self, owner, repo, numbers):
        return {number: self._by_number[number] for number in numbers if number in self._by_number}

    async def list_repo_labels(self, owner, repo):
        return []


async def _make_scope(db, **kw):
    preset = AgentTeamPreset(name=kw.pop("preset_name", "T"), description="", created_by="t")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id, repo_owner="o", repo_name="r", repo_path="/tmp/r", **kw
    )
    db.add(scope)
    await db.commit()
    await db.refresh(scope)
    return scope


def _issue(number, labels, updated="2026-07-04T00:00:00Z"):
    return {
        "number": number,
        "title": f"issue {number}",
        "html_url": f"https://github.com/o/r/issues/{number}",
        "updated_at": updated,
        "state": "open",
        "labels": [{"name": name} for name in labels],
    }


@pytest.mark.asyncio
async def test_poll_creates_pending_code_item(db):
    scope = await _make_scope(db)
    client = _FakeClient(labeled=[_issue(1, ["claude-deck-ready"])])
    await github_watcher_service.poll_scope(db, scope, client)
    items = (await db.execute(select(GithubWorkItem))).scalars().all()
    assert len(items) == 1
    assert items[0].issue_number == 1
    assert items[0].issue_type == "code"
    assert items[0].dispatch_status == "pending"


@pytest.mark.asyncio
async def test_poll_detects_design_type(db):
    scope = await _make_scope(db)
    client = _FakeClient(labeled=[_issue(2, ["claude-deck-ready", "claude-deck-design"])])
    await github_watcher_service.poll_scope(db, scope, client)
    item = (await db.execute(select(GithubWorkItem))).scalars().one()
    assert item.issue_type == "design"


@pytest.mark.asyncio
async def test_poll_is_idempotent(db):
    scope = await _make_scope(db)
    client = _FakeClient(labeled=[_issue(1, ["claude-deck-ready"])])
    await github_watcher_service.poll_scope(db, scope, client)
    await github_watcher_service.poll_scope(db, scope, client)
    items = (await db.execute(select(GithubWorkItem))).scalars().all()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_escalated_item_recovers_on_updated_timestamp(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=5,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 1),
        dispatch_status="escalated",
        escalation_reason="retry_count_exhausted",
        pending_reason="queued_slot_busy",
        handoff_state="pending",
        handoff_target_slot_id=123,
        retry_count=2,
        approval_round_count=1,
    )
    db.add(item)
    await db.commit()
    client = _FakeClient(
        labeled=[_issue(5, ["claude-deck-ready"], updated="2026-07-04T00:00:00Z")]
    )
    await github_watcher_service.poll_scope(db, scope, client)
    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.escalation_reason is None
    assert item.pending_reason is None
    assert item.handoff_state is None
    assert item.handoff_target_slot_id is None
    assert item.retry_count == 0
    assert item.approval_round_count == 0


@pytest.mark.asyncio
async def test_active_item_escalates_when_label_removed(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=7,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 1),
        dispatch_status="dispatched",
    )
    db.add(item)
    await db.commit()
    client = _FakeClient(
        labeled=[],
        by_number={7: _issue(7, ["some-other-label"])},
    )
    await github_watcher_service.poll_scope(db, scope, client)
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"


@pytest.mark.asyncio
async def test_label_removed_sends_broadcast_and_owner_direct_message(db):
    scope = await _make_scope(db)
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
        identity_key="slot:owner",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=scope.preset_id,
        team_slot_id=slot.id,
    )
    db.add(member)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=9,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 1),
        dispatch_status="dispatched",
        owner_slot_id=slot.id,
    )
    db.add(item)
    await db.commit()
    client = _FakeClient(labeled=[], by_number={9: _issue(9, ["some-other-label"])})

    await github_watcher_service.poll_scope(db, scope, client)

    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert any(message.kind == "broadcast" for message in messages)
    assert any(
        message.kind == "message" and message.recipient_member_id == member.id
        for message in messages
    )


@pytest.mark.asyncio
async def test_active_item_closed_does_not_escalate_as_label_removed(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=8,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 1),
        dispatch_status="dispatched",
    )
    db.add(item)
    await db.commit()
    closed = _issue(8, ["some-other-label"])
    closed["state"] = "closed"
    client = _FakeClient(labeled=[], by_number={8: closed})
    await github_watcher_service.poll_scope(db, scope, client)
    await db.refresh(item)
    assert item.dispatch_status == "completed"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_watcher_completed_fires_blocker_merged_notification(db):
    scope = await _make_scope(db)
    leader = AgentTeamSlot(
        preset_id=scope.preset_id,
        position=0,
        display_name="Leader",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
    )
    db.add(leader)
    await db.flush()
    member = MailTeamMember(
        identity_key="slot:leader",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Leader",
        participant_kind="team_slot",
        team_preset_id=scope.preset_id,
        team_slot_id=leader.id,
    )
    db.add(member)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=858,
        issue_title="design",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="awaiting_human_review",
    )
    db.add(item)
    await db.commit()
    closed = _issue(858, ["claude-deck-ready"])
    closed["state"] = "closed"

    await github_watcher_service.poll_scope(
        db,
        scope,
        _FakeClient(labeled=[], by_number={858: closed}),
    )

    await db.refresh(item)
    assert item.dispatch_status == "completed"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    notifications = [
        message
        for message in messages
        if (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
    ]
    assert len(notifications) == 1
    assert notifications[0].recipient_member_id == member.id


@pytest.mark.asyncio
async def test_closed_issue_reconciles_escalated_item(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=818,
        issue_title="blocked work",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 4),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
    )
    db.add(item)
    await db.commit()
    closed = _issue(818, ["claude-deck-ready"])
    closed["state"] = "closed"

    await github_watcher_service.poll_scope(
        db,
        scope,
        _FakeClient(labeled=[], by_number={818: closed}),
    )

    await db.refresh(item)
    assert item.dispatch_status == "completed"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_closed_issue_reconciliation_fires_blocker_merged_notification(db):
    scope = await _make_scope(db)
    leader = AgentTeamSlot(
        preset_id=scope.preset_id,
        position=0,
        display_name="Leader",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
    )
    db.add(leader)
    await db.flush()
    member = MailTeamMember(
        identity_key="slot:closed-reconciliation-leader",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Leader",
        participant_kind="team_slot",
        team_preset_id=scope.preset_id,
        team_slot_id=leader.id,
    )
    db.add(member)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=819,
        issue_title="blocked work",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 4),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
    )
    db.add(item)
    await db.commit()
    closed = _issue(819, ["claude-deck-ready"])
    closed["state"] = "closed"

    await github_watcher_service.poll_scope(
        db,
        scope,
        _FakeClient(labeled=[], by_number={819: closed}),
    )

    messages = (await db.execute(select(MailMessage))).scalars().all()
    notifications = [
        message
        for message in messages
        if (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
    ]
    assert len(notifications) == 1
    assert notifications[0].recipient_member_id == member.id


@pytest.mark.asyncio
async def test_closed_issue_reconciles_failed_item(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=820,
        issue_title="failed work",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 4),
        dispatch_status="failed",
        escalation_reason="launch_failed",
    )
    db.add(item)
    await db.commit()
    closed = _issue(820, ["claude-deck-ready"])
    closed["state"] = "closed"

    await github_watcher_service.poll_scope(
        db,
        scope,
        _FakeClient(labeled=[], by_number={820: closed}),
    )

    await db.refresh(item)
    assert item.dispatch_status == "completed"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_closed_issue_skips_item_with_open_pr(db, caplog):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=821,
        issue_title="work with open PR",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 4),
        dispatch_status="escalated",
        escalation_reason="dispatch_label_removed",
        pr_number=865,
    )
    db.add(item)
    await db.commit()
    closed = _issue(821, ["claude-deck-ready"])
    closed["state"] = "closed"
    caplog.set_level("INFO", logger="app.services.github_watcher_service")

    await github_watcher_service.poll_scope(
        db,
        scope,
        _FakeClient(labeled=[], by_number={821: closed}),
    )

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"
    assert item.pr_number == 865
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not any(
        (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
        for message in messages
    )
    assert "unresolved PR #865" in caplog.text


@pytest.mark.asyncio
async def test_failed_item_with_label_removed_is_not_laundered_into_escalated(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=822,
        issue_title="failed work",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 4),
        dispatch_status="failed",
        escalation_reason="launch_failed",
    )
    db.add(item)
    await db.commit()
    open_issue = _issue(822, [])

    await github_watcher_service.poll_scope(
        db,
        scope,
        _FakeClient(labeled=[], by_number={822: open_issue}),
    )

    await db.refresh(item)
    assert item.dispatch_status == "failed"
    assert item.escalation_reason == "launch_failed"


@pytest.mark.asyncio
async def test_escalated_item_with_open_labeled_issue_is_untouched(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=823,
        issue_title="blocked work",
        issue_url="u",
        github_updated_at=datetime(2026, 7, 4),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
    )
    db.add(item)
    await db.commit()
    open_issue = _issue(823, ["claude-deck-ready"])

    await github_watcher_service.poll_scope(
        db,
        scope,
        _FakeClient(labeled=[open_issue], by_number={823: open_issue}),
    )

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "plan_blocked"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not any(
        (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
        for message in messages
    )
