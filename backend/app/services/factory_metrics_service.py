"""Factory delivery metrics service (P05).

Safe aggregates over the observation ledger and persisted M1a state. The
service never fetches fresh GitHub facts and never performs writes. Cost is
null when measured attribution is unavailable; partial coverage is stated.

Outcome classification follows the contract without changing the dispatch
state machine: terminal status alone never establishes delivery or human
review; unknown and explicit non-delivery stay separate from successes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    FactoryAuditEvent,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    TeamGithubScope,
)
from app.models.schemas import FactoryMetricSample, FactoryMetricsWindow

_DELIVERED = "delivered"
_NON_DELIVERY = "closed_without_delivery"
_UNKNOWN = "unknown"


async def _count(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar_one_or_none() or 0)


async def _resolve_context_numeric(
    db: AsyncSession, key: str | None, key_kind: str
) -> int | None:
    """Resolve a historical context key of one kind to its current numeric identity.

    C04/C13: a key of another kind never resolves. A key whose resource no
    longer exists resolves to nothing; its retained history stays addressable
    in the ledger, but it has no current population.
    """
    if not key:
        return None
    from app.models.database import AgentTeamPreset, FactoryContextKey, TeamGithubScope
    row = (await db.scalars(
        select(FactoryContextKey.numeric_id).where(
            FactoryContextKey.context_key == key,
            FactoryContextKey.key_kind == key_kind).limit(1)
    )).first()
    if row is None:
        return None
    model = TeamGithubScope if key_kind == "scope" else AgentTeamPreset
    current = (await db.scalars(select(model.id).where(model.id == int(row)).limit(1))).first()
    return int(current) if current is not None else None


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

    numeric_scope = await _resolve_context_numeric(db, scope_context_key, "scope")
    numeric_team = await _resolve_context_numeric(db, team_context_key, "team")
    # C13: a requested key without a current resource has no present-state
    # population. Live counts are then unavailable, never global.
    live_unresolved = bool(
        (scope_context_key and numeric_scope is None)
        or (team_context_key and numeric_team is None))
    if team_context_key and scope_context_key and not live_unresolved:
        owner = (await db.scalars(select(TeamGithubScope.preset_id).where(
            TeamGithubScope.id == numeric_scope).limit(1))).first()
        live_unresolved = owner != numeric_team
    live_population = (
        "scope" if scope_context_key else "team" if team_context_key else "all teams")

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
        if numeric_team is not None:
            stmt = stmt.where(GithubWorkItem.scope_id.in_(
                select(TeamGithubScope.id).where(TeamGithubScope.preset_id == numeric_team)))
        return stmt

    attempts_stmt = live_scoped(select(func.count()).select_from(GithubWorkItem))
    total_attempts = await _count(db, attempts_stmt)
    current_queue = await _count(db, live_scoped(
        select(func.count()).select_from(GithubWorkItem)
        .where(GithubWorkItem.dispatch_status.not_in(_TERMINAL_ITEM_STATES))))
    if numeric_scope is not None or numeric_team is not None:
        scoped_items = live_scoped(select(GithubWorkItem.id))
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

    # C12: evidenced retry classes, separate from the authoritative counters.
    def retry_charges(retry_class: str):
        return ledger_scoped(
            select(func.count()).select_from(FactoryAuditEvent)
            .where(FactoryAuditEvent.event_kind == "retry_charge",
                   func.json_extract(FactoryAuditEvent.context_snapshot,
                                     '$.retry_class') == retry_class))

    implementation_retries = await _count(db, retry_charges("implementation"))
    diagnostic_retries = await _count(db, retry_charges("diagnostic"))
    implementation_counter = await _count(db, live_scoped(
        select(func.coalesce(func.sum(GithubWorkItem.retry_count), 0))))
    diagnostic_counter = await _count(db, live_scoped(
        select(func.coalesce(func.sum(GithubWorkItem.diagnostic_retry_count), 0))))
    duration = await _same_attempt_durations(db, ledger_scoped)

    instrumentation = await _audit.instrumentation_start(db)
    coverage, available, missing = _coverage(
        instrumentation, _naive_utc(window_start), _naive_utc(window_end))
    live_source = "live_persisted_state"
    ledger_source = "factory_audit_events"

    def sample(name: str, unit: str, value: float | None, sample_count: int,
               unknown: int = 0, excluded: int = 0, reasons: list[str] | None = None,
               coverage: str = "full", source: str = ledger_source) -> FactoryMetricSample:
        return FactoryMetricSample(
            name=name, counting_unit=unit, value=value, sample_count=sample_count,
            unknown_count=unknown, excluded_count=excluded,
            unknown_reasons=reasons or [], source=source, coverage=coverage)

    def windowed(name: str, unit: str, value: float | None, sample_count: int,
                 unknown: int = 0, reasons: list[str] | None = None,
                 note: str | None = None) -> FactoryMetricSample:
        """C12: a ledger fact count labelled with the window's real coverage."""
        reasons = list(reasons or [])
        label = coverage if note is None else f"{coverage}; {note}"
        if coverage == "unavailable":
            return sample(name, unit, None, 0, unknown=max(unknown, 1),
                          reasons=reasons + ["the requested window has no ledger coverage"],
                          coverage=label)
        if coverage == "partial":
            reasons.append("part of the requested window precedes instrumentation start")
        return sample(name, unit, value, sample_count, unknown=unknown, reasons=reasons,
                      coverage=label)

    def present(name: str, unit: str, value: int, *, coverage_note: str = "",
                reasons: list[str] | None = None) -> FactoryMetricSample:
        """C13: a present-state count labelled with its actual population."""
        label = f"present-state observation ({live_population}{coverage_note})"
        if live_unresolved:
            return sample(name, unit, None, 0, unknown=1, source=live_source, coverage=label,
                          reasons=["the selected context key has no current resource"])
        return sample(name, unit, float(value), value, source=live_source, coverage=label,
                      reasons=reasons)

    terminal_tracked = await _count(db, ledger_scoped(
        select(func.count(func.distinct(FactoryAuditEvent.item_id)))
        .select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind == "delivery_evidence")))

    metrics = [
        present("current_queue", "work_items", current_queue),
        present("total_tracked_attempts", "work_items", total_attempts),
        present("pending_reviews", "approval_requests", pending_approvals),
        present("active_revisions", "scope_revisions", active_revisions),
        # C13: terminal tracking is reported apart from delivery and review.
        windowed("terminal_tracking_in_window", "work_items", float(terminal_tracked),
                 terminal_tracked, note="terminal tracking is not delivery"),
        windowed("delivered_in_window", "tracked_attempts", float(delivered), delivered,
                 unknown=terminal_unknown,
                 reasons=["terminal tracking without result evidence"] if terminal_unknown else []),
        windowed("independently_human_reviewed_design", "artifacts", float(review_evidenced),
                 review_evidenced, unknown=max(delivered - review_evidenced, 0),
                 reasons=(["no attributable independent human acceptance"]
                          if delivered > review_evidenced else [])),
        windowed("closed_without_delivery", "tracked_attempts", float(non_delivery), non_delivery),
        windowed("unknown_outcomes", "tracked_attempts", float(terminal_unknown), terminal_unknown,
                 reasons=["terminal status without result evidence"] if terminal_unknown else []),
        windowed("recovery_success", "preserved_revision_outcomes", float(recovery_applied),
                 recovery_applied + recovery_rejected + recovery_uncertain,
                 unknown=recovery_uncertain,
                 reasons=(["transport or external effects need reconciliation"]
                          if recovery_uncertain else [])),
        windowed("operator_interventions", "authenticated_actions", float(interventions),
                 interventions),
        windowed("harness_failures", "launch_lifecycle_events", float(harness_failures),
                 harness_failures, note="failed launch transitions only"),
        windowed("elapsed_attempt_duration", "seconds_median", duration.value,
                 duration.sample_count, unknown=duration.unknown, reasons=duration.reasons,
                 note="dispatch to terminal tracking of the same launched attempt"),
        windowed("implementation_retries", "retry_charges", float(implementation_retries),
                 implementation_retries, note="evidenced charges; counters authoritative"),
        windowed("diagnostic_retries", "retry_charges", float(diagnostic_retries),
                 diagnostic_retries, note="evidenced charges; counters authoritative"),
        present("implementation_retry_counters", "counter_total", implementation_counter,
                coverage_note="; authoritative counters",
                reasons=["counters keep their budget semantics and can be reset by an "
                         "authorized retry; they are not a count of charges"]),
        present("diagnostic_retry_counters", "counter_total", diagnostic_counter,
                coverage_note="; authoritative counters"),
        sample("cost", "usage_attribution", None, 0, unknown=1,
               reasons=["no measured usage attribution"], coverage="unknown"),
    ]
    return FactoryMetricsWindow(
        window_start=window_start,
        window_end=window_end,
        filter_scope=filter_scope,
        counting_unit_note=_COUNTING_NOTE,
        available_interval_start=available[0],
        available_interval_end=available[1],
        missing_intervals=missing,
        instrumentation_start=instrumentation,
        metrics=metrics,
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _coverage(
    marker: datetime | None, start: datetime, end: datetime
) -> tuple[str, tuple[datetime | None, datetime | None], list[str]]:
    """C12: requested, available and missing intervals from the stable marker.

    An event inside the window never stands in for coverage. Intervals before
    the marker stay missing; nothing before it is reconstructed.
    """
    if marker is None:
        return "unavailable", (None, None), [
            f"{start.isoformat()}/{end.isoformat()}: no forward-coverage marker is installed"]
    if marker > end:
        return "unavailable", (None, None), [
            f"{start.isoformat()}/{end.isoformat()}: before instrumentation start"]
    if marker > start:
        return "partial", (marker, end), [
            f"{start.isoformat()}/{marker.isoformat()}: before instrumentation start"]
    return "full", (start, end), []


class _Duration:
    def __init__(self, value: float | None, sample_count: int, unknown: int,
                 reasons: list[str]):
        self.value = value
        self.sample_count = sample_count
        self.unknown = unknown
        self.reasons = reasons


async def _same_attempt_durations(db: AsyncSession, ledger_scoped) -> _Duration:
    """C12: elapsed time only between boundaries of one launched attempt.

    The start is the first dispatched lifecycle fact of a launch. The end is
    the first terminal delivery fact of the same launch in the window. A
    terminal fact without a launch identity, or without a recorded start for
    the same launch, is unknown. A start of another launch never pairs.
    """
    starts: dict[str, datetime] = {}
    for occurred_at, snapshot in (await db.execute(
        select(FactoryAuditEvent.occurred_at, FactoryAuditEvent.context_snapshot)
        .where(FactoryAuditEvent.event_kind == "work_lifecycle",
               func.json_extract(FactoryAuditEvent.after_values,
                                 '$.dispatch_status') == "dispatched")
    )).all():
        key = _launch_key(snapshot)
        if key is not None and (key not in starts or occurred_at < starts[key]):
            starts[key] = occurred_at
    ends: dict[str, datetime] = {}
    unbound: set[str] = set()
    for event_id, item_id, occurred_at, fact_time, snapshot in (await db.execute(ledger_scoped(
        select(FactoryAuditEvent.id, FactoryAuditEvent.item_id, FactoryAuditEvent.occurred_at,
               FactoryAuditEvent.fact_time, FactoryAuditEvent.context_snapshot)
        .where(FactoryAuditEvent.event_kind == "delivery_evidence")
    ))).all():
        key = _launch_key(snapshot)
        end = fact_time or occurred_at
        if key is None:
            unbound.add(str((snapshot or {}).get("attempt") or f"item:{item_id}:event:{event_id}"))
        elif key not in ends or end < ends[key]:
            ends[key] = end
    durations = [
        (end - starts[key]).total_seconds()
        for key, end in ends.items() if key in starts and starts[key] <= end
    ]
    unpaired = len(ends) - len(durations)
    reasons = ["elapsed time from dispatch to terminal tracking is not execution "
               "time or operator hands-on time"]
    if unpaired:
        reasons.append("no recorded launch boundary for the same attempt")
    if unbound:
        reasons.append("terminal fact without a launch identity")
    value = float(median(durations)) if durations else None
    return _Duration(value, len(durations), unpaired + len(unbound), reasons)


def _launch_key(snapshot: dict | None) -> str | None:
    key = (snapshot or {}).get("launch_attempt") if isinstance(snapshot, dict) else None
    if not isinstance(key, str) or key.endswith(":launch:None"):
        return None
    return key


_COUNTING_NOTE = (
    "Counts are tracked attempts or events as named per metric. "
    "Present-state observations come from live persisted state; windowed "
    "facts come from the ledger. Tracked attempts across separate scopes "
    "remain distinct and are never advertised as a unique-PR total.")
