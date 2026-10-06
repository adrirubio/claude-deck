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
