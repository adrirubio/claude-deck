"""P01 disposable read fixtures, with no application lifespan or live boundaries."""
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, GithubApprovalRequest,
    GithubAttemptScopeRevision, GithubWorkItem, GithubWorkspace, MailAgentSession,
    MailTeamMember, TeamGithubScope,
)
from app.config import settings
from app.models.factory_schemas import RuntimeObservation
from app.services import factory_projection_service as projection


NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
PRIVATE = "synthetic-private-forbidden"


def pytest_addoption(parser):
    parser.addoption("--freeze-factory-fixtures", action="store_true",
                     help="Write the disposable schema-v1 API contract fixtures.")


@pytest_asyncio.fixture
async def factory_store(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'factory.db'}")
    statements = []

    @event.listens_for(engine.sync_engine, "connect")
    def configure(conn, _):
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_queries(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    moment = NOW.replace(tzinfo=None)
    monkeypatch.setattr(projection, "utc_now", lambda: NOW)
    monkeypatch.setattr(settings, "github_dispatch_interval_seconds", 60)
    monkeypatch.setattr(settings, "operator_token", "synthetic-factory-operator")
    monkeypatch.setattr(settings, "github_recovery_only_attempt", "")
    async with maker() as db:
        teams = [AgentTeamPreset(name=f"Fixture team {n}", autonomy_enabled=True) for n in (1, 2)]
        db.add_all(teams)
        await db.flush()
        scopes = [TeamGithubScope(preset_id=t.id, repo_owner="fixture", repo_name="shared",
                                  repo_path=f"/private/{PRIVATE}", dispatch_label="ready",
                                  continuation_enabled=True, build_command_hint=PRIVATE,
                                  last_polled_at=moment if n == 0 else None,
                                  created_at=moment, updated_at=moment)
                  for n, t in enumerate(teams)]
        scopes.append(TeamGithubScope(preset_id=teams[0].id, repo_owner="fixture", repo_name="paused",
                                     repo_path=f"/private/{PRIVATE}", enabled=False,
                                     created_at=moment, updated_at=moment))
        db.add_all(scopes)
        await db.flush()
        owners, leaders, members = [], [], []
        for n, team in enumerate(teams):
            pair = [AgentTeamSlot(preset_id=team.id, position=position,
                                  display_name="Leader" if position == 0 else "Owner",
                                  provider="claude-code" if position == 0 else "codex-cli",
                                  repo_id="fixture", repo_name="shared", repo_path=f"/private/{PRIVATE}",
                                  launch_options={"prompt": PRIVATE}) for position in (0, 1)]
            db.add_all(pair)
            await db.flush()
            leaders.append(pair[0]); owners.append(pair[1])
            for slot in pair:
                member = MailTeamMember(identity_key=f"fixture-slot-{slot.id}", repo_id="fixture",
                    repo_name="shared", repo_path=f"/private/{PRIVATE}", display_name=slot.display_name,
                    participant_kind="team_slot", team_preset_id=team.id, team_slot_id=slot.id)
                db.add(member)
                await db.flush()
                members.append(member)
                session = MailAgentSession(member_id=member.id, source="mcp", provider=slot.provider,
                    session_key=f"fixture-mcp-{slot.id}", team_preset_id=team.id, team_slot_id=slot.id,
                    capability_token_hash=PRIVATE, mailbox_status="connected" if slot.position else "offline",
                    closed_at=None if slot.position else moment, last_seen_at=moment,
                    bound_pane_pid=1000 + slot.id, bound_pane_proc_start=f"start-{slot.id}")
                db.add(session)
                db.add(AgentPaneBinding(preset_id=team.id, slot_id=slot.id, pane_pid=1000 + slot.id,
                                       pane_proc_start=f"start-{slot.id}", tmux_target=PRIVATE))
        statuses = tuple(projection.STATUS_CATEGORY) + ("future_status",)
        items = []
        for i in range(132):
            scope = scopes[i % 2] if i < 131 else scopes[2]
            item = GithubWorkItem(scope_id=scope.id, issue_number=i + 1, issue_title=f"Fixture issue {i + 1}",
                issue_url=f"https://untrusted.example/{PRIVATE}", github_updated_at=moment,
                dispatch_status=statuses[i % len(statuses)], owner_slot_id=owners[i % 2 if i < 131 else 0].id if i % 7 else None,
                dispatch_nonce=PRIVATE, dispatch_head_ref=PRIVATE, status_note=PRIVATE,
                diagnostic_last_verified_sha=PRIVATE, created_at=moment, updated_at=moment)
            items.append(item)
        db.add_all(items)
        await db.flush()
        by_status = {status: next(i for i in items if i.dispatch_status == status) for status in statuses}
        dispatched = by_status["dispatched"]
        db.add(GithubApprovalRequest(work_item_id=dispatched.id, request_kind="initial_plan", dispatch_nonce=PRIVATE,
            approval_round=1, owner_member_id=members[3].id, leader_member_id=members[2].id,
            request_fingerprint=PRIVATE, status="pending", reason=PRIVATE))
        escalated = by_status["escalated"]
        escalated.escalation_reason = "abandoned_by_operator"
        workspace = GithubWorkspace(scope_id=escalated.scope_id, path=f"/private/{PRIVATE}",
                                    leased_item_id=escalated.id, lease_token=PRIVATE, leased_at=moment)
        db.add(workspace)
        await db.flush()
        escalated.active_scope_revision = 1
        escalated.pr_number = 123
        revision = GithubAttemptScopeRevision(work_item_id=escalated.id, dispatch_nonce=PRIVATE,
            revision=1, owner_slot_id=owners[1].id, owner_member_id=members[3].id,
            phase="diagnostic", execution_target=PRIVATE, summary=PRIVATE, allowed_paths=[PRIVATE],
            allowed_actions=[], allowed_commands=[PRIVATE], prohibited_actions=[], tool_fallbacks={},
            baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40, originating_escalation_reason="fixture",
            expected_workspace_id=workspace.id, expected_lease_token_hash=PRIVATE, max_failed_heads=1,
            status="active", evidence={"private": PRIVATE})
        db.add(revision)
        await db.commit()
        ids = SimpleNamespace(teams=[t.id for t in teams], scopes=[s.id for s in scopes],
            owners=[s.id for s in owners], leaders=[s.id for s in leaders], members=[m.id for m in members],
            items=[i.id for i in items], by_status={s: i.id for s, i in by_status.items()},
            workspace=workspace.id, revision=revision.id)
    job_ids = frozenset(projection.github_dispatch_scheduler._job_id(s.repo_owner, s.repo_name) for s in scopes)
    runtime = projection.RuntimeSnapshot(RuntimeObservation(mode="normal", scheduler_state="running",
        observed_at=NOW.replace(minute=59, hour=11), reason_code=None), job_ids)
    monkeypatch.setattr(projection, "observe_runtime", lambda: runtime)
    try:
        yield SimpleNamespace(maker=maker, engine=engine, ids=ids, statements=statements, runtime=runtime)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def factory_client(factory_store):
    async def override():
        async with factory_store.maker() as db:
            try:
                yield db
            finally:
                await db.rollback()

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
