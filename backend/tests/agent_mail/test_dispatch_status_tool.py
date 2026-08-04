"""Tests for the dispatch-status REST endpoint backing the MCP tool."""
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_workspace_service import github_workspace_service


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


class _FakeGitRunner:
    def __init__(self):
        self.statuses: dict[str, str] = {}
        self.rev_counts: dict[str, str] = {}
        self.failures: dict[str, str] = {}

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        path = args[1]
        command = args[2]
        if command in self.failures:
            return 1, self.failures[command]
        if command == "status":
            return 0, self.statuses.get(path, "")
        if command == "rev-list":
            return 0, f"{self.rev_counts.get(path, '0')}\n"
        return 0, ""


async def _seed_leased_item(
    maker,
    *,
    dispatch_status: str = "merged",
    lease_token: str = "lease-current",
):
    async with maker() as db:
        preset = AgentTeamPreset(name=f"release-{dispatch_status}-{datetime.utcnow()}")
        db.add(preset)
        await db.flush()
        owner = AgentTeamSlot(
            preset_id=preset.id,
            position=0,
            display_name="Owner",
            provider="codex-cli",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
        )
        other = AgentTeamSlot(
            preset_id=preset.id,
            position=1,
            display_name="Other",
            provider="codex-cli",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
        )
        db.add_all([owner, other])
        await db.flush()
        scope = TeamGithubScope(
            preset_id=preset.id,
            repo_owner="o",
            repo_name=f"r-{preset.id}",
            repo_path="/tmp/r",
        )
        db.add(scope)
        await db.flush()
        item = GithubWorkItem(
            scope_id=scope.id,
            issue_number=1,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status=dispatch_status,
            owner_slot_id=owner.id,
        )
        db.add(item)
        await db.flush()
        workspace = GithubWorkspace(
            scope_id=scope.id,
            path=f"/tmp/release-{item.id}",
            leased_item_id=item.id,
            lease_token=lease_token,
        )
        db.add(workspace)
        await db.commit()
        return item.id, owner.id, other.id, workspace.id, workspace.path


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


@pytest.mark.asyncio
async def test_owner_releases_terminal_item_idempotently(client_and_db, monkeypatch):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(maker)
    payload = {
        "work_item_id": item_id,
        "status": "workspace_released",
        "reporting_slot_id": owner_id,
        "lease_token": "lease-current",
    }

    first = await ac.post("/api/v1/agent-teams/dispatch-status", json=payload)
    second = await ac.post("/api/v1/agent-teams/dispatch-status", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_non_owner_cannot_release_workspace(client_and_db, monkeypatch):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, _, other_id, workspace_id, _ = await _seed_leased_item(maker)

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": other_id,
            "lease_token": "lease-current",
        },
    )

    assert response.status_code == 409
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id


@pytest.mark.asyncio
async def test_workspace_release_requires_token(client_and_db, monkeypatch):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(maker)

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": owner_id,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "lease_token required"
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id


@pytest.mark.asyncio
async def test_wrong_token_cannot_release_workspace(client_and_db, monkeypatch):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(maker)

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-stale",
        },
    )

    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_status", ["dispatched", "verifying", "ready_for_review"])
async def test_active_item_cannot_release_workspace(
    client_and_db, monkeypatch, dispatch_status
):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(
        maker, dispatch_status=dispatch_status
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-current",
        },
    )

    assert response.status_code == 409
    assert dispatch_status in response.json()["detail"]
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id


@pytest.mark.asyncio
async def test_release_refuses_dirty_tree_and_accepts_clean_tree(
    client_and_db, monkeypatch
):
    ac, maker = client_and_db
    runner = _FakeGitRunner()
    monkeypatch.setattr(github_workspace_service, "_runner", runner)
    dirty_item, dirty_owner, _, dirty_workspace, dirty_path = await _seed_leased_item(
        maker, dispatch_status="escalated"
    )
    runner.statuses[dirty_path] = " M src/foo.c\n"

    dirty = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": dirty_item,
            "status": "workspace_released",
            "reporting_slot_id": dirty_owner,
            "lease_token": "lease-current",
        },
    )

    assert dirty.status_code == 409
    assert "src/foo.c" in dirty.json()["detail"]
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, dirty_workspace)
        assert workspace.leased_item_id == dirty_item

    clean_item, clean_owner, _, clean_workspace, _ = await _seed_leased_item(
        maker, dispatch_status="escalated"
    )
    clean = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": clean_item,
            "status": "workspace_released",
            "reporting_slot_id": clean_owner,
            "lease_token": "lease-current",
        },
    )
    assert clean.status_code == 200
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, clean_workspace)
        assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_failed_item_with_retained_lease_can_release(client_and_db, monkeypatch):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(
        maker, dispatch_status="failed"
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-current",
        },
    )

    assert response.status_code == 200
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id is None


@pytest.mark.asyncio
async def test_owner_report_with_current_token_stamps_contact(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(
        maker, dispatch_status="dispatched"
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-current",
            "note": "working",
        },
    )

    assert response.status_code == 200
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.lease_last_owner_contact_at is not None


@pytest.mark.asyncio
async def test_owner_report_with_stale_token_does_not_stamp_contact(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(
        maker, dispatch_status="dispatched"
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-stale",
            "note": "new status note",
        },
    )

    assert response.status_code == 200
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        item = await db.get(GithubWorkItem, item_id)
        assert workspace.lease_last_owner_contact_at is None
        assert item.status_note == "new status note"


@pytest.mark.asyncio
async def test_release_refuses_unpushed_commits(client_and_db, monkeypatch):
    ac, maker = client_and_db
    runner = _FakeGitRunner()
    monkeypatch.setattr(github_workspace_service, "_runner", runner)
    item_id, owner_id, _, workspace_id, path = await _seed_leased_item(maker)
    runner.rev_counts[path] = "2"

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-current",
        },
    )

    assert response.status_code == 409
    assert "origin/HEAD" in response.json()["detail"]
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id


@pytest.mark.asyncio
async def test_release_fails_closed_when_status_is_unreadable(
    client_and_db, monkeypatch
):
    ac, maker = client_and_db
    runner = _FakeGitRunner()
    runner.failures["status"] = "fatal: unreadable worktree"
    monkeypatch.setattr(github_workspace_service, "_runner", runner)
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(maker)

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-current",
        },
    )

    assert response.status_code == 409
    assert "unreadable worktree" in response.json()["detail"]
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id


def test_shim_exposes_dispatch_status_tool():
    import importlib

    shim = importlib.import_module("mcp_shim.agent_mail_server")
    assert hasattr(shim, "deck_report_dispatch_status")
    assert hasattr(shim, "deck_retry_work_item")
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
        lease_token="lease-current",
    )

    assert result["ok"] is True
    assert requests[0][0:2] == ("POST", "/dispatch-status")
    assert requests[0][2]["json"]["reporting_slot_id"] == 7
    assert requests[0][2]["json"]["pr_number"] == 456
    assert requests[0][2]["json"]["lease_token"] == "lease-current"


def test_shim_retry_work_item_posts_reason(monkeypatch):
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
        return {"ok": True, "data": {"dispatch_status": "pending"}}

    monkeypatch.setattr(shim, "_dispatch_request", fake_dispatch_request)

    result = shim.deck_retry_work_item(
        123,
        reason="prerequisite #816 merged",
    )

    assert result["ok"] is True
    assert requests == [
        (
            "POST",
            "/github-work-items/123/retry",
            {"json": {"reason": "prerequisite #816 merged"}},
        )
    ]


def test_shim_list_work_items_filters_status_and_maps_ids(monkeypatch):
    import importlib

    shim = importlib.import_module("mcp_shim.agent_mail_server")
    requests = []

    monkeypatch.setattr(
        shim,
        "_ensure_registered",
        lambda: {
            "ok": True,
            "data": {"member": {"id": 1, "team_preset_id": 42}},
        },
    )

    def fake_dispatch_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {
            "ok": True,
            "data": {
                "items": [
                    {
                        "id": 17,
                        "issue_number": 817,
                        "dispatch_status": "escalated",
                        "escalation_reason": "plan_blocked",
                        "status_note": "Blocked by #816",
                    },
                    {
                        "id": 16,
                        "issue_number": 816,
                        "dispatch_status": "dispatched",
                        "escalation_reason": None,
                        "status_note": None,
                    },
                ]
            },
        }

    monkeypatch.setattr(shim, "_dispatch_request", fake_dispatch_request)

    result = shim.deck_list_work_items(status="escalated", limit=25)

    assert result == {
        "ok": True,
        "items": [
            {
                "work_item_id": 17,
                "issue_number": 817,
                "dispatch_status": "escalated",
                "escalation_reason": "plan_blocked",
                "status_note": "Blocked by #816",
            }
        ],
    }
    assert requests == [
        (
            "GET",
            "/presets/42/github-work-items",
            {"params": {"limit": 25}},
        )
    ]
