"""GitHub client + watcher service tests."""
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import AgentTeamPreset, GithubWorkItem, TeamGithubScope
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
