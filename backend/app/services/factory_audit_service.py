"""Factory audit ledger service (P05).

Observation-only ledger. The ledger observes actual results. It never
approves plans, raises limits, retries work, releases a workspace or replays
a mutation because an event is present or absent.

Actor derivation uses actual authentication or scheduler context. A shared
operator credential is recorded as an operator role, never a named person.
No credential, credential hash or agent token is ever stored.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import FactoryAuditEvent, FactoryContextKey

# Allowlisted value keys for before/after snapshots. Values outside this
# allowlist are dropped at write time.
SAFE_VALUE_FIELDS = {
    "status", "dispatch_status", "attempt_phase", "enabled", "autonomy_enabled",
    "leader_slot_id", "owner_slot_id", "owner_member_id", "approval_round",
    "approval_round_count", "retry_count", "diagnostic_retry_count",
    "delivery_outcome", "completion_kind", "action_outcome", "provider",
    "display_name", "name", "repo_owner", "repo_name", "issue_type",
    "merge_policy", "dispatch_label", "design_label", "base_ref",
    "wake_enabled", "mailbox_status", "kind", "request_kind", "decision",
    "status_note", "phase", "execution_target", "failed_head_count",
    "max_failed_heads", "workspace_enabled", "dispatchable",
    "recovery_checkpoint_stage", "active_scope_revision",
    # C11: typed finite continuation policy settings.
    "continuation_enabled", "max_continuation_revisions",
    "max_continuation_failed_heads", "max_failed_heads_per_revision",
    "max_scope_paths", "max_scope_commands",
}

# C10: typed, named fields for event-time snapshots. Values are primitive
# and bounded; nested dictionaries and lists of objects are never stored.
SAFE_SNAPSHOT_FIELDS = {
    "github_auth_mode", "configured_provider", "observed_runtime_provider",
    "repo_owner", "repo_name", "scope_created_at", "scope_updated_at",
    "team_created_at", "team_display_name", "slot_display_name",
    "issue_number", "pr_number", "issue_type", "artifact", "fact_source",
    "event_time_labels",
    # C06/C12: stable non-secret attempt identities and the retry class.
    "attempt", "launch_attempt", "retry_class",
}

# C10/C03: the typed fields of a human review evidence record.
SAFE_REVIEW_FIELDS = {"fact_kind", "artifact", "version", "actor", "source"}

_MAX_TEXT = 200
_MAX_REASON = 500

# Keys whose values are never stored, whatever their content.
_SECRET_KEY = re.compile(
    r"(?:^|[_\-\s])(?:token|secret|password|passwd|credential|capability|"
    r"api[_\-]?key|authorization|cookie|nonce)(?:$|[_\-\s])",
    re.IGNORECASE)

_SECRET_WORDS = (
    r"token|secret|password|passwd|pwd|credential|credentials|capability[_\-]?hash|"
    r"lease[_\-]?token|api[_\-]?key|access[_\-]?key|private[_\-]?key|authorization|"
    r"cookie|session[_\-]?token|nonce|bearer|basic"
)

# C10: credential-shaped text in free-form values, applied in order. Each
# entry keeps its leading label and replaces only the value.
_REDACTIONS = (
    # Assignment and header forms: "token=x", "password: x", '"secret": "x"',
    # "Authorization: Bearer x".
    # Prefixed names such as "github_token" or "X-Api-Key" count too.
    (re.compile(
        rf"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_\-])*(?:{_SECRET_WORDS})s?)"
        r"([\"']?\s*[:=]\s*)(?:bearer\s+|basic\s+)?[\"']?[^\s\"',;}]+"),
     r"\1\2[redacted]"),
    # Scheme forms without a separator: "Bearer x", "Basic x".
    (re.compile(r"(?i)\b((?:bearer|basic)\s+)[A-Za-z0-9._~+/\-]{8,}=*"),
     r"\1[redacted]"),
    # A credential word followed by any value: "token abc". This is
    # conservative; the next word is redacted even when it is ordinary text.
    (re.compile(
        rf"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_\-])*(?:{_SECRET_WORDS})s?\s+)"
        r"(?!\[redacted\])[^\s\"',;]+"),
     r"\1[redacted]"),
    # Known credential formats.
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"),
     "[redacted]"),
    (re.compile(r"\b(?:xox[abpr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{16,})\b"),
     "[redacted]"),
    # URLs with embedded user information.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"),
     r"\1[redacted]@"),
    # Opaque hex values of 16 or more characters (lease tokens, nonces,
    # digests). A 40-character Git commit SHA is public identity and stays.
    (re.compile(r"\b(?![A-Fa-f0-9]{40}\b)[A-Fa-f0-9]{16,}\b"), "[redacted]"),
    # Long opaque token-like blobs that mix letters and digits. Paths with
    # "/" separators are not matched. A 40-character commit SHA stays.
    (re.compile(
        r"\b(?![A-Fa-f0-9]{40}\b)(?=[A-Za-z0-9+_\-]*\d)(?=[A-Za-z0-9+_\-]*[A-Za-z])"
        r"[A-Za-z0-9+_\-]{40,}={0,2}"),
     "[redacted]"),
)


class AuditWriteError(RuntimeError):
    """An audit write failed; the caller must roll back its own change."""


def sanitize_text(value: str, *, limit: int = _MAX_TEXT) -> str:
    """C10: remove credential-shaped content from one free-text value.

    Keyword forms keep the keyword and redact the value that follows it, so
    ordinary words such as "release" stay readable. Known token formats,
    URL user information and long opaque blobs are redacted wherever they
    appear. The result is bounded.
    """
    cleaned = str(value)
    for pattern, replacement in _REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned[:limit]


def sanitize_reason(reason: str | None) -> str | None:
    """Keep a short sanitized reason with no credential-shaped content."""
    if reason is None:
        return None
    return sanitize_text(str(reason), limit=_MAX_REASON)


def _safe_primitive(value: Any) -> tuple[bool, Any]:
    """Accept only bounded primitives; sanitize text. Returns (keep, value)."""
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return True, value
    if isinstance(value, str):
        return True, sanitize_text(value)
    return False, None


def allowlist_values(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep allowlisted keys with safe primitive values only.

    C10: a value under an allowed key is sanitized too. Nested objects are
    dropped; no arbitrary dictionary is copied into the ledger.
    """
    if not values or not isinstance(values, dict):
        return None
    safe: dict[str, Any] = {}
    for key, value in values.items():
        if key not in SAFE_VALUE_FIELDS or _SECRET_KEY.search(str(key)):
            continue
        keep, projected = _safe_primitive(value)
        if keep:
            safe[key] = projected
    return safe or None


def project_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """C10: a typed, bounded projection of an event-time snapshot."""
    if not snapshot or not isinstance(snapshot, dict):
        return None
    safe: dict[str, Any] = {}
    for key, value in snapshot.items():
        if key not in SAFE_SNAPSHOT_FIELDS:
            continue
        if key == "event_time_labels":
            if isinstance(value, (list, tuple)):
                safe[key] = [
                    label for label in value
                    if isinstance(label, str) and label in SAFE_SNAPSHOT_FIELDS
                ]
            continue
        keep, projected = _safe_primitive(value)
        if keep:
            safe[key] = projected
    return safe or None


def project_review_evidence(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    """C10/C03: a typed projection of a review evidence record."""
    if not evidence or not isinstance(evidence, dict):
        return None
    safe: dict[str, Any] = {}
    for key in SAFE_REVIEW_FIELDS:
        if key in evidence:
            keep, projected = _safe_primitive(evidence[key])
            if keep:
                safe[key] = projected
    return safe or None


def derive_actor(
    *,
    actor_kind: str,
    member_id: int | None = None,
    session_id: int | None = None,
    scheduler: str | None = None,
) -> dict[str, Any]:
    """Derive the recorded actor from actual authentication context.

    ``operator`` records the shared operator credential with no invented
    personal identity. ``member`` records an authenticated member reference.
    ``scheduler`` records the scheduler identity used by scheduled work.
    """
    if actor_kind not in {"operator", "member", "scheduler", "system"}:
        raise ValueError(f"unsupported actor kind: {actor_kind}")
    # C08: client-supplied identity claims are never trusted. The shared
    # operator credential cannot also assert a personal member identity.
    if actor_kind == "operator" and (member_id is not None or session_id is not None):
        raise ValueError("operator_role_cannot_assert_identity")
    reference = None
    if actor_kind == "operator":
        reference = "shared-operator-credential"
    elif actor_kind == "scheduler":
        reference = scheduler
    elif actor_kind == "member" and member_id is not None:
        reference = f"member:{member_id}"
    return {
        "actor_kind": actor_kind,
        "actor_member_id": member_id if actor_kind == "member" else None,
        "actor_session_id": session_id,
        "actor_reference": reference,
    }


async def context_key_for(db: AsyncSession, key_kind: str, numeric_id: int) -> str:
    """Allocate or reuse one immutable context key for a logical identity."""
    existing = (await db.scalars(
        select(FactoryContextKey).where(
            FactoryContextKey.key_kind == key_kind,
            FactoryContextKey.numeric_id == numeric_id,
        ).limit(1)
    )).first()
    if existing is not None:
        return existing.context_key
    key = f"{key_kind}:{numeric_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    db.add(FactoryContextKey(key_kind=key_kind, numeric_id=numeric_id, context_key=key))
    await db.flush()
    return key


def replay_key_for(
    operation_id: str,
    event_kind: str,
    *,
    team_preset_id: int | None = None,
    team_slot_id: int | None = None,
    scope_id: int | None = None,
    item_id: int | None = None,
    revision_id: int | None = None,
    request_id: int | None = None,
) -> str:
    """C07: one replay identity per action and exact resource.

    The same supplied operation id used for different resources produces
    distinct replay keys; cross-resource collisions are impossible.
    """
    resource = "|".join(str(value) for value in (
        team_preset_id, team_slot_id, scope_id, item_id, revision_id, request_id))
    return f"{operation_id}|{event_kind}|{resource}"


async def find_by_operation(
    db: AsyncSession, replay_key: str
) -> FactoryAuditEvent | None:
    """Replay protection: one accepted action or terminal event per identity."""
    return (await db.scalars(
        select(FactoryAuditEvent).where(
            FactoryAuditEvent.replay_key == replay_key,
        ).limit(1)
    )).first()


async def record_event(
    db: AsyncSession,
    *,
    event_kind: str,
    source: str,
    occurred_at: datetime,
    actor: dict[str, Any],
    action_outcome: str | None = None,
    record_kind: str = "observed",
    fact_source: str | None = None,
    fact_time: datetime | None = None,
    team_preset_id: int | None = None,
    team_slot_id: int | None = None,
    scope_id: int | None = None,
    item_id: int | None = None,
    revision_id: int | None = None,
    request_id: int | None = None,
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
    item_context_key: str | None = None,
    context_snapshot: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    operation_id: str | None = None,
    sanitized_reason: str | None = None,
    before_values: dict[str, Any] | None = None,
    after_values: dict[str, Any] | None = None,
    delivery_outcome: str | None = None,
    completion_kind: str | None = None,
    human_review_evidence: dict[str, Any] | None = None,
) -> FactoryAuditEvent:
    """Record one event inside the caller's transaction.

    The caller's transaction must include any audited change. If this insert
    raises, the caller must roll back the change. Replay protection applies
    only when an explicit operation id is supplied; legacy callers keep their
    existing guards and are never blocked by missing ledger state.
    """
    replay_key = None
    if operation_id:
        replay_key = replay_key_for(
            operation_id, event_kind, team_preset_id=team_preset_id,
            team_slot_id=team_slot_id, scope_id=scope_id, item_id=item_id,
            revision_id=revision_id, request_id=request_id)
        existing = await find_by_operation(db, replay_key)
        if existing is not None:
            return existing
    # C05: every event site allocates immutable context keys for any live
    # identity it records. Numeric ID reuse can never reattach old history.
    if team_preset_id is not None and team_context_key is None:
        team_context_key = await context_key_for(db, "team", team_preset_id)
    if scope_id is not None and scope_context_key is None:
        scope_context_key = await context_key_for(db, "scope", scope_id)
    if item_id is not None and item_context_key is None:
        item_context_key = await context_key_for(db, "item", item_id)
    event = FactoryAuditEvent(
        occurred_at=occurred_at,
        event_kind=event_kind,
        source=source,
        record_kind=record_kind,
        fact_source=fact_source,
        fact_time=fact_time,
        actor_kind=actor["actor_kind"],
        actor_member_id=actor.get("actor_member_id"),
        actor_session_id=actor.get("actor_session_id"),
        actor_reference=actor.get("actor_reference"),
        team_preset_id=team_preset_id,
        team_slot_id=team_slot_id,
        scope_id=scope_id,
        item_id=item_id,
        revision_id=revision_id,
        request_id=request_id,
        team_context_key=team_context_key,
        scope_context_key=scope_context_key,
        item_context_key=item_context_key,
        # C10: every stored value passes a typed, bounded projection.
        context_snapshot=project_snapshot(context_snapshot),
        correlation_id=correlation_id,
        operation_id=operation_id,
        replay_key=replay_key,
        sanitized_reason=sanitize_reason(sanitized_reason),
        before_values=allowlist_values(before_values),
        after_values=allowlist_values(after_values),
        action_outcome=action_outcome,
        delivery_outcome=delivery_outcome,
        completion_kind=completion_kind,
        human_review_evidence=project_review_evidence(human_review_evidence),
    )
    # A failed insert, including a concurrent duplicate on the unique replay
    # key, propagates. The caller owns the transaction: the audited change
    # must never commit when its fact did not, and a duplicate winner never
    # stands in for a change that this transaction lost.
    db.add(event)
    await db.flush()
    return event


async def record_observation(db: AsyncSession, **fields: Any) -> FactoryAuditEvent | None:
    """C09: record a refusal or uncertainty in its own observation transaction.

    Use this only after the observed action's own transaction has ended.
    Services roll back their guarded writes before they refuse. Pending ORM
    changes are rolled back here and are never committed with the
    observation. A clean session is not rolled back, so rows the caller still
    reads stay loaded. Observation failure never masks the original result
    and never replays the action.
    """
    if db.new or db.dirty or db.deleted:
        try:
            await db.rollback()
        except Exception:
            pass
    # A failed earlier flush leaves the transaction unusable without pending
    # objects; one retry after rollback records the observation then.
    for attempt in range(2):
        try:
            event = await record_event(db, **fields)
            await db.commit()
            return event
        except Exception:
            try:
                await db.rollback()
            except Exception:
                return None
            if attempt:
                return None
    return None


async def record_observed_snapshot(
    db: AsyncSession,
    *,
    event_kind: str,
    source: str,
    observed_at: datetime,
    actor: dict[str, Any],
    fact_source: str | None = None,
    fact_time: datetime | None = None,
    team_preset_id: int | None = None,
    scope_id: int | None = None,
    item_id: int | None = None,
    context_snapshot: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    after_values: dict[str, Any] | None = None,
    operation_id: str | None = None,
) -> FactoryAuditEvent:
    """A13/A14: record imported current state as an observed snapshot.

    The import observation time is the event occurrence time. A reliable
    external fact keeps its own source and fact time distinct from the
    import time. Unknown historical times remain unavailable and are never
    inferred from generic row timestamps. C12: an operation identity makes
    a repeated import return the existing snapshot.
    """
    return await record_event(
        db,
        event_kind=event_kind,
        source=source,
        occurred_at=observed_at,
        actor=actor,
        record_kind="observed_snapshot",
        fact_source=fact_source,
        fact_time=fact_time,
        team_preset_id=team_preset_id,
        scope_id=scope_id,
        item_id=item_id,
        context_snapshot=context_snapshot,
        correlation_id=correlation_id or operation_id,
        operation_id=operation_id,
        after_values=after_values,
        action_outcome="applied",
    )


# C12: the stable forward-coverage marker. Its migration row time is the
# instrumentation start; it never moves when events are added or removed.
COVERAGE_MARKER = "p05_factory_audit_coverage"

_IMPORT_SOURCE = "factory_audit_service.import_observed_state"


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


async def coverage_marker_time(conn: Any) -> datetime | None:
    """Read the installed coverage marker from a session or connection."""
    table = (await conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table'"
        " AND name = 'deck_compat_migrations'"))).first()
    if table is None:
        return None
    value = (await conn.execute(text(
        "SELECT applied_at FROM deck_compat_migrations WHERE name = :name"),
        {"name": COVERAGE_MARKER})).scalar_one_or_none()
    return _as_datetime(value)


async def install_forward_coverage(
    conn: Any, *, installed_at: datetime | None = None
) -> datetime:
    """C12: install the coverage marker and import observed state once.

    Called from the SQLite compatibility migrations. A second run finds the
    marker and changes nothing. The import records the persisted state of
    each existing work item as an observed snapshot at the marker time; it
    never reconstructs history or infers fact times from row timestamps.
    """
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS deck_compat_migrations ("
        "name VARCHAR PRIMARY KEY, applied_at DATETIME NOT NULL)"))
    existing = await coverage_marker_time(conn)
    if existing is not None:
        return existing
    marker = (installed_at or datetime.utcnow()).replace(tzinfo=None)
    await conn.execute(text(
        "INSERT OR IGNORE INTO deck_compat_migrations (name, applied_at)"
        " VALUES (:name, :applied_at)"),
        {"name": COVERAGE_MARKER, "applied_at": marker})
    marker = await coverage_marker_time(conn) or marker
    await import_observed_state(conn, observed_at=marker)
    return marker


async def import_observed_state(conn: Any, *, observed_at: datetime) -> int:
    """C12: one idempotent observed snapshot per existing work item."""
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    from app.models.database import GithubWorkItem

    actor = derive_actor(actor_kind="system")
    imported = 0
    # The session joins the migration transaction; the caller commits it.
    session = _AsyncSession(bind=conn, expire_on_commit=False, autoflush=False)
    try:
        rows = (await session.execute(select(
            GithubWorkItem.id, GithubWorkItem.scope_id, GithubWorkItem.issue_number,
            GithubWorkItem.issue_type, GithubWorkItem.pr_number,
            GithubWorkItem.dispatch_status, GithubWorkItem.attempt_phase,
            GithubWorkItem.retry_count, GithubWorkItem.diagnostic_retry_count,
            GithubWorkItem.active_scope_revision,
        ).order_by(GithubWorkItem.id))).all()
        for row in rows:
            await record_observed_snapshot(
                session,
                event_kind="work_state_import",
                source=_IMPORT_SOURCE,
                observed_at=observed_at,
                actor=actor,
                fact_source="github_work_items persisted state",
                fact_time=None,
                scope_id=row.scope_id,
                item_id=row.id,
                context_snapshot={"issue_number": row.issue_number,
                                  "issue_type": row.issue_type,
                                  "pr_number": row.pr_number},
                after_values={
                    "dispatch_status": row.dispatch_status,
                    "attempt_phase": row.attempt_phase,
                    "retry_count": row.retry_count,
                    "diagnostic_retry_count": row.diagnostic_retry_count,
                    "active_scope_revision": row.active_scope_revision,
                },
                operation_id=f"{COVERAGE_MARKER}:item:{row.id}",
            )
            imported += 1
        await session.flush()
    finally:
        await session.close()
    return imported


def launch_attempt_key(item_id: int, launch_id: int | None) -> str:
    """C12: the non-secret identity of one launched attempt."""
    return f"item:{item_id}:launch:{launch_id}"


async def record_retry_charge(
    db: AsyncSession,
    *,
    item_id: int,
    scope_id: int | None,
    revision_id: int | None,
    retry_class: str,
    counter_value: int,
    reason_code: str,
    source: str,
) -> FactoryAuditEvent:
    """C12: evidence for one charged retry, in the charge's transaction.

    The counter stays authoritative; this fact only classifies the charge as
    an implementation or diagnostic retry. An audit-write failure surfaces
    and rolls back the charge, like other in-transaction facts.
    """
    if retry_class not in {"implementation", "diagnostic"}:
        raise ValueError(f"unsupported retry class: {retry_class}")
    counter = "diagnostic_retry_count" if retry_class == "diagnostic" else "retry_count"
    return await record_event(
        db,
        event_kind="retry_charge",
        source=source,
        occurred_at=datetime.utcnow(),
        actor=derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler"),
        scope_id=scope_id,
        item_id=item_id,
        revision_id=revision_id,
        after_values={counter: counter_value},
        context_snapshot={"retry_class": retry_class},
        sanitized_reason=reason_code,
        action_outcome="applied",
    )


def validated_review_evidence(evidence: dict | None) -> bool:
    """A33/C03: only validated independent review facts count.

    The evidence must name the review fact kind, the exact design artifact
    and version, an independent human actor (not the shared operator
    credential) and its review source. Absent, JSON-null, empty or partial
    evidence never counts.
    """
    if not isinstance(evidence, dict) or not evidence:
        return False
    if evidence.get("fact_kind") != "human_review_acceptance":
        return False
    if not evidence.get("artifact") or not evidence.get("version"):
        return False
    actor = evidence.get("actor")
    if not isinstance(actor, str) or actor in {"shared-operator-credential", "operator"}:
        return False
    if not evidence.get("source"):
        return False
    return True


async def record_delivery_fact(
    db: AsyncSession,
    *,
    item_id: int | None,
    revision_id: int | None = None,
    scope_id: int | None = None,
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
    delivery_outcome: str,
    completion_kind: str,
    fact_source: str,
    fact_time: datetime | None,
    artifact: str | None = None,
    actor: dict[str, Any] | None = None,
    attempt: str | None = None,
    launch_attempt: str | None = None,
) -> FactoryAuditEvent:
    """A28-A35: record one sourced delivery outcome fact per tracked attempt.

    Later facts reconcile the classification without double-counting
    delivery: the non-secret operation identity binds the fact to the
    attempt and artifact, so repeated evidence returns the same event.
    ``attempt`` is a stable non-secret attempt identity; a later attempt on
    the same item therefore records its own fact. Raw dispatch state is
    never rewritten. Merge evidence and independent human review stay
    distinct fields. C12: ``launch_attempt`` binds the terminal boundary to
    the launch that started the attempt, for same-attempt durations.
    """
    if attempt:
        operation_id = f"delivery:{attempt}:{artifact or 'attempt'}"
    else:
        operation_id = f"delivery:{item_id}:{artifact or 'attempt'}"
    context_snapshot: dict[str, Any] = {}
    if artifact:
        context_snapshot.update({"artifact": artifact, "fact_source": fact_source})
    if attempt:
        context_snapshot["attempt"] = attempt
    if launch_attempt:
        context_snapshot["launch_attempt"] = launch_attempt
    return await record_event(
        db,
        event_kind="delivery_evidence",
        source=fact_source,
        occurred_at=fact_time or datetime.utcnow(),
        actor=actor or derive_actor(actor_kind="scheduler", scheduler="github_watcher"),
        item_id=item_id,
        revision_id=revision_id,
        scope_id=scope_id,
        team_context_key=team_context_key,
        scope_context_key=scope_context_key,
        context_snapshot=context_snapshot or None,
        delivery_outcome=delivery_outcome,
        completion_kind=completion_kind,
        action_outcome="applied",
        operation_id=operation_id,
        correlation_id=operation_id,
        sanitized_reason=f"delivery fact: {completion_kind}",
    )


async def current_delivery_outcome(db: AsyncSession, item_id: int) -> str | None:
    """One current outcome per tracked attempt from its recorded facts.

    Delivered is retained through routine closure. Repeated delivered facts
    never change the count. A later non-delivery fact does not downgrade a
    proven delivery.
    """
    rows = (await db.scalars(
        select(FactoryAuditEvent).where(
            FactoryAuditEvent.item_id == item_id,
            FactoryAuditEvent.event_kind == "delivery_evidence",
        ).order_by(FactoryAuditEvent.occurred_at.asc(), FactoryAuditEvent.id.asc())
    )).all()
    outcome = None
    for row in rows:
        if row.delivery_outcome == "delivered":
            return "delivered"
        outcome = row.delivery_outcome
    return outcome


async def instrumentation_start(db: AsyncSession) -> datetime | None:
    """C12: the installed forward-coverage marker, or None when absent.

    The first event is never the coverage start. Without the marker no
    interval is covered; missing intervals stay unavailable rather than
    reconstructed.
    """
    return await coverage_marker_time(db)
