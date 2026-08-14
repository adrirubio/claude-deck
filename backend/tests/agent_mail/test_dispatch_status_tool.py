"""Tests for the dispatch-status REST endpoint backing the MCP tool."""

import ast
import inspect
import textwrap
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.v1.agent_teams as agent_teams_routes
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service
from app.services.github_app_auth_service import (
    GithubAppMintError,
    GithubAppNotInstalled,
    GithubAppUnconfigured,
)
from app.services.github_client import GithubClientResponseError
from app.services.github_workspace_service import (
    GithubWorkspaceCredentialRevokeError,
    github_workspace_service,
)

DEFAULT_TOKEN = "default-owner-token"


@pytest.fixture(autouse=True)
def require_capabilities(monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)


@pytest.fixture(autouse=True)
def stub_reported_pull(monkeypatch):
    async def get_pull(owner, repo, pr_number):
        full_name = f"{owner}/{repo}"
        return {
            "number": pr_number,
            "state": "open",
            "merged_at": None,
            "merged": False,
            "head": {
                "sha": "sha",
                "ref": "deck/test-attempt",
                "repo": {"full_name": full_name},
            },
            "base": {"ref": "master", "repo": {"full_name": full_name}},
            "user": {"login": "human"},
        }

    monkeypatch.setattr(agent_teams_routes.github_client, "get_pull", get_pull)


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
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Deck-Session-Token": DEFAULT_TOKEN},
    ) as ac:
        yield ac, maker
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def wal_client_and_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dispatch.db'}")
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Deck-Session-Token": DEFAULT_TOKEN},
    ) as ac:
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
        owner = AgentTeamSlot(
            preset_id=preset.id,
            position=0,
            display_name="Owner",
            provider="codex-cli",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
        )
        db.add(owner)
        await db.flush()
        member = MailTeamMember(
            identity_key=f"default:{owner.id}",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Owner",
            participant_kind="team_slot",
            team_preset_id=preset.id,
            team_slot_id=owner.id,
        )
        db.add(member)
        await db.flush()
        default_hash = agent_mail_service.hash_capability_token(DEFAULT_TOKEN)
        existing_session = (
            await db.execute(
                select(MailAgentSession).where(
                    MailAgentSession.capability_token_hash == default_hash
                )
            )
        ).scalar_one_or_none()
        if existing_session is None:
            existing_session = MailAgentSession(
                source="mcp",
                session_key=f"default:{owner.id}",
                capability_token_hash=default_hash,
            )
            db.add(existing_session)
        existing_session.member_id = member.id
        existing_session.team_preset_id = preset.id
        existing_session.team_slot_id = owner.id
        existing_session.bound_pane_pid = 1000 + owner.id
        existing_session.bound_pane_proc_start = f"start-{owner.id}"
        values = {
            "scope_id": scope.id,
            "issue_number": 1,
            "issue_title": "x",
            "issue_url": "u",
            "github_updated_at": datetime.utcnow(),
            "dispatch_status": "dispatched",
            "owner_slot_id": owner.id,
            "dispatch_head_ref": "deck/test-attempt",
            "dispatch_base_ref": "origin/master",
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
        member = MailTeamMember(
            identity_key=f"default:{owner.id}",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Owner",
            participant_kind="team_slot",
            team_preset_id=preset.id,
            team_slot_id=owner.id,
        )
        db.add(member)
        await db.flush()
        default_hash = agent_mail_service.hash_capability_token(DEFAULT_TOKEN)
        existing_session = (
            await db.execute(
                select(MailAgentSession).where(
                    MailAgentSession.capability_token_hash == default_hash
                )
            )
        ).scalar_one_or_none()
        if existing_session is None:
            existing_session = MailAgentSession(
                source="mcp",
                session_key=f"default:{owner.id}",
                capability_token_hash=default_hash,
            )
            db.add(existing_session)
        existing_session.member_id = member.id
        existing_session.team_preset_id = preset.id
        existing_session.team_slot_id = owner.id
        existing_session.bound_pane_pid = 1000 + owner.id
        existing_session.bound_pane_proc_start = f"start-{owner.id}"
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
            dispatch_head_ref="deck/test-attempt",
            dispatch_base_ref="origin/master",
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


async def _token_for_slot(maker, slot_id: int | None, *, key: str = "mcp:auth") -> str:
    """Mint a session bound directly to slot_id and return its plaintext token."""
    token = f"tok-{key}-{slot_id}"
    async with maker() as db:
        member = MailTeamMember(
            identity_key=f"slot:{key}:{slot_id}",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Reporter",
            participant_kind="team_slot",
            team_slot_id=slot_id,
        )
        db.add(member)
        await db.flush()
        db.add(
            MailAgentSession(
                member_id=member.id,
                source="mcp",
                session_key=key,
                team_slot_id=slot_id,
                capability_token_hash=agent_mail_service.hash_capability_token(token),
                bound_pane_pid=(1000 + slot_id if slot_id is not None else None),
                bound_pane_proc_start=(
                    f"start-{slot_id}" if slot_id is not None else None
                ),
            )
        )
        await db.commit()
    return token


def _auth(token: str) -> dict[str, str]:
    return {"X-Deck-Session-Token": token}


def _statuses_the_route_accepts() -> set[str]:
    source = textwrap.dedent(inspect.getsource(agent_teams_routes.report_dispatch_status))
    return {
        node.comparators[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "status"
        and isinstance(node.comparators[0], ast.Constant)
        and isinstance(node.comparators[0].value, str)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("triaging", {"note": "n"}),
        ("revision_requested", {}),
        ("handoff_initiated", {"reassign_to_slot_id": 2}),
        ("handoff_accepted", {}),
        ("blocked", {"note": "n"}),
        ("ack_received", {}),
        ("pr_opened", {"pr_number": 7, "lease_token": "lease"}),
        ("pr_ready", {"head_ref": "deck/test-attempt", "lease_token": "lease"}),
        ("in_progress", {}),
        ("workspace_released", {"lease_token": "lease"}),
    ],
)
async def test_grace_mode_refuses_every_dispatch_write(
    client_and_db, monkeypatch, status, extra
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", False)
    ac, maker = client_and_db
    item_id = await _seed_item(maker, approval_round_count=1)
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        before = {
            column.name: getattr(item, column.name)
            for column in GithubWorkItem.__table__.columns
        }

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": status, **extra},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "tokens_not_enforced"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        after = {
            column.name: getattr(item, column.name)
            for column in GithubWorkItem.__table__.columns
        }
    assert after == before


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
async def test_revision_requested_requires_explicit_decision_tool(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker, approval_round_count=1)
    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "revision_requested"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "use_deck_approve_work_item"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "dispatched"
        assert item.approval_round_count == 1


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
        json={
            "work_item_id": item_id,
            "status": "in_progress",
            "pr_number": 9999,
        },
    )
    assert resp.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "dispatched"
        assert item.ack_received_at is None
        assert item.last_nudge_at is None
        assert item.pr_number is None
        assert agent_teams_routes.github_dispatch_service._ack_satisfied(item) is False


@pytest.mark.asyncio
async def test_pr_opened_rejected_after_item_escalated(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker, dispatch_status="escalated")
    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_opened",
            "pr_number": 12,
            "lease_token": "no-current-lease",
        },
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
async def test_workspace_release_reports_push_token_revocation_failure_as_503(
    client_and_db, monkeypatch
):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, _, workspace_id, _ = await _seed_leased_item(maker)

    async def fail_revoke(*args, **kwargs):
        raise GithubWorkspaceCredentialRevokeError("revocation unavailable")

    monkeypatch.setattr(github_workspace_service, "release_by_owner", fail_revoke)

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "reporting_slot_id": owner_id,
            "lease_token": "lease-current",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "workspace_credential_revoke_failed"
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id


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

    assert response.status_code == 403
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
    assert response.json()["detail"]["block_code"] == "lease_changed"
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


def test_shim_dispatch_status_omits_caller_slot_claim(monkeypatch):
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
        "pr_ready",
        head_ref="deck/slot-7/issue-123/attempt",
        note="opened",
        lease_token="lease-current",
    )

    assert result["ok"] is True
    assert requests[0][0:2] == ("POST", "/dispatch-status")
    assert "reporting_slot_id" not in requests[0][2]["json"]
    assert requests[0][2]["json"]["pr_number"] is None
    assert requests[0][2]["json"]["head_ref"] == "deck/slot-7/issue-123/attempt"
    assert requests[0][2]["json"]["lease_token"] == "lease-current"


def test_shim_inbox_counts_do_not_send_a_member_identity(monkeypatch):
    import importlib

    shim = importlib.import_module("mcp_shim.agent_mail_server")
    requests = []
    monkeypatch.setitem(shim._state, "member_id", 7)

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {
            "ok": True,
            "data": {"unread_count": 2, "pending_count": 1},
        }

    monkeypatch.setattr(shim, "_request", fake_request)

    assert shim._counts() == {"unread_count": 2, "pending_count": 1}
    assert requests == [("GET", "/agent/inbox?unread_only=true&limit=1", {})]


def test_shim_approval_requires_registration(monkeypatch):
    import importlib

    shim = importlib.import_module("mcp_shim.agent_mail_server")
    refusal = {"ok": False, "error": {"code": "registration_failed"}}
    monkeypatch.setattr(shim, "_guard", lambda: refusal)

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("an unregistered shim must not submit a decision")

    monkeypatch.setattr(shim, "_request", unexpected_request)

    assert shim.deck_approve_work_item(1, "nonce", "approved", "safe") == refusal


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
                "ack_approval_round": None,
                "ack_enforcement_epoch": None,
                "dispatch_head_ref": None,
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


_OWNER_ONLY_STATUSES = [
    ("triaging", {"note": "n"}),
    ("in_progress", {}),
    ("blocked", {"note": "n"}),
    ("ack_received", {}),
    ("handoff_initiated", {"reassign_to_slot_id": 1}),
    ("pr_opened", {"pr_number": 7}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,extra", _OWNER_ONLY_STATUSES)
async def test_non_owner_is_refused_and_changes_nothing(client_and_db, status, extra):
    ac, maker = client_and_db
    item_id, _owner_id, other_id, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, other_id, key=f"mcp:{status}")
    async with maker() as db:
        before = await db.get(GithubWorkItem, item_id)
        snapshot = {
            column.name: getattr(before, column.name)
            for column in GithubWorkItem.__table__.columns
        }

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": status, **extra},
        headers=_auth(token),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_item_owner"
    async with maker() as db:
        after = await db.get(GithubWorkItem, item_id)
        assert {
            column.name: getattr(after, column.name)
            for column in GithubWorkItem.__table__.columns
        } == snapshot


@pytest.mark.asyncio
async def test_revision_requested_is_actionable_for_every_authenticated_slot(
    client_and_db,
):
    ac, maker = client_and_db
    item_id, _owner_id, other_id, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, other_id, key="mcp:retired-revision")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "revision_requested"},
        headers=_auth(token),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "use_deck_approve_work_item"


@pytest.mark.asyncio
async def test_handoff_accepted_belongs_to_the_target(client_and_db, monkeypatch):
    ac, maker = client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, other_id, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        item.handoff_target_slot_id = other_id
        item.handoff_state = "pending"
        await db.commit()

    owner_token = await _token_for_slot(maker, owner_id, key="mcp:ha-owner")
    refused = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "handoff_accepted"},
        headers=_auth(owner_token),
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "not_handoff_target"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.owner_slot_id == owner_id
        assert item.handoff_state == "pending"

    target_token = await _token_for_slot(maker, other_id, key="mcp:ha-target")
    accepted = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "handoff_accepted"},
        headers=_auth(target_token),
    )
    assert accepted.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.owner_slot_id == other_id
        assert item.handoff_state == "accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize("target_kind", ["missing", "different_preset"])
async def test_handoff_initiation_rejects_invalid_targets_without_mutation(
    client_and_db,
    target_kind,
):
    ac, maker = client_and_db
    item_id, owner_id, _other_id, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    async with maker() as db:
        if target_kind == "different_preset":
            preset = AgentTeamPreset(name="Other preset")
            db.add(preset)
            await db.flush()
            target = AgentTeamSlot(
                preset_id=preset.id,
                position=0,
                display_name="Foreign",
                provider="codex-cli",
                repo_id="foreign",
                repo_path="/tmp/foreign",
                repo_name="foreign",
                enabled=True,
            )
            db.add(target)
            await db.commit()
            target_id = target.id
        else:
            target_id = 999_999
    owner_token = await _token_for_slot(maker, owner_id, key=f"mcp:bad-{target_kind}")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "handoff_initiated",
            "reassign_to_slot_id": target_id,
        },
        headers=_auth(owner_token),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_handoff_target"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.handoff_state is None
        assert item.handoff_target_slot_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["owner", "acquisition"])
async def test_workspace_release_cas_survives_wal_interleaving(
    wal_client_and_db,
    monkeypatch,
    race,
):
    ac, maker = wal_client_and_db
    monkeypatch.setattr(github_workspace_service, "_runner", _FakeGitRunner())
    item_id, owner_id, other_id, workspace_id, _ = await _seed_leased_item(maker)
    entered_blocker = False

    async def interleaving_blocker(_scope, _workspace):
        nonlocal entered_blocker
        entered_blocker = True
        async with maker() as other_db:
            if race == "owner":
                item = await other_db.get(GithubWorkItem, item_id)
                item.owner_slot_id = other_id
            else:
                workspace = await other_db.get(GithubWorkspace, workspace_id)
                workspace.lease_token = "replacement-token"
            await other_db.commit()
        return None

    monkeypatch.setattr(
        github_workspace_service,
        "release_blocker",
        interleaving_blocker,
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "workspace_released",
            "lease_token": "lease-current",
        },
    )

    assert entered_blocker is True
    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.leased_item_id == item_id
        expected_token = "replacement-token" if race == "acquisition" else "lease-current"
        assert workspace.lease_token == expected_token


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["owner", "acquisition"])
async def test_owner_contact_cas_survives_wal_interleaving(
    wal_client_and_db,
    monkeypatch,
    race,
):
    ac, maker = wal_client_and_db
    item_id, owner_id, other_id, workspace_id, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    original_touch = github_workspace_service.touch_owner_contact
    entered_touch = False

    async def interleaving_touch(db, work_item_id, *, lease_token, owner_slot_id):
        nonlocal entered_touch
        entered_touch = True
        async with maker() as other_db:
            if race == "owner":
                item = await other_db.get(GithubWorkItem, item_id)
                item.owner_slot_id = other_id
            else:
                workspace = await other_db.get(GithubWorkspace, workspace_id)
                workspace.lease_token = "replacement-token"
            await other_db.commit()
        await original_touch(
            db,
            work_item_id,
            lease_token=lease_token,
            owner_slot_id=owner_slot_id,
        )

    monkeypatch.setattr(
        github_workspace_service,
        "touch_owner_contact",
        interleaving_touch,
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "lease_token": "lease-current",
            "note": "still working",
        },
    )

    assert entered_touch is True
    assert response.status_code == 200
    async with maker() as db:
        workspace = await db.get(GithubWorkspace, workspace_id)
        assert workspace.lease_last_owner_contact_at is None


@pytest.mark.asyncio
async def test_pr_opened_with_a_stale_token_leaves_pr_number_null(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key="mcp:pr")

    stale = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_opened",
            "pr_number": 7,
            "lease_token": "lease-stale",
        },
        headers=_auth(token),
    )
    assert stale.status_code == 409
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.pr_number is None
        assert item.dispatch_status == "dispatched"

    current = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_opened",
            "pr_number": 7,
            "lease_token": "lease-current",
        },
        headers=_auth(token),
    )
    assert current.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.pr_number == 7


@pytest.mark.asyncio
async def test_pr_opened_with_no_token_at_all_is_refused(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key="mcp:pr-none")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "pr_opened", "pr_number": 7},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "lease_token required"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.pr_number is None


@pytest.mark.asyncio
async def test_blocked_needs_no_lease_token(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key="mcp:blocked")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "blocked", "note": "stuck"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "escalated"
        assert item.escalation_reason == "plan_blocked"
        assert item.status_note == "stuck"


@pytest.mark.asyncio
async def test_a_disagreeing_slot_claim_is_refused(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, other_id, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key="mcp:claim")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": other_id,
            "note": "n",
        },
        headers=_auth(token),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "slot_claim_mismatch"

    agreeing = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": owner_id,
            "note": "n",
        },
        headers=_auth(token),
    )
    assert agreeing.status_code == 200


@pytest.mark.asyncio
async def test_an_unbound_session_cannot_speak_for_a_slot(client_and_db):
    ac, maker = client_and_db
    item_id, _, _, _, _ = await _seed_leased_item(maker, dispatch_status="dispatched")
    token = await _token_for_slot(maker, None, key="mcp:unbound")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "triaging", "note": "n"},
        headers=_auth(token),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "session_not_slot_bound"


@pytest.mark.asyncio
async def test_an_invalid_token_never_falls_back_to_the_legacy_path(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": owner_id,
            "note": "n",
        },
        headers=_auth("not-a-real-token"),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_invalid"


def test_every_accepted_status_has_an_authorization_rule():
    accepted = _statuses_the_route_accepts()
    assert len(accepted) == 10, f"branch count changed: {sorted(accepted)}"
    missing = accepted - set(agent_teams_routes._DISPATCH_STATUS_RULES)
    assert not missing, f"statuses with no authorization rule: {sorted(missing)}"


def test_the_rules_table_has_no_rule_for_a_status_the_route_rejects():
    stale = set(agent_teams_routes._DISPATCH_STATUS_RULES) - _statuses_the_route_accepts()
    assert not stale, f"rules for non-existent statuses: {sorted(stale)}"


@pytest.mark.asyncio
async def test_an_unknown_status_refuses_rather_than_falling_through(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key="mcp:unknown")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "not_a_real_status"},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unknown status not_a_real_status"


@pytest.mark.asyncio
async def test_pr_ready_cheap_path_returns_the_stored_number(client_and_db):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="verifying",
    )
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        item.pr_number = 42
        await db.commit()
    token = await _token_for_slot(maker, owner_id, key="mcp:pr-ready-cheap")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_ready",
            "head_ref": "deck/test-attempt",
            "lease_token": "lease-current",
        },
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["pr_number"] == 42


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (GithubAppNotInstalled("o", "r", 55), 409, "app_not_installed"),
        (GithubAppUnconfigured(), 503, "app_auth_unconfigured"),
        (GithubAppMintError("o", "r"), 502, "app_token_mint_failed"),
        (
            httpx.ReadTimeout(
                "timed out",
                request=httpx.Request("POST", "https://api.github.com"),
            ),
            503,
            "github_upstream_timeout",
        ),
        (
            httpx.ConnectError(
                "offline",
                request=httpx.Request("POST", "https://api.github.com"),
            ),
            502,
            "github_upstream_error",
        ),
        (
            GithubClientResponseError("unsafe pagination"),
            502,
            "github_upstream_error",
        ),
    ],
)
async def test_pr_ready_maps_upstream_failures_to_stable_http_contracts(
    client_and_db, monkeypatch, error, status_code, detail
):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key=f"mcp:pr-ready:{detail}")

    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        agent_teams_routes.github_verification_service,
        "report_pr_ready",
        fail,
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_ready",
            "head_ref": "deck/test-attempt",
            "lease_token": "lease-current",
        },
        headers=_auth(token),
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            httpx.ReadTimeout(
                "timed out",
                request=httpx.Request("GET", "https://api.github.com"),
            ),
            503,
            "github_upstream_timeout",
        ),
        (
            httpx.ConnectError(
                "offline",
                request=httpx.Request("GET", "https://api.github.com"),
            ),
            502,
            "github_upstream_error",
        ),
        (
            GithubClientResponseError("invalid GitHub response"),
            502,
            "github_upstream_error",
        ),
    ],
)
async def test_pr_opened_maps_upstream_failures_to_stable_http_contracts(
    client_and_db, monkeypatch, error, status_code, detail
):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key=f"mcp:pr-opened:{detail}")

    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        agent_teams_routes.github_verification_service,
        "report_pr_opened",
        fail,
    )

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_opened",
            "pr_number": 9,
            "lease_token": "lease-current",
        },
        headers=_auth(token),
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"status": "pr_ready", "pr_number": 9, "head_ref": "deck/test-attempt"},
        {"status": "pr_ready", "head_ref": ""},
        {"status": "pr_opened", "pr_number": 9, "head_ref": "deck/test-attempt"},
    ],
)
async def test_pr_status_payload_authorities_cannot_be_mixed(
    client_and_db, payload
):
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(
        maker,
        dispatch_status="dispatched",
    )
    token = await _token_for_slot(maker, owner_id, key=f"mcp:mixed:{payload['status']}")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "lease_token": "lease-current",
            **payload,
        },
        headers=_auth(token),
    )

    assert response.status_code == 400
