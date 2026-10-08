"""V33: disposable, FK-enforced state/API/rollback and real SQLite writer races."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import agent_teams
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamLaunch, AgentTeamPreset, AgentTeamSlot, GithubApprovalRequest,
    GithubAttemptScopeRevision, GithubWorkItem, GithubWorkspace, MailAgentSession,
    MailTeamMember, TeamGithubScope,
)
from app.services.agent_team_service import TeamDeletionConflictError, agent_team_service


pytestmark = pytest.mark.asyncio
PRIVATE = "synthetic-private-sentinel"
OPERATOR = "synthetic-deletion-fixture-operator"


@pytest_asyncio.fixture
async def fixture_store(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deletion.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def configure(conn, _):
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=100")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(settings, "github_recovery_only_attempt", "")
    monkeypatch.setattr(settings, "operator_token", OPERATOR)
    monkeypatch.setattr(agent_teams, "_sync_github_jobs", AsyncMock())

    async with maker() as db:
        preset = AgentTeamPreset(name="Disposable deletion team")
        db.add(preset)
        await db.flush()
        slot = AgentTeamSlot(preset_id=preset.id, display_name="Fixture worker",
                             provider="codex-cli", repo_id="fixture", repo_name="fixture",
                             repo_path=f"/private/{PRIVATE}")
        scope = TeamGithubScope(preset_id=preset.id, repo_owner="fixture", repo_name="one",
                                repo_path=f"/private/{PRIVATE}")
        other_scope = TeamGithubScope(preset_id=preset.id, repo_owner="fixture", repo_name="two",
                                      repo_path=f"/private/{PRIVATE}")
        db.add_all([slot, scope, other_scope])
        await db.flush()
        member = MailTeamMember(identity_key="fixture-slot", repo_id="fixture", repo_name="fixture",
                                repo_path=f"/private/{PRIVATE}", display_name="Fixture worker",
                                participant_kind="team_slot", team_preset_id=preset.id,
                                team_slot_id=slot.id)
        repo_member = MailTeamMember(identity_key="fixture-repo", repo_id="fixture", repo_name="fixture",
                                     repo_path=f"/private/{PRIVATE}", display_name="Fixture repository")
        item = GithubWorkItem(scope_id=other_scope.id, issue_number=1, issue_title=PRIVATE,
                              issue_url="https://github.com/fixture/two/issues/1",
                              github_updated_at=datetime.utcnow(), dispatch_status="merged",
                              status_note=PRIVATE, dispatch_nonce=PRIVATE, owner_slot_id=slot.id)
        workspace = GithubWorkspace(scope_id=other_scope.id, path=f"/private/{PRIVATE}")
        launch = AgentTeamLaunch(preset_id=preset.id, plan_hash="fixture-plan")
        db.add_all([member, repo_member, item, workspace, launch])
        await db.flush()
        session = MailAgentSession(member_id=member.id, session_key="fixture-session", source="mcp",
                                    team_preset_id=preset.id, team_slot_id=slot.id,
                                    cwd=f"/private/{PRIVATE}", capability_token_hash=PRIVATE)
        db.add(session)
        await db.commit()
        ids = SimpleNamespace(preset=preset.id, slot=slot.id, scope=scope.id,
                              other_scope=other_scope.id, item=item.id, workspace=workspace.id,
                              member=member.id, repo_member=repo_member.id, session=session.id)

    async def fake_repo_member(db, _cwd):
        return await db.get(MailTeamMember, ids.repo_member)

    monkeypatch.setattr("app.services.agent_team_service.agent_mail_service.get_or_create_repo_member",
                        fake_repo_member)
    try:
        yield maker, ids
    finally:
        await engine.dispose()


def approval(ids, status="pending"):
    return GithubApprovalRequest(work_item_id=ids.item, request_kind="initial_plan",
                                 dispatch_nonce=PRIVATE, approval_round=1,
                                 owner_member_id=ids.member, leader_member_id=ids.repo_member,
                                 request_fingerprint=PRIVATE, status=status, reason=PRIVATE)


def revision(ids, status="active"):
    return GithubAttemptScopeRevision(
        work_item_id=ids.item, owner_slot_id=ids.slot, owner_member_id=ids.member,
        dispatch_nonce=PRIVATE, revision=1, phase="implementation", execution_target="fixture",
        summary=PRIVATE, allowed_paths=[], allowed_actions=[], allowed_commands=[],
        prohibited_actions=[], tool_fallbacks={}, baseline_head_sha="a" * 40,
        baseline_tree_sha="b" * 40, originating_escalation_reason="fixture",
        expected_workspace_id=ids.workspace, expected_lease_token_hash=PRIVATE,
        max_failed_heads=1, status=status,
    )


async def seed_blocker(db, ids, case):
    kind, _, state = case.partition(":")
    if kind == "automation":
        await db.execute(update(AgentTeamPreset).where(AgentTeamPreset.id == ids.preset)
                         .values(autonomy_enabled=True))
    elif kind == "work_item":
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == ids.item)
                         .values(dispatch_status=state))
    elif kind == "approval":
        db.add(approval(ids, state))
    elif kind == "revision":
        db.add(revision(ids, state))
    elif kind == "workspace":
        values = {
            "item": {"leased_item_id": ids.item}, "token": {"lease_token": PRIVATE},
            "pid": {"leased_owner_pid": 123}, "proc": {"leased_owner_proc_start": PRIVATE},
            "push": {"push_token_expires_at": datetime.utcnow()},
            "time": {"leased_at": datetime.utcnow()},
        }[state]
        await db.execute(update(GithubWorkspace).where(GithubWorkspace.id == ids.workspace).values(**values))
    else:
        raise AssertionError(case)


async def snapshot(maker):
    # Compare all persisted fields, including sessions and private authority,
    # rather than merely asserting a conflict exception.
    async with maker() as db:
        return {table.name: (await db.execute(select(table).order_by(*table.primary_key.columns))).all()
                for table in Base.metadata.tables.values()}


STATE_CASES = (
    ["automation"]
    + [f"work_item:{s}" for s in ("pending", "dispatched", "verifying", "ready_for_review",
                                 "awaiting_human_review", "escalated", "failed", "future_state")]
    + [f"approval:{s}" for s in ("pending", "future_state")]
    + [f"revision:{s}" for s in ("proposed", "approved", "active", "submitted", "future_state")]
    + [f"workspace:{s}" for s in ("item", "token", "pid", "proc", "push", "time")]
)


@pytest.mark.parametrize("case", STATE_CASES)
async def test_service_refusal_preserves_entire_team(fixture_store, case):
    maker, ids = fixture_store
    async with maker() as db:
        await seed_blocker(db, ids, case)
        await db.commit()
    before = await snapshot(maker)
    async with maker() as db:
        with pytest.raises(TeamDeletionConflictError) as refused:
            await agent_team_service.delete_preset(db, ids.preset)
        assert refused.value.block_code == "team_in_use"
        assert any(b["kind"] == case.partition(":")[0] for b in refused.value.blockers)
        assert PRIVATE not in json.dumps(refused.value.blockers)
        assert not db.in_transaction()
    assert await snapshot(maker) == before


@pytest.mark.parametrize("case", STATE_CASES)
async def test_api_safe_409_preserves_team_and_does_not_sync(fixture_store, case):
    maker, ids = fixture_store
    async with maker() as db:
        await seed_blocker(db, ids, case)
        await db.commit()
    before = await snapshot(maker)
    async with api_client(maker) as client:
        response = await client.delete(f"/api/v1/agent-teams/presets/{ids.preset}")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["block_code"] == "team_in_use"
    assert 0 < len(detail["message"]) < 300
    assert PRIVATE not in response.text
    assert any(b["kind"] == case.partition(":")[0] for b in detail["blockers"])
    assert all(set(b) == {"kind", "id", "scope_id", "href"} for b in detail["blockers"])
    assert all(b["href"].startswith("/api/v1/agent-teams/") for b in detail["blockers"])
    agent_teams._sync_github_jobs.assert_not_awaited()
    assert await snapshot(maker) == before


@asynccontextmanager
async def api_client(maker, token=OPERATOR):
    async def override_db():
        async with maker() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture",
                                     headers={"X-Deck-Operator-Token": token} if token else {}) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("status", ("merged", "completed"))
@pytest.mark.parametrize("authority", ("none", "approved", "rejected", "superseded", "expired",
                                        "revision_completed", "revision_exhausted", "revision_rejected",
                                        "revision_superseded", "revision_expired"))
async def test_safe_delete_cascades_and_reassigns_sessions(fixture_store, status, authority):
    maker, ids = fixture_store
    async with maker() as db:
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == ids.item)
                         .values(dispatch_status=status))
        if authority.startswith("revision_"):
            db.add(revision(ids, authority.removeprefix("revision_")))
        elif authority != "none":
            db.add(approval(ids, authority))
        # A fully released historical workspace is permitted.
        await db.execute(update(GithubWorkspace).where(GithubWorkspace.id == ids.workspace)
                         .values(leased_at=datetime.utcnow(), released_at=datetime.utcnow()))
        await db.commit()
        await agent_team_service.delete_preset(db, ids.preset)
    async with maker() as db:
        for model in (AgentTeamPreset, AgentTeamSlot, AgentTeamLaunch, TeamGithubScope,
                      GithubWorkItem, GithubWorkspace, GithubApprovalRequest, GithubAttemptScopeRevision):
            assert (await db.execute(select(model))).scalars().all() == []
        session = await db.get(MailAgentSession, ids.session)
        assert session.member_id == ids.repo_member
        assert session.team_preset_id is None
        assert session.team_slot_id is None
        assert session.capability_token_hash == PRIVATE
        assert (await db.execute(text("PRAGMA foreign_key_check"))).all() == []


async def test_api_success_and_missing_preserve_existing_contract(fixture_store):
    maker, ids = fixture_store
    async with api_client(maker) as client:
        response = await client.delete(f"/api/v1/agent-teams/presets/{ids.preset}")
        assert response.status_code == 204
        assert response.content == b""
        response = await client.delete(f"/api/v1/agent-teams/presets/{ids.preset}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Agent team preset not found"
    agent_teams._sync_github_jobs.assert_awaited_once()


@pytest.mark.parametrize("token", (None, "synthetic-wrong-operator"))
async def test_api_operator_auth_still_precedes_deletion(fixture_store, token):
    maker, ids = fixture_store
    before = await snapshot(maker)
    async with api_client(maker, token) as client:
        response = await client.delete(f"/api/v1/agent-teams/presets/{ids.preset}")
    assert response.status_code in (401, 403)
    assert await snapshot(maker) == before
    agent_teams._sync_github_jobs.assert_not_awaited()


@pytest.mark.parametrize("failure_stage", ("sessions", "cascade"))
async def test_failure_after_safe_check_rolls_back_every_write(fixture_store, monkeypatch, failure_stage):
    maker, ids = fixture_store
    before = await snapshot(maker)
    original = agent_team_service._move_sessions_to_repo_members

    async def fail_after_sessions(db, condition):
        await original(db, condition)
        await db.flush()
        raise RuntimeError("synthetic session migration failure")

    if failure_stage == "sessions":
        monkeypatch.setattr(agent_team_service, "_move_sessions_to_repo_members", fail_after_sessions)
    else:
        async with maker() as db:
            await db.execute(text("CREATE TRIGGER refuse_team_delete BEFORE DELETE ON agent_team_presets "
                                  "BEGIN SELECT RAISE(ABORT, 'synthetic cascade failure'); END"))
            await db.commit()
    async with maker() as db:
        with pytest.raises((RuntimeError, IntegrityError)):
            await agent_team_service.delete_preset(db, ids.preset)
        assert not db.in_transaction()
    assert await snapshot(maker) == before


async def test_cached_preset_cannot_hide_new_automation(fixture_store):
    maker, ids = fixture_store
    async with maker() as reader, maker() as writer:
        cached = await reader.get(AgentTeamPreset, ids.preset)
        assert not cached.autonomy_enabled
        await writer.execute(update(AgentTeamPreset).where(AgentTeamPreset.id == ids.preset)
                             .values(autonomy_enabled=True))
        await writer.commit()
        with pytest.raises(TeamDeletionConflictError):
            await agent_team_service.delete_preset(reader, ids.preset)
    async with maker() as db:
        assert (await db.get(AgentTeamPreset, ids.preset)).autonomy_enabled


async def test_stale_wal_read_transaction_cannot_upgrade_and_delete_new_work(fixture_store):
    maker, ids = fixture_store
    async with maker() as reader, maker() as writer:
        await reader.execute(text("BEGIN"))
        assert (await reader.get(GithubWorkItem, ids.item)).dispatch_status == "merged"
        await seed_blocker(writer, ids, "work_item:dispatched")
        await writer.commit()
        with pytest.raises(TeamDeletionConflictError) as exc:
            await agent_team_service.delete_preset(reader, ids.preset)
        assert exc.value.block_code == "team_deletion_state_busy"
        assert not reader.in_transaction()
    async with maker() as db:
        assert await db.get(AgentTeamPreset, ids.preset) is not None
        assert (await db.get(GithubWorkItem, ids.item)).dispatch_status == "dispatched"


async def test_unflushed_automation_is_guarded_and_rolled_back(fixture_store):
    maker, ids = fixture_store
    before = await snapshot(maker)
    async with maker() as db:
        preset = await db.get(AgentTeamPreset, ids.preset)
        preset.autonomy_enabled = True
        with pytest.raises(TeamDeletionConflictError):
            await agent_team_service.delete_preset(db, ids.preset)
    assert await snapshot(maker) == before


@pytest.mark.parametrize("setting", ("target", "invalid", "unrelated"))
async def test_recovery_authority_fails_closed_without_private_target(fixture_store, monkeypatch, setting):
    maker, ids = fixture_store
    gate = f"{ids.other_scope}:1:99:0123456789abcdef:private-recovery-head"
    if setting == "invalid":
        gate = PRIVATE
    elif setting == "unrelated":
        gate = "999:1:99:0123456789abcdef:private-recovery-head"
    monkeypatch.setattr(settings, "github_recovery_only_attempt", gate)
    before = await snapshot(maker)
    async with maker() as db:
        if setting == "unrelated":
            await agent_team_service.delete_preset(db, ids.preset)
            return
        with pytest.raises(TeamDeletionConflictError) as exc:
            await agent_team_service.delete_preset(db, ids.preset)
        assert "private-recovery-head" not in json.dumps(exc.value.blockers)
        assert "0123456789abcdef" not in json.dumps(exc.value.blockers)
    assert await snapshot(maker) == before


async def test_unsupported_protection_is_safe409(fixture_store, monkeypatch):
    maker, ids = fixture_store
    before = await snapshot(maker)
    # Simulate a dialect for which child-insert serialization is not proven.
    async with maker() as db:
        monkeypatch.setattr(db, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="other")))
        with pytest.raises(TeamDeletionConflictError) as exc:
            await agent_team_service.delete_preset(db, ids.preset)
        assert exc.value.block_code == "team_deletion_protection_unavailable"
        assert exc.value.blockers == []
    assert await snapshot(maker) == before


RACE_CASES = ("automation", "work_item:dispatched", "workspace:token", "approval:pending", "revision:active")


@pytest.mark.parametrize("case", RACE_CASES)
async def test_competing_writer_acquisition_before_guard_is_preserved(fixture_store, case):
    maker, ids = fixture_store
    async with maker() as writer, maker() as deleter:
        await writer.execute(text("BEGIN IMMEDIATE"))
        await seed_blocker(writer, ids, case)
        await writer.flush()
        # A separate physical connection must fail closed while acquisition
        # owns the writer reservation; it may not cascade uncommitted work.
        with pytest.raises(TeamDeletionConflictError) as exc:
            await agent_team_service.delete_preset(deleter, ids.preset)
        assert exc.value.block_code == "team_deletion_state_busy"
        assert exc.value.blockers == []
        await writer.commit()
    before = await snapshot(maker)
    async with maker() as db:
        with pytest.raises(TeamDeletionConflictError) as exc:
            await agent_team_service.delete_preset(db, ids.preset)
        assert exc.value.block_code == "team_in_use"
    assert await snapshot(maker) == before


@pytest.mark.parametrize("case", RACE_CASES)
async def test_acquisition_cannot_slip_between_guard_and_cascade(fixture_store, monkeypatch, case):
    maker, ids = fixture_store
    guarded = asyncio.Event()
    finish = asyncio.Event()
    original = agent_team_service._guard_preset_deletion

    async def pause_after_guard(db, preset):
        await original(db, preset)
        guarded.set()
        await asyncio.wait_for(finish.wait(), 3)

    monkeypatch.setattr(agent_team_service, "_guard_preset_deletion", pause_after_guard)
    async with maker() as deleter, maker() as writer:
        deletion = asyncio.create_task(agent_team_service.delete_preset(deleter, ids.preset))
        await asyncio.wait_for(guarded.wait(), 3)
        try:
            # The writer must be locked out even after the predicate passed.
            with pytest.raises(OperationalError):
                await seed_blocker(writer, ids, case)
                await writer.flush()
            await writer.rollback()
        finally:
            finish.set()
            await deletion
        assert await writer.get(AgentTeamPreset, ids.preset) is None
        # After deletion a stale acquisition cannot resurrect dependent rows.
        if case.startswith("approval") or case.startswith("revision"):
            with pytest.raises(IntegrityError):
                await seed_blocker(writer, ids, case)
                await writer.flush()
            await writer.rollback()
        else:
            result = await writer.execute(update(GithubWorkItem).where(GithubWorkItem.id == ids.item)
                                          .values(dispatch_status="dispatched"))
            assert result.rowcount == 0
            await writer.rollback()


async def test_busy_api_returns_safe409_without_sync(fixture_store):
    maker, ids = fixture_store
    async with maker() as writer:
        await writer.execute(text("BEGIN IMMEDIATE"))
        async with api_client(maker) as client:
            response = await client.delete(f"/api/v1/agent-teams/presets/{ids.preset}")
        assert response.status_code == 409
        assert response.json()["detail"]["block_code"] == "team_deletion_state_busy"
        assert response.json()["detail"]["blockers"] == []
        assert PRIVATE not in response.text
        await writer.rollback()
    agent_teams._sync_github_jobs.assert_not_awaited()
