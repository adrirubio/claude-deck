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


async def build_metrics_window(
    db: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    filter_scope: str = "all",
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
) -> FactoryMetricsWindow:
    """Build one requested metrics window with explicit coverage."""
    from app.services import factory_audit_service as _audit

    def scoped(stmt):
        if team_context_key:
            stmt = stmt.where(FactoryAuditEvent.team_context_key == team_context_key)
        if scope_context_key:
            stmt = stmt.where(FactoryAuditEvent.scope_context_key == scope_context_key)
        return stmt.where(
            FactoryAuditEvent.occurred_at >= window_start,
            FactoryAuditEvent.occurred_at <= window_end,
        )

    attempts = select(func.count()).select_from(GithubWorkItem)
    total_attempts = await _count(db, attempts)
    delivered = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.delivery_outcome == _DELIVERED)))
    non_delivery = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.delivery_outcome == _NON_DELIVERY)))
    terminal_unknown = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.delivery_outcome == _UNKNOWN)))
    review_evidenced = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.human_review_evidence.is_not(None))))
    recovery_applied = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind.in_(("prepared_attempt_resume", "recovery_cancellation")),
               FactoryAuditEvent.action_outcome == "applied")))
    recovery_rejected = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind.in_(("prepared_attempt_resume", "recovery_cancellation")),
               FactoryAuditEvent.action_outcome == "rejected")))
    recovery_uncertain = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind.in_(("prepared_attempt_resume", "recovery_cancellation")),
               FactoryAuditEvent.action_outcome == "uncertain")))
    interventions = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.actor_kind == "operator")))
    harness_failures = await _count(db, scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind == "work_lifecycle",
               FactoryAuditEvent.after_values.is_not(None))))
    pending_approvals = await _count(db, select(func.count()).select_from(
        GithubApprovalRequest).where(GithubApprovalRequest.status == "pending"))
    active_revisions = await _count(db, select(func.count()).select_from(
        GithubAttemptScopeRevision).where(
        GithubAttemptScopeRevision.status.not_in(("completed", "cancelled", "rejected"))))

    instrumentation = await _audit.instrumentation_start(db)

    def sample(name: str, unit: str, value: float | None, sample_count: int,
               unknown: int = 0, excluded: int = 0, reasons: list[str] | None = None,
               coverage: str = "full") -> FactoryMetricSample:
        return FactoryMetricSample(
            name=name, counting_unit=unit, value=value, sample_count=sample_count,
            unknown_count=unknown, excluded_count=excluded,
            unknown_reasons=reasons or [], coverage=coverage)

    metrics = [
        sample("current_queue", "work_items", float(total_attempts), total_attempts),
        sample("pending_reviews", "approval_requests", float(pending_approvals), pending_approvals),
        sample("active_revisions", "scope_revisions", float(active_revisions), active_revisions),
        sample("delivered_in_window", "tracked_attempts", float(delivered), delivered,
               unknown=terminal_unknown,
               reasons=["terminal tracking without result evidence"] if terminal_unknown else []),
        sample("independently_human_reviewed_design", "artifacts", float(review_evidenced),
               review_evidenced, unknown=max(delivered - review_evidenced, 0),
               reasons=["no attributable independent human acceptance"] if delivered > review_evidenced else []),
        sample("closed_without_delivery", "tracked_attempts", float(non_delivery), non_delivery),
        sample("unknown_outcomes", "tracked_attempts", float(terminal_unknown), terminal_unknown,
               reasons=["terminal status without result evidence"] if terminal_unknown else []),
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
        sample("recovery_success", "recovery_actions", float(recovery_applied),
               recovery_applied + recovery_rejected + recovery_uncertain,
               unknown=recovery_uncertain,
               reasons=["transport or external effects need reconciliation"] if recovery_uncertain else []),
        sample("operator_interventions", "authenticated_actions", float(interventions), interventions),
        sample("harness_failures", "lifecycle_events", float(harness_failures), harness_failures,
               coverage="partial harness context"),
        sample("cost", "usage_attribution", None, 0, unknown=1,
               reasons=["no measured usage attribution"], coverage="unknown"),
    ]
    return FactoryMetricsWindow(
        window_start=window_start,
        window_end=window_end,
        filter_scope=filter_scope,
        counting_unit_note=(
            "Counts are tracked attempts or events as named per metric. "
            "Tracked attempts across separate scopes remain distinct and are "
            "never advertised as a unique-PR total."),
        available_interval_start=instrumentation,
        available_interval_end=window_end if instrumentation else None,
        missing_intervals=[] if instrumentation else ["before instrumentation start"],
        instrumentation_start=instrumentation,
        metrics=metrics,
    )
