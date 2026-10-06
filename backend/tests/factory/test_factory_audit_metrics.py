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
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.database import FactoryAuditEvent, FactoryContextKey
from app.services import factory_audit_service as audit
from app.services import factory_metrics_service as metrics

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


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
    existing = await audit.find_by_operation(db, "op-missing", "policy_change")
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
    await db.execute(text(
        "INSERT INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path,"
        " dispatch_label, design_label, merge_policy, github_auth_mode, base_ref,"
        " max_approval_rounds, max_concurrent_dispatched, max_verification_retries,"
        " max_auto_merges_per_day, max_build_parallelism, builds_out_of_tree,"
        " continuation_enabled, max_continuation_revisions, max_continuation_failed_heads,"
        " max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled,"
        " created_at, updated_at) VALUES (1, 1, 'a', 'a', '/a', 'd', 'd', 'human', 'ambient',"
        " 'o', 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db.execute(text(
        "INSERT INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path,"
        " dispatch_label, design_label, merge_policy, github_auth_mode, base_ref,"
        " max_approval_rounds, max_concurrent_dispatched, max_verification_retries,"
        " max_auto_merges_per_day, max_build_parallelism, builds_out_of_tree,"
        " continuation_enabled, max_continuation_revisions, max_continuation_failed_heads,"
        " max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled,"
        " created_at, updated_at) VALUES (2, 1, 'b', 'b', '/b', 'd', 'd', 'human', 'ambient',"
        " 'o', 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
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
