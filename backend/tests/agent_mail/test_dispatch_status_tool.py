"""Tests for the dispatch-status REST endpoint backing the MCP tool."""
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.database import AgentTeamPreset, GithubWorkItem, TeamGithubScope


@pytest_asyncio.fixture
async def client_and_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, maker
    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_item(maker, **overrides):
    async with maker() as db:
        preset = AgentTeamPreset(name="T", description="", created_by="t")
        db.add(preset)
        await db.flush()
        scope = TeamGithubScope(
            preset_id=preset.id,
            repo_owner="o",
            repo_name="r",
            repo_path="/tmp/r",
            max_approval_rounds=2,
        )
        db.add(scope)
        await db.flush()
        values = {
            "scope_id": scope.id,
            "issue_number": 1,
            "issue_title": "x",
            "issue_url": "u",
            "github_updated_at": datetime.utcnow(),
            "dispatch_status": "dispatched",
        }
        values.update(overrides)
        item = GithubWorkItem(**values)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item.id


@pytest.mark.asyncio
async def test_triaging_does_not_increment_approval_rounds(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker, approval_round_count=1)
    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "triaging"},
    )
    assert resp.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "dispatched"
        assert item.approval_round_count == 1
        assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_revision_requested_increments_and_caps(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker, approval_round_count=1)
    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "revision_requested"},
    )
    assert resp.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "escalated"
        assert item.escalation_reason == "approval_rounds_exhausted"


@pytest.mark.asyncio
async def test_blocked_uses_spec_reason_and_persists_note(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker)
    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "blocked", "note": "missing credentials"},
    )
    assert resp.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "escalated"
        assert item.escalation_reason == "plan_blocked"
        assert item.status_note == "missing credentials"


@pytest.mark.asyncio
async def test_in_progress_records_activity_without_satisfying_ack(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker, last_nudge_at=datetime.utcnow())
    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "in_progress"},
    )
    assert resp.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "dispatched"
        assert item.ack_received_at is None
        assert item.last_nudge_at is None
        assert item.pr_number is None


@pytest.mark.asyncio
async def test_pr_opened_rejected_after_item_escalated(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker, dispatch_status="escalated")
    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "pr_opened", "pr_number": 12},
    )
    assert resp.status_code == 409
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "escalated"
        assert item.pr_number is None


def test_shim_exposes_dispatch_status_tool():
    import importlib

    shim = importlib.import_module("mcp_shim.agent_mail_server")
    assert hasattr(shim, "deck_report_dispatch_status")
    assert hasattr(shim, "_dispatch_request")


def test_shim_dispatch_status_reports_team_slot(monkeypatch):
    import importlib

    shim = importlib.import_module("mcp_shim.agent_mail_server")
    requests = []

    monkeypatch.setattr(
        shim,
        "_ensure_registered",
        lambda: {"ok": True, "data": {"member": {"id": 1, "team_slot_id": 7}}},
    )

    def fake_dispatch_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"ok": True, "data": {"work_item_id": 123}}

    monkeypatch.setattr(shim, "_dispatch_request", fake_dispatch_request)

    result = shim.deck_report_dispatch_status(
        123,
        "pr_opened",
        pr_number=456,
        note="opened",
    )

    assert result["ok"] is True
    assert requests[0][0:2] == ("POST", "/dispatch-status")
    assert requests[0][2]["json"]["reporting_slot_id"] == 7
    assert requests[0][2]["json"]["pr_number"] == 456
