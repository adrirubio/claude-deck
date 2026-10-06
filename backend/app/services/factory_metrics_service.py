"""Factory delivery metrics service (P05).

Safe aggregates over the observation ledger and persisted M1a state. The
service never fetches fresh GitHub facts and never performs writes. Cost is
null when measured attribution is unavailable; partial coverage is stated.

Outcome classification follows the contract without changing the dispatch
state machine: terminal status alone never establishes delivery or human
review; unknown and explicit non-delivery stay separate from successes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    FactoryAuditEvent,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
)
from app.models.schemas import FactoryMetricSample, FactoryMetricsWindow

_DELIVERED = "delivered"
_NON_DELIVERY = "closed_without_delivery"
_UNKNOWN = "unknown"


async def _count(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar_one_or_none() or 0)


async def _resolve_context_numeric(db: AsyncSession, key: str | None) -> int | None:
    """Resolve a historical context key to its current numeric identity."""
    if not key:
        return None
    from app.models.database import FactoryContextKey
    row = (await db.scalars(
        select(FactoryContextKey.numeric_id).where(
            FactoryContextKey.context_key == key).limit(1)
    )).first()
    return int(row) if row is not None else None


_TERMINAL_ITEM_STATES = ("completed", "closed", "merged", "cancelled", "withdrawn")
_ACTIVE_REVISION_STATES = ("completed", "cancelled", "rejected", "exhausted", "expired", "superseded")


async def build_metrics_window(
    db: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    filter_scope: str = "all",
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
) -> FactoryMetricsWindow:
    """Build one requested metrics window with explicit coverage.

    Scoped requests resolve the historical context keys to current numeric
    identities and apply the same selection to ledger counts and live-state
    counts. Present-state observations are labelled separately from
    windowed ledger facts. Sources state where each count comes from.
    """
    from app.services import factory_audit_service as _audit

    scoped_request = filter_scope == "scoped"
    if scoped_request and not (team_context_key or scope_context_key):
        return FactoryMetricsWindow(
            window_start=window_start, window_end=window_end,
            filter_scope=filter_scope,
            counting_unit_note=_COUNTING_NOTE,
            metrics=[], missing_intervals=["no scope selected for a scoped request"])

    numeric_scope = await _resolve_context_numeric(db, scope_context_key)

    def ledger_scoped(stmt):
        if team_context_key:
            stmt = stmt.where(FactoryAuditEvent.team_context_key == team_context_key)
        if scope_context_key:
            stmt = stmt.where(FactoryAuditEvent.scope_context_key == scope_context_key)
        return stmt.where(
            FactoryAuditEvent.occurred_at >= window_start,
            FactoryAuditEvent.occurred_at <= window_end,
        )

    def live_scoped(stmt):
        if numeric_scope is not None:
            stmt = stmt.where(GithubWorkItem.scope_id == numeric_scope)
        return stmt

    attempts_stmt = live_scoped(select(func.count()).select_from(GithubWorkItem))
    total_attempts = await _count(db, attempts_stmt)
    current_queue = await _count(db, live_scoped(
        select(func.count()).select_from(GithubWorkItem)
        .where(GithubWorkItem.dispatch_status.not_in(_TERMINAL_ITEM_STATES))))
    if numeric_scope is not None:
        scoped_items = select(GithubWorkItem.id).where(GithubWorkItem.scope_id == numeric_scope)
        pending_approvals = await _count(db,
            select(func.count()).select_from(GithubApprovalRequest)
            .where(GithubApprovalRequest.status == "pending")
            .where(GithubApprovalRequest.work_item_id.in_(scoped_items)))
        active_revisions = await _count(db,
            select(func.count()).select_from(GithubAttemptScopeRevision)
            .where(GithubAttemptScopeRevision.status.not_in(_ACTIVE_REVISION_STATES))
            .where(GithubAttemptScopeRevision.work_item_id.in_(scoped_items)))
    else:
        pending_approvals = await _count(db,
            select(func.count()).select_from(GithubApprovalRequest)
            .where(GithubApprovalRequest.status == "pending"))
        active_revisions = await _count(db,
            select(func.count()).select_from(GithubAttemptScopeRevision)
            .where(GithubAttemptScopeRevision.status.not_in(_ACTIVE_REVISION_STATES)))

    delivered = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.delivery_outcome == _DELIVERED)))
    non_delivery = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.delivery_outcome == _NON_DELIVERY)))
    terminal_unknown = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.delivery_outcome == _UNKNOWN)))
    review_rows = (await db.execute(ledger_scoped(
        select(FactoryAuditEvent.human_review_evidence).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.human_review_evidence.is_not(None))))).scalars().all()
    review_evidenced = sum(
        1 for evidence in review_rows if _audit.validated_review_evidence(evidence))
    recovery_applied = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind.in_(("prepared_attempt_resume", "recovery_cancellation")),
               FactoryAuditEvent.action_outcome == "applied",
               FactoryAuditEvent.revision_id.is_not(None))))
    recovery_rejected = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind.in_(("prepared_attempt_resume", "recovery_cancellation")),
               FactoryAuditEvent.action_outcome == "rejected")))
    recovery_uncertain = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind.in_(("prepared_attempt_resume", "recovery_cancellation")),
               FactoryAuditEvent.action_outcome == "uncertain")))
    interventions = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.actor_kind == "operator")))
    # Real harness failures only: launch lifecycle transitions that recorded
    # the failed dispatch state. Successful dispatches never count.
    harness_failures = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind == "work_lifecycle",
               func.json_extract(FactoryAuditEvent.after_values, '$.dispatch_status') == "failed")))

    instrumentation = await _audit.instrumentation_start(db)
    live_source = "live_persisted_state"
    ledger_source = "factory_audit_events"

    def sample(name: str, unit: str, value: float | None, sample_count: int,
               unknown: int = 0, excluded: int = 0, reasons: list[str] | None = None,
               coverage: str = "full", source: str = ledger_source) -> FactoryMetricSample:
        return FactoryMetricSample(
            name=name, counting_unit=unit, value=value, sample_count=sample_count,
            unknown_count=unknown, excluded_count=excluded,
            unknown_reasons=reasons or [], source=source, coverage=coverage)

    metrics = [
        sample("current_queue", "work_items", float(current_queue), current_queue,
               source=live_source, coverage="present-state observation"),
        sample("total_tracked_attempts", "work_items", float(total_attempts), total_attempts,
               source=live_source, coverage="present-state observation"),
        sample("pending_reviews", "approval_requests", float(pending_approvals), pending_approvals,
               source=live_source, coverage="present-state observation"),
        sample("active_revisions", "scope_revisions", float(active_revisions), active_revisions,
               source=live_source, coverage="present-state observation"),
        sample("delivered_in_window", "tracked_attempts", float(delivered), delivered,
               unknown=terminal_unknown,
               reasons=["terminal tracking without result evidence"] if terminal_unknown else []),
        sample("independently_human_reviewed_design", "artifacts", float(review_evidenced),
               review_evidenced, unknown=max(delivered - review_evidenced, 0),
               reasons=["no attributable independent human acceptance"] if delivered > review_evidenced else []),
        sample("closed_without_delivery", "tracked_attempts", float(non_delivery), non_delivery),
        sample("unknown_outcomes", "tracked_attempts", float(terminal_unknown), terminal_unknown,
               reasons=["terminal status without result evidence"] if terminal_unknown else []),
        sample("recovery_success", "preserved_revision_outcomes", float(recovery_applied),
               recovery_applied + recovery_rejected + recovery_uncertain,
               unknown=recovery_uncertain,
               reasons=["transport or external effects need reconciliation"] if recovery_uncertain else []),
        sample("operator_interventions", "authenticated_actions", float(interventions), interventions),
        sample("harness_failures", "launch_lifecycle_events", float(harness_failures), harness_failures,
               coverage="failed launch transitions only"),
        sample("elapsed_attempt_duration", "tracked_attempts", None,
               0, unknown=max(total_attempts, 1),
               reasons=["recorded start and stop events for the same attempt "
                        "are required; elapsed time is not execution time or "
                        "operator hands-on time"],
               coverage="named boundaries only"),
        sample("diagnostic_retries", "retry_events", None, 0, unknown=1,
               reasons=["diagnostic and implementation retries stay separate; "
                        "authoritative budget counters retain their semantics"],
               coverage="counters authoritative"),
        sample("cost", "usage_attribution", None, 0, unknown=1,
               reasons=["no measured usage attribution"], coverage="unknown"),
    ]
    return FactoryMetricsWindow(
        window_start=window_start,
        window_end=window_end,
        filter_scope=filter_scope,
        counting_unit_note=_COUNTING_NOTE,
        available_interval_start=instrumentation,
        available_interval_end=window_end if instrumentation else None,
        missing_intervals=[] if instrumentation else ["before instrumentation start"],
        instrumentation_start=instrumentation,
        metrics=metrics,
    )


_COUNTING_NOTE = (
    "Counts are tracked attempts or events as named per metric. "
    "Present-state observations come from live persisted state; windowed "
    "facts come from the ledger. Tracked attempts across separate scopes "
    "remain distinct and are never advertised as a unique-PR total.")
