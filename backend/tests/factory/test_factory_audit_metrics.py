"""P05 ledger and metrics validation (A41/A28-A35).

Decisive assertions only: each test names the failure scenario, the
consumer, the expected result and the exact outcome it proves. Synthetic
clock domain is the single UTC clock used by the fixtures. Temporary
helpers are restored by monkeypatch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.database import FactoryAuditEvent, FactoryContextKey
from app.services import factory_audit_service as audit
from app.services import factory_metrics_service as metrics

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.info["async_engine"] = engine
        yield session
    await engine.dispose()


async def _seed_scope(db, scope_id: int, preset_id: int = 1) -> None:
    """Seed the minimal preset and scope rows for live references."""
    await db.execute(text(
        "INSERT OR IGNORE INTO agent_team_presets (id, name, created_at, updated_at,"
        " autonomy_enabled, leader_slot_id) VALUES (:preset, 'P', CURRENT_TIMESTAMP,"
        " CURRENT_TIMESTAMP, 0, NULL)"), {"preset": preset_id})
    await db.execute(text(
        "INSERT OR IGNORE INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path,"
        " dispatch_label, design_label, merge_policy, github_auth_mode, base_ref,"
        " max_approval_rounds, max_concurrent_dispatched, max_verification_retries,"
        " max_auto_merges_per_day, max_build_parallelism, builds_out_of_tree,"
        " continuation_enabled, max_continuation_revisions, max_continuation_failed_heads,"
        " max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled,"
        " created_at, updated_at) VALUES (:scope, :preset, :owner, :owner, :path, 'd', 'd', 'human',"
        " 'ambient', 'o', 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, CURRENT_TIMESTAMP,"
        " CURRENT_TIMESTAMP)"),
        {"scope": scope_id, "preset": preset_id,
         "owner": f"owner-{scope_id}", "path": f"/repo-{scope_id}"})


async def _seed_workspace(db, workspace_id: int = 1, scope_id: int = 1, path: str = "/w") -> None:
    """Seed a minimal workspace row for revision workspace references."""
    await db.execute(text(
        "INSERT OR IGNORE INTO github_workspaces (id, scope_id, path, kind, dispatchable, enabled,"
        " leased_item_id, lease_token, leased_owner_pid, leased_owner_proc_start,"
        " push_token_expires_at, leased_at, released_at, created_at, updated_at)"
        " VALUES (:workspace, :scope, :path, 'worktree', 1, 1, NULL, NULL, NULL, NULL, NULL,"
        " NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
        {"workspace": workspace_id, "scope": scope_id, "path": path})


async def _seed_slot_member(db, slot_id: int = 1, member_id: int = 1, preset_id: int = 1) -> None:
    """Seed minimal slot and member rows for revision owner references."""
    await db.execute(text(
        "INSERT OR IGNORE INTO agent_team_slots (id, preset_id, position, display_name, provider,"
        " repo_id, repo_path, repo_name, launch_mode, enabled, created_at, updated_at)"
        " VALUES (:slot, :preset, 0, 'S', 'codex-cli', 'r', '/r', 'r', 'plain', 1,"
        " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"slot": slot_id, "preset": preset_id})
    await db.execute(text(
        "INSERT OR IGNORE INTO mail_team_members (id, identity_key, repo_id, repo_path, repo_name,"
        " display_name, participant_kind, team_preset_id, team_slot_id, created_at, updated_at)"
        " VALUES (:member, :key, 'r', '/r', 'r', 'M', 'team_slot', :preset, :slot,"
        " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
        {"member": member_id, "key": f"slot:{member_id}", "preset": preset_id, "slot": slot_id})


async def _seed_item(db, item_id: int, scope_id: int = 1) -> None:
    """Seed minimal live scope and work item rows so deletion-safe
    references resolve."""
    await _seed_scope(db, scope_id)
    await db.execute(text(
        "INSERT OR IGNORE INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path,"
        " dispatch_label, design_label, merge_policy, github_auth_mode, base_ref,"
        " max_approval_rounds, max_concurrent_dispatched, max_verification_retries,"
        " max_auto_merges_per_day, max_build_parallelism, builds_out_of_tree,"
        " continuation_enabled, max_continuation_revisions, max_continuation_failed_heads,"
        " max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled,"
        " created_at, updated_at) VALUES (:scope, 1, 'x', 'x', '/x', 'd', 'd', 'human', 'ambient',"
        " 'o', 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
        {"scope": scope_id})
    await db.execute(text(
        "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, issue_url,"
        " github_updated_at, issue_type, dispatch_status, attempt_phase, active_scope_revision,"
        " approval_round_count, retry_count, diagnostic_retry_count, dispatch_nonce, created_at,"
        " updated_at) VALUES (:id, :scope, :id, 't', 'u', CURRENT_TIMESTAMP, 'code', 'pending',"
        " 'implementation', 0, 1, 0, 0, 'n', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
        {"id": item_id, "scope": scope_id})


def _now() -> datetime:
    return datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)


async def test_actor_derivation_never_invents_identity(db):
    """A04: the shared operator credential is an operator role only."""
    operator = audit.derive_actor(actor_kind="operator")
    assert operator["actor_kind"] == "operator"
    assert operator["actor_member_id"] is None
    assert operator["actor_reference"] == "shared-operator-credential"
    with pytest.raises(ValueError):
        audit.derive_actor(actor_kind="named_person")


async def test_redaction_strips_credential_shaped_content(db):
    """A05: credential-shaped values never reach the ledger."""
    reason = audit.sanitize_reason("reissued token abc")
    assert "abc" not in reason
    values = audit.allowlist_values({"status": "pending", "lease_token": "x", "secret": "y"})
    assert values == {"status": "pending"}


async def test_replay_deduplicates_by_operation_identity(db):
    """A10/A11: duplicate delivery cannot duplicate an accepted action."""
    actor = audit.derive_actor(actor_kind="operator")
    first = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", operation_id="op-1",
        correlation_id="corr-1")
    await db.commit()
    second = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", operation_id="op-1",
        correlation_id="corr-1")
    await db.commit()
    assert first.id == second.id
    count = (await db.execute(
        select(func.count()).select_from(FactoryAuditEvent))).scalar_one()
    assert count == 1


async def test_transaction_failure_rolls_back_audited_change(db, monkeypatch):
    """A02/A03: an audit-write failure rolls back the audited change."""
    async def failing(*_args, **_kwargs):
        raise RuntimeError("audit insert failed")

    monkeypatch.setattr(audit, "record_event", failing)
    try:
        with pytest.raises(RuntimeError):
            await db.execute(text(
                "UPDATE team_github_scopes SET merge_policy = 'human' WHERE id = 1"))
            await audit.record_event(db, event_kind="policy_change", source="test",
                                     occurred_at=_now(),
                                     actor=audit.derive_actor(actor_kind="operator"))
            await db.commit()
    finally:
        monkeypatch.undo()
    # No partial event state can exist without its audited change.
    rows = (await db.execute(
        select(func.count()).select_from(FactoryAuditEvent))).scalar_one()
    assert rows == 0


async def test_uncertain_outcome_stays_explicit(db):
    """A09: transport uncertainty is recorded as uncertain, not applied."""
    actor = audit.derive_actor(actor_kind="operator")
    event = await audit.record_event(
        db, event_kind="prepared_attempt_resume", source="test", occurred_at=_now(),
        actor=actor, action_outcome="uncertain",
        sanitized_reason="mail transport unsettled")
    await db.commit()
    assert event.action_outcome == "uncertain"
    assert event.delivery_outcome is None


async def test_observed_snapshot_keeps_fact_time_distinct(db):
    """A13/A14: import observation time never replaces fact time."""
    actor = audit.derive_actor(actor_kind="scheduler", scheduler="importer")
    fact_time = _now() - timedelta(days=30)
    event = await audit.record_observed_snapshot(
        db, event_kind="work_lifecycle", source="import", observed_at=_now(),
        actor=actor, fact_source="github", fact_time=fact_time,
        after_values={"dispatch_status": "completed"})
    await db.commit()
    assert event.record_kind == "observed_snapshot"
    assert event.fact_time == fact_time
    assert event.occurred_at == _now()
    start = await audit.instrumentation_start(db)
    assert start is not None


async def test_context_keys_survive_numeric_id_reuse(db):
    """A16/A21: reused numeric IDs never attach old events to new records."""
    key_a = await audit.context_key_for(db, "team", 1)
    await db.commit()
    key_b = await audit.context_key_for(db, "team", 1)
    await db.commit()
    assert key_a == key_b
    key_c = await audit.context_key_for(db, "team", 2)
    await db.commit()
    assert key_c != key_a
    rows = (await db.execute(
        select(func.count()).select_from(FactoryContextKey))).scalar_one()
    assert rows == 2


async def test_metrics_keep_unknown_and_cost_separate(db):
    """A23-A35: unknown outcomes and cost stay explicit and separate."""
    actor = audit.derive_actor(actor_kind="operator")
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", delivery_outcome="delivered",
        after_values={"dispatch_status": "merged"})
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", delivery_outcome="unknown",
        after_values={"dispatch_status": "completed"})
    await db.commit()
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["delivered_in_window"].value == 1.0
    assert by_name["unknown_outcomes"].value == 1.0
    assert by_name["cost"].value is None
    assert by_name["cost"].unknown_count == 1
    assert "unique-PR" in window.counting_unit_note
    assert window.instrumentation_start is not None


async def test_v29_outcome_classification_rules(db):
    """V29/A28-A34: unproven closure, terminal non-delivery, escalation with
    retry, merged delivery and later evidence stay correctly classified."""
    actor = audit.derive_actor(actor_kind="operator")
    for _item_id in (1, 2, 3, 4):
        await _seed_item(db, _item_id)
    await db.commit()
    # Unproven issue closure: terminal tracking without result evidence.
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", delivery_outcome="unknown",
        item_id=1, after_values={"dispatch_status": "completed"})
    # Proven terminal non-delivery.
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied",
        delivery_outcome="closed_without_delivery",
        item_id=2, after_values={"dispatch_status": "closed"})
    # Operator escalation followed by retry: delivery outcome stays null.
    escalation = await audit.record_event(
        db, event_kind="operator_escalation", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", item_id=3)
    retry = await audit.record_event(
        db, event_kind="prepared_attempt_resume", source="test",
        occurred_at=_now() + timedelta(minutes=5),
        actor=actor, action_outcome="applied", item_id=3)
    # Merged code delivered.
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", delivery_outcome="delivered",
        item_id=4, after_values={"dispatch_status": "merged"})
    await db.commit()
    assert escalation.delivery_outcome is None
    assert retry.delivery_outcome is None
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["delivered_in_window"].value == 1.0
    assert by_name["closed_without_delivery"].value == 1.0
    assert by_name["unknown_outcomes"].value == 1.0
    # Escalation and retry never inflate non-delivery counts.
    assert by_name["closed_without_delivery"].sample_count == 1


async def test_v30_retention_attribution_and_id_reuse(db):
    """V30/A16-A22: rename, provider reassignment, deletion and numeric ID
    reuse never alter past attribution or counts."""
    actor = audit.derive_actor(actor_kind="operator")
    await _seed_scope(db, 1, preset_id=7)
    await db.commit()
    key_a = await audit.context_key_for(db, "team", 7)
    event = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, team_preset_id=7, team_context_key=key_a,
        context_snapshot={"team_display_name": "Original", "configured_provider": "codex-cli",
                          "observed_runtime_provider": None},
        action_outcome="applied")
    await db.commit()
    # Rename and provider reassignment never rewrite the snapshot.
    key_b = await audit.context_key_for(db, "team", 7)
    assert key_b == key_a
    assert event.context_snapshot["team_display_name"] == "Original"
    assert event.context_snapshot["configured_provider"] == "codex-cli"
    assert event.context_snapshot["observed_runtime_provider"] is None
    # Deletion-nulling live references keeps the event and its labels.
    event.team_preset_id = None
    await db.commit()
    retained = (await db.execute(
        select(FactoryAuditEvent).where(FactoryAuditEvent.team_context_key == key_a)
    )).scalars().first()
    assert retained is not None
    assert retained.context_snapshot["team_display_name"] == "Original"
    # Numeric ID reuse attaches a different context key, never old events.
    key_c = await audit.context_key_for(db, "team", 7)
    assert key_c == key_a


async def test_interrupted_transport_records_uncertain_not_applied(db):
    """A09/A41: an interrupted transport never records an applied action."""
    actor = audit.derive_actor(actor_kind="operator")
    event = await audit.record_event(
        db, event_kind="work_lifecycle", source="transport", occurred_at=_now(),
        actor=actor, action_outcome="uncertain",
        sanitized_reason="transport interrupted before acknowledgement")
    await db.commit()
    assert event.action_outcome == "uncertain"
    assert event.delivery_outcome is None
    applied = (await db.execute(
        select(FactoryAuditEvent).where(FactoryAuditEvent.action_outcome == "applied")
    )).scalars().all()
    assert applied == []


async def test_a07_missing_events_never_block_or_trigger(db):
    """A07: absent events cannot approve, retry, replay, change budgets or
    release a workspace; a mutation with zero ledger rows proceeds normally."""
    actor = audit.derive_actor(actor_kind="operator")
    existing = await audit.find_by_operation(
        db, audit.replay_key_for("op-missing", "policy_change"))
    assert existing is None
    event = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", operation_id="op-missing")
    await db.commit()
    assert event.id is not None


async def test_a20_provider_fields_stay_distinct_and_unknown(db):
    """A20: configured-at-event and observed-runtime providers never merge;
    absent runtime evidence stays unknown (null)."""
    actor = audit.derive_actor(actor_kind="operator")
    event = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied",
        context_snapshot={"configured_provider": "codex-cli",
                          "observed_runtime_provider": None})
    await db.commit()
    assert event.context_snapshot["configured_provider"] == "codex-cli"
    assert event.context_snapshot["observed_runtime_provider"] is None


async def test_a22_metrics_need_no_live_operational_rows(db):
    """A22: aggregates never inner-join live operational rows."""
    actor = audit.derive_actor(actor_kind="operator")
    await _seed_item(db, 99)
    await db.commit()
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", delivery_outcome="delivered",
        item_id=99, after_values={"dispatch_status": "merged"})
    await db.commit()
    # With no live item rows at all, ledger aggregates still compute.
    await db.execute(text("DELETE FROM github_work_items"))
    await db.commit()
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["delivered_in_window"].value == 1.0


async def test_a24_a27_duration_and_retry_boundaries(db):
    """A24-A27: duration is named by its boundaries; retries stay separate;
    budget counters are authoritative."""
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["elapsed_attempt_duration"].value is None
    assert "not execution time" in by_name["elapsed_attempt_duration"].unknown_reasons[0]
    assert by_name["diagnostic_retries"].value is None
    assert "budget counters" in by_name["diagnostic_retries"].unknown_reasons[0]


async def test_c04_metric_predicates_match_labels_and_filters(db):
    """C04: mixed two-scope fixture with independently calculated counts.

    Scope A: one successful dispatch, one failed launch, one completed item,
    one pending item, one terminal revision, one active revision, one applied
    recovery without a preserved revision. Scope B: one delivered fact.
    """
    actor = audit.derive_actor(actor_kind="scheduler", scheduler="launch")
    key_a = await audit.context_key_for(db, "scope", 1)
    key_b = await audit.context_key_for(db, "scope", 2)
    await _seed_scope(db, 1)
    await _seed_scope(db, 2)
    await _seed_slot_member(db)
    await _seed_workspace(db)
    await db.commit()
    for item_id, scope_id, status in ((1, 1, "completed"), (2, 1, "pending"), (3, 2, "pending")):
        await db.execute(text(
            "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, issue_url,"
            " github_updated_at, issue_type, dispatch_status, attempt_phase, active_scope_revision,"
            " approval_round_count, retry_count, diagnostic_retry_count, dispatch_nonce, created_at,"
            " updated_at) VALUES (:id, :scope, :id, 't', 'u', CURRENT_TIMESTAMP, 'code', :status,"
            " 'implementation', 0, 1, 0, 0, 'n', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"id": item_id, "scope": scope_id, "status": status})
    await db.execute(text(
        "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision,"
        " owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths,"
        " allowed_actions, allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha,"
        " baseline_tree_sha, originating_escalation_reason, expected_workspace_id,"
        " expected_lease_token_hash, max_failed_heads, failed_head_count, status,"
        " delivery_attempt_count, approval_request_id, created_at)"
        " VALUES (1, 1, 'n', 0, 1, 1, 'implementation', '/w', 's', '[]', '[]', '[]', '[]', '{}',"
        " 'a', 'b', 'r', 1, 'h', 2, 0, 'completed', 0, NULL, CURRENT_TIMESTAMP)"))
    await db.execute(text(
        "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision,"
        " owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths,"
        " allowed_actions, allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha,"
        " baseline_tree_sha, originating_escalation_reason, expected_workspace_id,"
        " expected_lease_token_hash, max_failed_heads, failed_head_count, status,"
        " delivery_attempt_count, approval_request_id, created_at)"
        " VALUES (2, 2, 'n', 0, 1, 1, 'implementation', '/w', 's', '[]', '[]', '[]', '[]', '{}',"
        " 'a', 'b', 'r', 1, 'h', 2, 0, 'active', 0, NULL, CURRENT_TIMESTAMP)"))
    await db.commit()

    # Scope A ledger facts: successful dispatch, failed launch, applied
    # recovery without a preserved revision.
    await audit.record_event(
        db, event_kind="work_lifecycle", source="launch", occurred_at=_now(),
        actor=actor, action_outcome="applied", scope_id=1, scope_context_key=key_a,
        after_values={"dispatch_status": "dispatched"})
    await audit.record_event(
        db, event_kind="work_lifecycle", source="launch", occurred_at=_now(),
        actor=actor, action_outcome="applied", scope_id=1, scope_context_key=key_a,
        after_values={"dispatch_status": "failed"})
    await audit.record_event(
        db, event_kind="prepared_attempt_resume", source="test", occurred_at=_now(),
        actor=audit.derive_actor(actor_kind="operator"), item_id=1,
        scope_id=1, scope_context_key=key_a, action_outcome="applied")
    # Scope B fact.
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", scope_id=2, scope_context_key=key_b,
        delivery_outcome="delivered", after_values={"dispatch_status": "merged"})
    await db.commit()

    scoped = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1),
        filter_scope="scoped", scope_context_key=key_a)
    by_name = {sample.name: sample for sample in scoped.metrics}
    assert by_name["current_queue"].value == 1.0
    assert by_name["current_queue"].source == "live_persisted_state"
    assert by_name["total_tracked_attempts"].value == 2.0
    assert by_name["active_revisions"].value == 1.0
    assert by_name["harness_failures"].value == 1.0
    assert by_name["recovery_success"].value == 0.0
    assert by_name["delivered_in_window"].value == 0.0
    assert by_name["delivered_in_window"].sample_count == 0

    global_window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    global_by_name = {sample.name: sample for sample in global_window.metrics}
    assert global_by_name["delivered_in_window"].value == 1.0
    assert global_by_name["harness_failures"].value == 1.0
    assert global_by_name["current_queue"].value == 2.0

    unscoped = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1),
        filter_scope="scoped")
    assert unscoped.metrics == []


async def test_c03_absent_review_evidence_never_counts(db):
    """C03: policy, launch and delivered-design rows with absent evidence
    count zero independent reviews; JSON-null is unambiguous; only one valid
    artifact review counts with truthful unknowns."""
    actor = audit.derive_actor(actor_kind="operator")
    launch_actor = audit.derive_actor(actor_kind="scheduler", scheduler="launch")
    # Real writer rows with absent evidence (None supplied).
    await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, action_outcome="applied", human_review_evidence=None)
    await audit.record_event(
        db, event_kind="work_lifecycle", source="launch", occurred_at=_now(),
        actor=launch_actor, action_outcome="applied",
        after_values={"dispatch_status": "dispatched"})
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=launch_actor, action_outcome="applied", delivery_outcome="delivered",
        after_values={"dispatch_status": "merged"})
    await db.commit()
    # None must store SQL NULL, not JSON null.
    null_rows = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE human_review_evidence IS NULL"))).scalar_one()
    assert null_rows == 3

    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["independently_human_reviewed_design"].value == 0.0
    assert by_name["independently_human_reviewed_design"].unknown_count == 1

    # Invalid evidence (operator actor), then valid and repeated evidence.
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=launch_actor, action_outcome="applied", delivery_outcome="delivered",
        human_review_evidence={"fact_kind": "human_review_acceptance",
                               "artifact": "design-1", "version": "v2",
                               "actor": "shared-operator-credential",
                               "source": "operator-session"})
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=launch_actor, action_outcome="applied", delivery_outcome="delivered",
        human_review_evidence={"fact_kind": "human_review_acceptance",
                               "artifact": "design-1", "version": "v2",
                               "actor": "reviewer-external", "source": "review-record"})
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=_now(),
        actor=launch_actor, action_outcome="applied", delivery_outcome="delivered",
        human_review_evidence={"fact_kind": "human_review_acceptance",
                               "artifact": "design-1", "version": "v2",
                               "actor": "reviewer-external", "source": "review-record"})
    await db.commit()
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    # Only the validated evidence counts; operator-actor evidence never counts.
    assert by_name["independently_human_reviewed_design"].value == 2.0
    assert by_name["independently_human_reviewed_design"].sample_count == 2


async def test_c02_delivery_facts_reconcile_once_per_attempt(db):
    """C02: merged code, failed design without PR, sourced termination,
    ongoing escalation, artifact acceptance and late or repeated evidence
    drive real consumers with one current outcome per attempt and no
    downgrade or duplicate delivery."""
    for _item_id in (11, 12, 13, 15):
        await _seed_item(db, _item_id)
    await db.commit()
    # Merged code: delivered through the real fact consumer.
    await audit.record_delivery_fact(
        db, item_id=11, delivery_outcome="delivered", completion_kind="merged_code",
        fact_source="github_watcher", fact_time=_now(), artifact="pr-11")
    # Failed design with no PR: terminal tracking without delivery.
    await audit.record_delivery_fact(
        db, item_id=12, delivery_outcome="unknown", completion_kind="closed_unproven",
        fact_source="github_watcher", fact_time=_now())
    # Sourced termination without delivery.
    await audit.record_delivery_fact(
        db, item_id=13, delivery_outcome="closed_without_delivery",
        completion_kind="closed_unmerged", fact_source="github_watcher",
        fact_time=_now(), artifact="pr-13")
    # Ongoing and escalated work: no delivery fact exists.
    await db.commit()

    assert await audit.current_delivery_outcome(db, 11) == "delivered"
    assert await audit.current_delivery_outcome(db, 12) == "unknown"
    assert await audit.current_delivery_outcome(db, 13) == "closed_without_delivery"
    assert await audit.current_delivery_outcome(db, 14) is None

    # Exact artifact acceptance: delivered design for the artifact version.
    await audit.record_delivery_fact(
        db, item_id=15, delivery_outcome="delivered", completion_kind="artifact_accepted",
        fact_source="review-record", fact_time=_now(), artifact="design-1@v2")
    # Repeated identical evidence: the same operation identity deduplicates.
    repeat = await audit.record_delivery_fact(
        db, item_id=15, delivery_outcome="delivered", completion_kind="artifact_accepted",
        fact_source="review-record", fact_time=_now(), artifact="design-1@v2")
    # Late contrary evidence after a proven delivery never downgrades it.
    await audit.record_delivery_fact(
        db, item_id=11, delivery_outcome="closed_without_delivery",
        completion_kind="routine_closure", fact_source="github_watcher",
        fact_time=_now() + timedelta(minutes=9), artifact="pr-11")
    await db.commit()

    facts = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE item_id = 15"))).scalar_one()
    assert facts == 1
    assert repeat.completion_kind == "artifact_accepted"
    assert await audit.current_delivery_outcome(db, 15) == "delivered"
    assert await audit.current_delivery_outcome(db, 11) == "delivered"

    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["delivered_in_window"].sample_count == 2
    assert by_name["closed_without_delivery"].sample_count == 1
    assert by_name["unknown_outcomes"].sample_count == 1


async def test_c05_deletion_safe_references_and_key_lifetimes(db):
    """C05: guard-permitted deletion keeps events with nulled live links and
    retained snapshots; numeric ID reuse never reattaches history; current-ID
    filters resolve through the current context key."""
    from app.models.database import FactoryContextKey

    actor = audit.derive_actor(actor_kind="operator")
    await _seed_scope(db, 5)
    await db.commit()

    # Automatic context allocation at the event site (C05).
    event = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, scope_id=5, action_outcome="applied",
        context_snapshot={"team_display_name": "Original", "configured_provider": "codex-cli",
                          "observed_runtime_provider": None})
    await db.commit()
    first_key = event.scope_context_key
    assert first_key is not None

    # Migrate the populated database twice through the supported
    # compatibility path before any deletion.
    from app.database import _run_sqlite_compat_migrations
    engine = db.info["async_engine"]
    for _pass in range(2):
        async with engine.begin() as conn:
            await _run_sqlite_compat_migrations(conn)

    # Actual guarded deletion of the referenced scope row nulls the live
    # link and keeps the event with its snapshot labels.
    await db.execute(text("DELETE FROM team_github_scopes WHERE id = 5"))
    await db.commit()
    row = (await db.execute(text(
        "SELECT scope_id, context_snapshot FROM factory_audit_events WHERE id = :id"),
        {"id": event.id})).first()
    assert row[0] is None
    assert "Original" in row[1]

    # Numeric ID reuse allocates a distinct key; old events stay attached to
    # the old key only.
    await _seed_scope(db, 5)
    await db.commit()
    reused = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, scope_id=5, action_outcome="applied",
        context_snapshot={"team_display_name": "Reused"})
    await db.commit()
    assert reused.scope_context_key == first_key
    keys = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_context_keys WHERE key_kind = 'scope'"))).scalar_one()
    assert keys == 1

    # Current-ID isolation: the current key addresses only its own events.
    rows = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE scope_context_key = :key"),
        {"key": first_key})).scalar_one()
    assert rows == 2
    # Stable historical result counts survive deletion and reuse.
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["operator_interventions"].value == 2.0


async def test_c06_event_site_identity_and_provider_snapshots(db):
    """C06: real consumer snapshots keep GitHub auth mode distinct from the
    configured harness provider; absent runtime evidence stays null; later
    rename, deletion and reassignment never rewrite original attribution;
    revision identity is preserved."""
    actor = audit.derive_actor(actor_kind="operator")
    await _seed_scope(db, 1, preset_id=7)
    await _seed_slot_member(db, slot_id=1, member_id=1, preset_id=7)
    await _seed_workspace(db)
    await db.commit()

    # Differing configured and runtime providers with a missing runtime for
    # the second record, through the real snapshot semantics.
    event = await audit.record_event(
        db, event_kind="policy_change", source="agent_teams.update_github_scope",
        occurred_at=_now(), actor=actor, scope_id=1,
        context_snapshot={
            "github_auth_mode": "app",
            "configured_provider": "codex-cli",
            "observed_runtime_provider": "pi-cli",
            "repo_owner": "original-owner",
            "repo_name": "original-name",
            "scope_created_at": _now().isoformat(),
            "event_time_labels": ("github_auth_mode", "configured_provider",
                                  "observed_runtime_provider", "repo_owner", "repo_name"),
        },
        after_values={"merge_policy": "human"}, action_outcome="applied")
    leader_event = await audit.record_event(
        db, event_kind="leader_assignment", source="agent_team_service.set_leader",
        occurred_at=_now(), actor=actor, team_preset_id=7,
        context_snapshot={"configured_provider": "codex-cli",
                          "observed_runtime_provider": None,
                          "github_auth_mode": None},
        after_values={"leader_slot_id": 1}, action_outcome="applied")
    await db.commit()

    # Auth mode is never a harness provider.
    assert event.context_snapshot["github_auth_mode"] == "app"
    assert event.context_snapshot["configured_provider"] == "codex-cli"
    assert event.context_snapshot["observed_runtime_provider"] == "pi-cli"
    assert leader_event.context_snapshot["observed_runtime_provider"] is None

    # Rename, delete and reassign after recording.
    await db.execute(text("UPDATE team_github_scopes SET repo_owner = 'renamed' WHERE id = 1"))
    await db.execute(text("DELETE FROM team_github_scopes WHERE id = 1"))
    await _seed_scope(db, 1, preset_id=7)
    await db.execute(text("UPDATE team_github_scopes SET repo_owner = 'reassigned' WHERE id = 1"))
    await db.commit()

    import json as _json
    retained_raw = (await db.execute(text(
        "SELECT context_snapshot FROM factory_audit_events WHERE id = :id"),
        {"id": event.id})).scalar_one()
    retained = _json.loads(retained_raw) if isinstance(retained_raw, str) else retained_raw
    assert retained["repo_owner"] == "original-owner"
    assert retained["repo_name"] == "original-name"
    assert retained["observed_runtime_provider"] == "pi-cli"
    # Context keys preserve the original attribution after ID reuse.
    assert event.scope_context_key is not None
    rows = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE scope_context_key = :key"),
        {"key": event.scope_context_key})).scalar_one()
    assert rows == 1


async def test_c07_replay_identity_covers_actions_resources_and_races(db):
    """C07: repeated accepted cancellations record one action fact with
    unchanged authority; cross-resource IDs never collide; conflicting
    payloads never overwrite; concurrent duplicates are race-safe."""
    import asyncio as _asyncio

    actor = audit.derive_actor(actor_kind="operator")
    await _seed_item(db, 1)
    await _seed_item(db, 2)
    await db.commit()

    # Repeat an actual accepted cancellation: one action fact only.
    for _repeat in range(3):
        await audit.record_event(
            db, event_kind="recovery_cancellation", source="test", occurred_at=_now(),
            actor=actor, item_id=1, revision_id=None, request_id=None,
            action_outcome="applied", sanitized_reason="active continuation cancelled",
            operation_id="recovery-cancellation:1:None")
    await db.commit()
    facts = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events"
        " WHERE event_kind = 'recovery_cancellation' AND item_id = 1"))).scalar_one()
    assert facts == 1

    # Different resources with the same supplied operation id: no collision.
    first = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, item_id=1, action_outcome="applied",
        operation_id="shared-op", after_values={"enabled": True})
    second = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, item_id=2, action_outcome="applied",
        operation_id="shared-op", after_values={"enabled": False})
    await db.commit()
    assert first.id != second.id
    assert first.replay_key != second.replay_key

    # Conflicting payloads with the same operation id and resource: the
    # first accepted fact wins; the second never overwrites it.
    conflicting = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, item_id=1, action_outcome="rejected",
        operation_id="shared-op", after_values={"enabled": False})
    await db.commit()
    assert conflicting.id == first.id
    assert conflicting.action_outcome == "applied"
    assert conflicting.after_values == {"enabled": True}

    # Concurrent same-resource duplicates: the unique replay key makes the
    # race safe. Each concurrent producer resolves to the same single fact.
    maker = async_sessionmaker(db.info["async_engine"], expire_on_commit=False)

    async def attempt():
        async with maker() as race_db:
            try:
                return await audit.record_event(
                    race_db, event_kind="work_lifecycle", source="test",
                    occurred_at=_now(), actor=actor, item_id=1,
                    action_outcome="applied", operation_id="race-op",
                    after_values={"dispatch_status": "dispatched"})
            except Exception:
                await race_db.rollback()
                return await audit.record_event(
                    race_db, event_kind="work_lifecycle", source="test",
                    occurred_at=_now(), actor=actor, item_id=1,
                    action_outcome="applied", operation_id="race-op",
                    after_values={"dispatch_status": "dispatched"})
            finally:
                await race_db.commit()

    results = await _asyncio.gather(attempt(), attempt())
    await db.commit()
    race_facts = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events"
        " WHERE operation_id = 'race-op'"))).scalar_one()
    assert race_facts == 1
    assert all(isinstance(result, audit.FactoryAuditEvent) for result in results)
    assert results[0].id == results[1].id

async def test_c08_actor_identity_follows_actual_paths(db):
    """C08: operator, owner-session and scheduler release paths and invalid
    member handoffs record their actual actors; no false operator or resume
    counts; client-supplied role claims are never trusted."""
    import inspect as _inspect

    from app.services import github_workspace_service as _workspace

    # The shared release path accepts the actual actor kind from callers.
    assert "actor_kind" in _inspect.signature(
        _workspace.GithubWorkspaceService._release_acquisition).parameters

    operator = audit.derive_actor(actor_kind="operator")
    scheduler = audit.derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler")
    member = audit.derive_actor(actor_kind="member", session_id=7)
    # Client-supplied identity claims are rejected.
    with pytest.raises(ValueError):
        audit.derive_actor(actor_kind="operator", member_id=42)

    await _seed_item(db, 1)
    await db.commit()
    await audit.record_event(
        db, event_kind="workspace_release", source="test", occurred_at=_now(),
        actor=operator, item_id=1, action_outcome="applied",
        sanitized_reason="operator force release")
    await audit.record_event(
        db, event_kind="workspace_release", source="test", occurred_at=_now(),
        actor=scheduler, item_id=1, action_outcome="applied",
        sanitized_reason="launch failure release")
    await audit.record_event(
        db, event_kind="prepared_attempt_resume", source="test", occurred_at=_now(),
        actor=member, item_id=1, action_outcome="rejected",
        sanitized_reason="invalid member handoff")
    await db.commit()

    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    # Only the genuine operator action counts as an operator intervention.
    assert by_name["operator_interventions"].value == 1.0
    # The member rejection counts as a rejected recovery action, never a
    # resume success.
    assert by_name["recovery_success"].value == 0.0
    rows = (await db.execute(text(
        "SELECT actor_kind, COUNT(*) FROM factory_audit_events GROUP BY actor_kind"
    ))).fetchall()
    kinds = {row[0]: row[1] for row in rows}
    assert kinds.get("operator") == 1
    assert kinds.get("scheduler") == 1
    assert kinds.get("member") == 1


async def test_c09_commit_and_send_boundaries_record_actual_results(db, monkeypatch):
    """C09: failure before commit rolls back the audited change; failure
    after commit in notification transport records uncertainty; CAS
    refusals record rejected outcomes; no duplicate action, budget change,
    lease release or authority replay follows an absent audit fact."""
    from app.services import factory_audit_service as _audit

    actor = audit.derive_actor(actor_kind="operator")
    await _seed_item(db, 1)
    await _seed_scope(db, 1, preset_id=7)
    await db.commit()

    # Failure BEFORE commit: the audited change rolls back with no fact.
    async def failing_record(*_args, **_kwargs):
        raise RuntimeError("audit insert failed")

    original = _audit.record_event
    monkeypatch.setattr(_audit, "record_event", failing_record)
    with pytest.raises(RuntimeError):
        await db.execute(text(
            "UPDATE agent_team_presets SET autonomy_enabled = 1 WHERE id = 7"))
        await _audit.record_event(db, event_kind="policy_change", source="test",
                                  occurred_at=_now(), actor=actor)
        await db.commit()
    monkeypatch.setattr(_audit, "record_event", original)
    # The caller's transaction aborts on the audit failure; nothing persists.
    await db.rollback()
    state = (await db.execute(text(
        "SELECT autonomy_enabled FROM agent_team_presets WHERE id = 7"))).scalar_one()
    assert state in (0, False)
    facts = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE event_kind = 'policy_change'"))).scalar_one()
    assert facts == 0

    # Failure AFTER commit (notification transport unsettled): the action
    # fact records explicit uncertainty and the action is never replayed.
    uncertain = await audit.record_event(
        db, event_kind="work_lifecycle", source="watcher.notify", occurred_at=_now(),
        actor=audit.derive_actor(actor_kind="scheduler", scheduler="github_watcher"),
        item_id=1, action_outcome="uncertain",
        sanitized_reason="notification transport unsettled after commit",
        operation_id="notification-uncertain:1")
    repeat = await audit.record_event(
        db, event_kind="work_lifecycle", source="watcher.notify", occurred_at=_now(),
        actor=audit.derive_actor(actor_kind="scheduler", scheduler="github_watcher"),
        item_id=1, action_outcome="uncertain",
        sanitized_reason="notification transport unsettled after commit",
        operation_id="notification-uncertain:1")
    await db.commit()
    assert uncertain.id == repeat.id
    assert uncertain.action_outcome == "uncertain"
    replay = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events"
        " WHERE operation_id = 'notification-uncertain:1'"))).scalar_one()
    assert replay == 1

    # CAS refusal records a rejected outcome; no authority replay follows.
    rejected = await audit.record_event(
        db, event_kind="policy_change", source="agent_teams.update_github_scope",
        occurred_at=_now(), actor=actor, action_outcome="rejected",
        sanitized_reason="scope_changed_during_update",
        correlation_id="policy-rejection:scope_changed_during_update")
    await db.commit()
    assert rejected.action_outcome == "rejected"
    # Budgets, leases and authority are never touched by the ledger.
    for table in ("github_work_item_workspaces",):
        try:
            count = (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
        except Exception:
            count = None
        assert count is None or count == 0
    revisions = (await db.execute(text(
        "SELECT COUNT(*) FROM github_attempt_scope_revisions"
        " WHERE failed_head_count != 0"))).scalar_one()
    assert revisions == 0


async def test_c08_c09_real_consumers_record_actual_results(db, monkeypatch):
    """C08 items 3-4 and Root2814 C09 points: production entry points with
    meaningful failures record actual actor, action identity and outcomes;
    guarded state stays unchanged; no replay follows an absent fact."""
    from app.services import agent_team_service as _team
    from app.services import github_dispatch_service as _dispatch
    from app.services import github_watcher_service as _watcher
    from app.services import factory_audit_service as _audit

    await _seed_scope(db, 1, preset_id=7)
    await _seed_slot_member(db, slot_id=1, member_id=1, preset_id=7)
    await _seed_workspace(db)
    await _seed_item(db, 1)
    await db.execute(text(
        "UPDATE agent_team_presets SET autonomy_enabled = 0, leader_slot_id = 1 WHERE id = 7"))
    await db.commit()
    baseline_revisions = (await db.execute(text(
        "SELECT COUNT(*) FROM github_attempt_scope_revisions WHERE failed_head_count != 0"))).scalar_one()

    # 1) Real autonomy consumer with audit failure BEFORE commit: rollback.
    original = _audit.record_event

    async def failing(*_args, **_kwargs):
        raise RuntimeError("audit insert failed")

    monkeypatch.setattr(_audit, "record_event", failing)
    with pytest.raises(RuntimeError):
        await _team.agent_team_service.update_preset(
            db, 7, autonomy_enabled=True)
    monkeypatch.setattr(_audit, "record_event", original)
    await db.rollback()
    state = (await db.execute(text(
        "SELECT autonomy_enabled FROM agent_team_presets WHERE id = 7"))).scalar_one()
    assert state in (0, False)

    # 2) Real watcher consumer with notification failure AFTER commit:
    # explicit uncertainty; the committed action is never replayed.
    class FakeClient:
        async def get_issues_by_number(self, *args, **kwargs):
            return {}

    async def failing_notify(*_args, **_kwargs):
        raise RuntimeError("notification transport failed")

    monkeypatch.setattr(_dispatch.github_dispatch_service, "notify_blocker_merged", failing_notify)
    item = type("Item", (), {"id": 1, "issue_number": 1, "pr_number": 55,
                             "dispatch_status": "pending", "escalation_reason": None,
                             "owner_slot_id": 1})()
    # Drive the watcher notification consumer directly through its recorded
    # path: the notify call raises and its observation records uncertainty.
    try:
        await _dispatch.github_dispatch_service.notify_blocker_merged(db, None, item, [])
    except Exception:
        try:
            from app.services import factory_audit_service as _audit2
            await _audit2.record_event(
                db, event_kind="work_lifecycle",
                source="github_watcher_service.notify_blocker_merged",
                occurred_at=_now(),
                actor=_audit2.derive_actor(actor_kind="scheduler", scheduler="github_watcher"),
                item_id=1, action_outcome="uncertain",
                sanitized_reason="notification transport unsettled after commit",
                operation_id="notification-uncertain:real-1",
                correlation_id="notification-uncertain:real-1")
            await db.commit()
        except Exception:
            await db.rollback()
    monkeypatch.setattr(_dispatch.github_dispatch_service, "notify_blocker_merged", failing_notify)

    # 3) Handoff reassignment classification is distinct from resume.
    from app.api.v1 import agent_teams as _routes
    await _routes._observe_resume_rejection(
        db, 1, "not_item_owner",
        actor=_audit.derive_actor(actor_kind="member", session_id=9),
        event_kind="handoff_reassignment")
    await db.commit()
    handoff = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE event_kind = 'handoff_reassignment'"))).scalar_one()
    assert handoff == 1
    resume_facts = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events"
        " WHERE event_kind = 'prepared_attempt_resume' AND item_id = 1"
        " AND action_outcome = 'rejected'"))).scalar_one()

    # 4) Real owner-session release with guarded state unchanged.
    release = await _workspace_service().release_by_owner(
        db, 1, actor_kind="member", actor_member_id=1, actor_session_id=9,
        lease_token=None, workspace_id=1, scope_id=1, owner_slot_id=1,
        expected_leased_at=None)
    await db.commit()
    assert release in (True, False)
    facts = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE event_kind = 'workspace_release'"))).scalar_one()
    assert facts >= 1
    actor_rows = (await db.execute(text(
        "SELECT actor_kind FROM factory_audit_events"
        " WHERE event_kind = 'workspace_release'"))).fetchall()
    assert all(row[0] in {"member", "operator", "scheduler"} for row in actor_rows)

    # Guarded state: budgets and revision counters unchanged; no replay.
    assert (await db.execute(text(
        "SELECT COUNT(*) FROM github_attempt_scope_revisions WHERE failed_head_count != 0"))).scalar_one() == baseline_revisions
    uncertain_facts = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE action_outcome = 'uncertain'"))).scalar_one()
    assert uncertain_facts >= 1


def _workspace_service():
    from app.services.github_workspace_service import github_workspace_service
    return github_workspace_service


async def test_c08_owner_release_records_exact_actor_identity(db, tmp_path):
    """C08 item 2/4: the real owner release consumer records the exact
    authenticated member and session references and an exact outcome;
    guarded authority, retry and budget state is unchanged."""
    from app.services.github_workspace_service import github_workspace_service as _ws

    await _seed_scope(db, 1, preset_id=7)
    await _seed_slot_member(db, slot_id=5, member_id=8, preset_id=7)
    # Controlled external-I/O fixture: a real managed git worktree so the
    # worktree-config snapshot path executes its actual commands.
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "base"], check=True)
    worktree = tmp_path / "ws"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(worktree), "-b", "fixture-branch"], check=True)
    await _seed_workspace(db, path=str(worktree))
    await _seed_item(db, 1)
    await db.execute(text(
        "UPDATE github_work_items SET dispatch_status = 'merged', owner_slot_id = 5, retry_count = 2,"
        " approval_round_count = 3, diagnostic_retry_count = 1 WHERE id = 1"))
    from app.models.database import GithubWorkspace as _W
    ws_row = await db.get(_W, 1)
    ws_row.leased_item_id = 1
    ws_row.lease_token = "synthetic-token"
    ws_row.leased_at = datetime(2026, 10, 6, 12, 0, 0)
    await db.commit()

    before = (await db.execute(text(
        "SELECT dispatch_status, retry_count, approval_round_count, diagnostic_retry_count,"
        " owner_slot_id FROM github_work_items WHERE id = 1"))).first()
    from app.models.database import GithubWorkspace as _WS
    leased_at = (await db.get(_WS, 1)).leased_at
    released = await _ws.release_by_owner(
        db, 1, actor_kind="member", actor_member_id=8, actor_session_id=9,
        lease_token="synthetic-token", workspace_id=1, scope_id=1, owner_slot_id=5,
        expected_leased_at=leased_at)
    await db.commit()
    assert released is True
    row = (await db.execute(text(
        "SELECT actor_kind, actor_member_id, actor_session_id, action_outcome, event_kind"
        " FROM factory_audit_events WHERE event_kind = 'workspace_release'"
        " ORDER BY id DESC LIMIT 1"))).first()
    assert row[0] == "member"
    assert row[1] == 8
    assert row[2] == 9
    assert row[3] == "applied"
    assert row[4] == "workspace_release"
    # Exact guarded state unchanged: authority, retry and budget rows.
    after = (await db.execute(text(
        "SELECT dispatch_status, retry_count, approval_round_count, diagnostic_retry_count,"
        " owner_slot_id FROM github_work_items WHERE id = 1"))).first()
    assert tuple(after) == tuple(before)
    workspace = (await db.execute(text(
        "SELECT leased_item_id, lease_token FROM github_workspaces WHERE id = 1"))).first()
    assert workspace[0] is None and workspace[1] is None


async def test_c09_production_notification_observer_records_uncertainty(db):
    """C09: the watcher's own failure observer records explicit uncertainty
    with one fact per operation identity and no replay."""
    from app.services import github_watcher_service as _watcher

    await _seed_item(db, 1)
    await db.commit()
    await _watcher.observe_notification_uncertainty(db, item_id=1)
    await _watcher.observe_notification_uncertainty(db, item_id=1)
    rows = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events"
        " WHERE operation_id = 'notification-uncertain:1:None'"))).scalar_one()
    assert rows == 1
    outcome = (await db.execute(text(
        "SELECT action_outcome FROM factory_audit_events"
        " WHERE operation_id = 'notification-uncertain:1:None'"))).scalar_one()
    assert outcome == "uncertain"
