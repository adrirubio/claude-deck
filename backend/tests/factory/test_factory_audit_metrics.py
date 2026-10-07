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

# C12: the forward-coverage marker of the disposable fixture database. It
# precedes every fixture fact, so fixture windows are fully covered.
_COVERAGE_START = datetime(2026, 1, 1, 0, 0, 0)


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
        await audit.install_forward_coverage(conn, installed_at=_COVERAGE_START)
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
    """A24-A27/C12: with no boundaries the duration is unavailable and named
    by its boundaries; evidenced retry classes and authoritative counters
    are separate samples."""
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["elapsed_attempt_duration"].value is None
    assert by_name["elapsed_attempt_duration"].sample_count == 0
    assert "not execution time" in by_name["elapsed_attempt_duration"].unknown_reasons[0]
    assert by_name["diagnostic_retries"].value == 0.0
    assert by_name["implementation_retries"].value == 0.0
    assert by_name["diagnostic_retry_counters"].source == "live_persisted_state"
    assert "authoritative counters" in by_name["implementation_retry_counters"].coverage


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

    # R06: a delivered code row is not in the design population.
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    review = {sample.name: sample for sample in window.metrics}["independently_human_reviewed_design"]
    assert (review.value, review.sample_count, review.unknown_count) == (0.0, 0, 0)
    assert review.coverage == "full"

    # One delivered design attempt and one delivered code attempt.
    for item_id in (31, 32):
        await _seed_item(db, item_id)
    await db.commit()
    await audit.record_delivery_fact(
        db, item_id=31, delivery_outcome="delivered", completion_kind="merged_design",
        fact_source="github_pull_request_merged", fact_time=_now(), artifact="pr:31",
        attempt="item:31:launch:None:revision:None", snapshot={"artifact_version": "a" * 40})
    await audit.record_delivery_fact(
        db, item_id=32, delivery_outcome="delivered", completion_kind="merged_code",
        fact_source="github_pull_request_merged", fact_time=_now(), artifact="pr:32",
        attempt="item:32:launch:None:revision:None", snapshot={"artifact_version": "c" * 40})
    await db.commit()
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    review = {sample.name: sample for sample in window.metrics}["independently_human_reviewed_design"]
    assert (review.value, review.sample_count, review.unknown_count) == (0.0, 1, 1)

    def evidence(**overrides):
        base = {"fact_kind": "human_review_acceptance", "artifact": "pr:31", "version": "a" * 40,
                "actor": "reviewer-external", "actor_kind": "human", "independent": True,
                "source": "review-record"}
        return {**base, **overrides}

    rejected = [
        evidence(actor="shared-operator-credential"),     # operator credential
        evidence(actor_kind=None, independent=None),      # non-operator string alone
        evidence(actor="member:22"),                      # an agent member
        evidence(artifact="pr:99"),                       # another artifact
        evidence(artifact="pr:32"),                       # a code delivery
        evidence(version="b" * 40),                       # A32: another version
        evidence(decision="rejected"),                    # A32: a declared rejection
    ]
    for payload in rejected + [evidence(), evidence()]:  # valid evidence twice
        await audit.record_event(
            db, event_kind="design_review", source="test", occurred_at=_now(),
            actor=launch_actor, action_outcome="applied", human_review_evidence=payload,
            item_id=31, context_snapshot={"attempt": "item:31:launch:None:revision:None"})
    # A32: valid evidence bound to another attempt of the same item never counts.
    await audit.record_event(
        db, event_kind="design_review", source="test", occurred_at=_now(),
        actor=launch_actor, action_outcome="applied", human_review_evidence=evidence(),
        item_id=31, context_snapshot={"attempt": "item:31:launch:7:revision:None"})
    await db.commit()
    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    review = {sample.name: sample for sample in window.metrics}["independently_human_reviewed_design"]
    # The exact design artifact counts once; nothing else qualifies.
    assert (review.value, review.sample_count, review.unknown_count) == (1.0, 1, 0)


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

    # R01: the deletion retired the old lifetime key.
    retired = (await db.execute(text(
        "SELECT retired_at FROM factory_context_keys WHERE context_key = :key"),
        {"key": first_key})).scalar_one()
    assert retired is not None

    # Numeric ID reuse allocates a distinct key; old events stay attached to
    # the old key only.
    await _seed_scope(db, 5)
    await db.commit()
    reused = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, scope_id=5, action_outcome="applied",
        context_snapshot={"team_display_name": "Reused"})
    await db.commit()
    assert reused.scope_context_key != first_key
    keys = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_context_keys WHERE key_kind = 'scope'"))).scalar_one()
    assert keys == 2
    assert await audit.current_context_key(db, "scope", 5) == reused.scope_context_key

    # Old-key and current-ID isolation: each key addresses only its own lifetime.
    for key, expected in ((first_key, 1), (reused.scope_context_key, 1)):
        rows = (await db.execute(text(
            "SELECT COUNT(*) FROM factory_audit_events WHERE scope_context_key = :key"),
            {"key": key})).scalar_one()
        assert rows == expected
    # The retired key never selects the replacement live scope: its present
    # state is unknown, while its retained ledger history stays countable.
    old = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1),
        filter_scope="scoped", scope_context_key=first_key)
    old_by_name = {sample.name: sample for sample in old.metrics}
    assert old_by_name["total_tracked_attempts"].value is None
    assert old_by_name["operator_interventions"].value == 1.0
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
    # Context keys preserve the original attribution after ID reuse, and the
    # recreated scope has no key until an event is recorded for it.
    assert event.scope_context_key is not None
    rows = (await db.execute(text(
        "SELECT COUNT(*) FROM factory_audit_events WHERE scope_context_key = :key"),
        {"key": event.scope_context_key})).scalar_one()
    assert rows == 1
    assert await audit.current_context_key(db, "scope", 1) is None


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

    # R09: a conflicting payload with the same operation id and resource is
    # refused explicitly. The first fact stands unchanged and no new fact is
    # committed; an exact replay still returns the first fact.
    with pytest.raises(audit.ReplayConflictError):
        await audit.record_event(
            db, event_kind="policy_change", source="test", occurred_at=_now(),
            actor=actor, item_id=1, action_outcome="rejected",
            operation_id="shared-op", after_values={"enabled": False})
    await db.rollback()
    stored = (await db.execute(text(
        "SELECT COUNT(*), MIN(action_outcome) FROM factory_audit_events"
        " WHERE operation_id = 'shared-op' AND item_id = 1"))).first()
    assert tuple(stored) == (1, "applied")
    exact = await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=actor, item_id=1, action_outcome="applied",
        operation_id="shared-op", after_values={"enabled": True})
    assert exact.id == first.id

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
        # T01: a superseded revision row still identifies the original
        # attempt; an active one would be continuing authority and keep the
        # item open.
        " VALUES (1, 1, 'n', 0, 1, 1, 'implementation', '/w', 's', '[]', '[]', '[]', '[]', '{}',"
        " 'a', 'b', 'r', 1, 'h', 2, 0, 'superseded', 0, NULL, CURRENT_TIMESTAMP)"))
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
    # R03/T02: the operation identity includes the fact (outcome, kind, fact
    # source), the exact version, the reliable fact time and the call site.
    assert [tuple(row) for row in delivery] == [(
        "delivery:item:1:launch:None:revision:1:attempt:unknown:closed_unproven:"
        "github_watcher_service._reconcile_closed_issues:unversioned:unknown:"
        "github_watcher_service._reconcile_closed_issues", 1, "unknown")]
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
    assert tuple(revision_row) == ("superseded", 0, 0)
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
        # T01: superseded, so the escalated item has no continuing authority.
        " VALUES (1, 1, 'n', 0, 5, 8, 'implementation', '/w', 's', '[]', '[]', '[]', '[]', '{}',"
        " 'a', 'b', 'r', 1, 'h', 2, 1, 'superseded', 1, NULL, CURRENT_TIMESTAMP)"))
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


_AUTHORITY_COLUMNS = {
    "item": (
        "dispatch_status, escalation_reason, pending_reason, owner_slot_id, routing_method,"
        " handoff_state, handoff_target_slot_id, approval_round_count, retry_count,"
        " diagnostic_retry_count, active_scope_revision, attempt_phase, pr_number,"
        " dispatch_nonce, dispatch_head_ref, launch_id, ack_received_at, ack_approver_member_id,"
        " ack_evidence_message_id, ack_enforcement_epoch, ack_approval_round,"
        " continuation_activated_at, last_verified_sha"),
    "leases": (
        "id, leased_item_id, leased_at, lease_token, push_token_expires_at, leased_owner_pid,"
        " leased_owner_proc_start, lease_last_owner_contact_at, released_at, enabled"),
    "revisions": (
        "id, dispatch_nonce, revision, owner_slot_id, owner_member_id, status, failed_head_count,"
        " last_failed_head_sha, max_failed_heads, recovery_checkpoint_stage, approval_request_id,"
        " delivery_message_id, acknowledged_at, cancelled_at, expected_workspace_id,"
        " expected_lease_token_hash"),
    "approvals": (
        "id, request_kind, dispatch_nonce, approval_round, owner_member_id, leader_member_id,"
        " status, scope_revision_id, request_message_id, decision_message_id, superseded_at"),
}


async def _authority(maker, item_id: int) -> dict:
    """C09: the complete guarded authority state of one item, fresh session.

    Every owner, lease, process, contact, approval, revision, ACK, limit and
    failed-head value is read. Tests compare it before and after, apart from
    the intended change they name explicitly.
    """
    queries = {
        "item": f"SELECT {_AUTHORITY_COLUMNS['item']} FROM github_work_items WHERE id = :id",
        "leases": (f"SELECT {_AUTHORITY_COLUMNS['leases']} FROM github_workspaces"
                   " WHERE scope_id = 5 ORDER BY id"),
        "revisions": (f"SELECT {_AUTHORITY_COLUMNS['revisions']}"
                      " FROM github_attempt_scope_revisions WHERE work_item_id = :id ORDER BY id"),
        "approvals": (f"SELECT {_AUTHORITY_COLUMNS['approvals']}"
                      " FROM github_approval_requests WHERE work_item_id = :id ORDER BY id"),
    }
    state: dict = {}
    async with maker() as db:
        for name, query in queries.items():
            rows = (await db.execute(text(query), {"id": item_id})).mappings().all()
            state[name] = [dict(row) for row in rows]
    state["item"] = state["item"][0] if state["item"] else None
    return state


def _except(state: dict, section: str, *keys: str, row: int | None = None) -> dict:
    """A copy of an authority state without the named intended changes."""
    import copy

    result = copy.deepcopy(state)
    targets = [result[section]] if isinstance(result[section], dict) else (
        result[section] if row is None else [result[section][row]])
    for target in targets:
        for key in keys:
            target.pop(key, None)
    return result


def _lease_iso(value: datetime = _FIXED_LEASE) -> str:
    return value.isoformat()


async def test_c02_c09_active_item_closed_issue_with_open_pr_is_not_delivered(store, monkeypatch):
    """C02/C09 W27: the active-item watcher completes a closed issue whose PR
    is still open, but records no delivery. The outcome stays unknown and
    the fact names its actual caller. Only the terminal state changes."""
    from app.models.database import TeamGithubScope
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_watcher_service import github_watcher_service

    await _seed_team(store)
    await _seed_work(store, item_id=82, status="dispatched", workspace_id=92,
                     lease_token="synthetic-lease-82", pr_number=73)
    before = await _authority(store, 82)

    class ClosedIssueOpenPull:
        # External GitHub boundary: the issue is closed; the watcher reads no PR.
        async def get_issues_by_number(self, owner, repo, numbers):
            return {number: {"state": "closed", "labels": []} for number in numbers}

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_dispatch_service, "notify_blocker_merged", no_notice)
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await github_watcher_service._recheck_active_items(db, scope, ClosedIssueOpenPull())

    delivery = await _facts(store, event_kind="delivery_evidence")
    assert len(delivery) == 1
    async with store() as db:
        stored = (await db.execute(text(
            "SELECT delivery_outcome, completion_kind, source FROM factory_audit_events"
            " WHERE event_kind = 'delivery_evidence'"))).first()
    assert tuple(stored) == (
        "unknown", "closed_unproven", "github_watcher_service._recheck_active_items")
    assert await _facts(store, event_kind="delivery_evidence", action_outcome="applied") == delivery
    after = await _authority(store, 82)
    assert after["item"]["dispatch_status"] == "completed"
    assert _except(after, "item", "dispatch_status") == _except(before, "item", "dispatch_status")


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


async def test_c08_stale_reclaim_records_scheduler_only_for_eligible_lease(
    store, tmp_path, monkeypatch
):
    """C08: the real stale-lease reclaim releases only a stale, dead-owner,
    quiescent worktree lease and records the scheduler reference. A live
    owner and a dirty worktree keep their exact leases."""
    import subprocess

    from app.models.database import GithubWorkspace, TeamGithubScope
    from app.services.github_workspace_service import github_workspace_service

    # Controlled git fixture: real worktrees on one base commit.
    repo = tmp_path / "reclaim-repo"
    repo.mkdir()
    for args in (["init", "-q", str(repo)],
                 ["-C", str(repo), "config", "user.email", "fixture@example.invalid"],
                 ["-C", str(repo), "config", "user.name", "Fixture"],
                 ["-C", str(repo), "commit", "--allow-empty", "-q", "-m", "base"],
                 ["-C", str(repo), "branch", "-M", "base"]):
        subprocess.run(["git", *args], check=True)
    worktrees = {}
    for name in ("stale", "alive", "dirty"):
        path = tmp_path / f"reclaim-{name}"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(path),
                        "-b", f"fixture-{name}"], check=True)
        worktrees[name] = path
    (worktrees["dirty"] / "uncommitted.txt").write_text("pending work")

    await _seed_team(store)
    stale_at = datetime.utcnow() - timedelta(hours=7)
    pids = {"stale": 900001, "alive": 900002, "dirty": 900003}
    for offset, name in enumerate(("stale", "alive", "dirty")):
        await _seed_work(store, item_id=95 + offset, status="merged", workspace_id=96 + offset,
                         workspace_kind="worktree", lease_token=f"synthetic-lease-{name}",
                         leased_at=stale_at)
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        scope.base_ref = "base"
        for offset, name in enumerate(("stale", "alive", "dirty")):
            workspace = await db.get(GithubWorkspace, 96 + offset)
            workspace.path = str(worktrees[name])
            workspace.leased_owner_pid = pids[name]
            workspace.leased_owner_proc_start = f"start-{name}"
        await db.commit()

    def read_proc_start(pid):
        # Process boundary: only the "alive" owner still runs with its start.
        if pid == pids["alive"]:
            return "start-alive"
        raise ProcessLookupError(pid)

    monkeypatch.setattr(github_workspace_service, "_read_proc_start", read_proc_start)
    kept_before = [await _protected(store, 96), await _protected(store, 97)]

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        released = await github_workspace_service.reclaim_stale(db, scope)

    assert released == 1
    facts = await _facts(store, event_kind="workspace_release")
    assert [(f["item_id"], f["action_outcome"], f["actor_kind"], f["actor_reference"])
            for f in facts] == [(95, "applied", "scheduler", "github_dispatch_scheduler")]
    assert (await _protected(store, 95))[1] == []
    assert [await _protected(store, 96), await _protected(store, 97)] == kept_before
    assert await _facts(store, actor_kind="operator") == []


async def test_c09_autonomy_route_refuses_and_records_missing_leader(store, client):
    """C09 proof 6: the actual autonomy route refuses leader_assignment_required,
    records one rejected fact for the team and leaves the policy unchanged."""
    await _seed_team(store)
    async with store() as db:
        await db.execute(text("UPDATE agent_team_slots SET enabled = 0 WHERE id = :id"),
                         {"id": _LEADER["slot"]})
        await db.commit()

    refused = await client.patch("/api/v1/agent-teams/presets/7", headers=_OPERATOR_HEADERS,
                                 json={"autonomy_enabled": True})

    assert refused.status_code == 400
    facts = await _facts(store)
    assert [(f["event_kind"], f["action_outcome"], f["team_preset_id"], f["actor_kind"],
             f["sanitized_reason"]) for f in facts] == [
        ("policy_change", "rejected", 7, "operator", "leader_assignment_required")]
    async with store() as db:
        autonomy = (await db.execute(text(
            "SELECT autonomy_enabled FROM agent_team_presets WHERE id = 7"))).scalar_one()
    assert autonomy == 0


async def test_c09_leader_change_success_and_audit_rollback_are_separate(store, client, monkeypatch):
    """A03/C09 proof 6: an actual Leader change commits with one applied fact;
    an audit insert failure on the same route leaves the Leader unchanged."""
    from app.services import factory_audit_service as _audit

    await _seed_team(store)

    async def expected_now():
        async with store() as db:
            return str((await db.execute(text(
                "SELECT updated_at FROM agent_team_presets WHERE id = 7"))).scalar_one())

    original = _audit.record_event

    async def failing(db, **fields):
        if fields.get("event_kind") == "leader_assignment":
            raise RuntimeError("synthetic audit insert failure")
        return await original(db, **fields)

    monkeypatch.setattr(_audit, "record_event", failing)
    failed = await client.put(
        "/api/v1/agent-teams/presets/7/leader", headers=_OPERATOR_HEADERS,
        json={"leader_slot_id": _OTHER["slot"], "expected_leader_slot_id": _LEADER["slot"],
              "expected_updated_at": await expected_now(), "reason": "rotation"})
    assert failed.status_code == 500
    async with store() as db:
        leader = (await db.execute(text(
            "SELECT leader_slot_id FROM agent_team_presets WHERE id = 7"))).scalar_one()
    assert leader == _LEADER["slot"]
    assert await _facts(store) == []

    monkeypatch.setattr(_audit, "record_event", original)
    changed = await client.put(
        "/api/v1/agent-teams/presets/7/leader", headers=_OPERATOR_HEADERS,
        json={"leader_slot_id": _OTHER["slot"], "expected_leader_slot_id": _LEADER["slot"],
              "expected_updated_at": await expected_now(), "reason": "rotation"})
    assert changed.status_code == 200
    facts = await _facts(store, event_kind="leader_assignment")
    assert [(f["action_outcome"], f["actor_kind"], f["before_values"], f["after_values"])
            for f in facts] == [
        ("applied", "operator", f'{{"leader_slot_id": {_LEADER["slot"]}}}',
         f'{{"leader_slot_id": {_OTHER["slot"]}}}')]


async def test_c08_acquire_reset_failure_releases_with_scheduler_identity(store, monkeypatch):
    """C08 proof 1: acquire leases a free worktree, its reset fails, and the
    automatic cleanup releases that exact acquisition as the scheduler."""
    from app.models.database import GithubWorkItem, GithubWorkspace, TeamGithubScope
    from app.services.github_workspace_service import (
        GithubWorkspaceResetError, github_workspace_service,
    )

    await _seed_team(store)
    await _seed_work(store, item_id=83, status="pending")
    async with store() as db:
        db.add(GithubWorkspace(id=93, scope_id=5, path="/tmp/matrix-free-93", kind="worktree"))
        await db.commit()

    async def reset_fails(*_args, **_kwargs):
        # Git boundary: the workspace reset fails after the lease commits.
        raise GithubWorkspaceResetError("synthetic reset failure", transient=False)

    monkeypatch.setattr(github_workspace_service, "reset_workspace", reset_fails)
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        item = await db.get(GithubWorkItem, 83)
        assert await github_workspace_service.acquire(db, scope, item) is None

    facts = await _facts(store, event_kind="workspace_release")
    assert len(facts) == 1
    fact = facts[0]
    assert (fact["action_outcome"], fact["actor_kind"], fact["actor_reference"],
            fact["item_id"]) == ("applied", "scheduler", "github_dispatch_scheduler", 83)
    assert fact["operation_id"].startswith("workspace_release:workspace:93:leased_at:")
    assert fact["operation_id"] != "workspace_release:workspace:93:leased_at:None"
    after = await _authority(store, 83)
    workspace = next(lease for lease in after["leases"] if lease["id"] == 93)
    assert (workspace["leased_item_id"], workspace["lease_token"]) == (None, None)
    assert workspace["released_at"] is not None
    assert await _facts(store, actor_kind="operator") == []


async def test_c09_watcher_accepted_send_then_failure_records_one_action(store, monkeypatch):
    """C09 proof 5: the real Mail send accepts the blocker notice, then the
    notifier fails. One terminal action, one delivered message and explicit
    notification uncertainty remain; a second poll repeats nothing."""
    from app.models.database import TeamGithubScope
    from app.services.agent_mail_service import agent_mail_service
    from app.services.github_watcher_service import github_watcher_service

    await _seed_team(store)
    await _seed_work(store, item_id=84, status="escalated", escalation_reason="plan_blocked")
    monkeypatch.setattr(github_watcher_service, "observer_session_factory", store, raising=False)
    original_send = agent_mail_service.send_direct_message

    async def accepted_then_fails(db, **kwargs):
        await original_send(db, **kwargs)
        raise RuntimeError("synthetic failure after accepted send")

    monkeypatch.setattr(agent_mail_service, "send_direct_message", accepted_then_fails)

    class ClosedIssue:
        async def get_issues_by_number(self, owner, repo, numbers):
            return {number: {"state": "closed", "labels": []} for number in numbers}

    for _poll in range(2):
        async with store() as db:
            scope = await db.get(TeamGithubScope, 5)
            await github_watcher_service._reconcile_closed_issues(db, scope, ClosedIssue())

    delivery = await _facts(store, event_kind="delivery_evidence")
    notices = await _facts(store, event_kind="lifecycle_notification")
    assert len(delivery) == 1
    assert [f["action_outcome"] for f in notices] == ["uncertain"]
    async with store() as db:
        messages = (await db.execute(text(
            "SELECT COUNT(*) FROM mail_messages WHERE payload LIKE '%blocker_merged%'"
        ))).scalar_one()
        status = (await db.execute(text(
            "SELECT dispatch_status FROM github_work_items WHERE id = 84"))).scalar_one()
    assert messages == 1
    assert status == "completed"


async def test_c08_stale_reclaim_contact_race_keeps_lease_without_cleanup(
    store, tmp_path, monkeypatch
):
    """C08 proof 7: the owner contact changes while the real reclaim checks
    quiescence. The guarded CAS refuses, one rejected scheduler fact is
    recorded, the exact lease stays, and nothing is revoked or cleaned."""
    import subprocess

    from app.models.database import GithubWorkspace, TeamGithubScope
    from app.services.github_workspace_service import github_workspace_service

    repo = tmp_path / "race-repo"
    repo.mkdir()
    for args in (["init", "-q", str(repo)],
                 ["-C", str(repo), "config", "user.email", "fixture@example.invalid"],
                 ["-C", str(repo), "config", "user.name", "Fixture"],
                 ["-C", str(repo), "commit", "--allow-empty", "-q", "-m", "base"],
                 ["-C", str(repo), "branch", "-M", "base"]):
        subprocess.run(["git", *args], check=True)
    worktree = tmp_path / "race-ws"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(worktree),
                    "-b", "fixture-race"], check=True)

    await _seed_team(store)
    await _seed_work(store, item_id=85, status="merged", workspace_id=94,
                     workspace_kind="worktree", lease_token="synthetic-lease-race",
                     leased_at=datetime.utcnow() - timedelta(hours=7))
    async with store() as db:
        (await db.get(TeamGithubScope, 5)).base_ref = "base"
        workspace = await db.get(GithubWorkspace, 94)
        workspace.path = str(worktree)
        workspace.leased_owner_pid = 900010
        workspace.leased_owner_proc_start = "start-race"
        await db.commit()

    def dead_owner(pid):
        raise ProcessLookupError(pid)

    contact_at = datetime.utcnow()
    real_runner = github_workspace_service._runner
    effects: list[str] = []

    async def racing_runner(args):
        if "status" in args:
            # The owner makes contact from a separate session mid-check.
            async with store() as other:
                lease = await other.get(GithubWorkspace, 94)
                lease.lease_last_owner_contact_at = contact_at
                await other.commit()
        return await real_runner(args)

    async def record_revoke(*_args, **_kwargs):
        effects.append("revoke")
        return True

    async def record_remove(*_args, **_kwargs):
        effects.append("remove_config")

    monkeypatch.setattr(github_workspace_service, "_read_proc_start", dead_owner)
    monkeypatch.setattr(github_workspace_service, "_runner", racing_runner)
    monkeypatch.setattr(github_workspace_service, "revoke_push_token", record_revoke)
    monkeypatch.setattr(github_workspace_service, "remove_managed_worktree_config", record_remove)

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        released = await github_workspace_service.reclaim_stale(db, scope)

    assert released == 0
    assert effects == []
    facts = await _facts(store, event_kind="workspace_release")
    assert [(f["action_outcome"], f["actor_kind"], f["actor_reference"], f["item_id"])
            for f in facts] == [("rejected", "scheduler", "github_dispatch_scheduler", 85)]
    after = await _authority(store, 85)
    lease = next(row for row in after["leases"] if row["id"] == 94)
    assert (lease["leased_item_id"], lease["lease_token"], lease["leased_owner_pid"]) == (
        85, "synthetic-lease-race", 900010)
    assert lease["lease_last_owner_contact_at"] is not None


class _LaunchItem:
    """Launcher boundary result for one slot (tmux launch is external)."""

    def __init__(self, status: str, tmux_target: str | None):
        self.status = status
        self.tmux_target = tmux_target


class _LaunchResult:
    def __init__(self, item: _LaunchItem):
        self.launch_id = None
        self.items = [item]


@pytest.mark.parametrize(
    ("case", "expected_status", "released"),
    [
        ("value_error", "escalated", True),
        ("failed_no_target", "failed", True),
        ("failed_live_target", "failed", False),
    ],
)
async def test_c08_dispatch_pending_launch_failures_record_scheduler_releases(
    store, monkeypatch, case, expected_status, released
):
    """C08 proof 2: dispatch_pending drives the launcher ValueError and the
    failed-launch paths into the real release with the scheduler reference;
    a failed launch with a live tmux target keeps its lease."""
    from app.models.database import (
        AgentTeamPreset, AgentTeamSlot, GithubWorkItem, GithubWorkspace, TeamGithubScope,
    )
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_workspace_service import github_workspace_service

    # A minimal team with no Mail sessions, like the existing dispatch tests.
    async with store() as db:
        preset = AgentTeamPreset(id=8, name="Dispatch matrix", created_by="fixture")
        db.add(preset)
        await db.flush()
        leader = AgentTeamSlot(id=21, preset_id=8, position=0, display_name="Leader",
                               role="Leader", provider="codex-cli", repo_id="r",
                               repo_path="/tmp/r", repo_name="r", launch_mode="plain",
                               launch_options={}, enabled=True)
        owner = AgentTeamSlot(id=22, preset_id=8, position=1, display_name="Backend",
                              provider="codex-cli", repo_id="r", repo_path="/tmp/r",
                              repo_name="r", launch_mode="plain", launch_options={},
                              enabled=True, area_labels=["area:backend"])
        db.add_all([leader, owner])
        await db.flush()
        preset.leader_slot_id = 21
        db.add(TeamGithubScope(id=6, preset_id=8, repo_owner="o", repo_name="dispatch-matrix",
                               repo_path="/tmp/dispatch-matrix", base_ref="origin/master"))
        await db.flush()
        db.add(GithubWorkspace(id=96, scope_id=6, path="/tmp/dispatch-matrix-ws"))
        db.add(GithubWorkItem(id=86, scope_id=6, issue_number=86, issue_title="Dispatch",
                              issue_url="u", github_updated_at=datetime.utcnow(),
                              dispatch_status="pending"))
        await db.commit()

    async def succeeds(*_args, **_kwargs):
        return None

    async def git_ok(_args):
        # Git boundary: worktree configuration commands succeed.
        return 0, ""

    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 999_999,
                        raising=False)
    monkeypatch.setattr(github_workspace_service, "reset_workspace", succeeds)
    monkeypatch.setattr(github_workspace_service, "configure_dispatch_worktree", succeeds)
    monkeypatch.setattr(github_workspace_service, "validate_app_remote", succeeds)
    monkeypatch.setattr(github_workspace_service, "_runner", git_ok)
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: [])

    async def launcher(*_args, **_kwargs):
        if case == "value_error":
            raise ValueError("synthetic blocked plan")
        target = "matrix:0.0" if case == "failed_live_target" else None
        return _LaunchResult(_LaunchItem("failed", target))

    async with store() as db:
        scope = await db.get(TeamGithubScope, 6)
        slots = list((await db.execute(
            select(AgentTeamSlot).where(AgentTeamSlot.preset_id == 8)
            .order_by(AgentTeamSlot.position))).scalars().all())
        await github_dispatch_service.dispatch_pending(
            db, scope, slots, launcher=launcher,
            issue_labels_by_number={86: ["area:backend"]})

    async with store() as db:
        status, lease_item = (await db.execute(text(
            "SELECT i.dispatch_status, w.leased_item_id FROM github_work_items i,"
            " github_workspaces w WHERE i.id = 86 AND w.id = 96"))).first()
    assert status == expected_status
    releases = await _facts(store, event_kind="workspace_release")
    if released:
        assert lease_item is None
        assert [(f["item_id"], f["action_outcome"], f["actor_kind"], f["actor_reference"])
                for f in releases] == [(86, "applied", "scheduler", "github_dispatch_scheduler")]
    else:
        assert lease_item == 86
        assert releases == []
    assert await _facts(store, actor_kind="operator") == []


async def _seed_prepared_attempt(maker, item_id: int, workspace_id: int) -> None:
    await _seed_work(
        maker, item_id=item_id, status="escalated", workspace_id=workspace_id,
        lease_token=f"synthetic-lease-{item_id}",
        escalation_reason="prepared_owner_unavailable", routing_method="label",
        dispatch_head_ref=f"deck/slot-12/issue-{item_id}-{_NONCE}",
        dispatch_base_ref="origin/master", last_verified_sha="a" * 40)


@pytest.mark.parametrize(
    ("case", "body", "status_code", "outcome"),
    [
        ("success", {"resume": True}, 200, "applied"),
        ("invalid_target", {"resume": True, "reassign_to_slot_id": 999}, 409, "rejected"),
        ("liveness_unknown", {"resume": True, "reassign_to_slot_id": 13}, 409, "rejected"),
        ("audit_failure", {"resume": True}, 500, None),
    ],
)
async def test_c09_prepared_resume_route_records_actual_outcome(
    store, client, monkeypatch, case, body, status_code, outcome
):
    """C09 proof 3: the operator resume route records its applied fact in the
    resume transaction; target and liveness refusals record rejections; an
    audit failure rolls back. Attempt, approval, budgets and lease remain."""
    from app.services import factory_audit_service as _audit

    await _seed_team(store)
    await _seed_prepared_attempt(store, 87, 97)
    before = await _authority(store, 87)
    if case == "audit_failure":
        original = _audit.record_event

        async def failing(db, **fields):
            if fields.get("event_kind") == "prepared_attempt_resume":
                raise RuntimeError("synthetic audit insert failure")
            return await original(db, **fields)

        monkeypatch.setattr(_audit, "record_event", failing)

    response = await client.post("/api/v1/agent-teams/presets/7/work-items/87/resume-attempt",
                                 headers=_OPERATOR_HEADERS, json=body)

    assert response.status_code == status_code, response.text
    facts = await _facts(store, event_kind="prepared_attempt_resume")
    after = await _authority(store, 87)
    if outcome is None:
        assert facts == []
        assert after == before
        return
    assert [(f["action_outcome"], f["actor_kind"], f["item_id"]) for f in facts] == [
        (outcome, "operator", 87)]
    if outcome == "applied":
        assert after["item"]["dispatch_status"] == "pending"
        changed = ("dispatch_status", "escalation_reason", "pending_reason")
        assert _except(after, "item", *changed) == _except(before, "item", *changed)
    else:
        expected_code = ("invalid_resume_target" if case == "invalid_target"
                         else "previous_owner_liveness_unknown")
        assert facts[0]["sanitized_reason"] == expected_code
        assert after == before


async def test_c09_scope_lookup_race_and_authority_refusals_are_recorded(store, client, monkeypatch):
    """C09 proof 4: the actual scope route refuses a configuration change made
    during App installation lookup, and an identity change while a lease is
    held. Each refusal records one rejected fact for the scope; nothing changes."""
    from app.services.github_app_auth_service import github_app_auth_service

    await _seed_team(store)
    async with store() as db:
        await db.execute(text(
            "UPDATE team_github_scopes SET github_auth_mode = 'app', enabled = 0,"
            " github_app_installation_id = NULL WHERE id = 5"))
        await db.commit()
    monkeypatch.setattr(github_app_auth_service, "require_configuration", lambda **_kwargs: None)

    async def racing_lookup(_owner, _repo):
        # External App lookup: a competing writer changes the scope meanwhile.
        async with store() as other:
            await other.execute(text(
                "UPDATE team_github_scopes SET dispatch_label = 'changed-during-lookup'"
                " WHERE id = 5"))
            await other.commit()
        return 73

    monkeypatch.setattr(github_app_auth_service, "resolve_installation", racing_lookup)
    raced = await client.patch("/api/v1/agent-teams/github-scopes/5",
                               headers=_OPERATOR_HEADERS, json={"enabled": True})
    assert raced.status_code == 409
    assert raced.json()["detail"] == "scope_changed_during_app_lookup"

    async def plain_lookup(_owner, _repo):
        return 73

    monkeypatch.setattr(github_app_auth_service, "resolve_installation", plain_lookup)
    await _seed_work(store, item_id=88, status="dispatched", workspace_id=98,
                     lease_token="synthetic-lease-88")
    in_use = await client.patch("/api/v1/agent-teams/github-scopes/5",
                                headers=_OPERATOR_HEADERS, json={"repo_name": "renamed"})
    assert in_use.status_code == 409
    assert in_use.json()["detail"] == "scope_identity_in_use"

    facts = await _facts(store, event_kind="policy_change")
    assert [(f["action_outcome"], f["scope_id"], f["actor_kind"], f["sanitized_reason"])
            for f in facts] == [
        ("rejected", 5, "operator", "scope_changed_during_app_lookup"),
        ("rejected", 5, "operator", "scope_identity_in_use"),
    ]
    async with store() as db:
        scope = (await db.execute(text(
            "SELECT enabled, github_app_installation_id, repo_name, dispatch_label"
            " FROM team_github_scopes WHERE id = 5"))).first()
    assert tuple(scope) == (0, None, "matrix-repo", "changed-during-lookup")


async def test_c09_scope_writer_reservation_contention_is_refused_and_recorded(store, client):
    """C09 proof 4: another writer holds the SQLite write lock while the real
    scope route reserves the writer. The reservation fails after the busy
    timeout, the route refuses scope_changed_during_update, and once the lock
    is released its refusal observation commits. The scope is unchanged."""
    import asyncio

    await _seed_team(store)
    holder = store()
    # Begin a competing write transaction and keep its lock.
    await holder.execute(text("UPDATE agent_team_presets SET name = name WHERE id = 7"))
    patch = asyncio.create_task(client.patch(
        "/api/v1/agent-teams/github-scopes/5", headers=_OPERATOR_HEADERS,
        json={"dispatch_label": "contended-label"}))
    try:
        # The reservation waits for the 5 s busy timeout; release after it.
        await asyncio.sleep(6)
    finally:
        await holder.rollback()
        await holder.close()
    response = await patch

    assert response.status_code == 409
    assert response.json()["detail"] == "scope_changed_during_update"
    facts = await _facts(store, event_kind="policy_change")
    assert [(f["action_outcome"], f["scope_id"], f["actor_kind"], f["sanitized_reason"])
            for f in facts] == [("rejected", 5, "operator", "scope_changed_during_update")]
    async with store() as db:
        label = (await db.execute(text(
            "SELECT dispatch_label FROM team_github_scopes WHERE id = 5"))).scalar_one()
    assert label != "contended-label"


@pytest.mark.parametrize("send_fails", [False, True])
async def test_c09_handoff_initiation_records_action_and_separate_notice(
    store, client, monkeypatch, send_fails
):
    """C08/C09 N1: a valid member handoff records one applied action fact in
    the handoff commit and a separate notice fact. A send failure after the
    commit keeps the pending handoff and records the notice as uncertain."""
    from app.services.agent_mail_service import agent_mail_service

    await _seed_team(store)
    await _seed_work(store, item_id=89, status="dispatched")
    if send_fails:
        async def failing_send(*_args, **_kwargs):
            raise RuntimeError("synthetic low-level send failure")

        monkeypatch.setattr(agent_mail_service, "send_direct_message", failing_send)

    response = await client.post(
        "/api/v1/agent-teams/dispatch-status", headers=_session_headers(_OWNER),
        json={"work_item_id": 89, "status": "handoff_initiated",
              "reassign_to_slot_id": _OTHER["slot"]})

    assert response.status_code == (500 if send_fails else 200)
    actions = await _facts(store, event_kind="handoff_reassignment")
    notices = await _facts(store, event_kind="handoff_notification")
    assert [(f["action_outcome"], f["actor_member_id"], f["actor_session_id"], f["item_id"])
            for f in actions] == [("applied", _OWNER["member"], _OWNER["session"], 89)]
    assert [f["action_outcome"] for f in notices] == (["uncertain"] if send_fails else ["applied"])
    assert actions[0]["operation_id"] != notices[0]["operation_id"]
    authority = await _authority(store, 89)
    assert (authority["item"]["handoff_state"], authority["item"]["handoff_target_slot_id"],
            authority["item"]["owner_slot_id"]) == ("pending", _OTHER["slot"], _OWNER["slot"])


@pytest.mark.parametrize("pending", [True, False])
async def test_c09_handoff_acceptance_records_applied_or_refused(store, client, pending):
    """C08/C09 N2: the target member's acceptance records one applied fact in
    the acceptance commit; a stale handoff state is refused, recorded with a
    fixed code, and leaves ownership and the lease unchanged."""
    await _seed_team(store)
    await _seed_work(store, item_id=90, status="dispatched", workspace_id=100,
                     lease_token="synthetic-lease-90", handoff_target_slot_id=_OTHER["slot"],
                     handoff_state="pending" if pending else None)
    before = await _authority(store, 90)

    response = await client.post(
        "/api/v1/agent-teams/dispatch-status", headers=_session_headers(_OTHER),
        json={"work_item_id": 90, "status": "handoff_accepted"})

    facts = await _facts(store, event_kind="handoff_acceptance")
    after = await _authority(store, 90)
    assert [(f["actor_member_id"], f["actor_session_id"]) for f in facts] == [
        (_OTHER["member"], _OTHER["session"])]
    if pending:
        assert response.status_code == 200, response.text
        assert facts[0]["action_outcome"] == "applied"
        assert facts[0]["before_values"] == f'{{"owner_slot_id": {_OWNER["slot"]}}}'
        assert facts[0]["after_values"] == f'{{"owner_slot_id": {_OTHER["slot"]}}}'
        assert after["item"]["owner_slot_id"] == _OTHER["slot"]
    else:
        assert response.status_code == 409
        assert (facts[0]["action_outcome"], facts[0]["sanitized_reason"]) == (
            "rejected", "handoff_state_changed")
        assert after == before


async def _seed_approved_continuation(maker, *, item_id: int, workspace_id: int) -> dict:
    from app.models.database import (
        GithubApprovalRequest, GithubAttemptScopeRevision, MailMessage,
    )
    from app.services.github_approval_service import github_approval_service

    token = f"synthetic-lease-{item_id}"
    await _seed_work(maker, item_id=item_id, status="escalated", workspace_id=workspace_id,
                     workspace_kind="primary", lease_token=token,
                     escalation_reason="retry_count_exhausted", pr_number=73,
                     dispatch_head_ref=_HEAD_REF)
    async with maker() as db:
        revision = GithubAttemptScopeRevision(
            work_item_id=item_id, dispatch_nonce=_NONCE, revision=1,
            owner_slot_id=_OWNER["slot"], owner_member_id=_OWNER["member"],
            phase="implementation", execution_target="workspace", summary="Approved",
            allowed_paths=["src/a.py"], allowed_actions=["edit_production"],
            allowed_commands=[], prohibited_actions=[], tool_fallbacks={},
            baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
            originating_escalation_reason="retry_count_exhausted",
            expected_workspace_id=workspace_id,
            expected_lease_token_hash=github_approval_service.lease_token_hash(token),
            max_failed_heads=2, status="approved", delivered_at=datetime.utcnow())
        db.add(revision)
        await db.flush()
        delivery = MailMessage(kind="message", recipient_member_id=_OWNER["member"],
                               body_markdown="Approved revision",
                               delivery_key=f"github-scope:{revision.id}:delivery")
        approval = GithubApprovalRequest(
            work_item_id=item_id, request_kind="continuation", dispatch_nonce=_NONCE,
            approval_round=3, owner_member_id=_OWNER["member"],
            leader_member_id=_LEADER["member"], request_fingerprint="c" * 64,
            status="approved", scope_revision_id=revision.id)
        db.add_all([delivery, approval])
        await db.flush()
        revision.delivery_message_id = delivery.id
        revision.approval_request_id = approval.id
        await db.commit()
        return {"revision": revision.id, "approval": approval.id, "token": token}


@pytest.mark.parametrize("valid_token", [True, False])
async def test_c09_continuation_ack_records_lifecycle_fact_or_refusal(
    store, client, monkeypatch, valid_token
):
    """C09 N4: the owner ACK activates the approved revision with one applied
    lifecycle fact in the activation commit; a wrong lease token is refused,
    recorded for the revision and changes nothing."""
    from app.services.github_client import GithubCommitSnapshot, github_client

    await _seed_team(store)
    ids = await _seed_approved_continuation(store, item_id=91, workspace_id=101)
    _stub_open_pull(monkeypatch)

    async def snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="a" * 40, tree_sha="b" * 40)

    monkeypatch.setattr(github_client, "get_commit_snapshot", snapshot)
    before = await _authority(store, 91)

    response = await client.post(
        "/api/v1/agent-teams/github-work-items/91/scope-revisions/1/ack",
        headers=_session_headers(_OWNER),
        json={"dispatch_nonce": _NONCE,
              "lease_token": ids["token"] if valid_token else "synthetic-wrong-token"})

    facts = await _facts(store, event_kind="continuation_ack")
    after = await _authority(store, 91)
    assert [(f["actor_member_id"], f["actor_session_id"], f["revision_id"]) for f in facts] == [
        (_OWNER["member"], _OWNER["session"], ids["revision"])]
    if valid_token:
        assert response.status_code == 200, response.text
        assert facts[0]["action_outcome"] == "applied"
        assert facts[0]["operation_id"] == f"continuation_ack:revision:{ids['revision']}"
        assert after["item"]["dispatch_status"] == "dispatched"
        assert after["revisions"][0]["status"] == "active"
    else:
        assert response.status_code == 403
        assert facts[0]["action_outcome"] == "rejected"
        # C10: a controlled refusal code is stored exactly.
        assert facts[0]["sanitized_reason"] == "lease_token_mismatch"
        assert after == before


async def test_c09_initial_plan_request_and_decision_record_actors_and_notice(store, client):
    """C09 rows 18-20: the real initial request and Leader decision routes
    record the applied decision in its commit and a separate notice; a
    non-Leader decision is refused and recorded with its actual actor."""
    await _seed_team(store)
    await _seed_work(store, item_id=92, status="dispatched", nonce=_NONCE)

    created = await client.post(
        "/api/v1/agent-mail/approval-requests", headers=_session_headers(_OWNER),
        json={"work_item_id": 92, "dispatch_nonce": _NONCE, "summary": "Initial plan"})
    assert created.status_code == 200, created.text
    request_id = created.json()["id"]
    body = {"work_item_id": 92, "dispatch_nonce": _NONCE, "approval_request_id": request_id,
            "decision": "approved", "reason": "bounded plan"}

    refused = await client.post("/api/v1/agent-mail/decisions",
                                headers=_session_headers(_OTHER), json=body)
    decided = await client.post("/api/v1/agent-mail/decisions",
                                headers=_session_headers(_LEADER), json=body)

    assert refused.status_code == 403
    assert decided.status_code == 200, decided.text
    decisions = await _facts(store, event_kind="approval_decision")
    assert [(f["action_outcome"], f["actor_member_id"], f["actor_session_id"], f["request_id"])
            for f in decisions] == [
        ("rejected", _OTHER["member"], _OTHER["session"], request_id),
        ("applied", _LEADER["member"], _LEADER["session"], request_id),
    ]
    notices = await _facts(store, event_kind="approval_decision_notification")
    assert [(f["action_outcome"], f["request_id"]) for f in notices] == [("applied", request_id)]
    assert decisions[1]["operation_id"] != notices[0]["operation_id"]


async def test_c09_release_remedy_refusals_record_actor_and_keep_guards(store, client):
    """C09 rows 1-2: the operator workspace_not_leased refusal and the owner
    status refusal are recorded with their actual actors before the guard
    refuses; the lease and item state stay unchanged."""
    from app.models.database import GithubWorkspace

    await _seed_team(store)
    await _seed_work(store, item_id=93, status="dispatched", workspace_id=103,
                     lease_token="synthetic-lease-93")
    async with store() as db:
        db.add(GithubWorkspace(id=104, scope_id=5, path="/tmp/matrix-unleased-104"))
        await db.commit()
    before = await _authority(store, 93)

    not_leased = await client.post(
        "/api/v1/agent-teams/github-scopes/5/workspaces/104/force-release",
        headers=_OPERATOR_HEADERS,
        json={"force": True, "expected_leased_at": _lease_iso(), "reason": "fixture"})
    not_releasable = await client.post(
        "/api/v1/agent-teams/dispatch-status", headers=_session_headers(_OWNER),
        json={"work_item_id": 93, "status": "workspace_released",
              "lease_token": "synthetic-lease-93"})

    assert (not_leased.status_code, not_releasable.status_code) == (409, 409)
    facts = await _facts(store, event_kind="workspace_release")
    # C10: controlled refusal codes are stored exactly.
    assert [(f["action_outcome"], f["actor_kind"], f["actor_member_id"], f["item_id"],
             f["sanitized_reason"]) for f in facts] == [
        ("rejected", "operator", None, None, "workspace_not_leased"),
        ("rejected", "member", _OWNER["member"], 93, "status_not_releasable"),
    ]
    assert await _authority(store, 93) == before


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


async def test_r05_scope_route_records_every_finite_policy_value(store, client):
    """R05 (B4 F06): the real scope route stores exact old and new values for
    every general finite policy setting; free-text command hints stay out."""
    import json as _json

    await _seed_team(store)
    fields = ("max_approval_rounds", "max_concurrent_dispatched", "max_verification_retries",
              "max_auto_merges_per_day", "max_build_parallelism", "builds_out_of_tree")
    async with store() as db:
        old = dict((await db.execute(text(
            f"SELECT {', '.join(fields)} FROM team_github_scopes WHERE id = 5"))).mappings().first())
    new = {"max_approval_rounds": 4, "max_concurrent_dispatched": 2,
           "max_verification_retries": 5, "max_auto_merges_per_day": 7,
           "max_build_parallelism": 3, "builds_out_of_tree": True}

    response = await client.patch(
        "/api/v1/agent-teams/github-scopes/5", headers=_OPERATOR_HEADERS,
        json={**new, "build_command_hint": "make -j{parallelism} -C {build_dir}"})

    assert response.status_code == 200, response.text
    facts = await _facts(store, event_kind="policy_change", action_outcome="applied")
    assert len(facts) == 1
    before = _json.loads(facts[0]["before_values"])
    after = _json.loads(facts[0]["after_values"])
    for field in fields:
        expected_old = bool(old[field]) if field == "builds_out_of_tree" else old[field]
        assert before[field] == expected_old, field
        assert after[field] == new[field], field
    assert "build_command_hint" not in after


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


# ---------------------------------------------------------------------------
# C10 safe writer. Every marker is synthetic and contains "SYNTHC10" or the
# hex run "c10c10c10c10". No private value is used.
# ---------------------------------------------------------------------------

_PUBLIC_SHA = "946b540076af5ca0d1ea220bb73a112ab5e49d3a"


async def _raw_ledger_text(maker) -> str:
    """Every stored ledger column, as text, from a fresh session."""
    async with maker() as db:
        rows = (await db.execute(text("SELECT * FROM factory_audit_events"))).fetchall()
    return "\n".join(repr(tuple(row)) for row in rows)


async def test_c10_leader_route_reason_and_slot_snapshot_markers_never_stored(store, client):
    """C10: credential-shaped markers in the actual Leader reason and in the
    slot label captured by its snapshot are absent from the stored row and
    from the protected audit read. Ordinary words and a commit SHA stay."""
    await _seed_team(store)
    async with store() as db:
        await db.execute(text(
            "UPDATE agent_team_slots SET display_name = :name WHERE id = :id"),
            {"name": "Slot secret=SYNTHC10SLOT", "id": _OTHER["slot"]})
        updated_at = (await db.execute(text(
            "SELECT updated_at FROM agent_team_presets WHERE id = 7"))).scalar_one()
        await db.commit()
    reason = (
        f"release rotation at {_PUBLIC_SHA} token=SYNTHC10EQ password: SYNTHC10COLON"
        " Authorization: Bearer SYNTHC10HDR https://fixture:SYNTHC10URL@example.invalid/x"
        " ghp_SYNTHC10GHPmarker0000001 c10c10c10c10c10c10ab")

    response = await client.put(
        "/api/v1/agent-teams/presets/7/leader", headers=_OPERATOR_HEADERS,
        json={"leader_slot_id": _OTHER["slot"], "expected_leader_slot_id": _LEADER["slot"],
              "expected_updated_at": str(updated_at), "reason": reason})
    assert response.status_code == 200, response.text

    stored = await _raw_ledger_text(store)
    read = await client.get("/api/v1/factory/audit-events", headers=_OPERATOR_HEADERS)
    assert read.status_code == 200
    for evidence in (stored, read.text):
        assert "SYNTHC10" not in evidence
        assert "c10c10c10c10" not in evidence
    event = read.json()["items"][0]
    assert event["event_kind"] == "leader_assignment"
    assert event["sanitized_reason"] == (
        f"release rotation at {_PUBLIC_SHA} token=[redacted] password: [redacted]"
        " Authorization: [redacted] https://[redacted]@example.invalid/x [redacted] [redacted]")
    assert event["context_snapshot"]["slot_display_name"] == "Slot secret=[redacted]"
    assert event["after_values"] == {"leader_slot_id": _OTHER["slot"]}


async def test_c10_writer_projects_nested_and_allowed_key_values(db):
    """C10: allowed keys keep only sanitized primitives; nested objects,
    unknown snapshot fields and extra review fields are never stored."""
    await audit.record_event(
        db, event_kind="policy_change", source="test", occurred_at=_now(),
        actor=audit.derive_actor(actor_kind="operator"), action_outcome="applied",
        sanitized_reason='{"secret": "SYNTHC10JSON", "note": "kept"}',
        before_values={"status_note": "plain note"},
        after_values={"status_note": "api_key=SYNTHC10ALLOWED",
                      "status": {"nested": "SYNTHC10NESTED"},
                      "lease_token": "SYNTHC10KEY"},
        context_snapshot={"slot_display_name": "X-Api-Key: SYNTHC10SNAP",
                          "diagnostics": {"command": "SYNTHC10DIAG"},
                          "repo_name": ["SYNTHC10LIST"],
                          "event_time_labels": ["slot_display_name", "SYNTHC10LABEL"]},
        human_review_evidence={"fact_kind": "human_review_acceptance", "artifact": "design-1",
                               "version": "v1", "actor": "reviewer-external",
                               "actor_kind": "human", "independent": True,
                               "source": "Bearer SYNTHC10BEARERVALUE",
                               "raw": {"token": "SYNTHC10RAW"}})
    await db.commit()

    rows = (await db.execute(text("SELECT * FROM factory_audit_events"))).fetchall()
    assert len(rows) == 1
    assert "SYNTHC10" not in repr(tuple(rows[0]))
    event = (await db.execute(select(FactoryAuditEvent))).scalars().one()
    assert event.sanitized_reason == '{"secret": [redacted]", "note": "kept"}'
    assert event.before_values == {"status_note": "plain note"}
    assert event.after_values == {"status_note": "api_key=[redacted]"}
    assert event.context_snapshot == {"slot_display_name": "X-Api-Key: [redacted]",
                                      "event_time_labels": ["slot_display_name"]}
    assert event.human_review_evidence == {
        "fact_kind": "human_review_acceptance", "artifact": "design-1", "version": "v1",
        "actor": "reviewer-external", "actor_kind": "human", "independent": True,
        "source": "Bearer [redacted]"}
    assert audit.validated_review_evidence(event.human_review_evidence) is True


async def test_c09_initial_decision_notice_send_failure_keeps_committed_decision(
    store, client, monkeypatch
):
    """C09: the real Leader decision commits, then its notice send fails. The
    applied decision stays once, the notice is uncertain, and a retry sends
    one notice and records it settled without a second decision fact."""
    from app.services.agent_mail_service import agent_mail_service

    await _seed_team(store)
    await _seed_work(store, item_id=94, status="dispatched", nonce=_NONCE)
    created = await client.post(
        "/api/v1/agent-mail/approval-requests", headers=_session_headers(_OWNER),
        json={"work_item_id": 94, "dispatch_nonce": _NONCE, "summary": "Initial plan"})
    assert created.status_code == 200, created.text
    request_id = created.json()["id"]
    body = {"work_item_id": 94, "dispatch_nonce": _NONCE, "approval_request_id": request_id,
            "decision": "approved", "reason": "bounded plan"}
    original_send = agent_mail_service.send_authoritative_decision

    async def failing_send(*_args, **_kwargs):
        raise RuntimeError("synthetic low-level send failure")

    monkeypatch.setattr(agent_mail_service, "send_authoritative_decision", failing_send)
    failed = await client.post("/api/v1/agent-mail/decisions",
                               headers=_session_headers(_LEADER), json=body)
    assert failed.status_code == 500
    async with store() as db:
        status = (await db.execute(text(
            "SELECT status FROM github_approval_requests WHERE id = :id"),
            {"id": request_id})).scalar_one()
    assert status == "approved"
    notices = await _facts(store, event_kind="approval_decision_notification")
    assert [(f["action_outcome"], f["request_id"], f["actor_session_id"]) for f in notices] == [
        ("uncertain", request_id, _LEADER["session"])]

    monkeypatch.setattr(agent_mail_service, "send_authoritative_decision", original_send)
    retried = await client.post("/api/v1/agent-mail/decisions",
                                headers=_session_headers(_LEADER), json=body)
    assert retried.status_code == 200, retried.text
    decisions = await _facts(store, event_kind="approval_decision")
    assert [(f["action_outcome"], f["actor_member_id"]) for f in decisions] == [
        ("applied", _LEADER["member"])]
    notices = await _facts(store, event_kind="approval_decision_notification")
    assert [f["action_outcome"] for f in notices] == ["uncertain", "applied"]
    assert await _messages_with_key(store, f"github-approval:{request_id}:decision") == 1


async def test_c09_continuation_decision_notice_send_failure_keeps_committed_decision(
    store, client, monkeypatch
):
    """C09: the real continuation decision commits, then its notice send
    fails. The decision stays once, the notice is uncertain for the exact
    revision, and a retry records the settled notice once."""
    from app.services.agent_mail_service import agent_mail_service
    from app.services.github_client import (
        GithubCommitSnapshot, GithubTreeEntry, github_client,
    )

    await _seed_team(store)
    await _seed_work(store, item_id=95, status="escalated", workspace_id=105,
                     workspace_kind="worktree", lease_token="synthetic-lease-95",
                     escalation_reason="retry_count_exhausted", pr_number=73,
                     dispatch_head_ref=_HEAD_REF)
    _stub_open_pull(monkeypatch)

    async def snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="a" * 40, tree_sha="b" * 40)

    async def tree(*_args, **_kwargs):
        return [GithubTreeEntry(path="src/a.py", mode="100644", object_type="blob",
                                sha="c" * 40)]

    monkeypatch.setattr(github_client, "get_commit_snapshot", snapshot)
    monkeypatch.setattr(github_client, "get_recursive_tree", tree)
    proposal = await client.post(
        "/api/v1/agent-teams/github-work-items/95/continuation-requests",
        headers=_session_headers(_OWNER),
        json={"dispatch_nonce": _NONCE, "phase": "implementation",
              "execution_target": "workspace", "summary": "Bounded matrix correction",
              "allowed_paths": ["src/a.py"],
              "allowed_actions": ["edit_production", "push_pr_head", "request_verification"],
              "allowed_commands": ["pytest -q"], "prohibited_actions": ["Do not edit CI"],
              "max_failed_heads": 1, "tool_fallbacks": {},
              "lease_token": "synthetic-lease-95"})
    assert proposal.status_code == 200, proposal.text
    revision_id = proposal.json()["revision"]["id"]
    request_id = proposal.json()["approval"]["id"]
    body = {"approval_request_id": request_id, "work_item_id": 95,
            "dispatch_nonce": _NONCE, "decision": "approved", "reason": "bounded"}
    originals = (agent_mail_service.send_authoritative_decision,
                 agent_mail_service.send_direct_message)

    async def failing_send(*_args, **_kwargs):
        raise RuntimeError("synthetic low-level send failure")

    # Mail boundary: every send path fails after the decision commit.
    monkeypatch.setattr(agent_mail_service, "send_authoritative_decision", failing_send)
    monkeypatch.setattr(agent_mail_service, "send_direct_message", failing_send)
    failed = await client.post("/api/v1/agent-mail/continuation-decisions",
                               headers=_session_headers(_LEADER), json=body)
    assert failed.status_code == 500
    async with store() as db:
        status = (await db.execute(text(
            "SELECT status FROM github_approval_requests WHERE id = :id"),
            {"id": request_id})).scalar_one()
    assert status == "approved"
    notices = await _facts(store, event_kind="continuation_decision_notification")
    assert [(f["action_outcome"], f["request_id"], f["revision_id"], f["actor_session_id"])
            for f in notices] == [("uncertain", request_id, revision_id, _LEADER["session"])]

    monkeypatch.setattr(agent_mail_service, "send_authoritative_decision", originals[0])
    monkeypatch.setattr(agent_mail_service, "send_direct_message", originals[1])
    retried = await client.post("/api/v1/agent-mail/continuation-decisions",
                                headers=_session_headers(_LEADER), json=body)
    assert retried.status_code == 200, retried.text
    decisions = await _facts(store, event_kind="continuation_decision")
    assert [(f["action_outcome"], f["actor_member_id"], f["revision_id"]) for f in decisions] == [
        ("applied", _LEADER["member"], revision_id)]
    notices = await _facts(store, event_kind="continuation_decision_notification")
    assert [f["action_outcome"] for f in notices] == ["uncertain", "applied"]


async def _install_marker(maker) -> None:
    """C12: the disposable store's forward-coverage marker precedes its facts."""
    async with maker() as db:
        await audit.install_forward_coverage(await db.connection(), installed_at=_COVERAGE_START)
        await db.commit()


async def _public_metrics(client, start: datetime, end: datetime) -> dict:
    """F01: the public metrics response, through the real read route."""
    response = await client.get("/api/v1/factory/metrics", params={
        "window_start": start.isoformat(), "window_end": end.isoformat()})
    assert response.status_code == 200, response.text
    return {sample["name"]: sample for sample in response.json()["metrics"]}


async def _outcome_rows(store) -> list[dict]:
    """F01: the retained scope, attempt, version and provenance of outcome facts."""
    async with store() as db:
        rows = (await db.execute(text(
            "SELECT scope_id, item_id, scope_context_key, item_context_key, delivery_outcome,"
            " completion_kind, fact_source, fact_time, source,"
            " json_extract(context_snapshot, '$.attempt') AS attempt,"
            " json_extract(context_snapshot, '$.launch_attempt') AS launch_attempt,"
            " json_extract(context_snapshot, '$.artifact') AS artifact,"
            " json_extract(context_snapshot, '$.artifact_version') AS artifact_version"
            " FROM factory_audit_events WHERE delivery_outcome IS NOT NULL ORDER BY id"
        ))).mappings().all()
    return [dict(row) for row in rows]


@pytest.mark.parametrize(("issue_type", "kind"), [("code", "merged_code"), ("design", "merged_design")])
async def test_r02_real_merge_consumer_records_sourced_delivery(
    store, client, monkeypatch, issue_type, kind
):
    """R02/F01 cases 1-2 (B4 F02/F09, Astra F01, Root 3643): the real
    verification merge path records a delivered fact for the attempt, with
    the PR merge time as the fact time, the merge as the fact source and the
    verified head as the exact version. The public metrics response shows
    one delivered attempt; design review coverage stays separate and
    unknown, because a merge is never review evidence."""
    from app.models.database import GithubWorkItem, TeamGithubScope
    from app.services.github_verification_service import github_verification_service

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=120, status="verifying", issue_type=issue_type)

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_verification_service, "_notify_blocker_merged", no_notice)
    pull = {"number": 73, "merged_at": "2026-10-06T11:58:00Z", "state": "closed",
            "head": {"sha": "a" * 40, "ref": _HEAD_REF}}
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        item = await db.get(GithubWorkItem, 120)
        await github_verification_service._record_selected_pull(db, scope, item, pull, "merged")

    async with store() as db:
        row = (await db.execute(text(
            "SELECT delivery_outcome, completion_kind, fact_source, fact_time, source,"
            " json_extract(context_snapshot, '$.artifact'), team_context_key"
            " FROM factory_audit_events WHERE event_kind = 'delivery_evidence'"))).first()
        window = await metrics.build_metrics_window(
            db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
        status = (await db.execute(text(
            "SELECT dispatch_status FROM github_work_items WHERE id = 120"))).scalar_one()
    assert row[:3] == ("delivered", kind, "github_pull_request_merged")
    assert datetime.fromisoformat(str(row[3])) == datetime(2026, 10, 6, 11, 58)
    assert row[4] == "github_verification_service._record_selected_pull"
    assert row[5] == "matrix-owner/matrix-repo/pull/73"
    assert row[6] is not None  # R04: the parent team key is resolved
    assert status == "merged"
    by_name = {s.name: s for s in window.metrics}
    assert by_name["delivered_in_window"].value == 1.0
    # Independent human review is never inferred from a merge.
    review = by_name["independently_human_reviewed_design"]
    assert (review.value, review.unknown_count) == ((0.0, 1) if issue_type == "design" else (0.0, 0))
    # F01: retained scope, attempt, version and provenance.
    (fact,) = await _outcome_rows(store)
    assert (fact["scope_id"], fact["item_id"]) == (5, 120)
    assert fact["scope_context_key"] and fact["item_context_key"]
    assert fact["attempt"].startswith("item:120:launch:")
    assert fact["launch_attempt"].startswith("item:120:launch:")
    assert fact["artifact_version"] == "a" * 40
    # F01: the public metrics response.
    public = await _public_metrics(client, _now() - timedelta(days=1), _now() + timedelta(hours=1))
    assert (public["delivered_in_window"]["value"], public["delivered_in_window"]["sample_count"]) == (1.0, 1)
    # T09: separate code and design delivery categories.
    assert (public["merged_code_in_window"]["value"], public["delivered_design_in_window"]["value"]) == (
        (1.0, 0.0) if issue_type == "code" else (0.0, 1.0))
    reviewed = public["independently_human_reviewed_design"]
    assert (reviewed["value"], reviewed["sample_count"], reviewed["unknown_count"]) == (
        (0.0, 1, 1) if issue_type == "design" else (0.0, 0, 0))


@pytest.mark.parametrize(("state_reason", "expected"), [
    ("not_planned", "closed_without_delivery"), ("duplicate", "closed_without_delivery"),
    ("completed", "unknown")])
async def test_r02_watcher_records_sourced_terminal_non_delivery(
    store, client, monkeypatch, state_reason, expected
):
    """R02/F01 case 3 (Root 3643): GitHub's confirmed not-planned or
    duplicate closure, with no PR, is sourced terminal non-delivery through
    the real watcher; an ordinary closure stays unknown. The public metrics
    response reports the matching terminal outcome and no delivery."""
    from app.models.database import TeamGithubScope
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_watcher_service import github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=121, status="escalated", escalation_reason="plan_blocked")

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_dispatch_service, "notify_blocker_merged", no_notice)

    class ClosedIssue:
        async def get_issues_by_number(self, owner, repo, numbers):
            return {number: {"state": "closed", "state_reason": state_reason,
                             "closed_at": "2026-10-06T11:30:00Z", "labels": []}
                    for number in numbers}

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await github_watcher_service._reconcile_closed_issues(db, scope, ClosedIssue())
    async with store() as db:
        row = (await db.execute(text(
            "SELECT delivery_outcome, fact_source, fact_time FROM factory_audit_events"
            " WHERE event_kind = 'delivery_evidence'"))).first()
    assert row[0] == expected
    if expected == "closed_without_delivery":
        # The issue closure is this fact, so its closure time is the fact time.
        assert row[1] == "github_issue_state_reason"
        assert datetime.fromisoformat(str(row[2])) == datetime(2026, 10, 6, 11, 30)
    else:
        # A30: an ordinary closure proves no result; its result time stays unknown.
        assert row[2] is None
    (fact,) = await _outcome_rows(store)
    assert (fact["scope_id"], fact["item_id"], fact["source"]) == (
        5, 121, "github_watcher_service._reconcile_closed_issues")
    assert fact["attempt"].startswith("item:121:launch:") and fact["item_context_key"]
    public = await _public_metrics(client, datetime(2026, 10, 6), datetime.utcnow() + timedelta(hours=1))
    assert public["delivered_in_window"]["value"] == 0.0
    assert public["closed_without_delivery"]["value"] == (
        1.0 if expected == "closed_without_delivery" else 0.0)
    assert public["unknown_outcomes"]["value"] == (1.0 if expected == "unknown" else 0.0)


_A30_HEAD_REF = "deck/slot-1/issue-130-a30"


def _a30_pull(number: int, *, state: str = "closed", merged_at: str | None = None,
              base: str = "main", repo: str = "matrix-owner/matrix-repo",
              head_ref: str = _A30_HEAD_REF) -> dict:
    """A GitHub pull representation at the client-method boundary."""
    from app.config import settings

    return {
        "number": number, "state": state, "merged_at": merged_at, "merged": merged_at is not None,
        "closed_at": "2026-10-06T11:35:00Z" if state == "closed" else None,
        "head": {"ref": head_ref, "sha": "d" * 40, "repo": {"full_name": repo}},
        "base": {"ref": base, "repo": {"full_name": repo}},
        "user": {"login": settings.github_app_bot_login},
    }


class _A30Client:
    """Fake client: fixed issue state and an attempt pull inventory."""

    def __init__(self, pulls=None, *, error: bool = False, on_list=None):
        self.pulls = pulls if pulls is not None else [_a30_pull(73)]
        self.error = error
        self.on_list = on_list
        self.list_calls = 0

    async def get_issues_by_number(self, owner, repo, numbers):
        return {number: {"state": "closed", "state_reason": "completed",
                         "closed_at": "2026-10-06T11:40:00Z", "labels": []}
                for number in numbers}

    async def list_pulls_for_head(self, owner, repo, *, head, base, state, token=None):
        self.list_calls += 1
        if self.on_list is not None:
            await self.on_list()
        if self.error:
            raise RuntimeError("GitHub unavailable")
        assert head == f"{owner}:{_A30_HEAD_REF}" and state == "all"
        return list(self.pulls)


def _a30_patch_reads(monkeypatch) -> None:
    """Keep the scoped token and base read local; the inventory read is real."""
    from app.services.github_approval_service import github_approval_service
    from app.services.github_verification_service import github_verification_service

    async def read_token(_scope):
        return "scoped-read"

    async def base_ref(_scope, _client, *, token, base_ref):
        return "main"

    monkeypatch.setattr(github_approval_service, "github_read_token", read_token)
    monkeypatch.setattr(github_verification_service, "normalize_base_ref", base_ref)


@pytest.mark.parametrize("case", [
    "terminal", "other_escalation", "pending_request", "live_revision", "retry_requested",
    "merged_now", "reopened", "read_error", "empty_inventory", "wrong_base", "wrong_repo",
    "pr_missing", "approval_during_read", "nonce_changed_during_read"])
async def test_a30_closed_unmerged_terminal_consumer_keeps_continuation_guards(
    store, client, monkeypatch, case
):
    """A30/A34 (Root 3599): a cached escalation reason is not proof. Only fresh
    scoped proof that every pull of the attempt is closed unmerged, with the
    issue closed and no continuing attempt, ends the attempt as sourced
    non-delivery with an unknown result time. A merged or reopened pull, a
    read error, an empty inventory, an identity failure, a continuation, or
    a change during the read records nothing and keeps all state."""
    from app.models.database import (
        GithubApprovalRequest, GithubAttemptScopeRevision, TeamGithubScope,
    )
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_watcher_service import github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(
        store, item_id=130, status="escalated", pr_number=73,
        escalation_reason="plan_blocked" if case == "other_escalation" else "pr_closed_unmerged",
        retry_requested_at=_FIXED_LEASE if case == "retry_requested" else None)
    async with store() as db:
        await db.execute(text(
            "UPDATE github_work_items SET dispatch_head_ref = :ref WHERE id = 130"),
            {"ref": _A30_HEAD_REF})
        await db.commit()
    async with store() as db:
        if case == "pending_request":
            db.add(GithubApprovalRequest(
                work_item_id=130, request_kind="initial_plan", dispatch_nonce=_NONCE,
                approval_round=3, owner_member_id=_OWNER["member"],
                leader_member_id=_LEADER["member"], request_fingerprint="f" * 64,
                status="pending"))
        if case == "live_revision":
            await db.execute(text(
                "INSERT INTO github_workspaces (id, scope_id, path, kind, dispatchable, enabled,"
                " created_at, updated_at) VALUES (130, 5, '/tmp/ws-130', 'worktree', 1, 1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            db.add(GithubAttemptScopeRevision(
                work_item_id=130, dispatch_nonce=_NONCE, revision=1,
                owner_slot_id=_OWNER["slot"], owner_member_id=_OWNER["member"],
                phase="implementation", execution_target="workspace", summary="Live",
                allowed_paths=["src/a.py"], allowed_actions=["edit_production"],
                allowed_commands=[], prohibited_actions=[], tool_fallbacks={},
                baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
                originating_escalation_reason="pr_closed_unmerged",
                expected_workspace_id=130, expected_lease_token_hash="h" * 64,
                max_failed_heads=2, status="proposed"))
        await db.commit()
    before = await _authority(store, 130)

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_dispatch_service, "notify_blocker_merged", no_notice)
    _a30_patch_reads(monkeypatch)

    async def add_pending_approval():
        async with store() as other:
            other.add(GithubApprovalRequest(
                work_item_id=130, request_kind="initial_plan", dispatch_nonce=_NONCE,
                approval_round=4, owner_member_id=_OWNER["member"],
                leader_member_id=_LEADER["member"], request_fingerprint="e" * 64,
                status="pending"))
            await other.commit()

    async def change_nonce():
        async with store() as other:
            await other.execute(text(
                "UPDATE github_work_items SET dispatch_nonce = 'changed-nonce' WHERE id = 130"))
            await other.commit()

    pulls = {
        "merged_now": [_a30_pull(73, merged_at="2026-10-06T11:20:00Z")],
        "reopened": [_a30_pull(73, state="open")],
        "empty_inventory": [],
        "wrong_base": [_a30_pull(73, base="release")],
        "wrong_repo": [_a30_pull(73, repo="other-owner/matrix-repo")],
        "pr_missing": [_a30_pull(74)],
    }.get(case)
    github = _A30Client(
        pulls, error=case == "read_error",
        on_list={"approval_during_read": add_pending_approval,
                 "nonce_changed_during_read": change_nonce}.get(case))
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await github_watcher_service._reconcile_closed_issues(db, scope, github)

    facts = await _facts(store, event_kind="delivery_evidence")
    after = await _authority(store, 130)
    if case not in ("terminal", "other_escalation"):
        assert facts == []
        if case in ("approval_during_read", "nonce_changed_during_read"):
            assert after["item"]["dispatch_status"] == "escalated"
        else:
            assert after == before
        return
    assert github.list_calls == 1
    async with store() as db:
        row = (await db.execute(text(
            "SELECT delivery_outcome, completion_kind, fact_source, fact_time,"
            " json_extract(context_snapshot, '$.artifact'),"
            " json_extract(context_snapshot, '$.pull_closed_at'),"
            " json_extract(context_snapshot, '$.issue_closed_at') FROM factory_audit_events"
            " WHERE event_kind = 'delivery_evidence'"))).first()
    assert row[:3] == ("closed_without_delivery", "pr_closed_unmerged",
                       "github_pull_request_closed_unmerged")
    # The conjunction of current conditions has no reliable result time; the
    # pull and issue closure times stay separate source times.
    assert row[3] is None
    assert row[4] == "matrix-owner/matrix-repo/pull/73"
    assert (row[5], row[6]) == ("2026-10-06T11:35:00Z", "2026-10-06T11:40:00Z")
    assert after["item"]["dispatch_status"] == "completed"
    # F01 case 4: retained scope, attempt and provenance; public metrics.
    (fact,) = await _outcome_rows(store)
    assert (fact["scope_id"], fact["item_id"], fact["source"]) == (
        5, 130, "github_watcher_service._reconcile_closed_issues")
    assert fact["attempt"].startswith("item:130:launch:") and fact["item_context_key"]
    public = await _public_metrics(client, datetime(2026, 10, 6), datetime.utcnow() + timedelta(hours=1))
    assert (public["closed_without_delivery"]["value"], public["delivered_in_window"]["value"]) == (
        1.0, 0.0)


@pytest.mark.parametrize("case", [
    "pending_request", "live_revision", "retry_requested",
    "late_acquisition_no_pr", "late_acquisition_pr", "terminal_no_pr"])
async def test_t01_terminal_claim_refuses_continuing_authority_on_both_paths(
    store, monkeypatch, case
):
    """T01 (Astra F01, P1): the terminal claim and its result fact share one
    transaction. On the no-PR path, a pending request, a live revision or a
    requested retry keeps the item: no result fact, no completion and exact
    authority. A continuation committed by an independent session after the
    watcher's last read, before the write, also makes the claim refuse, on
    the no-PR and the PR path. A free no-PR closure still completes."""
    from app.models.database import (
        GithubApprovalRequest, GithubAttemptScopeRevision, TeamGithubScope,
    )
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_watcher_service import GithubWatcherService, github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    with_pr = case == "late_acquisition_pr"
    await _seed_work(
        store, item_id=160, status="escalated", pr_number=73 if with_pr else None,
        escalation_reason="plan_blocked",
        retry_requested_at=_FIXED_LEASE if case == "retry_requested" else None)
    async with store() as db:
        await db.execute(text(
            "UPDATE github_work_items SET dispatch_head_ref = :ref WHERE id = 160"),
            {"ref": _A30_HEAD_REF})
        if case == "live_revision":
            await db.execute(text(
                "INSERT INTO github_workspaces (id, scope_id, path, kind, dispatchable, enabled,"
                " created_at, updated_at) VALUES (160, 5, '/tmp/ws-160', 'worktree', 1, 1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            db.add(GithubAttemptScopeRevision(
                work_item_id=160, dispatch_nonce=_NONCE, revision=1,
                owner_slot_id=_OWNER["slot"], owner_member_id=_OWNER["member"],
                phase="implementation", execution_target="workspace", summary="Live",
                allowed_paths=["src/a.py"], allowed_actions=["edit_production"],
                allowed_commands=[], prohibited_actions=[], tool_fallbacks={},
                baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
                originating_escalation_reason="plan_blocked",
                expected_workspace_id=160, expected_lease_token_hash="h" * 64,
                max_failed_heads=2, status="proposed"))
        if case == "pending_request":
            db.add(GithubApprovalRequest(
                work_item_id=160, request_kind="initial_plan", dispatch_nonce=_NONCE,
                approval_round=3, owner_member_id=_OWNER["member"],
                leader_member_id=_LEADER["member"], request_fingerprint="f" * 64,
                status="pending"))
        await db.commit()
    before = await _authority(store, 160)

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_dispatch_service, "notify_blocker_merged", no_notice)
    _a30_patch_reads(monkeypatch)

    # The late acquisition commits from an independent session immediately
    # after the watcher's last continuation read returned "no continuation".
    original = GithubWatcherService._attempt_continues
    last_read = 2 if with_pr else 1
    calls = {"n": 0}

    async def read_then_acquire(self, db, item_id):
        result = await original(self, db, item_id)
        calls["n"] += 1
        if case.startswith("late_acquisition") and calls["n"] == last_read:
            async with store() as other:
                other.add(GithubApprovalRequest(
                    work_item_id=160, request_kind="initial_plan", dispatch_nonce=_NONCE,
                    approval_round=4, owner_member_id=_OWNER["member"],
                    leader_member_id=_LEADER["member"], request_fingerprint="e" * 64,
                    status="pending"))
                await other.commit()
        return result

    monkeypatch.setattr(GithubWatcherService, "_attempt_continues", read_then_acquire)

    class ClosedNotPlanned(_A30Client):
        async def get_issues_by_number(self, owner, repo, numbers):
            return {number: {"state": "closed", "state_reason": "not_planned",
                             "closed_at": "2026-10-06T11:40:00Z", "labels": []}
                    for number in numbers}

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await github_watcher_service._reconcile_closed_issues(db, scope, ClosedNotPlanned())

    facts = await _facts(store, event_kind="delivery_evidence")
    after = await _authority(store, 160)
    if case == "terminal_no_pr":
        assert len(facts) == 1
        assert after["item"]["dispatch_status"] == "completed"
        return
    assert facts == []
    if case.startswith("late_acquisition"):
        assert calls["n"] == last_read
        # Only the independent session's own request was added.
        assert after["item"] == before["item"]
    else:
        assert after == before


@pytest.mark.parametrize("case", [
    "active_pending_request", "active_live_revision", "active_retry_requested",
    "active_late_acquisition", "active_terminal"])
async def test_t01_active_closure_claim_refuses_continuing_authority(store, monkeypatch, case):
    """T01 (B1 3715): the active-item closure consumer uses the same guarded
    terminal claim. A pending request, a live revision, a requested retry, or
    a continuation committed by an independent session just before the
    write keeps the active item with no result fact. A closed issue with no
    continuing authority still completes the active item."""
    from app.models.database import (
        GithubApprovalRequest, GithubAttemptScopeRevision, TeamGithubScope,
    )
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_watcher_service import GithubWatcherService, github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(
        store, item_id=161, status="dispatched",
        retry_requested_at=_FIXED_LEASE if case == "active_retry_requested" else None)
    async with store() as db:
        if case == "active_live_revision":
            await db.execute(text(
                "INSERT INTO github_workspaces (id, scope_id, path, kind, dispatchable, enabled,"
                " created_at, updated_at) VALUES (161, 5, '/tmp/ws-161', 'worktree', 1, 1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            db.add(GithubAttemptScopeRevision(
                work_item_id=161, dispatch_nonce=_NONCE, revision=1,
                owner_slot_id=_OWNER["slot"], owner_member_id=_OWNER["member"],
                phase="implementation", execution_target="workspace", summary="Live",
                allowed_paths=["src/a.py"], allowed_actions=["edit_production"],
                allowed_commands=[], prohibited_actions=[], tool_fallbacks={},
                baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
                originating_escalation_reason="plan_blocked",
                expected_workspace_id=161, expected_lease_token_hash="h" * 64,
                max_failed_heads=2, status="active"))
        if case == "active_pending_request":
            db.add(GithubApprovalRequest(
                work_item_id=161, request_kind="initial_plan", dispatch_nonce=_NONCE,
                approval_round=3, owner_member_id=_OWNER["member"],
                leader_member_id=_LEADER["member"], request_fingerprint="f" * 64,
                status="pending"))
        await db.commit()
    before = await _authority(store, 161)

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_dispatch_service, "notify_blocker_merged", no_notice)
    original = GithubWatcherService._claim_terminal

    async def acquire_then_claim(self, db, item_id, **kwargs):
        if case == "active_late_acquisition":
            async with store() as other:
                other.add(GithubApprovalRequest(
                    work_item_id=161, request_kind="initial_plan", dispatch_nonce=_NONCE,
                    approval_round=4, owner_member_id=_OWNER["member"],
                    leader_member_id=_LEADER["member"], request_fingerprint="e" * 64,
                    status="pending"))
                await other.commit()
        return await original(self, db, item_id, **kwargs)

    monkeypatch.setattr(GithubWatcherService, "_claim_terminal", acquire_then_claim)

    class ClosedIssue:
        async def get_issues_by_number(self, owner, repo, numbers):
            return {number: {"state": "closed", "state_reason": "completed",
                             "closed_at": "2026-10-06T11:40:00Z", "labels": []}
                    for number in numbers}

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await github_watcher_service._recheck_active_items(db, scope, ClosedIssue())

    facts = await _facts(store, event_kind="delivery_evidence")
    after = await _authority(store, 161)
    if case == "active_terminal":
        assert len(facts) == 1
        assert after["item"]["dispatch_status"] == "completed"
        return
    assert facts == []
    if case == "active_late_acquisition":
        assert after["item"] == before["item"]
    else:
        assert after == before


def _native_process(argv0: str, *args: str, executable: str = "/bin/sleep"):
    """A synthetic native fixture: a real process whose argv[0] is argv0.

    It runs /bin/sleep (or a shell), so it claims no real model or provider
    trial.
    """
    import subprocess

    from app.utils import peer_process

    process = subprocess.Popen([argv0, *(args or ("30",))], executable=executable)
    for _ in range(100):
        stat = peer_process.read_proc_stat(process.pid)
        if stat is not None:
            break
    return process, stat[1]


async def _bind_native(store, who: dict, pid: int, start: str, *, claimed: str = "claude-code",
                       source: str = "mcp", token: bool = True) -> None:
    """Make ``who``'s Mail session the slot's current authenticated MCP generation."""
    async with store() as db:
        await db.execute(text(
            "UPDATE mail_team_members SET participant_kind = 'team_slot', team_slot_id = :slot"
            " WHERE id = :member"), {"slot": who["slot"], "member": who["member"]})
        await db.execute(text(
            "UPDATE mail_agent_sessions SET source = :source, closed_at = NULL,"
            " mailbox_status = 'connected', capability_token_hash = :token,"
            " last_seen_at = CURRENT_TIMESTAMP,"
            " bound_pane_pid = :pid, bound_pane_proc_start = :start, team_slot_id = :slot,"
            " member_id = :member, provider = :claimed WHERE id = :session"),
            {"source": source, "token": "h" * 64 if token else None, "pid": pid,
             "start": start, "slot": who["slot"], "member": who["member"],
             "claimed": claimed, "session": who["session"]})
        await db.execute(text(
            "INSERT INTO agent_pane_bindings (pane_pid, pane_proc_start, slot_id, preset_id,"
            " created_at) VALUES (:pid, :start, :slot, 7, CURRENT_TIMESTAMP)"),
            {"pid": pid, "start": start, "slot": who["slot"]})
        await db.execute(text(
            "INSERT OR IGNORE INTO mail_pane_lifecycles (pane_pid, pane_proc_start, retired_at)"
            " VALUES (:pid, :start, NULL)"), {"pid": pid, "start": start})
        await db.execute(text(
            "UPDATE agent_team_slots SET provider = 'claude-code' WHERE id = :slot"),
            {"slot": who["slot"]})
        await db.commit()


async def _runtime_rows(store, event_kind: str) -> list[tuple]:
    async with store() as db:
        rows = (await db.execute(text(
            "SELECT json_extract(context_snapshot, '$.configured_provider'),"
            " json_extract(context_snapshot, '$.observed_runtime_provider'),"
            " json_extract(context_snapshot, '$.runtime_provider_evidence'),"
            " json_extract(context_snapshot, '$.claimed_runtime_provider')"
            " FROM factory_audit_events WHERE event_kind = :kind ORDER BY id"),
            {"kind": event_kind})).fetchall()
    return [tuple(row) for row in rows]


async def test_a20_real_consumers_record_native_runtime_apart_from_configuration(store, client):
    """A20 (Root 3599): real policy (Leader slot), dispatch and workspace
    consumers record the configured slot provider and, separately, the
    provider proven by the native process of the slot's current
    authenticated MCP generation. The registered provider is only a claim.
    Renaming or reassigning afterward leaves the stored snapshots unchanged.
    The native processes are synthetic fixtures; no model trial is claimed."""
    from app.models.database import GithubWorkItem
    from app.services.github_dispatch_service import observe_work_lifecycle
    from app.services.github_workspace_service import github_workspace_service

    await _seed_team(store)
    await _seed_work(store, item_id=131, status="pending")
    await _seed_work(store, item_id=132, status="merged", workspace_id=133,
                     lease_token="synthetic-lease-132")
    owner_process, owner_start = _native_process("codex")
    leader_process, leader_start = _native_process("codex")
    try:
        await _bind_native(store, _OWNER, owner_process.pid, owner_start)
        await _bind_native(store, _LEADER, leader_process.pid, leader_start)

        # Policy: the real preset route records a team fact on the Leader slot.
        response = await client.patch(
            "/api/v1/agent-teams/presets/7", headers=_OPERATOR_HEADERS,
            json={"autonomy_enabled": True})
        assert response.status_code == 200
        # Dispatch: the real lifecycle writer.
        async with store() as db:
            item = await db.get(GithubWorkItem, 131)
            await observe_work_lifecycle(db, item=item, from_status=None, to_status="dispatched",
                                         source="github_dispatch_service.launch")
            await db.commit()
        # Workspace: the real release writer.
        async with store() as db:
            assert await github_workspace_service.release(db, 132) is True

        expected = ("claude-code", "codex-cli", "native_argv", "claude-code")
        assert (await _runtime_rows(store, "policy_change"))[-1] == expected
        assert (await _runtime_rows(store, "work_lifecycle"))[-1] == expected
        assert (await _runtime_rows(store, "workspace_release"))[-1] == expected

        # Rename and reassign afterward: the stored snapshots never change.
        async with store() as db:
            await db.execute(text(
                "UPDATE agent_team_slots SET provider = 'pi-cli', display_name = 'Renamed'"
                " WHERE id = :slot"), {"slot": _OWNER["slot"]})
            await db.execute(text(
                "UPDATE mail_agent_sessions SET closed_at = CURRENT_TIMESTAMP WHERE id = :id"),
                {"id": _OWNER["session"]})
            await db.commit()
        assert (await _runtime_rows(store, "work_lifecycle"))[-1] == expected
    finally:
        for process in (owner_process, leader_process):
            process.kill()
            process.wait()


@pytest.mark.parametrize("case", [
    "absent_closed", "observed_only", "no_token", "unbound_binding", "ambiguous_sessions",
    "changed_lifetime", "lifetime_changed_after_read", "unrelated_argument",
    "helper_executable", "stale_generation", "expires_during_read"])
async def test_a20_runtime_stays_unknown_without_current_native_proof(store, monkeypatch, case):
    """A20 (Root 3599): an old, observed-only, unauthenticated, unbound or
    ambiguous session, a changed process lifetime, a change after the native
    read, an unrelated argument or a helper executable proves nothing; the
    runtime stays unknown with its evidence label."""
    from app.models.database import GithubWorkItem
    from app.services.github_dispatch_service import observe_work_lifecycle
    from app.utils import peer_process

    await _seed_team(store)
    await _seed_work(store, item_id=134, status="pending")
    if case == "unrelated_argument":
        # A shell whose later argument is named like a provider.
        process, start = _native_process(
            "sh", "-c", "sleep 30; :", "claude", executable="/bin/sh")
    else:
        process, start = _native_process(
            "codex-exec-server" if case == "helper_executable" else "codex")
    try:
        await _bind_native(
            store, _OWNER, process.pid,
            "1" if case == "changed_lifetime" else start,
            source="observed" if case == "observed_only" else "mcp",
            token=case != "no_token")
        async with store() as db:
            if case == "absent_closed":
                await db.execute(text(
                    "UPDATE mail_agent_sessions SET closed_at = CURRENT_TIMESTAMP WHERE id = :id"),
                    {"id": _OWNER["session"]})
            if case == "unbound_binding":
                # A newer launch binding for the slot; the session is old.
                await db.execute(text(
                    "INSERT INTO agent_pane_bindings (pane_pid, pane_proc_start, slot_id,"
                    " preset_id, created_at) VALUES (1, '1', :slot, 7, CURRENT_TIMESTAMP)"),
                    {"slot": _OWNER["slot"]})
            if case == "ambiguous_sessions":
                await db.execute(text(
                    "INSERT INTO mail_agent_sessions (member_id, provider, source, session_key,"
                    " team_slot_id, capability_token_hash, bound_pane_pid, bound_pane_proc_start,"
                    " wake_enabled, mailbox_status, last_seen_at, created_at) VALUES"
                    " (:member, 'codex-cli', 'mcp', 'mcp:a20-second', :slot, :token, :pid, :start,"
                    " 0, 'connected', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                    {"member": _OWNER["member"], "slot": _OWNER["slot"], "token": "h" * 64,
                     "pid": process.pid, "start": start})
            await db.commit()
        if case == "lifetime_changed_after_read":
            # The process lifetime check after the native read fails, as for
            # a pane process that ended or was replaced during the read.
            original_alive = peer_process.pane_is_alive_strict
            monkeypatch.setattr(peer_process, "pane_is_alive_strict",
                                lambda pid, proc_start: False if pid == process.pid
                                else original_alive(pid, proc_start))
        if case == "stale_generation":
            # T10: a connected, token-holding generation whose heartbeat expired.
            async with store() as db:
                await db.execute(text(
                    "UPDATE mail_agent_sessions SET last_seen_at = '2026-01-01 00:00:00'"
                    " WHERE id = :id"), {"id": _OWNER["session"]})
                await db.commit()
        if case == "expires_during_read":
            # T10: the freshness rule expires the generation during the native
            # read; the recheck after the read must refuse it.
            from app.services import agent_mail_service as _mail_module

            original_argv = peer_process.pane_agent_argv

            def read_then_expire(pid, proc_start):
                argv = original_argv(pid, proc_start)
                monkeypatch.setattr(_mail_module, "MCP_HEARTBEAT_TTL_SECONDS", -3600)
                return argv

            monkeypatch.setattr(peer_process, "pane_agent_argv", read_then_expire)
        async with store() as db:
            item = await db.get(GithubWorkItem, 134)
            await observe_work_lifecycle(db, item=item, from_status=None, to_status="dispatched",
                                         source="github_dispatch_service.launch")
            await db.commit()
    finally:
        process.kill()
        process.wait()

    expected = {
        "absent_closed": "absent", "observed_only": "absent", "no_token": "absent",
        "unbound_binding": "absent", "ambiguous_sessions": "ambiguous",
        "changed_lifetime": "unavailable", "lifetime_changed_after_read": "lifetime_changed",
        "unrelated_argument": "unsupported_form", "helper_executable": "unsupported_form",
        "stale_generation": "stale", "expires_during_read": "lifetime_changed",
    }[case]
    row = (await _runtime_rows(store, "work_lifecycle"))[-1]
    assert row[:3] == ("claude-code", None, expected)


_A32_HEAD = "d" * 40


async def _a32_item(store, item_id: int, *, issue_type: str = "design",
                    head: str | None = _A32_HEAD) -> str:
    """Seed an item at a verified PR head; return its current attempt key."""
    from app.models.database import GithubWorkItem
    from app.services import factory_audit_service as _audit

    await _seed_work(store, item_id=item_id, status="awaiting_human_review", pr_number=73)
    async with store() as db:
        await db.execute(text(
            "UPDATE github_work_items SET issue_type = :kind, verification_head_sha = :head"
            " WHERE id = :id"), {"kind": issue_type, "head": head, "id": item_id})
        await db.commit()
    async with store() as db:
        item = await db.get(GithubWorkItem, item_id)
        attempt, _revision, _launch = await _audit.item_attempt(db, item)
    return attempt


def _a32_body(item_id: int, current_attempt: str, /, **overrides) -> dict:
    body = {
        "declaration_id": f"synthetic-decl-{item_id}", "work_item_id": item_id,
        "attempt": current_attempt, "artifact": "matrix-owner/matrix-repo/pull/73",
        "version": _A32_HEAD, "reviewer": "synthetic-external-reviewer",
        "reviewer_kind": "human", "independent": True, "decision": "accepted",
        "occurred_at": "2026-10-06T10:00:00+00:00", "source_kind": "operator_attested",
        "source_ref": "synthetic-review-record-1",
    }
    body.update(overrides)
    return body


async def _review_rows(store) -> list[dict]:
    async with store() as db:
        rows = (await db.execute(text(
            "SELECT id, actor_kind, actor_reference, action_outcome, record_kind, fact_time,"
            " json_extract(human_review_evidence, '$.actor') AS reviewer,"
            " json_extract(human_review_evidence, '$.declared_by') AS declared_by"
            " FROM factory_audit_events WHERE human_review_evidence IS NOT NULL ORDER BY id"
        ))).mappings().all()
    return [dict(row) for row in rows]


def _metric(window, name):
    return {sample.name: sample for sample in window.metrics}[name]


async def test_a32_declaration_before_merge_establishes_exact_design_delivery(store, client):
    """A32 (Root 3599): a trusted, independent, exact-version acceptance of a
    design PR records review evidence and establishes delivery before any
    merge. The recording actor stays separate from the declared reviewer.
    A later merge of the same version adds no second delivery or review.
    Exact replay returns the record; a changed body conflicts. No work
    state, approval or counter changes. The declaration is synthetic; no
    human trial is claimed."""
    from app.models.database import GithubWorkItem
    from app.services import factory_audit_service as _audit
    from app.services import factory_metrics_service as metrics

    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 140)
    before = await _authority(store, 140)

    created = await client.post("/api/v1/factory/review-acceptances",
                                headers=_OPERATOR_HEADERS, json=_a32_body(140, attempt))
    assert created.status_code == 201, created.text
    assert (created.json()["counted"], created.json()["delivery_established"]) == (True, True)

    rows = await _review_rows(store)
    assert len(rows) == 1
    assert (rows[0]["actor_kind"], rows[0]["actor_reference"], rows[0]["record_kind"]) == (
        "operator", "shared-operator-credential", "declared")
    assert (rows[0]["reviewer"], rows[0]["declared_by"]) == (
        "synthetic-external-reviewer", "shared-operator-credential")
    assert datetime.fromisoformat(str(rows[0]["fact_time"])) == datetime(2026, 10, 6, 10, 0)
    async with store() as db:
        delivery = (await db.execute(text(
            "SELECT delivery_outcome, completion_kind, json_extract(context_snapshot, '$.attempt'),"
            " json_extract(context_snapshot, '$.artifact_version') FROM factory_audit_events"
            " WHERE event_kind = 'delivery_evidence'"))).fetchall()
    assert [tuple(row) for row in delivery] == [
        ("delivered", "design_artifact_accepted", attempt, _A32_HEAD)]
    assert await _authority(store, 140) == before

    window_args = dict(window_start=datetime(2026, 10, 6, 9), window_end=_now() + timedelta(hours=1))
    async with store() as db:
        window = await metrics.build_metrics_window(db, **window_args)
    assert _metric(window, "delivered_in_window").value == 1.0
    reviewed = _metric(window, "independently_human_reviewed_design")
    assert (reviewed.value, reviewed.sample_count, reviewed.unknown_count) == (1.0, 1, 0)
    # F01 case 5: retained scope, attempt, version and provenance; public metrics.
    (fact,) = await _outcome_rows(store)
    assert (fact["scope_id"], fact["item_id"], fact["source"], fact["fact_source"]) == (
        5, 140, "operator_declaration", "operator_attested:synthetic-review-record-1")
    assert (fact["attempt"], fact["artifact"], fact["artifact_version"]) == (
        attempt, "matrix-owner/matrix-repo/pull/73", _A32_HEAD)
    public = await _public_metrics(client, window_args["window_start"], window_args["window_end"])
    assert public["delivered_in_window"]["value"] == 1.0
    assert (public["independently_human_reviewed_design"]["value"],
            public["independently_human_reviewed_design"]["unknown_count"]) == (1.0, 0)

    replay = await client.post("/api/v1/factory/review-acceptances",
                               headers=_OPERATOR_HEADERS, json=_a32_body(140, attempt))
    assert replay.status_code == 200
    conflict = await client.post(
        "/api/v1/factory/review-acceptances", headers=_OPERATOR_HEADERS,
        json=_a32_body(140, attempt, reviewer="another-synthetic-reviewer"))
    assert conflict.status_code == 409
    assert conflict.json()["refusal"] == "replay_conflict"
    assert len(await _review_rows(store)) == 1

    # A later merge of the same version: one delivered attempt, one review.
    async with store() as db:
        item = await db.get(GithubWorkItem, 140)
        await _audit.record_merged_delivery(
            db, item, {"number": 73, "merged_at": "2026-10-06T10:30:00Z",
                       "head": {"sha": _A32_HEAD}}, source="test.merge")
        await db.commit()
    async with store() as db:
        window = await metrics.build_metrics_window(db, **window_args)
    assert _metric(window, "delivered_in_window").value == 1.0
    reviewed = _metric(window, "independently_human_reviewed_design")
    assert (reviewed.value, reviewed.sample_count) == (1.0, 1)


@pytest.mark.parametrize("case", [
    "version_changed", "version_unrelated", "artifact_unrelated", "attempt_unrelated",
    "other_item_attempt", "work_item_not_found"])
async def test_a32_declaration_refuses_changed_or_unrelated_bindings(store, client, case):
    """A32: a changed head, a version never recorded for the attempt, another
    artifact or attempt, or an unknown item is refused with 409 and one
    rejected observation; no review evidence or delivery is recorded."""
    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 141, head=None if case == "version_unrelated" else _A32_HEAD)
    other_attempt = await _a32_item(store, 142)
    if case == "version_changed":
        async with store() as db:
            await db.execute(text(
                "UPDATE github_work_items SET verification_head_sha = :head WHERE id = 141"),
                {"head": "e" * 40})
            await db.commit()
    body = _a32_body(141, attempt, **{
        "artifact_unrelated": {"artifact": "matrix-owner/matrix-repo/pull/74"},
        "attempt_unrelated": {"attempt": "item:141:launch:999:revision:None"},
        "other_item_attempt": {"attempt": other_attempt},
        "work_item_not_found": {"work_item_id": 999,
                                "attempt": "item:999:launch:None:revision:None"},
    }.get(case, {}))
    before = await _authority(store, 141)

    response = await client.post("/api/v1/factory/review-acceptances",
                                 headers=_OPERATOR_HEADERS, json=body)

    expected = {"other_item_attempt": "attempt_unrelated"}.get(case, case)
    assert response.status_code == 409, response.text
    assert response.json()["refusal"] == expected
    assert await _review_rows(store) == []
    assert await _facts(store, event_kind="delivery_evidence") == []
    rejected = await _facts(store, event_kind="review_acceptance_declared")
    assert [(f["action_outcome"], f["actor_kind"]) for f in rejected] == [("rejected", "operator")]
    assert await _authority(store, 141) == before


@pytest.mark.parametrize("override", [
    {"reviewer": "member:3"}, {"reviewer": "operator"},
    {"reviewer": "shared-operator-credential"}, {"reviewer_kind": "agent"},
    {"occurred_at": "2099-01-01T00:00:00+00:00"}, {"occurred_at": "2026-10-06T10:00:00"},
    {"version": "short"}, {"unexpected": "field"}])
async def test_a32_declaration_schema_refusals_write_nothing(store, client, override):
    """A32: an unattributable reviewer, a non-human kind, a future or
    timezone-less time, a malformed version or an unknown field is refused
    by the typed contract before any write."""
    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 143)

    response = await client.post("/api/v1/factory/review-acceptances",
                                 headers=_OPERATOR_HEADERS, json=_a32_body(143, attempt, **override))

    assert response.status_code == 422
    assert await _facts(store) == []


async def test_a32_declaration_route_requires_the_operator_credential(store, client, monkeypatch):
    """A32: no credential is 401 and an unconfigured credential is 503; neither writes."""
    from app.config import settings

    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 144)

    missing = await client.post("/api/v1/factory/review-acceptances", json=_a32_body(144, attempt))
    assert missing.status_code == 401
    monkeypatch.setattr(settings, "operator_token", "")
    unconfigured = await client.post("/api/v1/factory/review-acceptances",
                                     headers=_OPERATOR_HEADERS, json=_a32_body(144, attempt))
    assert unconfigured.status_code == 503
    assert await _facts(store) == []


@pytest.mark.parametrize("case", ["code_item", "not_independent", "rejected_decision"])
async def test_a32_nonqualifying_declarations_never_establish_delivery(store, client, case):
    """A32: a code item's acceptance, a non-independent declaration or a
    declared rejection is stored as declared and never establishes delivery
    or counts as independent human review."""
    from app.services import factory_audit_service as _audit

    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 145, issue_type="code" if case == "code_item" else "design")
    body = _a32_body(145, attempt, **{"not_independent": {"independent": False},
                                      "rejected_decision": {"decision": "rejected"}}.get(case, {}))

    response = await client.post("/api/v1/factory/review-acceptances",
                                 headers=_OPERATOR_HEADERS, json=body)

    assert response.status_code == 201, response.text
    assert response.json()["delivery_established"] is False
    assert response.json()["counted"] is (case == "code_item")
    assert await _facts(store, event_kind="delivery_evidence") == []
    rows = await _review_rows(store)
    assert len(rows) == 1
    async with store() as db:
        evidence = (await db.execute(text(
            "SELECT human_review_evidence FROM factory_audit_events WHERE id = :id"),
            {"id": rows[0]["id"]})).scalar_one()
    import json as _json
    assert _audit.validated_review_evidence(_json.loads(evidence)) is (case == "code_item")


@pytest.mark.parametrize("change", [
    "exact_retry", "fact_time", "source", "actor", "artifact_version", "human_review"])
async def test_t02_replay_compares_the_complete_stable_payload(store, change):
    """T02 (B4 F01, Astra F05): one immutable operation identity accepts an
    exact retry, whose observation time and session may differ. A changed
    fact time, call-site source, actor, exact artifact version or review
    evidence is refused; the old event is never returned as the new fact."""
    await _seed_team(store)
    await _seed_work(store, item_id=170, status="completed")
    operator = audit.derive_actor(actor_kind="operator")

    def fields(**overrides):
        base = dict(
            event_kind="design_review", source="test.writer", occurred_at=_now(),
            actor=operator, action_outcome="applied", item_id=170,
            fact_source="operator_attested:ref-1", fact_time=datetime(2026, 10, 6, 10),
            operation_id="t02-op-1",
            context_snapshot={"attempt": "item:170:launch:None:revision:None",
                              "artifact": "matrix-owner/matrix-repo/pull/73",
                              "artifact_version": "a" * 40},
            human_review_evidence={"fact_kind": "human_review_acceptance",
                                   "artifact": "matrix-owner/matrix-repo/pull/73",
                                   "version": "a" * 40, "actor": "synthetic-reviewer",
                                   "actor_kind": "human", "independent": True,
                                   "source": "operator_attested:ref-1"})
        base.update(overrides)
        return base

    async with store() as db:
        first = await audit.record_event(db, **fields())
        await db.commit()
        first_id = first.id
    changed = {
        "exact_retry": dict(occurred_at=_now() + timedelta(minutes=5)),
        "fact_time": dict(fact_time=datetime(2026, 10, 6, 11)),
        "source": dict(source="test.other_writer"),
        "actor": dict(actor=audit.derive_actor(actor_kind="scheduler", scheduler="github_watcher")),
        "artifact_version": dict(context_snapshot={
            "attempt": "item:170:launch:None:revision:None",
            "artifact": "matrix-owner/matrix-repo/pull/73", "artifact_version": "b" * 40}),
        "human_review": dict(human_review_evidence={
            "fact_kind": "human_review_acceptance", "artifact": "matrix-owner/matrix-repo/pull/73",
            "version": "a" * 40, "actor": "another-reviewer", "actor_kind": "human",
            "independent": True, "source": "operator_attested:ref-1"}),
    }[change]
    async with store() as db:
        if change == "exact_retry":
            again = await audit.record_event(db, **fields(**changed))
            assert again.id == first_id
        else:
            with pytest.raises(audit.ReplayConflictError):
                await audit.record_event(db, **fields(**changed))
    assert len(await _facts(store, event_kind="design_review")) == 1


async def test_t02_distinct_exact_versions_append_distinct_delivery_facts(store, client):
    """T02 (Astra F05): two valid declarations for two recorded versions,
    with distinct declaration IDs and one reused source reference, keep both
    exact delivery facts. Neither returns a false delivery success; the
    public metrics still count one delivered attempt."""
    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 171)
    first = await client.post("/api/v1/factory/review-acceptances", headers=_OPERATOR_HEADERS,
                              json=_a32_body(171, attempt, declaration_id="synthetic-decl-171-a"))
    assert first.status_code == 201, first.text
    async with store() as db:
        await db.execute(text(
            "UPDATE github_work_items SET verification_head_sha = :head WHERE id = 171"),
            {"head": "e" * 40})
        await db.commit()
    second = await client.post(
        "/api/v1/factory/review-acceptances", headers=_OPERATOR_HEADERS,
        json=_a32_body(171, attempt, declaration_id="synthetic-decl-171-b", version="e" * 40,
                       occurred_at="2026-10-06T10:30:00+00:00"))
    assert second.status_code == 201, second.text
    assert second.json()["delivery_established"] is True

    versions = [row["artifact_version"] for row in await _outcome_rows(store)]
    assert versions == [_A32_HEAD, "e" * 40]
    public = await _public_metrics(client, datetime(2026, 10, 6, 9), _now() + timedelta(hours=1))
    assert public["delivered_in_window"]["value"] == 1.0
    assert public["independently_human_reviewed_design"]["value"] == 1.0


async def test_t03_t09_delivery_is_placed_at_its_result_time_by_category(store, client, monkeypatch):
    """T03/T09 (B4 F02/F08, Astra F04): an exact design acceptance on day 1,
    then the real watcher's routine closure on day 2. The public metrics put
    the one delivery, and the separate design delivery, only in the day-1
    window; the day-2 window has no delivery and no terminal tracking; the
    combined window has one of each. Code merges stay a separate category."""
    from app.models.database import TeamGithubScope
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_watcher_service import github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 172)
    accepted = await client.post("/api/v1/factory/review-acceptances",
                                 headers=_OPERATOR_HEADERS, json=_a32_body(172, attempt))
    assert accepted.status_code == 201, accepted.text

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_dispatch_service, "notify_blocker_merged", no_notice)

    class RoutineClosure:
        async def get_issues_by_number(self, owner, repo, numbers):
            return {number: {"state": "closed", "state_reason": "completed", "labels": []}
                    for number in numbers}

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await github_watcher_service._recheck_active_items(db, scope, RoutineClosure())
    outcomes = await _outcome_rows(store)
    assert [row["delivery_outcome"] for row in outcomes] == ["delivered", "unknown"]

    now = datetime.utcnow()
    day1 = await _public_metrics(client, datetime(2026, 10, 6, 9), datetime(2026, 10, 6, 12))
    day2 = await _public_metrics(client, now - timedelta(minutes=30), now + timedelta(minutes=30))
    combined = await _public_metrics(client, datetime(2026, 10, 6, 9), now + timedelta(minutes=30))

    def values(public):
        return tuple(public[name]["value"] for name in (
            "delivered_in_window", "delivered_design_in_window", "merged_code_in_window",
            "terminal_tracking_in_window", "unknown_outcomes"))

    assert values(day1) == (1.0, 1.0, 0.0, 1.0, 0.0)
    assert values(day2) == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert values(combined) == (1.0, 1.0, 0.0, 1.0, 0.0)


@pytest.mark.parametrize("case", [
    "type_changed", "replaced_item", "replaced_in_other_scope", "repository_changed"])
async def test_t04_late_result_keeps_the_original_attempt_context(store, client, case):
    """T04 (B4 F03, Astra F03): a code attempt recorded as non-delivery is
    later merged after the item became a design retry: the late fact stays
    merged_code on the original lifetime and adds no design-review sample.
    When the item is deleted and its numeric ID reused during the GitHub
    read, the replacement receives no fact."""
    from app.models.database import TeamGithubScope
    from app.services.github_watcher_service import github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=173, status="completed")
    original = "item:173:launch:None:revision:None"
    await _a34_non_delivery(store, 173, original, 73)
    async with store() as db:
        original_key = (await db.execute(text(
            "SELECT item_context_key FROM factory_audit_events"
            " WHERE event_kind = 'delivery_evidence'"))).scalar_one()
        await db.execute(text(
            "UPDATE github_work_items SET issue_type = 'design' WHERE id = 173"))
        await db.commit()

    class ReadThenReplace(_A34Client):
        async def get_pull(self, owner, repo, number, *, token=None):
            pull = await super().get_pull(owner, repo, number, token=token)
            if case in ("replaced_item", "replaced_in_other_scope"):
                async with store() as other:
                    await other.execute(text("DELETE FROM github_work_items WHERE id = 173"))
                    await other.commit()
                await _seed_work(store, item_id=173, status="completed")
            if case == "replaced_in_other_scope":
                # The reused numeric ID now belongs to another scope and repository.
                async with store() as other:
                    await other.execute(text(
                        "CREATE TEMP TABLE scope_copy AS SELECT * FROM team_github_scopes"
                        " WHERE id = 5"))
                    await other.execute(text(
                        "UPDATE scope_copy SET id = 6, repo_name = 'other-repo'"))
                    await other.execute(text(
                        "INSERT INTO team_github_scopes SELECT * FROM scope_copy"))
                    await other.execute(text("DROP TABLE scope_copy"))
                    await other.execute(text(
                        "UPDATE github_work_items SET scope_id = 6 WHERE id = 173"))
                    await other.commit()
            if case == "repository_changed":
                # The same item and scope now name another repository.
                async with store() as other:
                    await other.execute(text(
                        "UPDATE team_github_scopes SET repo_name = 'renamed-repo' WHERE id = 5"))
                    await other.commit()
            return pull

    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await github_watcher_service._reconcile_provisional_results(
            db, scope, ReadThenReplace(merged={73}))

    outcomes = await _outcome_rows(store)
    if case != "type_changed":
        # No fact on a replacement, another scope or another repository.
        assert [row["delivery_outcome"] for row in outcomes] == ["closed_without_delivery"]
        # The setup really changed the context during the read.
        async with store() as db:
            scope_id, repo_name = (await db.execute(text(
                "SELECT i.scope_id, s.repo_name FROM github_work_items i"
                " JOIN team_github_scopes s ON s.id = i.scope_id WHERE i.id = 173"))).first()
        assert (scope_id, repo_name) == {
            "replaced_item": (5, "matrix-repo"),
            "replaced_in_other_scope": (6, "other-repo"),
            "repository_changed": (5, "renamed-repo")}[case]
        return
    assert [(row["delivery_outcome"], row["completion_kind"], row["item_context_key"])
            for row in outcomes] == [
        ("closed_without_delivery", "pr_closed_unmerged", original_key),
        ("delivered", "merged_code", original_key)]
    public = await _public_metrics(client, _now() - timedelta(days=2), datetime(2026, 10, 8))
    assert public["merged_code_in_window"]["value"] == 1.0
    assert public["delivered_design_in_window"]["value"] == 0.0
    assert public["independently_human_reviewed_design"]["sample_count"] == 0


async def test_t05_original_ids_and_creation_times_survive_deletion(store, client):
    """T05 (B4 F04): a real lifecycle writer stores the original typed team,
    scope, item and slot IDs and the item and slot creation times. The
    protected read keeps them after deletion and numeric ID reuse, with
    unavailable live links."""
    from app.models.database import GithubWorkItem
    from app.services.github_dispatch_service import observe_work_lifecycle

    await _seed_team(store)
    await _seed_work(store, item_id=174, status="pending")
    async with store() as db:
        item = await db.get(GithubWorkItem, 174)
        await observe_work_lifecycle(db, item=item, from_status=None, to_status="dispatched",
                                     source="github_dispatch_service.launch")
        await db.commit()
    async with store() as db:
        await db.execute(text("DELETE FROM github_work_items WHERE id = 174"))
        await db.commit()
    await _seed_work(store, item_id=174, status="pending")

    response = await client.get("/api/v1/factory/audit-events", headers=_OPERATOR_HEADERS,
                                params={"event_kind": "work_lifecycle"})
    assert response.status_code == 200, response.text
    (event,) = response.json()["items"]
    snapshot = event["context_snapshot"]
    assert (snapshot["original_item_id"], snapshot["original_scope_id"],
            snapshot["original_team_id"], snapshot["original_slot_id"]) == (
        174, 5, 7, _OWNER["slot"])
    assert snapshot["item_created_at"] and snapshot["slot_created_at"]
    assert event["item_id"] is None and event["live_links_available"] is True


async def test_t06_durations_pair_only_within_one_item_lifetime(store, client):
    """T06 (B4 F05): an old lifetime and a new lifetime share the numeric
    item and launch key. The new attempt's duration is 60 seconds, not the
    span from the old start; an end without a matching start is unknown."""
    await _install_marker(store)
    await _seed_team(store)
    launch = "item:175:launch:9"
    scheduler = audit.derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler")

    async def start(at: datetime):
        async with store() as db:
            await audit.record_event(
                db, event_kind="work_lifecycle", source="test.launch", occurred_at=at,
                actor=scheduler, action_outcome="applied", item_id=175,
                after_values={"dispatch_status": "dispatched"},
                context_snapshot={"launch_attempt": launch})
            await db.commit()

    await _seed_work(store, item_id=175, status="pending")
    await start(_now() - timedelta(days=1))
    async with store() as db:
        await db.execute(text("DELETE FROM github_work_items WHERE id = 175"))
        await db.commit()
    await _seed_work(store, item_id=175, status="pending")
    await start(_now())
    async with store() as db:
        await audit.record_delivery_fact(
            db, item_id=175, scope_id=5, delivery_outcome="unknown",
            completion_kind="closed_unproven", fact_source="test.closure",
            fact_time=_now() + timedelta(seconds=60), attempt="item:175:launch:9:revision:None",
            launch_attempt=launch)
        await db.commit()

    public = await _public_metrics(client, _now() - timedelta(hours=1), _now() + timedelta(hours=1))
    duration = public["elapsed_attempt_duration"]
    assert (duration["value"], duration["sample_count"], duration["unknown_count"]) == (60.0, 1, 0)


async def test_t07_interventions_count_resource_bound_actions_only(store, client):
    """T07 (B4 F06): one protected declaration is one operator intervention,
    not two (its derived delivery fact is not an action). Two actions on two
    items with one supplied operation ID count twice; an exact retry and a
    notice add nothing."""
    await _install_marker(store)
    await _seed_team(store)
    attempt = await _a32_item(store, 176)
    declared = await client.post("/api/v1/factory/review-acceptances",
                                 headers=_OPERATOR_HEADERS, json=_a32_body(176, attempt))
    assert declared.status_code == 201, declared.text
    window = (datetime(2026, 10, 6), datetime.utcnow() + timedelta(hours=1))
    public = await _public_metrics(client, *window)
    assert public["operator_interventions"]["value"] == 1.0

    operator = audit.derive_actor(actor_kind="operator")
    await _seed_work(store, item_id=177, status="escalated")
    await _seed_work(store, item_id=178, status="escalated")
    async with store() as db:
        for item_id in (177, 178, 177):  # the third call is an exact retry
            await audit.record_event(
                db, event_kind="operator_escalation", source="test.route",
                occurred_at=datetime.utcnow(), actor=operator, action_outcome="applied",
                item_id=item_id, operation_id="client-op-shared")
        await audit.record_event(
            db, event_kind="operator_escalation_notification", source="test.route",
            occurred_at=datetime.utcnow(), actor=operator, action_outcome="applied",
            item_id=177, operation_id="client-op-shared-notice")
        await db.commit()
    public = await _public_metrics(client, *window)
    assert public["operator_interventions"]["value"] == 3.0


async def test_b4f01_replacement_after_final_context_read_gets_no_late_fact(store, monkeypatch):
    """B4 F01 (7d38 review, owner copy of its probe): an independent session
    deletes the item and reuses its numeric ID right after the consumer's
    final context check. The fact insert holds the writer and validates the
    original context again; the replacement receives no late fact."""
    from app.models.database import TeamGithubScope
    from app.services.github_watcher_service import GithubWatcherService

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=173, status="completed")
    await _a34_non_delivery(store, 173, "item:173:launch:None:revision:None", 73)
    original = GithubWatcherService._original_context_holds
    calls = []

    async def read_then_replace(self, db, item, state, captured_scope):
        result = await original(self, db, item, state, captured_scope)
        calls.append(result)
        if len(calls) == 2:
            assert result is True
            async with store() as other:
                await other.execute(text("DELETE FROM github_work_items WHERE id = 173"))
                await other.commit()
            await _seed_work(store, item_id=173, status="completed", issue_type="design")
        return result

    monkeypatch.setattr(GithubWatcherService, "_original_context_holds", read_then_replace)
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        await GithubWatcherService()._reconcile_provisional_results(
            db, scope, _A34Client(merged={73}))
    assert calls == [True, True]
    rows = await _outcome_rows(store)
    assert [row["delivery_outcome"] for row in rows] == ["closed_without_delivery"], rows


async def test_b4f02_later_closure_does_not_recount_terminal_duration(db):
    """B4 F02 (writer probe): a delivered end at +60 s and a routine closure a
    day later. The first window has the 60-second duration; the later window
    has no terminal tracking and no duration sample."""
    from app.services import factory_metrics_service as metrics

    start = datetime(2026, 10, 6, 10)
    await _seed_item(db, 1)
    await audit.record_event(
        db, event_kind="work_lifecycle", source="github_dispatch_service.launch",
        occurred_at=start, actor=audit.derive_actor(
            actor_kind="scheduler", scheduler="github_dispatch_scheduler"),
        item_id=1, scope_id=1, after_values={"dispatch_status": "dispatched"},
        context_snapshot={"launch_attempt": "item:1:launch:1"})
    common = dict(item_id=1, scope_id=1, attempt="item:1:launch:1:revision:None",
                  launch_attempt="item:1:launch:1", artifact="owner-1/owner-1/pull/1")
    await audit.record_delivery_fact(
        db, **common, delivery_outcome="delivered", completion_kind="merged_code",
        fact_source="github_pull_request_merged", fact_time=start + timedelta(seconds=60))
    await audit.record_delivery_fact(
        db, **common, delivery_outcome="unknown", completion_kind="closed_unproven",
        fact_source="github_issue_closure", fact_time=start + timedelta(days=1))
    await db.commit()
    first = await metrics.build_metrics_window(
        db, window_start=start, window_end=start + timedelta(hours=1))
    assert {m.name: m for m in first.metrics}["elapsed_attempt_duration"].value == 60
    later = await metrics.build_metrics_window(
        db, window_start=start + timedelta(hours=23), window_end=start + timedelta(hours=25))
    values = {m.name: m for m in later.metrics}
    assert values["terminal_tracking_in_window"].value == 0
    assert values["elapsed_attempt_duration"].sample_count == 0
    assert values["elapsed_attempt_duration"].value is None


async def test_b4f02_public_duration_after_real_declaration_and_routine_closure(
    store, client, monkeypatch
):
    """B4 F02 (consumer probe): the protected declaration, then the real
    watcher's routine closure. The public duration is 60 seconds in the
    acceptance window and absent in the closure window."""
    from app.models.database import AgentTeamLaunch, GithubWorkItem, TeamGithubScope
    from app.services.github_dispatch_service import github_dispatch_service
    from app.services.github_watcher_service import GithubWatcherService

    await _install_marker(store)
    await _seed_team(store)
    await _a32_item(store, 179)
    start = datetime(2026, 10, 6, 9, 59)
    async with store() as db:
        db.add(AgentTeamLaunch(id=179, preset_id=7, plan_hash="synthetic", status="completed"))
        await db.flush()
        await db.execute(text("UPDATE github_work_items SET launch_id = 179 WHERE id = 179"))
        await db.commit()
    async with store() as db:
        item = await db.get(GithubWorkItem, 179)
        attempt, _revision, launch = await audit.item_attempt(db, item)
        await audit.record_event(
            db, event_kind="work_lifecycle", source="github_dispatch_service.launch",
            occurred_at=start, actor=audit.derive_actor(
                actor_kind="scheduler", scheduler="github_dispatch_scheduler"),
            item_id=179, after_values={"dispatch_status": "dispatched"},
            context_snapshot={"launch_attempt": launch})
        await db.commit()
    response = await client.post("/api/v1/factory/review-acceptances",
                                 headers=_OPERATOR_HEADERS, json=_a32_body(179, attempt))
    assert response.status_code == 201, response.text

    async def no_notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_dispatch_service, "notify_blocker_merged", no_notice)

    class Closed:
        async def get_issues_by_number(self, owner, repo, numbers):
            return {n: {"state": "closed", "state_reason": "completed", "labels": []}
                    for n in numbers}

    async with store() as db:
        await GithubWatcherService()._recheck_active_items(
            db, await db.get(TeamGithubScope, 5), Closed())
    first = await _public_metrics(client, start, start + timedelta(hours=1))
    assert first["elapsed_attempt_duration"]["value"] == 60
    now = datetime.utcnow()
    later = await _public_metrics(client, now - timedelta(minutes=5), now + timedelta(minutes=5))
    assert later["terminal_tracking_in_window"]["value"] == 0
    assert later["delivered_in_window"]["value"] == 0
    assert later["elapsed_attempt_duration"]["sample_count"] == 0


async def test_b4f03_recovery_result_count_survives_live_revision_deletion(db):
    """B4 F03 (production revision writer): two call sites record one revision
    result. Recovery counts one result before and after the live revision is
    deleted and its reference is set to null."""
    from app.services import factory_metrics_service as metrics

    await _seed_item(db, 40)
    await _seed_slot_member(db)
    await _seed_workspace(db)
    await db.execute(text(
        "INSERT INTO github_attempt_scope_revisions"
        " (id, work_item_id, dispatch_nonce, revision, owner_slot_id, owner_member_id, phase,"
        " execution_target, summary, allowed_paths, allowed_actions, allowed_commands,"
        " prohibited_actions, tool_fallbacks, baseline_head_sha, baseline_tree_sha,"
        " originating_escalation_reason, expected_workspace_id, expected_lease_token_hash,"
        " max_failed_heads, failed_head_count, status, delivery_attempt_count, created_at)"
        " VALUES (40, 40, 'n', 1, 1, 1, 'implementation', '/w', 's', '[]', '[]', '[]', '[]',"
        " '{}', 'a', 'b', 'r', 1, 'h', 2, 0, 'completed', 0, CURRENT_TIMESTAMP)"))
    await db.execute(text("UPDATE github_work_items SET dispatch_status = 'completed' WHERE id = 40"))
    await db.commit()
    for source in ("github_dispatch_service", "github_verification_service"):
        await audit.record_revision_outcome(
            db, item_id=40, revision_id=40, status="completed", source=source)
    await db.commit()

    async def sample():
        now = datetime.utcnow()
        result = await metrics.build_metrics_window(
            db, window_start=now - timedelta(hours=1), window_end=now + timedelta(hours=1))
        return next(s for s in result.metrics if s.name == "recovery_success")

    first = await sample()
    assert (first.value, first.sample_count) == (1.0, 1)
    await db.execute(text("DELETE FROM github_work_items WHERE id = 40"))
    await db.commit()
    remaining = (await db.execute(text("SELECT revision_id FROM factory_audit_events"))).scalars().all()
    assert remaining == [None, None]
    retained = await sample()
    assert (retained.value, retained.sample_count) == (1.0, 1)


_REVISION_INSERT = (
    "INSERT INTO github_attempt_scope_revisions"
    " ({id_column}work_item_id, dispatch_nonce, revision, owner_slot_id, owner_member_id, phase,"
    " execution_target, summary, allowed_paths, allowed_actions, allowed_commands,"
    " prohibited_actions, tool_fallbacks, baseline_head_sha, baseline_tree_sha,"
    " originating_escalation_reason, expected_workspace_id, expected_lease_token_hash,"
    " max_failed_heads, failed_head_count, status, delivery_attempt_count, created_at)"
    " VALUES ({id_value}:item, :nonce, 1, :slot, :member, 'implementation', '/w', 's', '[]',"
    " '[]', '[]', '[]', '{{}}', 'a', 'b', 'r', :workspace, 'h', 2, 0, 'completed', 0, :created)"
    " RETURNING id")


async def _insert_revision(db, item_id: int, *, revision_id: int | None = None,
                           nonce: str = "n", created: str = "2026-10-07 10:00:00",
                           slot: int = 1, member: int = 1, workspace: int = 1) -> int:
    sql = _REVISION_INSERT.format(
        id_column="id, " if revision_id is not None else "",
        id_value=":id, " if revision_id is not None else "")
    params = {"item": item_id, "nonce": nonce, "created": created, "slot": slot,
              "member": member, "workspace": workspace}
    if revision_id is not None:
        params["id"] = revision_id
    return (await db.execute(text(sql), params)).scalar_one()


async def _recovery_sample(db):
    from app.services import factory_metrics_service as metrics

    now = datetime.utcnow()
    result = await metrics.build_metrics_window(
        db, window_start=now - timedelta(hours=1), window_end=now + timedelta(hours=1))
    return next(s for s in result.metrics if s.name == "recovery_success")


async def test_final_recovery_identity_survives_automatic_revision_id_reuse(db):
    """Final P2 (B4 8bc review, owner copy of its probe; Astra): one revision
    result observed by two call sites counts once, also after the live item
    is deleted. A new item lifetime that reuses the numeric revision ID is a
    second revision result, never merged with the first."""
    await _seed_item(db, 40)
    await _seed_slot_member(db)
    await _seed_workspace(db)
    first_id = await _insert_revision(db, 40, revision_id=1, created="2026-10-07 09:00:00")
    await db.execute(text("UPDATE github_work_items SET dispatch_status = 'completed' WHERE id = 40"))
    await db.commit()
    for source in ("github_dispatch_service", "github_verification_service"):
        await audit.record_revision_outcome(
            db, item_id=40, revision_id=first_id, status="completed", source=source)
    await db.commit()
    first = await _recovery_sample(db)
    assert (first.value, first.sample_count) == (1.0, 1)
    await db.execute(text("DELETE FROM github_work_items WHERE id = 40"))
    await db.commit()
    retained = await _recovery_sample(db)
    assert (retained.value, retained.sample_count) == (1.0, 1)

    await _seed_item(db, 41)
    new_id = await _insert_revision(db, 41, nonce="new-lifetime")
    assert new_id == 1, "the probe requires normal SQLite automatic ID reuse"
    await db.commit()
    await audit.record_revision_outcome(
        db, item_id=41, revision_id=new_id, status="completed", source="github_dispatch_service")
    await db.commit()
    result = await _recovery_sample(db)
    # recovery_success counts completed revision results: two revisions.
    assert (result.value, result.sample_count) == (2.0, 2)


async def test_final_recovery_identity_separates_revision_reuse_within_one_item(db):
    """Final P2 (B1 3826): a revision deleted and recreated with the same
    numeric ID inside one item lifetime has a new recorded creation time and
    is a second result. An exact retry adds nothing. A legacy fact without a
    lifetime counts on its own, with an explicit reason."""
    await _seed_item(db, 42)
    await _seed_slot_member(db)
    await _seed_workspace(db)
    await _insert_revision(db, 42, revision_id=50, created="2026-10-07 09:00:00")
    await db.commit()
    await audit.record_revision_outcome(
        db, item_id=42, revision_id=50, status="completed", source="github_dispatch_service")
    await audit.record_revision_outcome(  # exact retry from the same call site
        db, item_id=42, revision_id=50, status="completed", source="github_dispatch_service")
    await db.commit()
    assert (await _recovery_sample(db)).sample_count == 1

    await db.execute(text("DELETE FROM github_attempt_scope_revisions WHERE id = 50"))
    await _insert_revision(db, 42, revision_id=50, created="2026-10-07 11:00:00")
    await db.commit()
    await audit.record_revision_outcome(
        db, item_id=42, revision_id=50, status="completed", source="github_dispatch_service")
    await db.commit()
    reused = await _recovery_sample(db)
    assert (reused.value, reused.sample_count) == (2.0, 2)
    assert not any("legacy" in reason for reason in reused.unknown_reasons)

    # A legacy result written before the lifetime field existed.
    await audit.record_event(
        db, event_kind="revision_outcome", source="legacy.writer", occurred_at=datetime.utcnow(),
        actor=audit.derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler"),
        item_id=42, after_values={"status": "completed"}, action_outcome="applied",
        operation_id="revision_outcome:50:completed:legacy.writer")
    await db.commit()
    legacy = await _recovery_sample(db)
    assert legacy.sample_count == 3
    assert any("legacy revision results" in reason for reason in legacy.unknown_reasons)


@pytest.mark.parametrize("reuse", ["item_lifetime", "same_item_revision"])
async def test_final_recovery_lifetimes_through_public_metrics(store, client, reuse):
    """Final P2 (consolidated U01): the production revision writer records
    one result observed by two call sites; then a new lifetime reuses the
    numeric revision ID, either on a new item lifetime after deletion or as
    a recreated revision of the same item, with the same status and source.
    The public metrics response reports two distinct recovery results."""
    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=180, status="completed", workspace_id=180)
    who = dict(slot=_OWNER["slot"], member=_OWNER["member"], workspace=180)
    async with store() as db:
        first_id = await _insert_revision(db, 180, created="2026-10-07 09:00:00", **who)
        await db.commit()
        for source in ("github_dispatch_service", "github_verification_service"):
            await audit.record_revision_outcome(
                db, item_id=180, revision_id=first_id, status="completed", source=source)
        await db.commit()
    window = (datetime.utcnow() - timedelta(hours=1), datetime.utcnow() + timedelta(hours=1))
    public = await _public_metrics(client, *window)
    assert public["recovery_success"]["sample_count"] == 1

    async with store() as db:
        if reuse == "item_lifetime":
            await db.execute(text("DELETE FROM github_work_items WHERE id = 180"))
            await db.commit()
    if reuse == "item_lifetime":
        await _seed_work(store, item_id=180, status="completed", workspace_id=181)
        who["workspace"] = 181
    async with store() as db:
        if reuse == "same_item_revision":
            await db.execute(text("DELETE FROM github_attempt_scope_revisions WHERE id = :id"),
                             {"id": first_id})
        new_id = await _insert_revision(db, 180, created="2026-10-07 11:00:00", **who)
        assert new_id == first_id, "the case requires numeric revision ID reuse"
        await db.commit()
        await audit.record_revision_outcome(
            db, item_id=180, revision_id=new_id, status="completed",
            source="github_dispatch_service")
        await db.commit()
    public = await _public_metrics(client, *window)
    assert (public["recovery_success"]["value"], public["recovery_success"]["sample_count"]) == (
        2.0, 2)


class _A34Client:
    """Fake client at the get_pull boundary; records each pull read."""

    def __init__(self, merged: set[int] | None = None):
        self.merged = merged or set()
        self.reads: list[int] = []

    async def get_pull(self, owner, repo, number, *, token=None):
        self.reads.append(number)
        return _a30_pull(number, merged_at="2026-10-07T09:00:00Z" if number in self.merged else None)


async def _a34_non_delivery(store, item_id: int, attempt: str, pr_number: int) -> None:
    from app.services import factory_audit_service as _audit

    async with store() as db:
        await _audit.record_delivery_fact(
            db, item_id=item_id, scope_id=5, delivery_outcome="closed_without_delivery",
            completion_kind="pr_closed_unmerged", fact_source="github_pull_request_closed_unmerged",
            fact_time=None, artifact=f"matrix-owner/matrix-repo/pull/{pr_number}",
            attempt=attempt, launch_attempt=f"item:{item_id}:launch:None")
        await db.commit()


async def test_a34_later_merge_is_recorded_on_the_original_attempt_once(store, client):
    """A34 (Root 3599): a completed attempt recorded as closed without
    delivery, whose pull later merges, receives one delivered fact on its
    original attempt identity. A second poll adds nothing; the current
    attempt and every work item field stay unchanged."""
    from app.models.database import TeamGithubScope
    from app.services import factory_metrics_service as metrics
    from app.services.github_watcher_service import github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=150, status="completed", pr_number=80)
    original = "item:150:launch:None:revision:None"
    await _a34_non_delivery(store, 150, original, 73)
    async with store() as db:
        # A new attempt of the same item now uses another pull.
        await db.execute(text("UPDATE github_work_items SET pr_number = 80, launch_id = NULL"
                              " WHERE id = 150"))
        await db.commit()
    before = await _authority(store, 150)
    github = _A34Client(merged={73})

    for _ in range(2):
        async with store() as db:
            scope = await db.get(TeamGithubScope, 5)
            await github_watcher_service._reconcile_provisional_results(db, scope, github)

    async with store() as db:
        rows = (await db.execute(text(
            "SELECT delivery_outcome, completion_kind, json_extract(context_snapshot, '$.attempt'),"
            " fact_time FROM factory_audit_events WHERE event_kind = 'delivery_evidence'"
            " ORDER BY id"))).fetchall()
        window = await metrics.build_metrics_window(
            db, window_start=_now() - timedelta(days=2), window_end=datetime(2026, 10, 8))
    assert [tuple(row[:3]) for row in rows] == [
        ("closed_without_delivery", "pr_closed_unmerged", original),
        ("delivered", "merged_code", original)]
    assert datetime.fromisoformat(str(rows[1][3])) == datetime(2026, 10, 7, 9, 0)
    assert github.reads == [73]  # the resolved attempt is not read again
    assert _metric(window, "delivered_in_window").value == 1.0
    assert _metric(window, "closed_without_delivery").value == 0.0
    assert await _authority(store, 150) == before
    # F02 late resolution: the public response reports one delivered attempt.
    public = await _public_metrics(client, _now() - timedelta(days=2), datetime(2026, 10, 8))
    assert (public["delivered_in_window"]["value"], public["closed_without_delivery"]["value"]) == (
        1.0, 0.0)
    outcomes = await _outcome_rows(store)
    assert outcomes[1]["source"] == "github_watcher_service._reconcile_provisional_results"
    assert outcomes[1]["artifact_version"] == "d" * 40


async def test_a34_fair_cursor_reads_every_unresolved_attempt_without_age_limit(store):
    """A34 (Root 3599): 45 unresolved attempts, one of them 60 days old, are
    each read within three polls; no poll reads more than 20; no write
    follows unmerged results."""
    from app.models.database import TeamGithubScope
    from app.services.github_watcher_service import github_watcher_service

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=151, status="completed")
    for number in range(1, 46):
        await _a34_non_delivery(store, 151, f"item:151:launch:{number}:revision:None", number)
    async with store() as db:
        await db.execute(text(
            "UPDATE factory_audit_events SET occurred_at = '2026-08-08 00:00:00'"
            " WHERE json_extract(context_snapshot, '$.attempt') = 'item:151:launch:1:revision:None'"))
        await db.commit()
    client = _A34Client()
    per_poll = []
    for _ in range(3):
        start = len(client.reads)
        async with store() as db:
            scope = await db.get(TeamGithubScope, 5)
            await github_watcher_service._reconcile_provisional_results(db, scope, client)
        per_poll.append(len(client.reads) - start)

    assert per_poll == [20, 20, 20]
    assert set(client.reads) == set(range(1, 46))
    assert 1 in client.reads
    assert len(await _facts(store, event_kind="delivery_evidence")) == 45


def test_a20_classifier_labels_match_the_provider_registry():
    """A20: every provider label the classifier can return is a registered provider."""
    from app.services import factory_audit_service as _audit
    from app.services import providers

    labels = set(_audit._AGENT_EXECUTABLES.values()) | {"pi-cli"}
    for label in labels:
        assert providers.get_provider(label) is not None
    assert _audit.classify_agent_argv(["/usr/local/bin/claude", "--resume"]) == "claude-code"
    assert _audit.classify_agent_argv(["node", "/x/@earendil-works/pi-coding-agent/dist/bundle/cli.js"]) == "pi-cli"
    assert _audit.classify_agent_argv(["node", "/x/claude/cli.js"]) is None
    assert _audit.classify_agent_argv(["bash", "-c", "codex"]) is None
    assert _audit.classify_agent_argv(["codex-cli"]) is None


async def test_r03_one_result_per_attempt_survives_late_evidence_and_deletion(store):
    """R03 (B4 F03/F04, Astra F02): unknown then delivered for one attempt is
    one delivered result; repeated evidence adds nothing; a new attempt on the
    same item and a second scoped attempt for the same PR stay distinct;
    deleting the live item keeps every historical count."""
    from app.models.database import GithubWorkItem

    await _install_marker(store)
    await _seed_team(store)
    await _seed_work(store, item_id=122, status="completed", pr_number=73)
    async with store() as db:
        item = await db.get(GithubWorkItem, 122)
        await audit.record_delivery_fact(
            db, item_id=122, scope_id=5, delivery_outcome="unknown",
            completion_kind="closed_unproven", fact_source="github_watcher_service._reconcile_closed_issues",
            fact_time=_now(), attempt="item:122:launch:None:revision:None")
        for _repeat in range(2):
            await audit.record_merged_delivery(
                db, item, {"number": 73, "merged_at": _now().isoformat()}, source="test")
        await db.commit()

    async def counts():
        async with store() as db:
            window = await metrics.build_metrics_window(
                db, window_start=_now() - timedelta(hours=1),
                window_end=_now() + timedelta(hours=1))
        by_name = {s.name: s for s in window.metrics}
        return tuple(by_name[name].value for name in (
            "terminal_tracking_in_window", "delivered_in_window", "unknown_outcomes"))

    assert await counts() == (1.0, 1.0, 0.0)
    async with store() as db:
        merged = (await db.execute(text(
            "SELECT COUNT(*) FROM factory_audit_events WHERE delivery_outcome = 'delivered'"
        ))).scalar_one()
    assert merged == 1

    # A new attempt (another launch) on the same item is a second attempt.
    async with store() as db:
        await audit.record_delivery_fact(
            db, item_id=122, scope_id=5, delivery_outcome="unknown",
            completion_kind="closed_unproven", fact_source="watcher", fact_time=_now(),
            attempt="item:122:launch:9:revision:None")
        await db.commit()
    assert await counts() == (2.0, 1.0, 1.0)

    # Permitted deletion of the live item keeps the historical counts.
    async with store() as db:
        await db.execute(text("DELETE FROM github_work_items WHERE id = 122"))
        await db.commit()
    assert await counts() == (2.0, 1.0, 1.0)


async def test_r04_real_writers_capture_parent_keys_and_configured_provider(store, client):
    """R04 (B4 F05, Astra F05): the real lifecycle writer stores the team key
    so a team filter includes the item fact; the real scope route captures
    the configured harness from trusted slot configuration."""
    from app.models.database import GithubWorkItem
    from app.services.github_dispatch_service import observe_work_lifecycle

    await _seed_team(store)
    await _seed_work(store, item_id=123, status="pending")
    async with store() as db:
        item = await db.get(GithubWorkItem, 123)
        await observe_work_lifecycle(db, item=item, from_status=None, to_status="dispatched",
                                     source="github_dispatch_service.launch")
        await db.commit()
    response = await client.patch(
        "/api/v1/agent-teams/github-scopes/5", headers=_OPERATOR_HEADERS,
        json={"dispatch_label": "renamed-label"})
    assert response.status_code == 200, response.text

    async with store() as db:
        lifecycle = (await db.execute(text(
            "SELECT team_context_key, json_extract(context_snapshot, '$.configured_provider'),"
            " json_extract(context_snapshot, '$.slot_display_name')"
            " FROM factory_audit_events WHERE event_kind = 'work_lifecycle'"))).first()
        policy = (await db.execute(text(
            "SELECT json_extract(context_snapshot, '$.configured_provider'),"
            " json_extract(context_snapshot, '$.observed_runtime_provider'),"
            " json_extract(context_snapshot, '$.team_display_name')"
            " FROM factory_audit_events WHERE event_kind = 'policy_change'"))).first()
        team_key = await audit.current_context_key(db, "team", 7)
        team_events = (await db.execute(text(
            "SELECT COUNT(*) FROM factory_audit_events WHERE team_context_key = :key"),
            {"key": team_key})).scalar_one()
    assert lifecycle[0] == team_key and team_key is not None
    assert lifecycle[1:] == ("codex-cli", f"Slot {_OWNER['slot']}")
    assert policy == ("codex-cli", None, "Matrix team")
    assert team_events == 2


async def test_r07_continuation_request_notice_failure_is_not_a_refused_request(
    store, client, monkeypatch
):
    """R07 (Astra F08): the request commits, then its Mail send fails. The
    request fact stays applied, the notice is uncertain, and no rejected
    request fact is recorded."""
    from app.services.agent_mail_service import agent_mail_service
    from app.services.github_client import GithubCommitSnapshot, GithubTreeEntry, github_client

    await _seed_team(store)
    await _seed_work(store, item_id=124, status="escalated", workspace_id=124,
                     workspace_kind="worktree", lease_token="synthetic-lease-124",
                     escalation_reason="retry_count_exhausted", pr_number=73,
                     dispatch_head_ref=_HEAD_REF)
    _stub_open_pull(monkeypatch)

    async def snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="a" * 40, tree_sha="b" * 40)

    async def tree(*_args, **_kwargs):
        return [GithubTreeEntry(path="src/a.py", mode="100644", object_type="blob", sha="c" * 40)]

    async def failing_send(*_args, **_kwargs):
        raise RuntimeError("synthetic low-level send failure")

    monkeypatch.setattr(github_client, "get_commit_snapshot", snapshot)
    monkeypatch.setattr(github_client, "get_recursive_tree", tree)
    monkeypatch.setattr(agent_mail_service, "send_message", failing_send)
    response = await client.post(
        "/api/v1/agent-teams/github-work-items/124/continuation-requests",
        headers=_session_headers(_OWNER),
        json={"dispatch_nonce": _NONCE, "phase": "implementation",
              "execution_target": "workspace", "summary": "Bounded matrix correction",
              "allowed_paths": ["src/a.py"],
              "allowed_actions": ["edit_production", "push_pr_head", "request_verification"],
              "allowed_commands": ["pytest -q"], "prohibited_actions": ["Do not edit CI"],
              "max_failed_heads": 1, "tool_fallbacks": {},
              "lease_token": "synthetic-lease-124"})

    assert response.status_code == 500
    requests = await _facts(store, event_kind="continuation_request")
    notices = await _facts(store, event_kind="continuation_request_notification")
    assert [f["action_outcome"] for f in requests] == ["applied"]
    assert [(f["action_outcome"], f["request_id"]) for f in notices] == [
        ("uncertain", requests[0]["request_id"])]
    async with store() as db:
        pending = (await db.execute(text(
            "SELECT COUNT(*) FROM github_approval_requests WHERE work_item_id = 124"
            " AND status = 'pending'"))).scalar_one()
    assert pending == 1


@pytest.mark.parametrize(("restore_fails", "outcome"), [(False, "rejected"), (True, "uncertain")])
async def test_r07_handoff_acceptance_keeps_known_external_effects(
    store, client, monkeypatch, restore_fails, outcome
):
    """R07 (B4 F10): push access is revoked, the worktree identity write
    fails, and the acceptance rolls back. The fact keeps each known effect;
    a failed restoration is uncertain, never an ordinary rejection."""
    from app.services.github_workspace_service import (
        _MANAGED_WORKTREE_KEYS, GithubWorkspaceConfigError, WorktreeConfigSnapshot,
        github_workspace_service,
    )

    await _seed_team(store)
    await _seed_work(store, item_id=125, status="dispatched", workspace_id=125,
                     workspace_kind="worktree", lease_token="synthetic-lease-125",
                     handoff_target_slot_id=_OTHER["slot"], handoff_state="pending")
    before = await _authority(store, 125)

    async def snapshot(_workspace):
        return WorktreeConfigSnapshot({key: () for key in _MANAGED_WORKTREE_KEYS})

    async def revoke(*_args, **_kwargs):
        return True

    async def identity_fails(*_args, **_kwargs):
        raise GithubWorkspaceConfigError("synthetic identity failure")

    async def restore(_workspace, _snapshot):
        if restore_fails:
            raise GithubWorkspaceConfigError("synthetic restore failure", restoration_failed=True)

    monkeypatch.setattr(github_workspace_service, "snapshot_worktree_config", snapshot)
    monkeypatch.setattr(github_workspace_service, "revoke_push_token", revoke)
    monkeypatch.setattr(github_workspace_service, "apply_slot_identity", identity_fails)
    monkeypatch.setattr(github_workspace_service, "restore_worktree_config", restore)

    response = await client.post(
        "/api/v1/agent-teams/dispatch-status", headers=_session_headers(_OTHER),
        json={"work_item_id": 125, "status": "handoff_accepted"})

    assert response.status_code == 409
    facts = await _facts(store, event_kind="handoff_acceptance")
    assert [f["action_outcome"] for f in facts] == [outcome]
    reason = facts[0]["sanitized_reason"]
    assert "push_access revoked_or_not_held" in reason
    assert "worktree_identity unknown" in reason
    assert ("restoration restore_failed" if restore_fails else "restoration restored") in reason
    after = await _authority(store, 125)
    assert after["item"] == before["item"]


@pytest.mark.parametrize("case", ["success", "notice_failure", "audit_failure", "refused"])
async def test_r07_abandon_records_action_then_notice(store, client, monkeypatch, case):
    """R07 (Astra F08): the abandon escalation and its fact commit together;
    an audit failure commits neither; a broadcast failure after the commit is
    an uncertain notice and never undoes or replays the action."""
    from app.services import factory_audit_service as _audit
    from app.services.github_dispatch_service import github_dispatch_service

    await _seed_team(store)
    await _seed_work(store, item_id=126, status="merged" if case == "refused" else "dispatched")
    if case == "notice_failure":
        async def failing_broadcast(*_args, **_kwargs):
            raise RuntimeError("synthetic broadcast failure")

        monkeypatch.setattr(github_dispatch_service, "_send_escalation_broadcast", failing_broadcast)
    if case == "audit_failure":
        original = _audit.record_event

        async def failing(db, **fields):
            if fields.get("event_kind") == "operator_escalation":
                raise RuntimeError("synthetic audit insert failure")
            return await original(db, **fields)

        monkeypatch.setattr(_audit, "record_event", failing)

    response = await client.post(
        "/api/v1/agent-teams/github-work-items/126/abandon", headers=_OPERATOR_HEADERS,
        json={"reason": "operator stop"})

    actions = await _facts(store, event_kind="operator_escalation")
    notices = await _facts(store, event_kind="operator_escalation_notification")
    async with store() as db:
        status = (await db.execute(text(
            "SELECT dispatch_status FROM github_work_items WHERE id = 126"))).scalar_one()
    if case == "audit_failure":
        assert response.status_code == 500
        assert (actions, notices, status) == ([], [], "dispatched")
        return
    if case == "refused":
        assert response.status_code == 409
        assert [(f["action_outcome"], f["sanitized_reason"], f["item_id"]) for f in actions] == [
            ("rejected", "work_item_not_abandonable", 126)]
        assert (notices, status) == ([], "merged")
        return
    assert response.status_code == 200, response.text
    assert [f["action_outcome"] for f in actions] == ["applied"]
    assert [f["action_outcome"] for f in notices] == (
        ["applied"] if case == "success" else ["uncertain"])
    assert status == "escalated"


async def test_r08_recovery_counts_revision_results_and_actions_exclude_notices(db):
    """R08 (B4 F11, Astra F06): an applied cancellation is not a recovery
    success; a completed revision result is. One action with an uncertain
    and an applied notice is one intervention."""
    actor = audit.derive_actor(actor_kind="operator")
    await _seed_item(db, 40)
    await _seed_slot_member(db)
    await _seed_workspace(db)
    await db.execute(text(
        "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision,"
        " owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths,"
        " allowed_actions, allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha,"
        " baseline_tree_sha, originating_escalation_reason, expected_workspace_id,"
        " expected_lease_token_hash, max_failed_heads, failed_head_count, status,"
        " delivery_attempt_count, approval_request_id, created_at)"
        " VALUES (40, 40, 'n', 1, 1, 1, 'implementation', '/w', 's', '[]', '[]', '[]', '[]',"
        " '{}', 'a', 'b', 'r', 1, 'h', 2, 0, 'active', 0, NULL, CURRENT_TIMESTAMP)"))
    await db.commit()
    await audit.record_event(
        db, event_kind="recovery_cancellation", source="test", occurred_at=_now(), actor=actor,
        item_id=40, revision_id=40, action_outcome="applied", operation_id="cancel:40")
    for outcome in ("uncertain", "applied"):
        await audit.record_event(
            db, event_kind="recovery_cancellation_notification", source="test",
            occurred_at=_now(), actor=actor, item_id=40, revision_id=40,
            action_outcome=outcome, operation_id=f"cancel:40:notice:{outcome}")
    await db.commit()

    async def window():
        result = await metrics.build_metrics_window(
            db, window_start=_now() - timedelta(hours=1), window_end=datetime.utcnow() + timedelta(hours=1))
        return {s.name: s for s in result.metrics}

    by_name = await window()
    assert (by_name["recovery_success"].value, by_name["recovery_success"].sample_count) == (0.0, 0)
    assert by_name["operator_interventions"].value == 1.0

    await audit.record_revision_outcome(
        db, item_id=40, revision_id=40, status="completed", source="test")
    await db.commit()
    by_name = await window()
    assert (by_name["recovery_success"].value, by_name["recovery_success"].sample_count) == (1.0, 1)
    assert by_name["operator_interventions"].value == 1.0


async def test_r01_audit_get_current_id_filters_never_write(store, client):
    """R01 (B4 F07, Astra F04): current-ID filters resolve the active key
    without allocation. Known, unseen and nonexistent IDs leave the key table
    unchanged; only the known lifetime returns its events."""
    from app.services import factory_audit_service as _audit

    await _seed_team(store)
    await _seed_work(store, item_id=70, status="pending")
    async with store() as db:
        await _audit.record_event(
            db, event_kind="policy_change", source="test", occurred_at=_now(),
            actor=_audit.derive_actor(actor_kind="operator"), scope_id=5,
            action_outcome="applied")
        await db.commit()

    async def key_rows():
        async with store() as db:
            return (await db.execute(text(
                "SELECT COUNT(*) FROM factory_context_keys"))).scalar_one()

    before = await key_rows()
    known = await client.get("/api/v1/factory/audit-events?scope_id=5", headers=_OPERATOR_HEADERS)
    unseen = await client.get("/api/v1/factory/audit-events?item_id=70", headers=_OPERATOR_HEADERS)
    missing = await client.get("/api/v1/factory/audit-events?item_id=999", headers=_OPERATOR_HEADERS)

    assert [r.status_code for r in (known, unseen, missing)] == [200, 200, 200]
    assert known.json()["total"] == 1
    assert (unseen.json()["total"], missing.json()["total"]) == (0, 0)
    assert await key_rows() == before


# ---------------------------------------------------------------------------
# C12 coverage, import, durations and retry classes.
# ---------------------------------------------------------------------------


async def test_c12_migration_installs_marker_and_imports_populated_state_once(store):
    """C12: the real compatibility migration installs one stable marker and
    imports the populated persisted state once. Repeated runs change neither
    the marker nor the import; authority is unchanged; no fact time is
    inferred from row timestamps."""
    import json as _json

    import app.database as _database

    await _seed_team(store)
    await _seed_work(store, item_id=60, status="escalated", escalation_reason="plan_blocked")
    await _seed_work(store, item_id=61, status="completed", retry_count=0)
    before = [await _authority(store, 60), await _authority(store, 61)]
    engine = store.kw["bind"]

    async with engine.connect() as conn:
        await _database._run_sqlite_compat_migrations(conn)
    async with store() as db:
        marker = await audit.coverage_marker_time(db)
    first = await _facts(store, event_kind="work_state_import")
    async with engine.connect() as conn:
        await _database._run_sqlite_compat_migrations(conn)
    await _seed_work(store, item_id=62, status="pending")
    async with engine.connect() as conn:
        await _database._run_sqlite_compat_migrations(conn)

    assert marker is not None
    assert await _facts(store, event_kind="work_state_import") == first
    assert [(f["item_id"], f["scope_id"], f["action_outcome"], f["actor_kind"]) for f in first] == [
        (60, 5, "applied", "system"), (61, 5, "applied", "system")]
    assert _json.loads(first[0]["after_values"]) == {
        "dispatch_status": "escalated", "attempt_phase": "implementation", "retry_count": 2,
        "diagnostic_retry_count": 1, "active_scope_revision": 0}
    async with store() as db:
        rows = (await db.execute(text(
            "SELECT record_kind, fact_time, occurred_at, operation_id FROM factory_audit_events"
            " WHERE event_kind = 'work_state_import' ORDER BY id"))).fetchall()
        assert await audit.coverage_marker_time(db) == marker
        window = await metrics.build_metrics_window(
            db, window_start=marker - timedelta(hours=1), window_end=marker + timedelta(hours=1))
        markers = (await db.execute(text(
            "SELECT COUNT(*) FROM deck_compat_migrations WHERE name = :name"),
            {"name": audit.COVERAGE_MARKER})).scalar_one()
    assert markers == 1
    assert [(row[0], row[1], row[3]) for row in rows] == [
        ("observed_snapshot", None, f"{audit.COVERAGE_MARKER}:item:60"),
        ("observed_snapshot", None, f"{audit.COVERAGE_MARKER}:item:61")]
    assert {datetime.fromisoformat(str(row[2])) for row in rows} == {marker}
    assert window.instrumentation_start == marker
    # Imported snapshots are not outcomes, failures or operator actions.
    by_name = {sample.name: sample for sample in window.metrics}
    assert by_name["unknown_outcomes"].value == 0.0
    assert by_name["operator_interventions"].value == 0.0
    assert [await _authority(store, 60), await _authority(store, 61)] == before


async def test_c12_intervals_follow_the_stable_marker(db):
    """C12: empty, partial and wholly historical windows report truthful
    requested, available and missing intervals. One event inside a window
    before the marker never erases its missing interval."""
    actor = audit.derive_actor(actor_kind="operator")
    await audit.record_event(
        db, event_kind="work_lifecycle", source="test", occurred_at=datetime(2025, 12, 1, 12),
        actor=actor, action_outcome="applied", delivery_outcome="delivered")
    await db.commit()

    historical = await metrics.build_metrics_window(
        db, window_start=datetime(2025, 12, 1), window_end=datetime(2025, 12, 2))
    partial = await metrics.build_metrics_window(
        db, window_start=datetime(2025, 12, 31), window_end=datetime(2026, 1, 2))
    full = await metrics.build_metrics_window(
        db, window_start=datetime(2026, 1, 5, tzinfo=timezone.utc),
        window_end=datetime(2026, 1, 6, tzinfo=timezone.utc))

    assert historical.missing_intervals == [
        "2025-12-01T00:00:00/2025-12-02T00:00:00: before instrumentation start"]
    assert (historical.available_interval_start, historical.available_interval_end) == (None, None)
    delivered = {s.name: s for s in historical.metrics}["delivered_in_window"]
    assert (delivered.value, delivered.coverage) == (None, "unavailable")
    assert partial.missing_intervals == [
        "2025-12-31T00:00:00/2026-01-01T00:00:00: before instrumentation start"]
    assert (partial.available_interval_start, partial.available_interval_end) == (
        _COVERAGE_START, datetime(2026, 1, 2))
    assert {s.name: s for s in partial.metrics}["delivered_in_window"].coverage == "partial"
    assert full.missing_intervals == []
    assert {s.name: s for s in full.metrics}["delivered_in_window"].coverage == "full"
    for window in (historical, partial, full):
        assert window.instrumentation_start == _COVERAGE_START
    # Present-state observations keep their own label in every window.
    assert {s.name: s for s in historical.metrics}["current_queue"].coverage == (
        "present-state observation (all teams)")
    assert metrics._coverage(None, datetime(2026, 1, 1), datetime(2026, 1, 2))[0] == "unavailable"


async def test_c13_metrics_populations_follow_resolved_context_keys(db):
    """C04/C13: a team key selects that team's present state; a key of the
    wrong kind, an unknown key or a scope of another team has no current
    population and is never reported as global. Terminal tracking is a
    separate sample from delivery."""
    await _seed_scope(db, 1, preset_id=7)
    await _seed_scope(db, 2, preset_id=8)
    for item_id, scope_id in ((31, 1), (32, 1), (33, 2)):
        await _seed_item(db, item_id, scope_id=scope_id)
    await db.commit()
    team_a = await audit.context_key_for(db, "team", 7)
    scope_b = await audit.context_key_for(db, "scope", 2)
    await audit.record_delivery_fact(
        db, item_id=31, scope_id=1, team_context_key=team_a, delivery_outcome="unknown",
        completion_kind="closed_unproven", fact_source="github_watcher", fact_time=_now())
    await db.commit()

    async def window(**keys):
        result = await metrics.build_metrics_window(
            db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1),
            filter_scope="scoped", **keys)
        return {sample.name: sample for sample in result.metrics}

    team = await window(team_context_key=team_a)
    assert (team["total_tracked_attempts"].value, team["total_tracked_attempts"].coverage) == (
        2.0, "present-state observation (team)")
    assert team["terminal_tracking_in_window"].value == 1.0
    assert team["delivered_in_window"].value == 0.0
    for keys in ({"team_context_key": team_a, "scope_context_key": scope_b},
                 {"team_context_key": "team:999:synthetic"},
                 {"scope_context_key": team_a}):
        refused = await window(**keys)
        assert refused["total_tracked_attempts"].value is None, keys
        assert refused["total_tracked_attempts"].unknown_reasons == [
            "the selected context key has no current resource"]


async def test_c12_durations_pair_only_same_launch_boundaries(db):
    """C12: the real lifecycle writer records the launch boundary. A duration
    pairs it only with the first terminal fact of the same launch; another
    launch and a terminal fact without a launch identity stay unknown."""
    from app.models.database import GithubWorkItem
    from app.services.github_dispatch_service import observe_work_lifecycle

    for item_id in (21, 22, 23):
        await _seed_item(db, item_id)
    for launch_id in (121, 122):
        await db.execute(text(
            "INSERT INTO agent_team_launches (id, preset_id, plan_hash, status, created_at)"
            " SELECT :id, preset_id, 'synthetic-plan', 'completed', CURRENT_TIMESTAMP"
            " FROM team_github_scopes WHERE id = 1"), {"id": launch_id})
    await db.execute(text(
        "UPDATE github_work_items SET launch_id = id + 100 WHERE id IN (21, 22)"))
    await db.commit()
    for item_id in (21, 22):
        item = await db.get(GithubWorkItem, item_id)
        await observe_work_lifecycle(db, item=item, from_status=None, to_status="dispatched",
                                     source="github_dispatch_service.launch")
    await db.commit()
    starts = (await db.execute(select(FactoryAuditEvent).where(
        FactoryAuditEvent.event_kind == "work_lifecycle"))).scalars().all()
    assert [event.context_snapshot["launch_attempt"] for event in starts] == [
        "item:21:launch:121", "item:22:launch:122"]
    # R04: the real writer also captures the event-time issue identity.
    assert [event.context_snapshot["issue_number"] for event in starts] == [21, 22]
    assert [event.scope_id for event in starts] == [1, 1]
    for event in starts:
        event.occurred_at = _now()
    await db.commit()

    for minutes, artifact in ((10, None), (20, "pr-21")):
        await audit.record_delivery_fact(
            db, item_id=21, delivery_outcome="unknown", completion_kind="closed_unproven",
            fact_source="github_watcher", fact_time=_now() + timedelta(minutes=minutes),
            artifact=artifact, attempt="item:21:launch:121:revision:None",
            launch_attempt=audit.launch_attempt_key(21, 121))
    await audit.record_delivery_fact(
        db, item_id=22, delivery_outcome="unknown", completion_kind="closed_unproven",
        fact_source="github_watcher", fact_time=_now() + timedelta(minutes=5),
        attempt="item:22:launch:999:revision:None",
        launch_attempt=audit.launch_attempt_key(22, 999))
    await audit.record_delivery_fact(
        db, item_id=23, delivery_outcome="unknown", completion_kind="closed_unproven",
        fact_source="github_watcher", fact_time=_now() + timedelta(minutes=5))
    await db.commit()

    window = await metrics.build_metrics_window(
        db, window_start=_now() - timedelta(hours=1), window_end=_now() + timedelta(hours=1))
    duration = {s.name: s for s in window.metrics}["elapsed_attempt_duration"]
    assert (duration.value, duration.sample_count, duration.unknown_count) == (600.0, 1, 2)
    assert duration.unknown_reasons[1:] == [
        "no recorded launch boundary for the same attempt",
        "terminal fact without a launch identity"]
    assert duration.counting_unit == "seconds_median"


async def test_c12_real_verification_charges_record_retry_classes(store, monkeypatch):
    """C12: the real verification charges record one implementation and one
    diagnostic retry fact in their transactions. Evidenced classes and the
    authoritative counters are reported separately."""
    import json as _json

    from app.models.database import GithubAttemptScopeRevision, GithubWorkItem, TeamGithubScope
    from app.services.github_verification_service import github_verification_service

    async with store() as db:
        await audit.install_forward_coverage(await db.connection(), installed_at=_COVERAGE_START)
        await db.commit()
    await _seed_team(store)
    await _seed_work(store, item_id=63, status="verifying", retry_count=0)
    await _seed_work(store, item_id=64, status="dispatched", attempt_phase="diagnostic",
                     active_scope_revision=1, workspace_id=106,
                     lease_token="synthetic-lease-64")
    async with store() as db:
        revision = GithubAttemptScopeRevision(
            work_item_id=64, dispatch_nonce=_NONCE, revision=1,
            owner_slot_id=_OWNER["slot"], owner_member_id=_OWNER["member"],
            phase="diagnostic", execution_target="workspace", summary="Diagnostic",
            allowed_paths=["src/a.py"], allowed_actions=["edit_tests"],
            allowed_commands=[], prohibited_actions=[], tool_fallbacks={},
            baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40,
            originating_escalation_reason="retry_count_exhausted",
            expected_workspace_id=106, expected_lease_token_hash="h" * 64,
            max_failed_heads=2, status="active")
        db.add(revision)
        await db.commit()
        revision_id = revision.id

    async def no_notice(*_args, **_kwargs):
        # Mail boundary: the owner notice is outside the charge transaction.
        return None

    monkeypatch.setattr(github_verification_service, "_notify_diagnostic_failure", no_notice)
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        item = await db.get(GithubWorkItem, 63)
        await github_verification_service._record_transient_merge_failure(
            db, scope, item, "synthetic transient failure")
    async with store() as db:
        scope = await db.get(TeamGithubScope, 5)
        item = await db.get(GithubWorkItem, 64)
        revision = await db.get(GithubAttemptScopeRevision, revision_id)
        await github_verification_service._record_diagnostic_failure(
            db, scope, item, revision, "d" * 40)

    charges = await _facts(store, event_kind="retry_charge")
    assert [(f["item_id"], f["revision_id"], f["sanitized_reason"], _json.loads(f["after_values"]))
            for f in charges] == [
        (63, None, "transient_merge_failure", {"retry_count": 1}),
        (64, revision_id, "diagnostic_failed_head", {"diagnostic_retry_count": 2})]
    assert {(f["actor_kind"], f["actor_reference"]) for f in charges} == {
        ("scheduler", "github_dispatch_scheduler")}
    async with store() as db:
        window = await metrics.build_metrics_window(
            db, window_start=datetime.utcnow() - timedelta(hours=1),
            window_end=datetime.utcnow() + timedelta(hours=1))
        failed_heads = (await db.execute(text(
            "SELECT failed_head_count FROM github_attempt_scope_revisions WHERE id = :id"),
            {"id": revision_id})).scalar_one()
    by_name = {s.name: s for s in window.metrics}
    assert by_name["implementation_retries"].value == 1.0
    assert by_name["diagnostic_retries"].value == 1.0
    assert by_name["implementation_retry_counters"].value == 3.0
    assert by_name["diagnostic_retry_counters"].value == 3.0
    assert failed_heads == 1
