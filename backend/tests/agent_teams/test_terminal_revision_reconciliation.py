"""Terminal revision maintenance preserves attempt authority and delivery evidence."""
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.models.database import (
    AgentTeamPreset, AgentTeamSlot, FactoryAuditEvent, GithubAttemptScopeRevision,
    GithubWorkItem, GithubWorkspace, MailTeamMember, TeamGithubScope,
)
from app.services.github_watcher_service import github_watcher_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def seed(db, *, item_status="merged", revision_status="active", current=True):
    preset = AgentTeamPreset(name="Test", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="test", repo_name="test", repo_path="/test")
    slot = AgentTeamSlot(preset_id=preset.id, position=0, display_name="Owner", provider="codex-cli",
                         repo_id="test", repo_path="/test", repo_name="test")
    db.add_all([scope, slot])
    await db.flush()
    member = MailTeamMember(identity_key=f"test:{slot.id}", display_name="Owner", repo_id="test",
                            repo_path="/test", repo_name="test", participant_kind="team_slot",
                            team_preset_id=preset.id, team_slot_id=slot.id)
    item = GithubWorkItem(scope_id=scope.id, issue_number=492, issue_title="Test", issue_url="test",
                          github_updated_at=datetime.utcnow(), dispatch_status=item_status,
                          dispatch_nonce="synthetic-current-attempt", active_scope_revision=1,
                          owner_slot_id=slot.id, attempt_phase="implementation", retry_count=2)
    db.add_all([member, item])
    await db.flush()
    workspace = GithubWorkspace(scope_id=scope.id, path=f"/test/{item.id}", leased_item_id=item.id,
                                 lease_token="synthetic-lease")
    db.add(workspace)
    await db.flush()
    revision = GithubAttemptScopeRevision(
        work_item_id=item.id, dispatch_nonce=item.dispatch_nonce if current else "synthetic-old-attempt",
        revision=1, owner_slot_id=slot.id, owner_member_id=member.id, phase="implementation",
        execution_target="workspace", summary="Test", allowed_paths=["test.py"], allowed_actions=[],
        allowed_commands=[], prohibited_actions=[], tool_fallbacks={}, baseline_head_sha="baseline",
        baseline_tree_sha="tree", originating_escalation_reason="test", expected_workspace_id=workspace.id,
        expected_lease_token_hash="synthetic-hash", max_failed_heads=3, failed_head_count=2,
        status=revision_status,
    )
    db.add(revision)
    await db.commit()
    return scope, item, revision, workspace


@pytest.mark.asyncio
async def test_issue_closure_completes_current_revision_without_proving_delivery(db):
    scope, item, revision, workspace = await seed(db, item_status="dispatched")
    await github_watcher_service._complete_and_notify(
        db, scope, item, issue={"state": "closed", "closed_at": "2026-10-13T01:00:00Z"})
    await db.refresh(item)
    await db.refresh(revision)
    assert item.dispatch_status == "completed"
    assert revision.status == "completed"
    assert revision.completed_at is not None
    assert revision.failed_head_count == 2
    assert item.retry_count == 2
    assert workspace.leased_item_id == item.id
    facts = (await db.scalars(select(FactoryAuditEvent).where(
        FactoryAuditEvent.event_kind == "delivery_evidence"))).all()
    assert len(facts) == 1
    assert facts[0].delivery_outcome == "unknown"


@pytest.mark.asyncio
async def test_terminal_report_is_read_only_and_excludes_private_authority(db):
    from app.services.github_terminal_revision_service import terminal_revision_report
    scope, item, revision, _workspace = await seed(db)
    before = await db.scalar(select(func.count()).select_from(FactoryAuditEvent))
    report = await terminal_revision_report(db, scope.preset_id)
    assert report["truncated"] is False
    row = report["revisions"][0]
    assert row["work_item_id"] == item.id
    assert row["revision_id"] == revision.id
    assert row["current_attempt"] is True
    assert row["proposed_status"] == "completed"
    assert len(row["context_sha256"]) == 64
    assert "synthetic-current-attempt" not in str(report)
    assert "synthetic-lease" not in str(report)
    assert revision.status == "active"
    assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("current,status,outcome", [(True,"active","completed"),
    (True,"submitted","completed"), (True,"approved","superseded"), (False,"active","superseded")])
async def test_operator_reconciles_only_selected_revision_and_records_actor(db, current, status, outcome):
    from app.services.github_terminal_revision_service import terminal_revision_report, reconcile_terminal_revision
    scope, item, revision, workspace = await seed(db, current=current, revision_status=status)
    row = (await terminal_revision_report(db, scope.preset_id))["revisions"][0]
    result = await reconcile_terminal_revision(db, item, revision.id, row["context_sha256"],
                                              "test-reconcile", "Inspect the terminal item.")
    assert result["status"] == "reconciled"
    await db.refresh(revision)
    await db.refresh(item)
    assert revision.status == outcome
    assert revision.failed_head_count == 2
    assert item.retry_count == 2
    assert item.dispatch_status == "merged"
    assert workspace.leased_item_id == item.id
    events = (await db.scalars(select(FactoryAuditEvent))).all()
    assert len(events) == 1
    assert events[0].event_kind == "revision_outcome"
    assert events[0].actor_kind == "operator"
    assert events[0].delivery_outcome is None
    repeated = await reconcile_terminal_revision(db, item, revision.id, row["context_sha256"],
                                                "test-reconcile", "Inspect the terminal item.")
    assert repeated["status"] == "already_reconciled"
    assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["retry", "nonce", "status", "revision"])
async def test_reconcile_refuses_changed_context(db, change):
    from app.services.github_terminal_revision_service import terminal_revision_report, reconcile_terminal_revision
    scope, item, revision, _workspace = await seed(db)
    row = (await terminal_revision_report(db, scope.preset_id))["revisions"][0]
    if change == "revision":
        await db.execute(update(GithubAttemptScopeRevision).where(GithubAttemptScopeRevision.id == revision.id)
                         .values(failed_head_count=3).execution_options(synchronize_session=False))
    else:
        values = {"retry": {"retry_count": 3}, "nonce": {"dispatch_nonce": "synthetic-new-attempt"},
                  "status": {"dispatch_status": "dispatched"}}[change]
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(**values)
                         .execution_options(synchronize_session=False))
    await db.commit()
    with pytest.raises(ValueError, match="terminal_revision_context_changed"):
        await reconcile_terminal_revision(db, item, revision.id, row["context_sha256"], "test-stale", "Inspect.")
    await db.rollback()
    await db.refresh(revision)
    assert revision.status == "active"
    assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == 0


@pytest.mark.asyncio
async def test_reconcile_audit_failure_rolls_back_revision(db, monkeypatch):
    from app.services import factory_audit_service as audit
    from app.services.github_terminal_revision_service import terminal_revision_report, reconcile_terminal_revision
    scope, item, revision, _workspace = await seed(db)
    row = (await terminal_revision_report(db, scope.preset_id))["revisions"][0]
    async def failed(*_args, **_kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(audit, "record_revision_outcome", failed)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        await reconcile_terminal_revision(db, item, revision.id, row["context_sha256"], "test-fail", "Inspect.")
    await db.rollback()
    await db.refresh(revision)
    assert revision.status == "active"


@pytest.mark.asyncio
async def test_reconcile_replay_refuses_a_different_request(db):
    from app.services.github_terminal_revision_service import terminal_revision_report, reconcile_terminal_revision
    scope, item, revision, _workspace = await seed(db)
    row = (await terminal_revision_report(db, scope.preset_id))["revisions"][0]
    await reconcile_terminal_revision(db, item, revision.id, row["context_sha256"], "test-repeat", "Inspect.")
    with pytest.raises(ValueError, match="terminal_revision_replay_conflict"):
        await reconcile_terminal_revision(db, item, revision.id, row["context_sha256"], "test-repeat", "Different.")
    assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == 1


@pytest.mark.asyncio
async def test_report_is_bounded_and_does_not_modify_old_attempts(db):
    from app.services.github_terminal_revision_service import terminal_revision_report
    scope, item, revision, _workspace = await seed(db)
    columns = [c.name for c in GithubAttemptScopeRevision.__table__.columns if c.name not in {"id", "created_at"}]
    values = {name:getattr(revision,name) for name in columns}
    for number in range(2, 103):
        db.add(GithubAttemptScopeRevision(**{**values, "revision":number}))
    await db.commit()
    report = await terminal_revision_report(db, scope.preset_id)
    assert len(report["revisions"]) == 100
    assert report["truncated"] is True
    assert await db.scalar(select(func.count()).select_from(GithubAttemptScopeRevision)
                           .where(GithubAttemptScopeRevision.status == "active")) == 102


@pytest.mark.asyncio
async def test_foreign_revision_cannot_be_reconciled(db):
    from app.services.github_terminal_revision_service import terminal_revision_report, reconcile_terminal_revision
    scope, item, _revision, _workspace = await seed(db)
    other_scope, _other_item, foreign, _other_workspace = await seed(db)
    row = (await terminal_revision_report(db, other_scope.preset_id))["revisions"][0]
    with pytest.raises(ValueError, match="terminal_revision_context_changed"):
        await reconcile_terminal_revision(db, item, foreign.id, row["context_sha256"], "test-foreign", "Inspect.")
    await db.rollback()
    await db.refresh(foreign)
    assert foreign.status == "active"
    assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == 0


@pytest.mark.asyncio
async def test_changed_attempt_cannot_complete_from_a_stale_merge_object(db):
    from app.services.github_terminal_revision_service import TerminalRevisionContextChanged
    from app.services.github_verification_service import github_verification_service
    _scope, item, revision, _workspace = await seed(db, item_status="ready_for_review")
    await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id)
                     .values(dispatch_nonce="synthetic-new-attempt").execution_options(synchronize_session=False))
    await db.commit()
    with pytest.raises(TerminalRevisionContextChanged):
        await github_verification_service._mark_merged_with_fact(db, item, {"number":5}, source="test-stale")
    await db.rollback()
    await db.refresh(item)
    await db.refresh(revision)
    assert item.dispatch_status == "ready_for_review"
    assert revision.status == "active"
    assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["item", "revision"])
async def test_reconciliation_refuses_a_concurrent_committed_change(tmp_path, monkeypatch, change):
    from app.services.github_terminal_revision_service import terminal_revision_report, reconcile_terminal_revision
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'terminal.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine,expire_on_commit=False)
    async with maker() as db:
        scope, item, revision, _workspace = await seed(db)
        row = (await terminal_revision_report(db,scope.preset_id))["revisions"][0]
        item_id, revision_id = item.id, revision.id
        await db.commit()
        original_execute = db.execute
        changed = False
        async def execute(statement,*args,**kwargs):
            nonlocal changed
            if not changed and str(statement).startswith("UPDATE github_work_items"):
                changed = True
                async with maker() as other:
                    if change == "item":
                        await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == item_id)
                                             .values(pr_number=7))
                    else:
                        await other.execute(update(GithubAttemptScopeRevision)
                            .where(GithubAttemptScopeRevision.id == revision_id).values(failed_head_count=3))
                    await other.commit()
            return await original_execute(statement,*args,**kwargs)
        monkeypatch.setattr(db,"execute",execute)
        with pytest.raises(ValueError,match="terminal_revision_context_changed"):
            await reconcile_terminal_revision(db,item,revision_id,row["context_sha256"],"test-race","Inspect.")
        await db.rollback()
        await db.refresh(revision)
        assert changed
        assert revision.status == "active"
        assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_merge_revision_audit_failure_rolls_back_delivery_and_terminal_state(db, monkeypatch):
    from app.services import factory_audit_service as audit
    from app.services.github_verification_service import github_verification_service
    _scope, item, revision, _workspace = await seed(db, item_status="ready_for_review")
    async def failed(*_args, **_kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(audit,"record_revision_outcome",failed)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        await github_verification_service._mark_merged_with_fact(db,item,{"number":5},source="test-rollback")
    await db.rollback()
    await db.refresh(item)
    await db.refresh(revision)
    assert item.dispatch_status == "ready_for_review"
    assert revision.status == "active"
    assert await db.scalar(select(func.count()).select_from(FactoryAuditEvent)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "wrong", "synthetic-operator"])
async def test_maintenance_routes_require_operator_for_reads_and_writes(db, monkeypatch, header):
    from app.api.v1.factory_maintenance import router
    scope, item, revision, _workspace = await seed(db)
    monkeypatch.setattr(settings, "operator_token", "synthetic-operator")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/agent-teams")
    async def database():
        yield db
    app.dependency_overrides[get_db] = database
    headers = {"X-Deck-Operator-Token": header} if header else {}
    root = f"/api/v1/agent-teams/presets/{scope.preset_id}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        report = await client.get(root + "/terminal-revisions", headers=headers)
        expected = 200 if header == "synthetic-operator" else 401
        assert report.status_code == expected
        fingerprint = report.json()["revisions"][0]["context_sha256"] if expected == 200 else "a" * 64
        response = await client.post(root + f"/work-items/{item.id}/terminal-revisions/{revision.id}/reconcile",
            headers=headers, json={"operation_id":"test-api", "expected_context_sha256":fingerprint,
                                   "reason":"Inspect the terminal item."})
        assert response.status_code == expected
        if expected == 200:
            assert report.headers["cache-control"] == "no-store"
            assert response.headers["cache-control"] == "no-store"
        await db.refresh(revision)
        assert revision.status == ("completed" if expected == 200 else "active")
