"""Runtime truth table, identity evidence and shared authoritative state semantics."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, GithubWorkItem,
    GithubApprovalRequest, GithubWorkspace, MailAgentSession, MailPaneLifecycle, TeamGithubScope,
)
from app.models.factory_schemas import RuntimeObservation
from app.services import factory_projection_service as projection
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_verification_service import github_verification_service
from app.services.github_work_item_projection import _load_work_item_authority, _work_item_response

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
PRIVATE = "synthetic-private-forbidden"


@pytest.mark.parametrize("mode,state,jobs,reason,intake_state", [
    ("normal", "running", True, "intake_eligible", "eligible"),
    ("recovery_only", "running", True, "recovery_only_gate", "blocked"),
    ("normal", "stopped", True, "scheduler_stopped", "blocked"),
    ("unknown", "unknown", True, "runtime_not_observed", "unknown"),
    ("normal", "running", False, "job_not_scheduled", "blocked"),
])
async def test_runtime_intake_polling_partitions(factory_client, factory_store, monkeypatch, mode, state, jobs, reason, intake_state):
    snapshot = projection.RuntimeSnapshot(RuntimeObservation(mode=mode, scheduler_state=state,
        observed_at=NOW - timedelta(seconds=1), reason_code=None), factory_store.runtime.job_ids if jobs else frozenset())
    calls = []
    monkeypatch.setattr(projection, "observe_runtime", lambda: calls.append(1) or snapshot)
    response = await factory_client.get("/api/v1/factory/overview")
    assert response.status_code == 200, response.text
    automation = response.json()["automation"]
    assert len(calls) == 1
    assert automation["configured_scopes"] == automation["enabled_scopes"] + automation["paused_scopes"] == 3
    assert automation["enabled_scopes"] == sum(automation[f"intake_{s}_scopes"] for s in ("eligible", "blocked", "unknown")) == 2
    assert automation[f"intake_{intake_state}_scopes"] == 2
    assert automation["runtime"]["observed_at"] != response.json()["generated_at"]
    if intake_state != "eligible":
        assert automation["never_polled_scopes"] == automation["stale_scopes"] == 0
    else:
        assert automation["never_polled_scopes"] == 1
    calls.clear()
    repos = (await factory_client.get("/api/v1/factory/repositories")).json()["repositories"]
    assert len(calls) == 1
    enabled = [r for r in repos if r["configured_enabled"]]
    assert len(enabled) == 2
    assert all(r["intake"]["reason_code"] == reason for r in enabled)
    assert all(r["poll"]["freshness"] == "suspended" for r in enabled) if intake_state == "blocked" else True
    assert all(r["poll"]["freshness"] == "unknown" for r in enabled) if intake_state == "unknown" else True


async def test_runtime_observer_never_initializes_scheduler_or_exposes_gate(monkeypatch):
    scheduler = projection.github_dispatch_scheduler
    monkeypatch.setattr(scheduler, "recovery_only_attempt", SimpleNamespace(scope_id=99, dispatch_nonce=PRIVATE, head_ref=PRIVATE))
    monkeypatch.setattr(scheduler, "scheduler", SimpleNamespace(running=True, get_jobs=lambda: [SimpleNamespace(id="safe-job")]))
    monkeypatch.setattr(scheduler, "_ensure_scheduler", lambda: pytest.fail("scheduler initialized"))
    observed = projection.observe_runtime()
    assert observed.public.mode == "recovery_only"
    assert PRIVATE not in observed.public.model_dump_json()
    monkeypatch.setattr(scheduler, "scheduler", None)
    assert projection.observe_runtime().public.scheduler_state == "stopped"
    class Unavailable:
        @property
        def running(self): raise RuntimeError(PRIVATE)
    monkeypatch.setattr(scheduler, "scheduler", Unavailable())
    unknown = projection.observe_runtime()
    assert unknown.public.mode == "unknown" and unknown.job_ids is None
    assert PRIVATE not in unknown.public.model_dump_json()


async def test_missing_owner_never_gets_default_provider(factory_client, factory_store):
    result = (await factory_client.get(f"/api/v1/factory/work-items/{factory_store.ids.items[0]}")).json()["work_item"]
    assert result["owner"] is None
    assert result["session"]["state"] == "unknown"
    assert result["session"]["observed_provider"] is None
    assert result["links"]["bridge_target"] is None
    async with factory_store.maker() as db:
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == factory_store.ids.items[1])
                         .values(owner_slot_id=factory_store.ids.owners[0]))
        await db.commit()
    conflicting = (await factory_client.get(f"/api/v1/factory/work-items/{factory_store.ids.items[1]}")).json()["work_item"]
    assert conflicting["owner"] is None


async def test_cross_team_approver_never_supplies_actor_or_launch_target(factory_client, factory_store):
    ids = factory_store.ids
    async with factory_store.maker() as db:
        approval = (await db.execute(select(GithubApprovalRequest).where(
            GithubApprovalRequest.work_item_id == ids.by_status["dispatched"]))).scalar_one()
        approval.leader_member_id = ids.members[0]  # Valid member, wrong team.
        await db.commit()
    # Both teams are loaded by this page, so presence in the bulk result must
    # never be treated as proof of a per-item authority association.
    page = (await factory_client.get("/api/v1/factory/work-items", params={"limit": 100, "category": "active"})).json()
    item = next(row for row in page["items"] if row["item"]["id"] == ids.by_status["dispatched"])
    assert item["approver"] is None
    assert item["approver_session"]["state"] == "unknown"
    assert item["approver_session"]["bridge_target"] is None
    assert item["links"]["launch_plan"] is None


@pytest.mark.parametrize("condition,expected", [
    ("verified", "bound"), ("duplicate", "ambiguous"), ("offline", "offline"),
    ("stale_pid", "unknown"), ("mismatched_pane", "unknown"), ("retired_pane", "unknown"),
])
async def test_session_links_require_exact_verified_association(factory_client, factory_store, condition, expected):
    ids = factory_store.ids
    async with factory_store.maker() as db:
        session = (await db.execute(select(MailAgentSession).where(MailAgentSession.team_slot_id == ids.owners[1]))).scalar_one()
        if condition == "duplicate":
            db.add(MailAgentSession(member_id=session.member_id, session_key="fixture-duplicate", source="mcp",
                provider="codex-cli", team_preset_id=ids.teams[1], team_slot_id=ids.owners[1],
                capability_token_hash=PRIVATE, last_seen_at=NOW.replace(tzinfo=None), mailbox_status="connected",
                bound_pane_pid=session.bound_pane_pid, bound_pane_proc_start=session.bound_pane_proc_start))
        if condition == "offline": session.closed_at = NOW.replace(tzinfo=None)
        if condition == "stale_pid":
            session.last_seen_at = NOW.replace(tzinfo=None) - timedelta(days=1)
            session.pid = 42
        if condition == "mismatched_pane": session.bound_pane_proc_start = "wrong-start"
        if condition == "retired_pane":
            db.add(MailPaneLifecycle(pane_pid=session.bound_pane_pid,
                                    pane_proc_start=session.bound_pane_proc_start, retired_at=NOW.replace(tzinfo=None)))
        await db.commit()
    body = (await factory_client.get(f"/api/v1/factory/work-items/{ids.items[1]}")).json()["work_item"]
    assert body["session"]["state"] == expected
    if expected == "bound":
        target = body["session"]["bridge_target"]
        assert target["slot_id"] == ids.owners[1] and target["team_id"] == ids.teams[1]
        assert target["member_id"] == ids.members[3]
        assert body["links"]["bridge_target"] == target
        assert body["session"]["observed_provider"] == "codex-cli"
    else:
        assert body["session"]["bridge_target"] is None
        assert body["links"]["bridge_target"] is None
    if expected == "offline":
        assert body["links"]["launch_plan"] == {"team_id": ids.teams[1], "slot_id": ids.owners[1]}
    # Verified offline Leader receives its exact slot hint when owner is bound.
    if expected == "bound":
        assert body["approver_session"]["state"] == "offline"
        assert body["links"]["launch_plan"]["slot_id"] == ids.leaders[1]


async def test_factory_and_legacy_share_normalized_projection_and_retry(factory_client, factory_store):
    ids = factory_store.ids
    legacy = (await factory_client.get(f"/api/v1/agent-teams/presets/{ids.teams[1]}/github-work-items", params={"limit": 200})).json()["items"]
    safe = (await factory_client.get("/api/v1/factory/work-items", params={"team_id": ids.teams[1], "limit": 100})).json()["items"]
    by_id = {row["id"]: row for row in legacy}
    for row in safe:
        original = by_id[row["item"]["id"]]
        retry = next(a for a in row["actions"] if a["name"] == "retry")
        assert (retry["state"] == "eligible") == original["retry_allowed"]
        assert retry["block_code"] == original["retry_block_code"]
        assert row["item"]["active_scope_status"] == original["active_scope_status"]
        assert row["item"]["pending_approval_status"] == original["pending_approval_status"]
    assert PRIVATE in str(legacy) and PRIVATE not in str(safe)


async def test_operator_escalation_manual_and_issue_update_retry_semantics(factory_client, factory_store):
    ids = factory_store.ids
    target = ids.by_status["escalated"]
    async with factory_store.maker() as db:
        item = await db.get(GithubWorkItem, target)
        item.active_scope_revision = 0
        item.pr_number = None
        await db.commit()
        assert await github_dispatch_service.can_auto_retry_from_issue_update(db, item)
    response = await factory_client.get(f"/api/v1/factory/work-items/{target}")
    row = response.json()["work_item"]
    assert row["category"] == "attention"
    assert row["waiting"]["reason_code"] == "abandoned_by_operator"
    assert next(a for a in row["actions"] if a["name"] == "retry")["state"] == "eligible"
    assert "delivery_outcome" not in str(row)


async def test_counts_and_records_share_one_real_read_snapshot(factory_client, factory_store, monkeypatch):
    original = projection.counts
    called = []
    async def interleave_writer(db, query):
        result = await original(db, query)
        if not called:
            called.append(1)
            async with factory_store.maker() as writer:
                writer.add(GithubWorkItem(scope_id=factory_store.ids.scopes[0], issue_number=9999,
                    issue_title="Concurrent fixture", issue_url="https://github.com/fixture/shared/issues/9999",
                    github_updated_at=NOW.replace(tzinfo=None), updated_at=NOW.replace(tzinfo=None) + timedelta(seconds=1)))
                await writer.commit()
        return result
    monkeypatch.setattr(projection, "counts", interleave_writer)
    first = await factory_client.get("/api/v1/factory/work-items", params={"limit": 100})
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 132
    assert max(r["item"]["id"] for r in first.json()["items"]) == 132
    refreshed = await factory_client.get("/api/v1/factory/work-items", params={"limit": 1})
    assert refreshed.json()["total"] == 133
    assert refreshed.json()["items"][0]["item"]["issue_number"] == 9999


async def test_representative_existing_mutations_persist_update_timestamp(factory_store, monkeypatch):
    ids = factory_store.ids
    async with factory_store.maker() as db:
        item = await db.get(GithubWorkItem, ids.by_status["pending"])
        item.dispatch_nonce = item.dispatch_head_ref = item.dispatch_base_ref = None
        await db.commit()
        original_time = item.updated_at
        await github_dispatch_service.prepare_attempt(db, item, owner_slot_id=ids.owners[0],
            routing_method="fixture", base_ref="feature/software-delivery-product-reposition")
        await db.refresh(item)
        assert item.updated_at > original_time
        item.updated_at = original_time
        await db.commit()
        await github_dispatch_service.escalate_without_notification(db, item, "abandoned_by_operator")
        await db.refresh(item)
        assert item.updated_at > original_time and item.dispatch_status == "escalated"
        item.updated_at = original_time
        await db.commit()
        await github_dispatch_service.reset_for_retry(db, item)
        await db.commit(); await db.refresh(item)
        assert item.updated_at > original_time and item.dispatch_status == "pending"
        item.updated_at = original_time
        item.pr_number = 77
        scope = await db.get(TeamGithubScope, item.scope_id)
        monkeypatch.setattr(github_verification_service, "_notify_code_pr_ready_for_review", AsyncMock())
        monkeypatch.setattr(github_verification_service, "_process_review_item", AsyncMock())
        await github_verification_service._promote_verified_item(db, scope, item, SimpleNamespace(),
                                                                {"draft": False}, "a" * 40)
        await db.refresh(item)
        assert item.updated_at > original_time and item.dispatch_status == "ready_for_review"
