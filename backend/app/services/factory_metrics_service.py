"""Factory delivery metrics service (P05).

Safe aggregates over the observation ledger and persisted M1a state. The
service never fetches fresh GitHub facts and never performs writes. Cost is
null when measured attribution is unavailable; partial coverage is stated.

Outcome classification follows the contract without changing the dispatch
state machine: terminal status alone never establishes delivery or human
review; unknown and explicit non-delivery stay separate from successes.
"""
from __future__ import annotations

import re
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
    from app.models.database import AgentTeamPreset, TeamGithubScope
    from app.services.factory_audit_service import context_key_is_current
    # R01: a retired key (its resource was deleted) never selects the live
    # resource that now reuses the numeric ID.
    row = await context_key_is_current(db, key, key_kind)
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

    def ledger_keyed(stmt):
        """Context-key selection only; the caller applies its own time bound."""
        if team_context_key:
            stmt = stmt.where(FactoryAuditEvent.team_context_key == team_context_key)
        if scope_context_key:
            stmt = stmt.where(FactoryAuditEvent.scope_context_key == scope_context_key)
        return stmt

    # R03: one current result per immutable scoped attempt, reconciled from
    # every retained outcome fact up to the window end. Retained context keys
    # and snapshots identify the attempt, so deletion never changes history.
    # A known sourced fact time places the result; otherwise the observation
    # time does.
    effective_time = func.coalesce(FactoryAuditEvent.fact_time, FactoryAuditEvent.occurred_at)
    outcome_rows = (await db.execute(ledger_keyed(
        select(FactoryAuditEvent.id, effective_time.label("occurred_at"),
               FactoryAuditEvent.delivery_outcome, FactoryAuditEvent.completion_kind,
               FactoryAuditEvent.context_snapshot, FactoryAuditEvent.item_context_key)
        .where(FactoryAuditEvent.delivery_outcome.is_not(None),
               effective_time <= window_end)))).all()
    attempts = _reconcile_attempts(
        outcome_rows, _naive_utc(window_start), _naive_utc(window_end))
    in_window = [state for state in attempts.values() if state["in_window"]]
    delivered = sum(1 for state in in_window if state["outcome"] == _DELIVERED)
    # T09: separate safe code and design delivery aggregates, with the same
    # attempt, window and coverage rules as delivered_in_window.
    delivered_design = sum(1 for state in in_window
                           if state["outcome"] == _DELIVERED and state["design"])
    merged_code = sum(1 for state in in_window
                      if state["outcome"] == _DELIVERED and not state["design"]
                      and "merged_code" in state["kinds"])
    non_delivery = sum(1 for state in in_window if state["outcome"] == _NON_DELIVERY)
    terminal_unknown = sum(1 for state in in_window if state["outcome"] == _UNKNOWN)
    terminal_tracked = sum(1 for state in attempts.values() if state["terminal_in_window"])

    # R06: independent review of the exact design artifact, once per eligible
    # delivered design attempt. Code deliveries are not in the population.
    review_rows = (await db.execute(ledger_keyed(
        select(FactoryAuditEvent.id, FactoryAuditEvent.human_review_evidence,
               FactoryAuditEvent.context_snapshot, FactoryAuditEvent.item_context_key)
        .where(FactoryAuditEvent.human_review_evidence.is_not(None),
               effective_time <= window_end)))).all()
    eligible_design = [state for state in in_window
                       if state["outcome"] == _DELIVERED and state["design"]]
    reviewed_design = _reviewed_design_attempts(eligible_design, review_rows, _audit)

    # R08: recovery counts preserved revision results, not action requests.
    # T02: one result per revision, however many call sites observed it.
    recovery_rows = (await db.execute(ledger_scoped(
        select(FactoryAuditEvent.id, FactoryAuditEvent.revision_id,
               FactoryAuditEvent.operation_id,
               func.json_extract(FactoryAuditEvent.after_values, '$.status').label("status"))
        .select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind == "revision_outcome")))).all()
    revision_results: dict[str, set] = {}
    for row in recovery_rows:
        revision_results.setdefault(_revision_result_identity(row), set()).add(row.status)
    recovery_applied = sum(1 for statuses in revision_results.values() if "completed" in statuses)
    recovery_total = len(revision_results)
    recovery_uncertain = await _count(db, ledger_scoped(
        select(func.count()).select_from(FactoryAuditEvent)
        .where(FactoryAuditEvent.event_kind.in_(("prepared_attempt_resume", "recovery_cancellation")),
               FactoryAuditEvent.action_outcome == "uncertain")))
    # R08: interventions are distinct applied operator actions. Notification
    # facts are not actions; rejected and uncertain actions are excluded and
    # reported.
    # T07: an action is identified by its resource-bound replay key (action
    # kind, operation and exact resource lifetimes), or by its own event.
    # Derived evidence facts (delivery facts, notices) are not actions.
    operator_rows = (await db.execute(ledger_scoped(
        select(FactoryAuditEvent.id, FactoryAuditEvent.replay_key,
               FactoryAuditEvent.event_kind, FactoryAuditEvent.action_outcome)
        .where(FactoryAuditEvent.actor_kind == "operator")))).all()
    action_rows = [row for row in operator_rows
                   if not row.event_kind.endswith("_notification")
                   and row.event_kind not in _DERIVED_EVIDENCE_KINDS]
    interventions = len({row.replay_key or f"event:{row.id}"
                         for row in action_rows if row.action_outcome == "applied"})
    intervention_excluded = sum(1 for row in action_rows if row.action_outcome != "applied")
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
    duration = await _same_attempt_durations(db, ledger_keyed, window_start, window_end)

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
                 note: str | None = None, excluded: int = 0) -> FactoryMetricSample:
        """C12: a ledger fact count labelled with the window's real coverage."""
        reasons = list(reasons or [])
        label = coverage if note is None else f"{coverage}; {note}"
        if coverage == "unavailable":
            return sample(name, unit, None, 0, unknown=max(unknown, 1),
                          reasons=reasons + ["the requested window has no ledger coverage"],
                          coverage=label)
        if coverage == "partial":
            reasons.append("part of the requested window precedes instrumentation start")
        return sample(name, unit, value, sample_count, unknown=unknown, excluded=excluded,
                      reasons=reasons, coverage=label)

    def present(name: str, unit: str, value: int, *, coverage_note: str = "",
                reasons: list[str] | None = None) -> FactoryMetricSample:
        """C13: a present-state count labelled with its actual population."""
        label = f"present-state observation ({live_population}{coverage_note})"
        if live_unresolved:
            return sample(name, unit, None, 0, unknown=1, source=live_source, coverage=label,
                          reasons=["the selected context key has no current resource"])
        return sample(name, unit, float(value), value, source=live_source, coverage=label,
                      reasons=reasons)

    review_unknown = len(eligible_design) - reviewed_design

    metrics = [
        present("current_queue", "work_items", current_queue),
        present("total_tracked_attempts", "work_items", total_attempts),
        present("pending_reviews", "approval_requests", pending_approvals),
        present("active_revisions", "scope_revisions", active_revisions),
        # C13/R03: terminal tracking is reported apart from delivery and
        # review, per retained attempt identity.
        windowed("terminal_tracking_in_window", "tracked_attempts", float(terminal_tracked),
                 terminal_tracked, note="terminal tracking is not delivery"),
        windowed("delivered_in_window", "tracked_attempts", float(delivered), delivered,
                 unknown=terminal_unknown,
                 reasons=["terminal tracking without result evidence"] if terminal_unknown else []),
        windowed("merged_code_in_window", "code_attempts", float(merged_code), merged_code,
                 note="sourced merged code pull requests"),
        windowed("delivered_design_in_window", "design_attempts", float(delivered_design),
                 delivered_design,
                 note="merged design or exact accepted design version; review is separate"),
        windowed("independently_human_reviewed_design", "design_attempts",
                 float(reviewed_design), len(eligible_design), unknown=review_unknown,
                 reasons=(["no attributable independent human review of the exact artifact"]
                          if review_unknown else [])),
        windowed("closed_without_delivery", "tracked_attempts", float(non_delivery), non_delivery),
        windowed("unknown_outcomes", "tracked_attempts", float(terminal_unknown), terminal_unknown,
                 reasons=["terminal status without result evidence"] if terminal_unknown else []),
        windowed("recovery_success", "preserved_revision_outcomes", float(recovery_applied),
                 recovery_total, unknown=recovery_uncertain,
                 reasons=(["recovery actions with unsettled transport or external effects"]
                          if recovery_uncertain else [])),
        windowed("operator_interventions", "authenticated_actions", float(interventions),
                 interventions, excluded=intervention_excluded,
                 reasons=(["rejected or uncertain operator actions are excluded"]
                          if intervention_excluded else [])),
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


_OUTCOME_RANK = {_UNKNOWN: 1, _NON_DELIVERY: 2, _DELIVERED: 3}
# T07: facts derived from an action's evidence, never actions themselves.
_DERIVED_EVIDENCE_KINDS = ("delivery_evidence",)
_REVISION_RESULT_OPERATION = re.compile(r"^revision_outcome:(\d+):")


def _revision_result_identity(row) -> str:
    """B4 F03: the immutable revision of a result fact.

    The retained operation identity names the revision, so deleting the live
    revision (which nulls revision_id) never splits one result into two.
    """
    match = _REVISION_RESULT_OPERATION.match(row.operation_id or "")
    if match is not None:
        return f"revision:{match.group(1)}"
    if row.revision_id is not None:
        return f"revision:{row.revision_id}"
    return f"event:{row.id}"
_DESIGN_COMPLETION_KINDS = ("merged_design", "design_artifact_accepted")


def _snapshot(value) -> dict:
    return value if isinstance(value, dict) else {}


def _attempt_identity(item_context_key: str | None, snapshot: dict, event_id: int) -> str:
    """R03: the immutable scoped attempt identity of an outcome fact."""
    attempt = snapshot.get("attempt")
    if attempt:
        # The item context key is a resource lifetime; numeric ID reuse can
        # never merge two attempts.
        return f"{item_context_key or 'item:unknown'}|{attempt}"
    return f"event:{event_id}"


def _reconcile_attempts(rows, window_start: datetime, window_end: datetime) -> dict:
    """R03: one current outcome per attempt; no downgrade, no duplicates.

    A delivered fact outranks sourced non-delivery, which outranks unknown.
    Repeated or weaker later facts never lower the current outcome.

    T03: outcome strength and window placement are separate. The selected
    outcome is placed at the earliest effective time of a fact with that
    outcome (its sourced fact time, or its observation time when that is
    unknown), so a weaker later fact never places an old delivery in
    another window. Terminal tracking is placed at the first terminal fact.
    """
    attempts: dict[str, dict] = {}
    for row in rows:
        snapshot = _snapshot(row.context_snapshot)
        identity = _attempt_identity(row.item_context_key, snapshot, row.id)
        state = attempts.setdefault(identity, {
            "identity": identity, "outcome": None, "in_window": False,
            "terminal_in_window": False, "placed_at": None, "terminal_at": None,
            "design": False, "artifacts": set(), "versions": set(), "kinds": set()})
        if row.delivery_outcome == _DELIVERED and row.completion_kind:
            state["kinds"].add(row.completion_kind)
        when = row.occurred_at
        if isinstance(when, str):
            when = datetime.fromisoformat(when)
        if row.delivery_outcome in _OUTCOME_RANK:
            if (state["outcome"] is None
                    or _OUTCOME_RANK[row.delivery_outcome] > _OUTCOME_RANK[state["outcome"]]):
                state["outcome"] = row.delivery_outcome
                state["placed_at"] = when
            elif (row.delivery_outcome == state["outcome"] and when is not None
                    and (state["placed_at"] is None or when < state["placed_at"])):
                state["placed_at"] = when
            if when is not None and (state["terminal_at"] is None or when < state["terminal_at"]):
                state["terminal_at"] = when
        if (row.completion_kind in _DESIGN_COMPLETION_KINDS
                or snapshot.get("issue_type") == "design"):
            state["design"] = True
        if snapshot.get("artifact"):
            state["artifacts"].add(snapshot["artifact"])
            # A32: the exact delivered version of the artifact, when known.
            if row.delivery_outcome == _DELIVERED and snapshot.get("artifact_version"):
                state["versions"].add((snapshot["artifact"], snapshot["artifact_version"]))
    for state in attempts.values():
        state["in_window"] = (state["placed_at"] is not None
                              and window_start <= state["placed_at"] <= window_end)
        state["terminal_in_window"] = (state["terminal_at"] is not None
                                       and window_start <= state["terminal_at"] <= window_end)
    return attempts


def _reviewed_design_attempts(eligible: list[dict], review_rows, audit) -> int:
    """R06/A32: eligible design attempts with a validated exact-version review.

    A review counts only for the attempt it is bound to and only for an
    artifact version that the attempt delivered. A merge alone, a changed
    head or a review of another version never counts. Each attempt counts
    once, however many times its review is repeated.
    """
    reviews: list[tuple[str, str, str]] = []
    for row in review_rows:
        evidence = row.human_review_evidence
        if not audit.validated_review_evidence(evidence):
            continue
        identity = _attempt_identity(row.item_context_key, _snapshot(row.context_snapshot), row.id)
        reviews.append((identity, evidence["artifact"], evidence["version"]))
    count = 0
    for state in eligible:
        if any(identity == state["identity"] and (artifact, version) in state["versions"]
               for identity, artifact, version in reviews):
            count += 1
    return count


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


async def _same_attempt_durations(
    db: AsyncSession, ledger_keyed, window_start: datetime, window_end: datetime
) -> _Duration:
    """C12: elapsed time only between boundaries of one launched attempt.

    The start is the first dispatched lifecycle fact of a launch. The end is
    the first terminal delivery fact of the same launch in the window. A
    terminal fact without a launch identity, or without a recorded start for
    the same launch, is unknown. A start of another launch never pairs.
    """
    # T06: boundaries pair only within one immutable item lifetime and
    # launch, and both use the same scope selection.
    starts: dict[str, datetime] = {}
    for occurred_at, item_key, snapshot in (await db.execute(ledger_keyed(
        select(FactoryAuditEvent.occurred_at, FactoryAuditEvent.item_context_key,
               FactoryAuditEvent.context_snapshot)
        .where(FactoryAuditEvent.event_kind == "work_lifecycle",
               func.json_extract(FactoryAuditEvent.after_values,
                                 '$.dispatch_status') == "dispatched")
    ))).all():
        key = _lifetime_launch_key(item_key, snapshot)
        if key is not None and (key not in starts or occurred_at < starts[key]):
            starts[key] = occurred_at
    ends: dict[str, datetime] = {}
    unbound: set[str] = set()
    # The terminal boundary is the sourced fact time when known. B4 F02: the
    # canonical boundary of each lifetime launch is its first terminal fact,
    # chosen before window filtering; the duration counts once, in the
    # window that contains that boundary. A later closure adds nothing.
    effective_time = func.coalesce(FactoryAuditEvent.fact_time, FactoryAuditEvent.occurred_at)
    start_bound = _naive_utc(window_start)
    for event_id, item_id, item_key, occurred_at, fact_time, snapshot in (await db.execute(
        ledger_keyed(
            select(FactoryAuditEvent.id, FactoryAuditEvent.item_id,
                   FactoryAuditEvent.item_context_key, FactoryAuditEvent.occurred_at,
                   FactoryAuditEvent.fact_time, FactoryAuditEvent.context_snapshot)
            .where(FactoryAuditEvent.event_kind == "delivery_evidence",
                   effective_time <= window_end)
    ))).all():
        key = _lifetime_launch_key(item_key, snapshot)
        end = fact_time or occurred_at
        if key is None:
            if end is not None and end >= start_bound:
                unbound.add(str((snapshot or {}).get("attempt")
                                or f"item:{item_id}:event:{event_id}"))
        elif key not in ends or end < ends[key]:
            ends[key] = end
    ends = {key: end for key, end in ends.items() if end >= start_bound}
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


def _lifetime_launch_key(item_context_key: str | None, snapshot: dict | None) -> str | None:
    """T06: the launch of one immutable item lifetime, or None when unknown."""
    key = _launch_key(snapshot)
    if key is None or not item_context_key:
        return None
    return f"{item_context_key}|{key}"


_COUNTING_NOTE = (
    "Counts are tracked attempts or events as named per metric. "
    "Present-state observations come from live persisted state; windowed "
    "facts come from the ledger. Tracked attempts across separate scopes "
    "remain distinct and are never advertised as a unique-PR total.")
