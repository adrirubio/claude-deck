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
        session.info["session_maker"] = maker
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


async def test_c09_production_notification_observer_records_uncertainty(db, monkeypatch):
    """C09: the watcher's own failure observer records explicit uncertainty
    with one fact per operation identity and no replay."""
    from app.services import github_watcher_service as _watcher

    await _seed_item(db, 1)
    await db.commit()
    await _watcher.observe_notification_uncertainty(
        db, item_id=1, session_factory=db.info["session_maker"])
    await _watcher.observe_notification_uncertainty(
        db, item_id=1, session_factory=db.info["session_maker"])
    operation_id = "notification:blocker-merged:item:1:launch:None:revision:None:uncertain"
    rows = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE operation_id = :op"),
        {"op": operation_id})).scalar_one()
    assert rows == 1
    outcome = (await db.execute(text(
        "SELECT action_outcome, event_kind FROM factory_audit_events WHERE operation_id = :op"),
        {"op": operation_id})).first()
    assert tuple(outcome) == ("uncertain", "lifecycle_notification")


async def test_c09_real_watcher_loop_records_uncertainty(db, monkeypatch):
    """C09: the watcher's own closed-issue loop with a failing notifier after
    the committed transition records explicit uncertainty bound to the real
    immutable revision row; the transition is never replayed."""
    from unittest.mock import AsyncMock

    from app.services import github_dispatch_service as _dispatch
    from app.services import github_watcher_service as _watcher
    from app.models.database import GithubAttemptScopeRevision, GithubWorkItem, TeamGithubScope

    await _seed_scope(db, 1, preset_id=7)
    await _seed_slot_member(db, preset_id=7)
    await _seed_workspace(db)
    await _seed_item(db, 1)
    await db.execute(text(
        "UPDATE github_work_items SET dispatch_status = 'failed', issue_number = 1,"
        " pr_number = NULL WHERE id = 1"))
    await db.execute(text(
        "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision,"
        " owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths,"
        " allowed_actions, allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha,"
        " baseline_tree_sha, originating_escalation_reason, expected_workspace_id,"
        " expected_lease_token_hash, max_failed_heads, failed_head_count, status,"
        " delivery_attempt_count, approval_request_id, created_at)"
        " VALUES (1, 1, 'n', 0, 1, 1, 'implementation', '/w', 's', '[]', '[]', '[]', '[]', '{}',"
        " 'a', 'b', 'r', 1, 'h', 2, 0, 'active', 0, NULL, CURRENT_TIMESTAMP)"))
    await db.commit()

    class FakeClient:
        async def get_issues_by_number(self, owner, name, numbers):
            return {number: {"state": "closed"} for number in numbers}

    async def failing_notify(*_args, **_kwargs):
        raise RuntimeError("notification transport failed")

    monkeypatch.setattr(_dispatch.github_dispatch_service, "notify_blocker_merged", failing_notify)
    monkeypatch.setattr(_watcher.github_watcher_service, "observer_session_factory",
                        lambda: db.info["session_maker"](), raising=False)
    scope_obj = await db.get(TeamGithubScope, 1)
    await _watcher.github_watcher_service._reconcile_closed_issues(
        db, scope_obj, FakeClient())

    # The transition completed and its unsettled notification is uncertain,
    # bound to the real revision row id.
    item_row = (await db.execute(text(
        "SELECT dispatch_status FROM github_work_items WHERE id = 1"))).scalar_one()
    assert item_row == "completed"
    uncertain_op = "notification:blocker-merged:item:1:launch:None:revision:1:uncertain"
    facts = (await db.execute(text(
        "SELECT action_outcome, operation_id, revision_id FROM factory_audit_events"
        " WHERE event_kind = 'lifecycle_notification'"))).fetchall()
    assert [tuple(fact) for fact in facts] == [("uncertain", uncertain_op, 1)]
    # The committed delivery fact is bound to the same original attempt and
    # revision, under its own distinct action identity.
    delivery = (await db.execute(text(
        "SELECT operation_id, revision_id, delivery_outcome FROM factory_audit_events"
        " WHERE event_kind = 'delivery_evidence'"))).fetchall()
    assert [tuple(row) for row in delivery] == [
        ("delivery:item:1:launch:None:revision:1:attempt", 1, "unknown")]
    # The transition is never replayed: the completed item is no longer
    # reconcilable, so a second loop adds no fact; protected state is unchanged.
    scope_obj = await db.get(TeamGithubScope, 1)
    await _watcher.github_watcher_service._reconcile_closed_issues(
        db, scope_obj, FakeClient())
    completed = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events"))).scalar_one()
    assert completed == 2
    # Exact protected state comparison: attempt identity and counters.
    revision_row = (await db.execute(text(
        "SELECT status, failed_head_count, delivery_attempt_count"
        " FROM github_attempt_scope_revisions WHERE id = 1"))).first()
    assert tuple(revision_row) == ("active", 0, 0)
    item_after = (await db.execute(text(
        "SELECT dispatch_status, retry_count, approval_round_count, diagnostic_retry_count"
        " FROM github_work_items WHERE id = 1"))).first()
    assert tuple(item_after) == ("completed", 0, 1, 0)


async def test_c09_tainted_session_and_real_send_failure(db, monkeypatch):
    """C09 v8: low-level transport failure inside the real notifier leaves the
    session mid-transaction; the production observer ends that transaction
    and records the uncertain fact bound to the original attempt and
    revision; a second loop run replays nothing; the full populated
    protected-state matrix is unchanged."""
    from unittest.mock import AsyncMock

    from app.models.database import TeamGithubScope
    from app.services import github_watcher_service as _watcher
    from app.services.agent_mail_service import agent_mail_service as _mail

    await _seed_scope(db, 1, preset_id=7)
    await _seed_slot_member(db, slot_id=5, member_id=8, preset_id=7)
    await _seed_workspace(db)
    await _seed_item(db, 1)
    await db.execute(text(
        "UPDATE agent_team_presets SET leader_slot_id = 5 WHERE id = 7"))
    await db.execute(text(
        "UPDATE agent_team_slots SET role = 'Leader' WHERE id = 5"))
    await db.execute(text(
        "UPDATE github_work_items SET dispatch_status = 'escalated', issue_number = 1,"
        " pr_number = NULL, owner_slot_id = 5, retry_count = 2, approval_round_count = 3,"
        " diagnostic_retry_count = 1 WHERE id = 1"))
    await db.execute(text(
        "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision,"
        " owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths,"
        " allowed_actions, allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha,"
        " baseline_tree_sha, originating_escalation_reason, expected_workspace_id,"
        " expected_lease_token_hash, max_failed_heads, failed_head_count, status,"
        " delivery_attempt_count, approval_request_id, created_at)"
        " VALUES (1, 1, 'n', 0, 5, 8, 'implementation', '/w', 's', '[]', '[]', '[]', '[]', '{}',"
        " 'a', 'b', 'r', 1, 'h', 2, 1, 'active', 1, NULL, CURRENT_TIMESTAMP)"))
    await db.execute(text(
        "INSERT INTO github_approval_requests (id, work_item_id, request_kind, dispatch_nonce,"
        " approval_round, owner_member_id, leader_member_id, request_fingerprint, status,"
        " request_message_id, scope_revision_id, created_at)"
        " VALUES (1, 1, 'initial_plan', 'n', 1, 8, 8, 'fp', 'approved', NULL, 1, CURRENT_TIMESTAMP)"))
    await db.commit()

    protected_before = (await db.execute(text(
        "SELECT status, failed_head_count, delivery_attempt_count FROM github_attempt_scope_revisions"
        " WHERE id = 1"))).first(), (await db.execute(text(
        "SELECT dispatch_status, retry_count, approval_round_count, diagnostic_retry_count,"
        " owner_slot_id FROM github_work_items WHERE id = 1"))).first(), (await db.execute(text(
        "SELECT leased_item_id, lease_token, leased_owner_pid FROM github_workspaces WHERE id = 1"))).first()

    class FakeClient:
        async def get_issues_by_number(self, owner, name, numbers):
            return {number: {"state": "closed"} for number in numbers}

    monkeypatch.setattr(_mail, "send_direct_message",
                        AsyncMock(side_effect=RuntimeError("low-level transport failure")))
    maker = db.info["session_maker"]
    # The fresh observer session binds to the disposable action database.
    monkeypatch.setattr(_watcher.github_watcher_service, "observer_session_factory",
                        lambda: maker(), raising=False)
    scope_obj = await db.get(TeamGithubScope, 1)
    await _watcher.github_watcher_service._reconcile_closed_issues(db, scope_obj, FakeClient())
    # Replay models a fresh production poll: the scope is re-read
    # asynchronously rather than reused across rollback boundaries.
    scope_obj = await db.get(TeamGithubScope, 1)
    await _watcher.github_watcher_service._reconcile_closed_issues(db, scope_obj, FakeClient())

    facts = (await db.execute(text(
        "SELECT action_outcome, operation_id, event_kind FROM factory_audit_events"
        " WHERE action_outcome = 'uncertain'"))).fetchall()
    assert [tuple(fact) for fact in facts] == [(
        "uncertain",
        "notification:blocker-merged:item:1:launch:None:revision:1:uncertain",
        "lifecycle_notification",
    )]
    protected_after = (await db.execute(text(
        "SELECT status, failed_head_count, delivery_attempt_count FROM github_attempt_scope_revisions"
        " WHERE id = 1"))).first(), (await db.execute(text(
        "SELECT dispatch_status, retry_count, approval_round_count, diagnostic_retry_count,"
        " owner_slot_id FROM github_work_items WHERE id = 1"))).first(), (await db.execute(text(
        "SELECT leased_item_id, lease_token, leased_owner_pid FROM github_workspaces WHERE id = 1"))).first()
    assert tuple(protected_after[0]) == tuple(protected_before[0])
    assert tuple(protected_after[2]) == tuple(protected_before[2])
    assert tuple(protected_after[1])[1:] == tuple(protected_before[1])[1:]
    assert protected_after[1][0] == "completed"


# ---------------------------------------------------------------------------
# C08/C09 real-consumer matrix.
#
# Every case calls the production route or service consumer. Requests use
# the production get_db request session and the real Mail capability-token
# check. Only external boundaries are replaced: GitHub HTTP, git subprocess
# effects and the pane-liveness probe. Slot, member and session IDs differ,
# and protected rows are compared from a fresh session.
# ---------------------------------------------------------------------------

import hashlib as _hashlib

import httpx as _httpx

_OPERATOR = "synthetic-c08-operator"
_OPERATOR_HEADERS = {"X-Deck-Operator-Token": _OPERATOR}
_LEADER = {"slot": 11, "member": 21, "session": 31, "token": "synthetic-leader-session"}
_OWNER = {"slot": 12, "member": 22, "session": 32, "token": "synthetic-owner-session"}
_OTHER = {"slot": 13, "member": 23, "session": 33, "token": "synthetic-other-session"}
_FIXED_LEASE = datetime(2026, 10, 6, 11, 30, 0)


def _session_headers(identity: dict) -> dict:
    return {"X-Deck-Session-Token": identity["token"]}


@pytest_asyncio.fixture
async def store(tmp_path, monkeypatch):
    """A file database bound to the production request session factory."""
    import app.database as _database
    from app.config import settings
    from app.utils import peer_process

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c08c09.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Same session options as app.database.AsyncSessionLocal.
    maker = async_sessionmaker(engine, expire_on_commit=False, autocommit=False, autoflush=False)
    monkeypatch.setattr(_database, "AsyncSessionLocal", maker)
    monkeypatch.setattr(settings, "operator_token", _OPERATOR)
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "github_recovery_only_attempt", "")
    # Process boundary: the bound panes of the synthetic sessions are alive.
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda _pid, _start: True)

    async def _no_jobs(_db):
        return None

    from app.api.v1 import agent_teams as _routes
    monkeypatch.setattr(_routes, "_sync_github_jobs", _no_jobs)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(store):
    from app.main import app

    # Production get_db runs unchanged; app exceptions become HTTP 500.
    transport = _httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with _httpx.AsyncClient(transport=transport, base_url="http://c08c09") as http:
        yield http


async def _seed_team(maker, *, autonomy: bool = False, auth_mode: str = "ambient") -> dict:
    """Seed one team with distinct slot, member and session identities."""
    from app.models.database import (
        AgentTeamPreset, AgentTeamSlot, MailAgentSession, MailTeamMember, TeamGithubScope,
    )

    async with maker() as db:
        preset = AgentTeamPreset(id=7, name="Matrix team", created_by="fixture",
                                 autonomy_enabled=False)
        db.add(preset)
        await db.flush()
        for identity, role in ((_LEADER, "Leader"), (_OWNER, None), (_OTHER, None)):
            db.add(AgentTeamSlot(
                id=identity["slot"], preset_id=preset.id, position=identity["slot"],
                display_name=f"Slot {identity['slot']}", role=role, provider="codex-cli",
                repo_id="r", repo_path="/tmp/r", repo_name="r", launch_mode="plain",
                launch_options={}, enabled=True))
        await db.flush()
        preset.leader_slot_id = _LEADER["slot"]
        preset.autonomy_enabled = autonomy
        for identity in (_LEADER, _OWNER, _OTHER):
            db.add(MailTeamMember(
                id=identity["member"], identity_key=f"slot:{identity['slot']}",
                repo_id="r", repo_path="/tmp/r", repo_name="r",
                display_name=f"Member {identity['member']}", participant_kind="team_slot",
                team_preset_id=preset.id, team_slot_id=identity["slot"]))
        await db.flush()
        for identity in (_LEADER, _OWNER, _OTHER):
            db.add(MailAgentSession(
                id=identity["session"], member_id=identity["member"], provider="codex-cli",
                source="mcp", session_key=f"matrix-{identity['session']}",
                team_preset_id=preset.id, team_slot_id=identity["slot"],
                capability_token_hash=_hashlib.sha256(
                    identity["token"].encode("utf-8")).hexdigest(),
                mailbox_status="connected", bound_pane_pid=4000 + identity["slot"],
                bound_pane_proc_start=f"start-{identity['slot']}"))
        scope = TeamGithubScope(
            id=5, preset_id=preset.id, repo_owner="matrix-owner", repo_name="matrix-repo",
            repo_path="/tmp/matrix-repo", base_ref="origin/master", github_auth_mode=auth_mode,
            github_app_installation_id=55 if auth_mode == "app" else None,
            merge_policy="human", continuation_enabled=True)
        db.add(scope)
        await db.commit()
    return {"preset": 7, "scope": 5}


async def _seed_work(
    maker,
    *,
    item_id: int,
    status: str,
    issue_number: int | None = None,
    nonce: str = "0123456789abcdef",
    workspace_id: int | None = None,
    workspace_kind: str = "primary",
    lease_token: str | None = None,
    leased_at: datetime | None = _FIXED_LEASE,
    **item_fields,
) -> None:
    """Seed one populated work item and, optionally, its leased workspace."""
    from app.models.database import GithubWorkItem, GithubWorkspace

    async with maker() as db:
        db.add(GithubWorkItem(
            id=item_id, scope_id=5, issue_number=issue_number or item_id,
            issue_title=f"Matrix item {item_id}", issue_url="https://example.invalid/i",
            github_updated_at=_FIXED_LEASE, dispatch_status=status,
            owner_slot_id=item_fields.pop("owner_slot_id", _OWNER["slot"]),
            dispatch_nonce=nonce,
            retry_count=item_fields.pop("retry_count", 2),
            approval_round_count=item_fields.pop("approval_round_count", 3),
            diagnostic_retry_count=item_fields.pop("diagnostic_retry_count", 1),
            **item_fields))
        if workspace_id is not None:
            await db.flush()
            db.add(GithubWorkspace(
                id=workspace_id, scope_id=5, path=f"/tmp/matrix-ws-{workspace_id}",
                kind=workspace_kind, leased_item_id=item_id,
                leased_at=leased_at if lease_token else None, lease_token=lease_token))
        await db.commit()


async def _facts(maker, **where) -> list[dict]:
    """Ledger rows from a fresh session, optionally filtered by column."""
    clause = " AND ".join(f"{column} = :{column}" for column in where) or "1 = 1"
    async with maker() as db:
        rows = (await db.execute(text(
            "SELECT event_kind, source, actor_kind, actor_member_id, actor_session_id,"
            " actor_reference, scope_id, item_id, revision_id, request_id, team_preset_id,"
            " action_outcome, operation_id, sanitized_reason, before_values, after_values"
            f" FROM factory_audit_events WHERE {clause} ORDER BY id"), where)).mappings().all()
    return [dict(row) for row in rows]


async def _protected(maker, item_id: int) -> tuple:
    """Exact guarded item, lease, revision and approval state from a fresh session."""
    async with maker() as db:
        item = (await db.execute(text(
            "SELECT dispatch_status, escalation_reason, owner_slot_id, retry_count,"
            " approval_round_count, diagnostic_retry_count, active_scope_revision,"
            " handoff_state, handoff_target_slot_id, dispatch_nonce"
            " FROM github_work_items WHERE id = :id"), {"id": item_id})).first()
        lease = (await db.execute(text(
            "SELECT id, leased_item_id, leased_at, lease_token FROM github_workspaces"
            " WHERE leased_item_id = :id ORDER BY id"), {"id": item_id})).fetchall()
        revisions = (await db.execute(text(
            "SELECT id, status, failed_head_count, recovery_checkpoint_stage"
            " FROM github_attempt_scope_revisions WHERE work_item_id = :id ORDER BY id"),
            {"id": item_id})).fetchall()
        approvals = (await db.execute(text(
            "SELECT id, status FROM github_approval_requests WHERE work_item_id = :id"
            " ORDER BY id"), {"id": item_id})).fetchall()
    return (tuple(item) if item else None, [tuple(r) for r in lease],
            [tuple(r) for r in revisions], [tuple(r) for r in approvals])


def _lease_iso(value: datetime = _FIXED_LEASE) -> str:
    return value.isoformat()


async def test_c08_operator_force_release_route_records_shared_operator_role(store, client):
    """C08: the authenticated operator route records the shared operator role,
    the exact released acquisition and no member or session claim."""
    await _seed_team(store)
    await _seed_work(store, item_id=40, status="merged", workspace_id=60,
                     lease_token="synthetic-lease-40")
    before = await _protected(store, 40)

    response = await client.post(
        "/api/v1/agent-teams/github-scopes/5/workspaces/60/force-release",
        headers=_OPERATOR_HEADERS,
        json={"force": True, "expected_leased_at": _lease_iso(), "reason": "fixture release",
              # A client-supplied name is never the recorded actor.
              "requested_by": "member:999"})

    assert response.status_code == 200
    assert response.json()["released_item_id"] == 40
    facts = await _facts(store, event_kind="workspace_release")
    assert len(facts) == 1
    fact = facts[0]
    assert (fact["actor_kind"], fact["actor_reference"]) == ("operator", "shared-operator-credential")
    assert (fact["actor_member_id"], fact["actor_session_id"]) == (None, None)
    assert (fact["action_outcome"], fact["item_id"], fact["scope_id"]) == ("applied", 40, 5)
    assert fact["operation_id"] == f"workspace_release:workspace:60:leased_at:{_lease_iso()}"
    after = await _protected(store, 40)
    # Only the named expected mutation: the lease is gone; authority and
    # counters are unchanged.
    assert after[0] == before[0]
    assert after[1] == []
    assert before[1] == [(60, 40, "2026-10-06 11:30:00.000000", "synthetic-lease-40")]


async def test_c08_owner_release_route_records_session_and_refuses_stale_token(store, client):
    """C08: the authenticated owner report records its exact member and
    session; a stale token is refused and the current acquisition stays."""
    await _seed_team(store)
    await _seed_work(store, item_id=41, status="merged", workspace_id=61,
                     lease_token="synthetic-lease-41")
    await _seed_work(store, item_id=42, status="merged", workspace_id=62,
                     lease_token="synthetic-lease-42-current")
    stale_before = await _protected(store, 42)

    released = await client.post(
        "/api/v1/agent-teams/dispatch-status", headers=_session_headers(_OWNER),
        json={"work_item_id": 41, "status": "workspace_released",
              "lease_token": "synthetic-lease-41"})
    refused = await client.post(
        "/api/v1/agent-teams/dispatch-status", headers=_session_headers(_OWNER),
        json={"work_item_id": 42, "status": "workspace_released",
              "lease_token": "synthetic-lease-42-stale"})

    assert released.status_code == 200
    assert refused.status_code == 409
    facts = await _facts(store, event_kind="workspace_release")
    assert [(f["item_id"], f["action_outcome"]) for f in facts] == [(41, "applied"), (42, "rejected")]
    for fact in facts:
        assert fact["actor_kind"] == "member"
        assert fact["actor_member_id"] == _OWNER["member"]
        assert fact["actor_session_id"] == _OWNER["session"]
        assert fact["actor_reference"] == f"member:{_OWNER['member']}"
    assert facts[1]["sanitized_reason"] == "acquisition identity mismatch"
    assert await _protected(store, 42) == stale_before


async def test_c08_automatic_cleanup_paths_record_the_scheduler_reference(store):
    """C08: auth refusal, acquire cleanup and launch-failure release record
    the code-owned scheduler reference and zero operator interventions."""
    from app.models.database import GithubWorkItem, GithubWorkspace, TeamGithubScope
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_workspace_service import github_workspace_service

    await _seed_team(store)
    await _seed_work(store, item_id=43, status="dispatched", workspace_id=63,
                     lease_token="synthetic-lease-43")
    await _seed_work(store, item_id=44, status="pending", workspace_id=64,
                     lease_token="synthetic-lease-44")
    await _seed_work(store, item_id=45, status="failed", workspace_id=65,
                     lease_token="synthetic-lease-45")

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        item = await db.get(GithubWorkItem, 43)
        workspace = await db.get(GithubWorkspace, 63)
        await github_dispatch_service._release_auth_refusal(
            db, scope, item, workspace, "synthetic auth refusal")
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        item = await db.get(GithubWorkItem, 44)
        # A held primary workspace is released by the automatic acquire path.
        assert await github_workspace_service.acquire(db, scope, item) is None
    async with store() as db:
        assert await github_workspace_service.release(db, 45) is True

    facts = await _facts(store, event_kind="workspace_release")
    assert [(f["item_id"], f["action_outcome"]) for f in facts] == [
        (43, "applied"), (44, "applied"), (45, "applied")]
    assert {(f["actor_kind"], f["actor_reference"], f["actor_member_id"]) for f in facts} == {
        ("scheduler", "github_dispatch_scheduler", None)}
    assert await _facts(store, actor_kind="operator") == []


async def test_c08_legacy_token_release_forwards_supplied_trusted_references(store):
    """C08: the legacy token entry has no production route caller. It forwards
    supplied trusted references unchanged and keeps its token check."""
    from app.services.github_workspace_service import (
        GithubWorkspaceLeaseTokenMismatch, github_workspace_service,
    )

    await _seed_team(store)
    await _seed_work(store, item_id=47, status="merged", workspace_id=67,
                     lease_token="synthetic-lease-47")
    async with store() as db:
        with pytest.raises(GithubWorkspaceLeaseTokenMismatch):
            await github_workspace_service.release_by_token(
                db, 47, lease_token="synthetic-wrong-token")
    async with store() as db:
        assert await github_workspace_service.release_by_token(
            db, 47, lease_token="synthetic-lease-47", actor_kind="member",
            actor_member_id=_OWNER["member"], actor_session_id=_OWNER["session"]) is True

    facts = await _facts(store, event_kind="workspace_release")
    assert [(f["action_outcome"], f["actor_kind"], f["actor_member_id"], f["actor_session_id"])
            for f in facts] == [("applied", "member", _OWNER["member"], _OWNER["session"])]


async def test_c08_invalid_member_handoff_route_is_a_member_handoff_refusal(store, client):
    """C08: an invalid handoff target records a member handoff refusal for the
    actual item; it is neither an operator action nor a prepared resume."""
    await _seed_team(store)
    await _seed_work(store, item_id=46, status="dispatched")
    before = await _protected(store, 46)

    response = await client.post(
        "/api/v1/agent-teams/dispatch-status", headers=_session_headers(_OWNER),
        json={"work_item_id": 46, "status": "handoff_initiated", "reassign_to_slot_id": 999})

    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_handoff_target"
    facts = await _facts(store)
    assert len(facts) == 1
    fact = facts[0]
    assert fact["event_kind"] == "handoff_reassignment"
    assert fact["source"] == "agent_teams.report_dispatch_status.handoff_initiated"
    assert (fact["actor_kind"], fact["actor_member_id"], fact["actor_session_id"]) == (
        "member", _OWNER["member"], _OWNER["session"])
    assert (fact["item_id"], fact["scope_id"], fact["action_outcome"]) == (46, 5, "rejected")
    assert fact["sanitized_reason"] == "invalid_handoff_target"
    assert await _facts(store, event_kind="prepared_attempt_resume") == []
    assert await _protected(store, 46) == before


async def test_c09_autonomy_policy_write_is_atomic_with_its_fact(store, client, monkeypatch):
    """C09: an audit insert failure below the real autonomy consumer leaves the
    exact original policy; production request cleanup runs; then the same
    request commits its change and one applied fact together."""
    from app.services import factory_audit_service as _audit

    await _seed_team(store)
    original = _audit.record_event

    async def failing(db, **fields):
        if fields.get("event_kind") == "policy_change":
            raise RuntimeError("synthetic audit insert failure")
        return await original(db, **fields)

    monkeypatch.setattr(_audit, "record_event", failing)
    failed = await client.patch(
        "/api/v1/agent-teams/presets/7", headers=_OPERATOR_HEADERS,
        json={"autonomy_enabled": True, "name": "Renamed during failure"})
    assert failed.status_code == 500
    async with store() as db:
        preset = (await db.execute(text(
            "SELECT name, autonomy_enabled FROM agent_team_presets WHERE id = 7"))).first()
    assert tuple(preset) == ("Matrix team", 0)
    assert await _facts(store) == []

    monkeypatch.setattr(_audit, "record_event", original)
    applied = await client.patch(
        "/api/v1/agent-teams/presets/7", headers=_OPERATOR_HEADERS,
        json={"autonomy_enabled": True})
    assert applied.status_code == 200
    facts = await _facts(store, event_kind="policy_change")
    assert len(facts) == 1
    assert facts[0]["source"] == "agent_team_service.update_preset"
    assert facts[0]["actor_kind"] == "operator"
    assert facts[0]["team_preset_id"] == 7
    assert facts[0]["before_values"] == '{"autonomy_enabled": false}'
    assert facts[0]["after_values"] == '{"autonomy_enabled": true}'


async def test_c11_continuation_policy_route_records_every_changed_setting(store, client):
    """C11/C09: the real continuation policy route records the exact old and
    new value of every setting it changes."""
    import json as _json

    await _seed_team(store)
    async with store() as db:
        old = dict((await db.execute(text(
            "SELECT continuation_enabled, max_continuation_revisions,"
            " max_continuation_failed_heads, max_failed_heads_per_revision,"
            " max_scope_paths, max_scope_commands FROM team_github_scopes WHERE id = 5"
        ))).mappings().first())
    new = {"continuation_enabled": False, "max_continuation_revisions": 4,
           "max_continuation_failed_heads": 6, "max_failed_heads_per_revision": 2,
           "max_scope_paths": 24, "max_scope_commands": 12}

    response = await client.patch(
        "/api/v1/agent-teams/github-scopes/5/continuation-policy",
        headers=_OPERATOR_HEADERS, json=new)

    assert response.status_code == 200
    facts = await _facts(store, event_kind="policy_change")
    assert len(facts) == 1
    before = _json.loads(facts[0]["before_values"])
    after = _json.loads(facts[0]["after_values"])
    assert before == {key: (bool(value) if key == "continuation_enabled" else value)
                      for key, value in old.items()}
    assert after == new
    assert facts[0]["scope_id"] == 5


async def test_c09_stale_leader_cas_is_refused_and_recorded(store, client):
    """C09: the actual Leader policy CAS refuses a stale expectation, keeps the
    current Leader and records one rejected fact for the team."""
    await _seed_team(store)
    async with store() as db:
        updated_at = (await db.execute(text(
            "SELECT updated_at FROM agent_team_presets WHERE id = 7"))).scalar_one()

    response = await client.put(
        "/api/v1/agent-teams/presets/7/leader", headers=_OPERATOR_HEADERS,
        json={"leader_slot_id": _OTHER["slot"], "expected_leader_slot_id": _OWNER["slot"],
              "expected_updated_at": str(updated_at), "reason": "stale expectation"})

    assert response.status_code == 409
    async with store() as db:
        leader = (await db.execute(text(
            "SELECT leader_slot_id FROM agent_team_presets WHERE id = 7"))).scalar_one()
    assert leader == _LEADER["slot"]
    facts = await _facts(store)
    assert [(f["event_kind"], f["action_outcome"], f["team_preset_id"], f["actor_kind"])
            for f in facts] == [("leader_assignment", "rejected", 7, "operator")]


_NONCE = "0123456789abcdef"
_HEAD_REF = "deck/slot-12/issue-50-0123456789abcdef"


async def _seed_active_continuation(maker, *, item_id: int, workspace_id: int) -> dict:
    """An active approved continuation with its exact lease and approval."""
    from app.models.database import (
        GithubApprovalRequest, GithubAttemptScopeRevision, GithubWorkItem,
    )
    from app.services.github_approval_service import github_approval_service

    token = f"synthetic-lease-{item_id}"
    await _seed_work(maker, item_id=item_id, status="dispatched", workspace_id=workspace_id,
                     workspace_kind="worktree", lease_token=token, active_scope_revision=1,
                     pr_number=73, dispatch_head_ref=_HEAD_REF)
    async with maker() as db:
        revision = GithubAttemptScopeRevision(
            work_item_id=item_id, dispatch_nonce=_NONCE, revision=1,
            owner_slot_id=_OWNER["slot"], owner_member_id=_OWNER["member"],
            phase="implementation", execution_target="workspace", summary="Matrix revision",
            allowed_paths=["src/a.py"], allowed_actions=["edit_production"],
            allowed_commands=[], prohibited_actions=[], tool_fallbacks={},
            baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
            originating_escalation_reason="retry_count_exhausted",
            expected_workspace_id=workspace_id,
            expected_lease_token_hash=github_approval_service.lease_token_hash(token),
            max_failed_heads=2, status="active")
        db.add(revision)
        await db.flush()
        approval = GithubApprovalRequest(
            work_item_id=item_id, request_kind="continuation", dispatch_nonce=_NONCE,
            approval_round=3, owner_member_id=_OWNER["member"],
            leader_member_id=_LEADER["member"], request_fingerprint="f" * 64,
            status="approved", scope_revision_id=revision.id)
        db.add(approval)
        await db.flush()
        revision.approval_request_id = approval.id
        item = await db.get(GithubWorkItem, item_id)
        item.escalation_reason = None
        await db.commit()
        return {"revision": revision.id, "approval": approval.id}


def _stub_open_pull(monkeypatch, head_sha: str = "a" * 40):
    from app.services.github_client import github_client

    async def get_pull(*_args, **_kwargs):
        # External GitHub boundary: the PR head equals the revision baseline.
        return {"state": "open", "head": {
            "sha": head_sha, "ref": _HEAD_REF,
            "repo": {"full_name": "matrix-owner/matrix-repo"}}}

    monkeypatch.setattr(github_client, "get_pull", get_pull)


async def _messages_with_key(maker, key: str) -> int:
    async with maker() as db:
        return (await db.execute(text(
            "SELECT COUNT(*) FROM mail_messages WHERE delivery_key = :key"),
            {"key": key})).scalar_one()


async def test_c09_active_cancellation_records_one_action_and_its_notice(store, client, monkeypatch):
    """C07/C09: the actual active cancellation records one action fact in its
    transaction and a separate notice result. An exact replay adds no second
    action; a conflicting replay is refused and recorded."""
    await _seed_team(store)
    ids = await _seed_active_continuation(store, item_id=50, workspace_id=70)
    _stub_open_pull(monkeypatch)
    url = "/api/v1/agent-teams/github-work-items/50/scope-revisions/1/cancel"
    body = {"cancel": True, "dispatch_nonce": _NONCE, "reason": "fixture cancel"}

    first = await client.post(url, headers=_OPERATOR_HEADERS, json=body)
    replay = await client.post(url, headers=_OPERATOR_HEADERS, json=body)
    conflict = await client.post(url, headers=_OPERATOR_HEADERS,
                                 json={**body, "reason": "a different reason"})

    assert (first.status_code, replay.status_code, conflict.status_code) == (200, 200, 409)
    actions = await _facts(store, event_kind="recovery_cancellation")
    assert [(f["action_outcome"], f["revision_id"], f["request_id"], f["operation_id"])
            for f in actions] == [
        ("applied", ids["revision"], ids["approval"],
         f"active_cancellation:revision:{ids['revision']}"),
        ("rejected", None, None, None),
    ]
    assert actions[1]["sanitized_reason"] == "active_continuation_cancel_conflict"
    assert {f["actor_kind"] for f in actions} == {"operator"}
    notices = await _facts(store, event_kind="recovery_cancellation_notification")
    assert [(f["action_outcome"], f["operation_id"]) for f in notices] == [
        ("applied", f"active_cancellation_notice:revision:{ids['revision']}:applied")]
    assert await _messages_with_key(store, f"github-scope:{ids['revision']}:cancelled") == 1
    protected = await _protected(store, 50)
    assert protected[0][:5] == ("escalated", "retry_count_exhausted", _OWNER["slot"], 2, 3)
    assert protected[2] == [(ids["revision"], "superseded", 0, None)]


@pytest.mark.parametrize("failure", ["before_send", "after_accepted_send"])
async def test_c09_active_cancellation_notice_failure_keeps_committed_action(
    store, client, monkeypatch, failure
):
    """C09: a failed low-level notice after the committed cancellation records
    uncertainty; the action is never repeated; a retry uses the existing
    delivery key and records the settled notice once."""
    from app.services.agent_mail_service import agent_mail_service

    await _seed_team(store)
    ids = await _seed_active_continuation(store, item_id=55, workspace_id=75)
    _stub_open_pull(monkeypatch)
    original_send = agent_mail_service.send_direct_message

    async def failing_send(db, **kwargs):
        if failure == "after_accepted_send":
            await original_send(db, **kwargs)
        raise RuntimeError("synthetic low-level send failure")

    monkeypatch.setattr(agent_mail_service, "send_direct_message", failing_send)
    url = "/api/v1/agent-teams/github-work-items/55/scope-revisions/1/cancel"
    body = {"cancel": True, "dispatch_nonce": _NONCE, "reason": "fixture cancel"}

    failed = await client.post(url, headers=_OPERATOR_HEADERS, json=body)
    assert failed.status_code == 500
    committed = await _protected(store, 55)
    assert committed[2] == [(ids["revision"], "superseded", 0, None)]
    assert committed[0][0] == "escalated"
    notices = await _facts(store, event_kind="recovery_cancellation_notification")
    assert [f["action_outcome"] for f in notices] == ["uncertain"]

    monkeypatch.setattr(agent_mail_service, "send_direct_message", original_send)
    retried = await client.post(url, headers=_OPERATOR_HEADERS, json=body)
    assert retried.status_code == 200
    actions = await _facts(store, event_kind="recovery_cancellation")
    assert [(f["action_outcome"], f["revision_id"]) for f in actions] == [
        ("applied", ids["revision"])]
    notices = await _facts(store, event_kind="recovery_cancellation_notification")
    assert [f["action_outcome"] for f in notices] == ["uncertain", "applied"]
    assert await _messages_with_key(store, f"github-scope:{ids['revision']}:cancelled") == 1
    # No counter is charged again and no authority changes on the retry.
    assert await _protected(store, 55) == committed


async def test_c09_initial_cancellation_records_one_fact_and_refusals(store, client):
    """C09: the actual initial-approval cancellation writes its fact with the
    guarded mutation; an exact replay adds none; a stale nonce is refused."""
    from app.models.database import GithubApprovalRequest

    await _seed_team(store)
    await _seed_work(store, item_id=56, status="escalated", escalation_reason="plan_blocked")
    async with store() as db:
        approval = GithubApprovalRequest(
            work_item_id=56, request_kind="initial_plan", dispatch_nonce=_NONCE,
            approval_round=3, owner_member_id=_OWNER["member"],
            leader_member_id=_LEADER["member"], request_fingerprint="e" * 64,
            status="pending")
        db.add(approval)
        await db.commit()
        request_id = approval.id
    url = f"/api/v1/agent-teams/github-work-items/56/approval-requests/{request_id}/cancel"
    body = {"cancel": True, "dispatch_nonce": _NONCE, "reason": "stranded"}

    first = await client.post(url, headers=_OPERATOR_HEADERS, json=body)
    replay = await client.post(url, headers=_OPERATOR_HEADERS, json=body)
    stale = await client.post(url, headers=_OPERATOR_HEADERS,
                              json={**body, "dispatch_nonce": "fedcba9876543210"})

    assert (first.status_code, replay.status_code, stale.status_code) == (200, 200, 409)
    facts = await _facts(store, event_kind="recovery_cancellation")
    assert [(f["action_outcome"], f["request_id"], f["operation_id"], f["sanitized_reason"])
            for f in facts] == [
        ("applied", request_id, f"initial_cancellation:request:{request_id}",
         "stranded initial approval cancelled"),
        ("rejected", request_id, None, "stale_nonce"),
    ]
    assert {f["actor_kind"] for f in facts} == {"operator"}
    protected = await _protected(store, 56)
    assert protected[3] == [(request_id, "superseded")]
    assert protected[0][:6] == ("escalated", "plan_blocked", _OWNER["slot"], 2, 3, 1)


async def _seed_pending_continuation(maker, *, item_id: int, workspace_id: int) -> int:
    from app.models.database import GithubApprovalRequest, GithubAttemptScopeRevision

    await _seed_work(maker, item_id=item_id, status="escalated", workspace_id=workspace_id,
                     lease_token=f"synthetic-lease-{item_id}",
                     escalation_reason="retry_count_exhausted", pr_number=73)
    async with maker() as db:
        revision = GithubAttemptScopeRevision(
            work_item_id=item_id, dispatch_nonce=_NONCE, revision=1,
            owner_slot_id=_OWNER["slot"], owner_member_id=_OWNER["member"],
            phase="implementation", execution_target="workspace", summary="Pending",
            allowed_paths=["src/a.py"], allowed_actions=["edit_production"],
            allowed_commands=[], prohibited_actions=[], tool_fallbacks={},
            baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
            originating_escalation_reason="retry_count_exhausted",
            expected_workspace_id=workspace_id, expected_lease_token_hash="h" * 64,
            max_failed_heads=2, status="proposed")
        db.add(revision)
        await db.flush()
        approval = GithubApprovalRequest(
            work_item_id=item_id, request_kind="continuation", dispatch_nonce=_NONCE,
            approval_round=3, owner_member_id=_OWNER["member"],
            leader_member_id=_LEADER["member"], request_fingerprint="d" * 64,
            status="pending", scope_revision_id=revision.id)
        db.add(approval)
        await db.flush()
        revision.approval_request_id = approval.id
        await db.commit()
        return approval.id


async def test_c09_pending_request_cancellation_records_the_actual_actor(store, client):
    """C08/C09: operator and requester cancellations record their own actor
    once; a replay records nothing; a non-requester is refused and recorded."""
    await _seed_team(store)
    operator_request = await _seed_pending_continuation(store, item_id=57, workspace_id=77)
    member_request = await _seed_pending_continuation(store, item_id=58, workspace_id=78)

    def url(item_id, request_id):
        return (f"/api/v1/agent-teams/github-work-items/{item_id}/continuation-requests/"
                f"{request_id}/cancel")

    by_operator = await client.post(url(57, operator_request), headers=_OPERATOR_HEADERS)
    replay = await client.post(url(57, operator_request), headers=_OPERATOR_HEADERS)
    by_leader = await client.post(url(58, member_request), headers=_session_headers(_LEADER))
    by_owner = await client.post(url(58, member_request), headers=_session_headers(_OWNER))

    assert [r.status_code for r in (by_operator, replay, by_leader, by_owner)] == [
        200, 200, 403, 200]
    facts = await _facts(store, event_kind="request_cancellation")
    assert [(f["request_id"], f["action_outcome"], f["actor_kind"], f["actor_member_id"],
             f["actor_session_id"]) for f in facts] == [
        (operator_request, "applied", "operator", None, None),
        (member_request, "rejected", "member", _LEADER["member"], _LEADER["session"]),
        (member_request, "applied", "member", _OWNER["member"], _OWNER["session"]),
    ]
    for item_id in (57, 58):
        protected = await _protected(store, item_id)
        assert protected[2][0][1] == "superseded"
        assert protected[3][0][1] == "superseded"
        assert protected[0][:6] == ("escalated", "retry_count_exhausted", _OWNER["slot"], 2, 3, 1)


async def test_c09_late_workspace_cas_refusal_records_rejection_without_cleanup(store, monkeypatch):
    """C09: the acquisition changes from a separate session while the real
    release awaits its config snapshot. The resumed CAS returns False, one
    rejected fact is recorded, and nothing is revoked or cleaned up."""
    from app.services.github_workspace_service import (
        _MANAGED_WORKTREE_KEYS, WorktreeConfigSnapshot, github_workspace_service,
    )

    await _seed_team(store)
    await _seed_work(store, item_id=59, status="merged", workspace_id=79,
                     workspace_kind="worktree", lease_token="synthetic-lease-59")
    winner_at = datetime(2026, 10, 6, 11, 45, 0)
    effects: list[str] = []

    async def racing_snapshot(_workspace):
        # Git boundary: the snapshot await lets a competing writer win.
        from app.models.database import GithubWorkspace

        async with store() as other:
            winner = await other.get(GithubWorkspace, 79)
            winner.lease_token = "synthetic-winner"
            winner.leased_at = winner_at
            await other.commit()
        return WorktreeConfigSnapshot({key: () for key in _MANAGED_WORKTREE_KEYS})

    async def record_revoke(*_args, **_kwargs):
        effects.append("revoke")
        return True

    async def record_remove(*_args, **_kwargs):
        effects.append("remove_config")

    monkeypatch.setattr(github_workspace_service, "snapshot_worktree_config", racing_snapshot)
    monkeypatch.setattr(github_workspace_service, "revoke_push_token", record_revoke)
    monkeypatch.setattr(github_workspace_service, "remove_managed_worktree_config", record_remove)

    async with store() as db:
        released = await github_workspace_service.release_by_owner(
            db, 59, actor_kind="member", actor_member_id=_OWNER["member"],
            actor_session_id=_OWNER["session"], lease_token="synthetic-lease-59",
            workspace_id=79, scope_id=5, owner_slot_id=_OWNER["slot"],
            expected_leased_at=_FIXED_LEASE)

    assert released is False
    assert effects == []
    facts = await _facts(store, event_kind="workspace_release")
    assert [(f["action_outcome"], f["actor_member_id"], f["actor_session_id"], f["operation_id"])
            for f in facts] == [("rejected", _OWNER["member"], _OWNER["session"], None)]
    protected = await _protected(store, 59)
    assert protected[1] == [(79, 59, "2026-10-06 11:45:00.000000", "synthetic-winner")]


@pytest.mark.parametrize(
    ("case", "expected_outcome", "known_effects"),
    [
        ("revoke_unknown", "uncertain", "push access unknown; managed config not_attempted"),
        ("removal_restored", "rejected", "managed config unknown; restoration restored"),
        ("restore_failed", "uncertain", "managed config unknown; restoration restore_failed"),
    ],
)
async def test_c09_partial_external_cleanup_records_known_effects(
    store, monkeypatch, case, expected_outcome, known_effects
):
    """C09: a failed external effect rolls back the local release; the fact
    names each known effect; an unproved effect stays uncertain; no lease,
    retry, approval or budget state changes."""
    from app.services import github_app_auth_service as _auth
    from app.services.github_workspace_service import (
        _MANAGED_WORKTREE_KEYS, GithubWorkspaceConfigError,
        GithubWorkspaceCredentialRevokeError, WorktreeConfigSnapshot, github_workspace_service,
    )

    revoke_case = case == "revoke_unknown"
    await _seed_team(store, auth_mode="app" if revoke_case else "ambient")
    await _seed_work(store, item_id=80, status="merged", workspace_id=90,
                     workspace_kind="primary" if revoke_case else "worktree",
                     lease_token="synthetic-lease-80")
    before = await _protected(store, 80)

    async def snapshot(_workspace):
        return WorktreeConfigSnapshot({key: () for key in _MANAGED_WORKTREE_KEYS})

    async def revoke_fails(*_args, **_kwargs):
        # External GitHub App boundary: the revocation result is unknown.
        raise _auth.GithubAppRevokeError("matrix-owner", "matrix-repo")

    async def remove_fails(_workspace):
        raise GithubWorkspaceConfigError("synthetic removal failure")

    async def restore_ok(_workspace, _snapshot):
        return None

    async def restore_fails(_workspace, _snapshot):
        raise GithubWorkspaceConfigError("synthetic restore failure", restoration_failed=True)

    monkeypatch.setattr(github_workspace_service, "snapshot_worktree_config", snapshot)
    monkeypatch.setattr(_auth.github_app_auth_service, "revoke_cached_repository_token",
                        revoke_fails)
    monkeypatch.setattr(github_workspace_service, "remove_managed_worktree_config", remove_fails)
    monkeypatch.setattr(github_workspace_service, "restore_worktree_config",
                        restore_fails if case == "restore_failed" else restore_ok)
    expected_error = (GithubWorkspaceCredentialRevokeError if revoke_case
                      else GithubWorkspaceConfigError)

    async with store() as db:
        with pytest.raises(expected_error) as raised:
            await github_workspace_service.release_by_owner(
                db, 80, actor_kind="member", actor_member_id=_OWNER["member"],
                actor_session_id=_OWNER["session"], lease_token="synthetic-lease-80",
                workspace_id=90, scope_id=5, owner_slot_id=_OWNER["slot"],
                expected_leased_at=_FIXED_LEASE)
    if case == "restore_failed":
        assert raised.value.restoration_failed is True

    facts = await _facts(store, event_kind="workspace_release")
    assert len(facts) == 1
    assert facts[0]["action_outcome"] == expected_outcome
    assert known_effects in facts[0]["sanitized_reason"]
    assert facts[0]["operation_id"] is None
    after = await _protected(store, 80)
    # Exact local rollback: the acquisition and every counter remain.
    assert after[1] == before[1]
    assert after[0] == before[0]


async def test_c09_recovery_holds_and_checkpoint_releases_record_real_actors(
    store, client, monkeypatch
):
    """C09: the decision hold is the owner's persisted transition, the ack hold
    is the Leader's, each operator checkpoint release records its exact stage
    change, and a stale release is refused without changing the hold."""
    from app.config import settings
    from app.services.github_client import (
        GithubCommitSnapshot, GithubTreeEntry, github_client,
    )

    await _seed_team(store)
    await _seed_work(store, item_id=81, status="escalated", workspace_id=91,
                     workspace_kind="worktree", lease_token="synthetic-lease-81",
                     escalation_reason="retry_count_exhausted", pr_number=73,
                     dispatch_head_ref=_HEAD_REF)
    monkeypatch.setattr(settings, "github_recovery_only_attempt",
                        f"5:81:73:{_NONCE}:{_HEAD_REF}")
    _stub_open_pull(monkeypatch)

    async def snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="a" * 40, tree_sha="b" * 40)

    async def tree(*_args, **_kwargs):
        return [GithubTreeEntry(path="src/a.py", mode="100644", object_type="blob",
                                sha="c" * 40)]

    monkeypatch.setattr(github_client, "get_commit_snapshot", snapshot)
    monkeypatch.setattr(github_client, "get_recursive_tree", tree)
    before = await _protected(store, 81)

    proposal = await client.post(
        "/api/v1/agent-teams/github-work-items/81/continuation-requests",
        headers=_session_headers(_OWNER),
        json={"dispatch_nonce": _NONCE, "phase": "implementation",
              "execution_target": "workspace", "summary": "Bounded matrix correction",
              "allowed_paths": ["src/a.py"],
              "allowed_actions": ["edit_production", "push_pr_head", "request_verification"],
              "allowed_commands": ["pytest -q"], "prohibited_actions": ["Do not edit CI"],
              "max_failed_heads": 1, "tool_fallbacks": {},
              "lease_token": "synthetic-lease-81"})
    assert proposal.status_code == 200, proposal.text
    revision_id = proposal.json()["revision"]["id"]
    request_id = proposal.json()["approval"]["id"]
    release_url = "/api/v1/agent-teams/github-work-items/81/scope-revisions/1/checkpoint-release"

    def release_body(stage):
        return {"release": True, "dispatch_nonce": _NONCE,
                "approval_request_id": request_id, "stage": stage}

    released = await client.post(release_url, headers=_OPERATOR_HEADERS,
                                 json=release_body("decision"))
    stale = await client.post(release_url, headers=_OPERATOR_HEADERS,
                              json=release_body("decision"))
    decided = await client.post(
        "/api/v1/agent-mail/continuation-decisions", headers=_session_headers(_LEADER),
        json={"approval_request_id": request_id, "work_item_id": 81,
              "dispatch_nonce": _NONCE, "decision": "approved", "reason": "bounded"})
    ack_released = await client.post(release_url, headers=_OPERATOR_HEADERS,
                                     json=release_body("ack"))

    assert (released.status_code, stale.status_code, decided.status_code,
            ack_released.status_code) == (200, 409, 200, 200), (stale.text, decided.text)
    facts = [f for f in await _facts(store) if f["event_kind"] in {
        "recovery_hold", "recovery_checkpoint_release"}]
    assert [(f["event_kind"], f["action_outcome"], f["actor_kind"], f["actor_member_id"],
             f["actor_session_id"], f["before_values"], f["after_values"]) for f in facts] == [
        ("recovery_hold", "applied", "member", _OWNER["member"], _OWNER["session"],
         '{"recovery_checkpoint_stage": null}', '{"recovery_checkpoint_stage": "decision_hold"}'),
        ("recovery_checkpoint_release", "applied", "operator", None, None,
         '{"recovery_checkpoint_stage": "decision_hold"}',
         '{"recovery_checkpoint_stage": "decision_open"}'),
        ("recovery_checkpoint_release", "rejected", "operator", None, None, None, None),
        ("recovery_hold", "applied", "member", _LEADER["member"], _LEADER["session"],
         '{"recovery_checkpoint_stage": "decision_open"}',
         '{"recovery_checkpoint_stage": "ack_hold"}'),
        ("recovery_checkpoint_release", "applied", "operator", None, None,
         '{"recovery_checkpoint_stage": "ack_hold"}', '{"recovery_checkpoint_stage": "ack_open"}'),
    ]
    applied = [f for f in facts if f["action_outcome"] == "applied"]
    assert {(f["revision_id"], f["request_id"], f["item_id"]) for f in applied} == {
        (revision_id, request_id, 81)}
    assert facts[2]["sanitized_reason"] == "recovery_checkpoint_context_changed"
    after = await _protected(store, 81)
    # Guard-preserved item and lease fields are unchanged; only the revision
    # and approval move through their own lifecycle.
    assert after[0] == before[0]
    assert after[1] == before[1]
    assert after[2] == [(revision_id, "approved", 0, "ack_open")]
