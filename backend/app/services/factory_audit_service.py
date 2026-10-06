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
}

# Value shapes that must never appear in ledger content.
_FORBIDDEN_VALUE = re.compile(
    r"(token|secret|password|credential|capability_hash|lease)", re.IGNORECASE)


class AuditWriteError(RuntimeError):
    """An audit write failed; the caller must roll back its own change."""


def sanitize_reason(reason: str | None) -> str | None:
    """Keep a short sanitized reason with no credential-shaped content."""
    if reason is None:
        return None
    cleaned = _FORBIDDEN_VALUE.sub("[redacted]", str(reason))
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


async def find_by_operation(
    db: AsyncSession, operation_id: str, event_kind: str
) -> FactoryAuditEvent | None:
    """Replay protection: one accepted action or terminal event per operation."""
    return (await db.scalars(
        select(FactoryAuditEvent).where(
            FactoryAuditEvent.operation_id == operation_id,
            FactoryAuditEvent.event_kind == event_kind,
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
    if operation_id:
        existing = await find_by_operation(db, operation_id, event_kind)
        if existing is not None:
            return existing
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
        sanitized_reason=sanitize_reason(sanitized_reason),
        before_values=allowlist_values(before_values),
        after_values=allowlist_values(after_values),
        action_outcome=action_outcome,
        delivery_outcome=delivery_outcome,
        completion_kind=completion_kind,
        human_review_evidence=human_review_evidence,
    )
    db.add(event)
    await db.flush()
    return event
