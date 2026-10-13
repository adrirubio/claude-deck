"""Team summaries collect existing observations without adding authority."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubOwnerObservationPause, GithubWorkItem, TeamGithubScope
from app.models.github_work_progress_schemas import GithubPublicationObservation, GithubWorkProgressResponse, GithubWorkRemainingView
from app.services.agent_team_summary_service import AgentTeamSummaryService


@pytest_asyncio.fixture
async def db(tmp_path):
    # Timeout cancellation can discard a connection. A file preserves the store across that boundary.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'summary.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def seed(db, statuses=("dispatched",), *, enabled=True):
    team = AgentTeamPreset(name="Summary", description="Ship the release.",
                           parent_issue_url="https://github.com/example/repo/issues/506", autonomy_enabled=enabled)
    db.add(team)
    await db.flush()
    scope = TeamGithubScope(preset_id=team.id, repo_owner="example", repo_name="repo",
                            repo_path="/private/repo", enabled=enabled)
    db.add(scope)
    await db.flush()
    slot = AgentTeamSlot(preset_id=team.id, display_name="Owner", provider="codex-cli",
                         repo_path="/private/repo", repo_id="private", repo_name="repo",
                         bootstrap_prompt="private-launch-prompt", launch_options={"secret": "private-launch-option"})
    db.add(slot)
    await db.flush()
    items = []
    for n, status in enumerate(statuses, 1):
        item = GithubWorkItem(scope_id=scope.id, issue_number=n, issue_title="Item",
                              issue_url=f"https://github.com/example/repo/issues/{n}",
                              github_updated_at=datetime.utcnow(), dispatch_status=status,
                              owner_slot_id=slot.id, dispatch_nonce=f"private-nonce-{n}")
        db.add(item)
        items.append(item)
    await db.commit()
    return team, scope, items


def progress(item_id, *, low=10, high=20, actor="owner", state="current", expired=False, confidence="medium"):
    now = datetime.now(timezone.utc)
    return GithubWorkProgressResponse(work_item_id=item_id, dispatch_nonce="private-nonce", owner_slot_id=1,
        checked_at=now, valid_until=now + timedelta(seconds=-1 if expired else 15),
        phase="implementation", next_actor=actor, next_action="Continue the approved work.",
        publication=GithubPublicationObservation(state="current"),
        remaining_work=GithubWorkRemainingView(state=state, effort_low_minutes=low,
            effort_high_minutes=high, confidence=confidence, reason=None, reported_at=now))


class Progress:
    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []

    async def summary(self, db, item_id):
        self.calls.append(item_id)
        value = self.values.get(item_id, progress(item_id))
        if callable(value):
            return await value(db, item_id)
        return value


class Attention:
    async def summary(self, db, preset_id):
        return {"coverage_complete": True, "actions": [],
                "observation_expires_at": datetime.now(timezone.utc) + timedelta(seconds=60)}

    async def dispatch_snapshot(self, db, scopes):
        return {"complete": True, "actions": []}


def service(monkeypatch, values=None, attention=None, hold=None, **kwargs):
    monkeypatch.setattr("app.services.agent_team_summary_service.hold_code", lambda: hold)
    reads = Progress(values)
    return AgentTeamSummaryService(progress=reads, attention=attention or Attention(), **kwargs), reads


@pytest.mark.asyncio
async def test_empty_team_has_zero_effort_and_no_actor(db, monkeypatch):
    team, _, _ = await seed(db, ())
    summary, reads = service(monkeypatch)
    result = await summary.summary(db, team.id)
    assert result.description == "Ship the release."
    assert "outcome" not in type(result).model_fields
    assert "done_when" not in type(result).model_fields
    assert result.parent_issue_url.endswith("/issues/506")
    assert result.supervisor == "none"
    assert result.remaining_work.state == "known"
    assert result.remaining_work.effort_low_minutes == result.remaining_work.effort_high_minutes == 0
    assert result.next_actors == [] and result.next_actor_coverage_complete
    assert reads.calls == []


@pytest.mark.asyncio
async def test_team_ci_signal_has_safe_context_and_clears_without_authority_changes(db, monkeypatch):
    team, scope, items = await seed(db, ("verifying", "verifying", "merged"))
    team_id, scope_id, item_id = team.id, scope.id, items[0].id
    started = datetime.utcnow() - timedelta(minutes=16)
    items[0].checks_unavailable_since = started
    items[0].checks_unavailable_reason = "synthetic-private-error"
    items[1].checks_unavailable_since = datetime.utcnow()
    items[1].checks_unavailable_reason = "api_error"
    items[2].checks_unavailable_since = started
    await db.commit()
    summary, _ = service(monkeypatch)
    result = await summary.summary(db, team_id)
    assert result.attention == []
    assert len(result.required_ci_unreadable) == 1
    signal = result.required_ci_unreadable[0]
    assert (signal.work_item_id, signal.scope_id, signal.issue_number) == (item_id, scope_id, 1)
    assert signal.since == started.replace(tzinfo=timezone.utc)
    assert signal.reason == "unknown"
    public = result.model_dump_json()
    for private in ("synthetic-private-error", "private-nonce", "private-launch", "/private", "lease_token"):
        assert private not in public
    item = await db.get(GithubWorkItem, item_id)
    assert item.dispatch_status == "verifying" and item.retry_count == item.diagnostic_retry_count == 0
    item.checks_unavailable_since = item.checks_unavailable_reason = None
    await db.commit()
    assert (await summary.summary(db, team_id)).required_ci_unreadable == []
    assert (await db.get(TeamGithubScope, scope_id)).enabled


@pytest.mark.asyncio
async def test_active_team_sums_all_unfinished_items_and_preserves_actors(db, monkeypatch):
    team, _, items = await seed(db, ("dispatched", "verifying", "merged", "completed"))
    summary, reads = service(monkeypatch, {
        items[0].id: progress(items[0].id, confidence="low"),
        items[1].id: progress(items[1].id, low=30, high=60, actor="controller", confidence="high")})
    item_ids = [items[0].id, items[1].id]
    result = await summary.summary(db, team.id)
    assert result.remaining_work.effort_low_minutes == 40
    assert result.remaining_work.effort_high_minutes == 80
    assert result.remaining_work.unfinished_items == 2
    assert result.remaining_work.confidence == "low"
    assert set(result.next_actors) == {"owner", "controller"}
    assert reads.calls == item_ids
    public = result.model_dump_json()
    for private in ("private-nonce", "private-launch", "/private", "launch_options", "remaining_work_context", "lease_token"):
        assert private not in public


@pytest.mark.parametrize("failure", ["historical", "unavailable", "unknown", "expired", "missing"])
@pytest.mark.asyncio
async def test_one_unknown_item_keeps_the_whole_estimate_unknown(db, monkeypatch, failure):
    team, _, items = await seed(db, ("dispatched", "dispatched"))
    value = None if failure == "missing" else progress(items[1].id,
        state=failure if failure in {"historical", "unavailable"} else "current",
        low=None if failure == "unknown" else 10, high=None if failure == "unknown" else 20,
        expired=failure == "expired")
    summary, _ = service(monkeypatch, {items[1].id: value})
    result = await summary.summary(db, team.id)
    assert result.remaining_work.state == "unknown"
    assert result.remaining_work.effort_low_minutes is None
    assert result.remaining_work.effort_high_minutes is None


@pytest.mark.parametrize("hold", ["hold", "recovery_only", "hold_unavailable"])
@pytest.mark.asyncio
async def test_existing_hold_is_collected_without_changing_policy(db, monkeypatch, hold):
    team, scope, _ = await seed(db, ())
    team_id, scope_id = team.id, scope.id
    summary, _ = service(monkeypatch, hold=hold)
    result = await summary.summary(db, team.id)
    assert result.hold_code == hold
    assert result.next_actors == ["operator"]
    assert result.attention[0].code == hold
    assert (await db.get(TeamGithubScope, scope_id)).enabled
    assert (await db.get(AgentTeamPreset, team_id)).autonomy_enabled


@pytest.mark.asyncio
async def test_stopped_attempts_and_recorded_pauses_use_existing_signals(db, monkeypatch):
    team, _, items = await seed(db, ("escalated",))
    items[0].escalation_reason = "owner_observation_pause"
    pause = GithubOwnerObservationPause(work_item_id=items[0].id, wait_key="private-wait-key",
        authority_sha256="private-authority", status="paused", deadline=datetime.utcnow(),
        paused_at=datetime.utcnow(), resume_deadline=datetime.utcnow() + timedelta(minutes=15))
    db.add(pause)
    await db.commit()
    item_id, scope_id = items[0].id, items[0].scope_id
    class Existing(Attention):
        async def dispatch_snapshot(self, db, scopes):
            return {"complete": True, "actions": [{"kind": "inspect_checkpoint", "work_item_id": item_id,
                    "scope_id": scope_id, "issue_number": 1}]}
    summary, _ = service(monkeypatch, attention=Existing())
    result = await summary.summary(db, team.id)
    assert {a.code for a in result.attention} == {"recovery_decision", "observation_pause"}
    assert "private-wait-key" not in result.model_dump_json()
    await db.refresh(pause)
    assert pause.status == "paused"


@pytest.mark.asyncio
async def test_shared_time_limit_and_item_limit_keep_unknown_coverage(db, monkeypatch):
    team, _, items = await seed(db, ("dispatched", "dispatched"))
    async def slow(db, item_id):
        await asyncio.sleep(2)
    summary, reads = service(monkeypatch, {items[0].id: slow}, observation_seconds=0.5)
    item_id, team_id = items[0].id, team.id
    result = await summary.summary(db, team.id)
    assert result.remaining_work.state == "unknown"
    assert not result.next_actor_coverage_complete
    assert reads.calls == [item_id]
    summary, reads = service(monkeypatch, item_limit=1)
    result = await summary.summary(db, team_id)
    assert result.remaining_work.unfinished_items == 2
    assert result.remaining_work.state == "unknown"
    assert not result.coverage_complete and len(reads.calls) <= 1


@pytest.mark.asyncio
async def test_changed_context_invalidates_the_complete_total(db, monkeypatch):
    team, _, items = await seed(db)
    async def change(db, item_id):
        item = await db.get(GithubWorkItem, item_id)
        item.active_scope_revision += 1
        await db.commit()
        return progress(item_id)
    summary, _ = service(monkeypatch, {items[0].id: change})
    result = await summary.summary(db, team.id)
    assert result.remaining_work.state == "unknown"
    assert not result.next_actor_coverage_complete


@pytest.mark.asyncio
async def test_human_actions_preserve_pending_details_and_drop_private_fields(db, monkeypatch):
    team, _, _ = await seed(db, ())
    class Existing(Attention):
        async def summary(self, db, preset_id):
            return {"coverage_complete": False, "actions": [{"scope_id": 1, "issue_number": 1,
                "kind": "scope_clarification", "state": "context_pending", "source": "leader",
                "assessment_current": True, "dispatch_epoch": "private-epoch",
                "context_template": "private-prompt"}],
                "observation_expires_at": datetime.now(timezone.utc) + timedelta(seconds=60)}
    summary, _ = service(monkeypatch, attention=Existing())
    result = await summary.summary(db, team.id)
    assert result.human_actions[0].state == "context_pending"
    assert result.remaining_work.state == "unknown"
    assert result.next_actors == ["operator"]
    assert "private-" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_unknown_team_returns_none(db, monkeypatch):
    summary, _ = service(monkeypatch)
    assert await summary.summary(db, 999999) is None


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio
async def test_real_progress_preserves_paused_and_missing_workspace_actors(db, monkeypatch, enabled):
    from app.services.github_work_progress_service import GithubWorkProgressService
    team, scope, items = await seed(db, enabled=enabled)
    ids = team.id, scope.id, items[0].id
    monkeypatch.setattr("app.services.github_work_progress_service.hold_code", lambda: None)
    monkeypatch.setattr("app.services.agent_team_summary_service.hold_code", lambda: None)
    result = await AgentTeamSummaryService(progress=GithubWorkProgressService(), attention=Attention()).summary(db, team.id)
    assert result.next_actors == ["leader" if enabled else "operator"]
    assert result.remaining_work.state == "unknown"
    assert (await db.get(GithubWorkItem, ids[2])).dispatch_status == "dispatched"
    assert (await db.get(AgentTeamPreset, ids[0])).autonomy_enabled is enabled
    assert (await db.get(TeamGithubScope, ids[1])).enabled is enabled


@pytest.mark.parametrize(("status", "merge", "reason", "expected"), [
    ("escalated", "auto", "owner_idle_timeout", {"attempt_stopped", "owner_stalled"}),
    ("failed", "auto", None, {"attempt_stopped"}),
    ("ready_for_review", "auto", None, set()),
    ("ready_for_review", "human", None, {"human_review"}),
    ("awaiting_human_review", "auto", None, {"human_review"}),
])
@pytest.mark.asyncio
async def test_real_existing_attention_rules_are_collected(db, monkeypatch, status, merge, reason, expected):
    from app.services.github_operator_attention_service import GithubOperatorAttentionService
    team, scope, items = await seed(db, (status,))
    scope.merge_policy = merge
    items[0].escalation_reason = reason
    items[0].pr_number = 12
    await db.commit()
    class Existing(Attention):
        async def dispatch_snapshot(self, db, scopes):
            return await GithubOperatorAttentionService().dispatch_snapshot(db, scopes)
    summary, _ = service(monkeypatch, attention=Existing())
    result = await summary.summary(db, team.id)
    assert {signal.code for signal in result.attention} == expected


@pytest.mark.asyncio
async def test_deleted_team_during_read_returns_none(db, monkeypatch):
    from sqlalchemy import delete
    team, _, items = await seed(db)
    team_id = team.id
    async def change(db, item_id):
        await db.execute(delete(AgentTeamPreset).where(AgentTeamPreset.id == team_id))
        await db.commit()
        return progress(item_id)
    summary, _ = service(monkeypatch, {items[0].id: change})
    assert await summary.summary(db, team_id) is None


@pytest.mark.asyncio
async def test_observation_budget_is_shared_across_items(db, monkeypatch):
    team, _, items = await seed(db, ("dispatched", "dispatched"))
    async def delayed(db, item_id):
        await asyncio.sleep(0.3)
        return progress(item_id)
    summary, reads = service(monkeypatch, {item.id: delayed for item in items}, observation_seconds=0.5)
    result = await summary.summary(db, team.id)
    assert len(reads.calls) == 2
    assert result.remaining_work.reported_items == 1
    assert result.remaining_work.state == "unknown"
    assert not result.next_actor_coverage_complete


@pytest.mark.asyncio
async def test_more_than_64_items_cannot_produce_a_partial_total(db, monkeypatch):
    team, _, _ = await seed(db, ("dispatched",) * 65)
    summary, reads = service(monkeypatch)
    result = await summary.summary(db, team.id)
    assert result.remaining_work.unfinished_items == 65
    assert len(reads.calls) == 64
    assert result.remaining_work.state == "unknown"
    assert not result.coverage_complete


@pytest.mark.parametrize("age", [timedelta(hours=2, seconds=1), timedelta(minutes=-6)])
@pytest.mark.asyncio
async def test_report_age_is_rechecked_before_the_total(db, monkeypatch, age):
    team, _, items = await seed(db)
    value = progress(items[0].id)
    value.remaining_work.reported_at = datetime.now(timezone.utc) - age
    summary, _ = service(monkeypatch, {items[0].id: value})
    result = await summary.summary(db, team.id)
    assert result.remaining_work.state == "unknown"
    assert result.remaining_work.effort_low_minutes is None


@pytest.mark.asyncio
async def test_summary_expiry_cannot_outlive_a_current_report(db, monkeypatch):
    team, _, items = await seed(db)
    value = progress(items[0].id)
    value.remaining_work.reported_at = datetime.now(timezone.utc) - timedelta(hours=2) + timedelta(seconds=5)
    summary, _ = service(monkeypatch, {items[0].id: value})
    result = await summary.summary(db, team.id)
    assert result.remaining_work.state == "known"
    assert result.valid_until <= value.remaining_work.reported_at + timedelta(hours=2)
