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

from sqlalchemy import select
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
    "recovery_checkpoint_stage",
    # C11: typed finite continuation policy settings.
    "continuation_enabled", "max_continuation_revisions",
    "max_continuation_failed_heads", "max_failed_heads_per_revision",
    "max_scope_paths", "max_scope_commands",
}

# Value shapes that must never appear in ledger content.
_FORBIDDEN_VALUE = re.compile(
    r"(token|secret|password|credential|capability_hash|lease)", re.IGNORECASE)


class AuditWriteError(RuntimeError):
    """An audit write failed; the caller must roll back its own change."""


_CREDENTIAL_SEGMENT = re.compile(
    r"(?:token|secret|password|credential|capability_hash|lease)\S*\s+\S+",
    re.IGNORECASE)


def sanitize_reason(reason: str | None) -> str | None:
    """Keep a short sanitized reason with no credential-shaped content.

    Credential-shaped keywords remove the keyword and the value token that
    follows it.
    """
    if reason is None:
        return None
    cleaned = _CREDENTIAL_SEGMENT.sub("[redacted]", str(reason))
    cleaned = _FORBIDDEN_VALUE.sub("[redacted]", cleaned)
    return cleaned[:500]


def allowlist_values(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep only allowlisted keys and refuse credential-shaped values."""
    if not values:
        return None
    safe: dict[str, Any] = {}
    for key, value in values.items():
        if key not in SAFE_VALUE_FIELDS:
            continue
        if isinstance(value, str) and _FORBIDDEN_VALUE.search(key):
            continue
        safe[key] = value
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
        context_snapshot=context_snapshot,
        correlation_id=correlation_id,
        operation_id=operation_id,
        replay_key=replay_key,
        sanitized_reason=sanitize_reason(sanitized_reason),
        before_values=allowlist_values(before_values),
        after_values=allowlist_values(after_values),
        action_outcome=action_outcome,
        delivery_outcome=delivery_outcome,
        completion_kind=completion_kind,
        human_review_evidence=human_review_evidence,
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
) -> FactoryAuditEvent:
    """A13/A14: record imported current state as an observed snapshot.

    The import observation time is the event occurrence time. A reliable
    external fact keeps its own source and fact time distinct from the
    import time. Unknown historical times remain unavailable and are never
    inferred from generic row timestamps.
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
        correlation_id=correlation_id,
        after_values=after_values,
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
) -> FactoryAuditEvent:
    """A28-A35: record one sourced delivery outcome fact per tracked attempt.

    Later facts reconcile the classification without double-counting
    delivery: the non-secret operation identity binds the fact to the
    attempt and artifact, so repeated evidence returns the same event.
    ``attempt`` is a stable non-secret attempt identity; a later attempt on
    the same item therefore records its own fact. Raw dispatch state is
    never rewritten. Merge evidence and independent human review stay
    distinct fields.
    """
    if attempt:
        operation_id = f"delivery:{attempt}:{artifact or 'attempt'}"
    else:
        operation_id = f"delivery:{item_id}:{artifact or 'attempt'}"
    context_snapshot = None
    if artifact:
        context_snapshot = {"artifact": artifact, "fact_source": fact_source}
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
        context_snapshot=context_snapshot,
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
    """Earliest recorded_at in the ledger: the instrumentation start marker.

    Reads expose this as the coverage start. Events before it do not exist;
    missing intervals stay unavailable rather than reconstructed.
    """
    from sqlalchemy import func
    return (await db.execute(
        select(func.min(FactoryAuditEvent.recorded_at))
    )).scalar_one_or_none()
