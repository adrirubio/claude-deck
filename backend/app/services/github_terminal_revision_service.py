"""Finish terminal attempt revisions. Maintenance never grants new authority."""
from datetime import datetime
import hashlib
import json

from sqlalchemy import String, cast, exists, inspect, select, update

from app.models.api_model import format_utc_time
from app.models.database import (
    FactoryAuditEvent, GithubAttemptScopeRevision, GithubMaintenanceEvent, GithubWorkItem, TeamGithubScope,
)
from app.services import factory_audit_service as audit

TERMINAL_ITEMS = ("merged", "completed", "closed", "cancelled", "withdrawn")
TERMINAL_REVISIONS = ("completed", "cancelled", "rejected", "exhausted", "expired", "superseded")
REPORT_LIMIT = 100


class TerminalRevisionContextChanged(ValueError):
    """The terminal transition no longer owns its captured attempt."""


def _same(column, value):
    return column.is_(None) if value is None else column == value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _values(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _current(item, revision):
    return item.dispatch_nonce == revision.dispatch_nonce and item.active_scope_revision == revision.revision


def _outcome(item, revision):
    return "completed" if _current(item, revision) and revision.status in {"active", "submitted"} else "superseded"


async def lock_terminal_transition(db, item):
    """Hold the item writer with the original attempt identity before terminal facts."""
    conditions = [GithubWorkItem.id == item.id]
    state = inspect(item)
    for name in ("scope_id", "created_at", "dispatch_status", "dispatch_nonce", "launch_id",
                 "owner_slot_id", "active_scope_revision", "pr_number", "dispatch_head_ref"):
        history = state.attrs[name].history
        # An unloaded nullable field has no previous value in ORM history.
        # Its first local assignment may claim only a persisted NULL value.
        if history.deleted:
            original = history.deleted[0]
        elif history.added:
            original = None
        else:
            original = getattr(item, name)
        if name == "created_at" and original is not None:
            # SQLite accepts timestamps with or without explicit zero microseconds.
            conditions.append(cast(GithubWorkItem.created_at, String).in_(
                (original.isoformat(" "), original.isoformat(" ", timespec="microseconds"))))
        else:
            conditions.append(_same(getattr(GithubWorkItem, name), original))
    with db.no_autoflush:
        claim = await db.execute(update(GithubWorkItem).where(*conditions)
            .values(updated_at=GithubWorkItem.updated_at).execution_options(synchronize_session=False))
    if claim.rowcount != 1:
        raise TerminalRevisionContextChanged("terminal_revision_context_changed")


async def complete_current_revision(db, item, *, source, terminal_status):
    """End only this attempt's current revision in the caller's terminal transaction."""
    await db.flush()
    revision = await db.scalar(select(GithubAttemptScopeRevision).where(
        GithubAttemptScopeRevision.work_item_id == item.id,
        GithubAttemptScopeRevision.dispatch_nonce == item.dispatch_nonce,
        GithubAttemptScopeRevision.revision == item.active_scope_revision,
        GithubAttemptScopeRevision.status.not_in(TERMINAL_REVISIONS),
    ).execution_options(populate_existing=True))
    if revision is None:
        return
    outcome = _outcome(item, revision)
    now = datetime.utcnow()
    statement = update(GithubAttemptScopeRevision).where(
        GithubAttemptScopeRevision.id == revision.id,
        GithubAttemptScopeRevision.status == revision.status,
        exists().where(
            GithubWorkItem.id == item.id, GithubWorkItem.dispatch_status == terminal_status,
            _same(GithubWorkItem.dispatch_nonce, item.dispatch_nonce),
            GithubWorkItem.active_scope_revision == revision.revision,
            _same(GithubWorkItem.launch_id, item.launch_id),
        ),
    ).execution_options(synchronize_session=False)
    if outcome == "completed":
        statement = statement.values(status="completed", completed_at=now)
    else:
        statement = statement.values(status="superseded", cancelled_at=now,
            cancellation_reason="The work item reached a terminal state.")
    claim = await db.execute(statement)
    if claim.rowcount != 1:
        raise TerminalRevisionContextChanged("terminal_revision_context_changed")
    await audit.record_revision_outcome(db, item_id=item.id, revision_id=revision.id, status=outcome, source=source)
    await db.refresh(revision)


async def terminal_revision_report(db, preset_id):
    """Read bounded inconsistent rows. Return no nonce, lease or private configuration."""
    rows = (await db.execute(select(GithubWorkItem, GithubAttemptScopeRevision, TeamGithubScope)
        .join(GithubAttemptScopeRevision, GithubAttemptScopeRevision.work_item_id == GithubWorkItem.id)
        .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
        .where(TeamGithubScope.preset_id == preset_id, GithubWorkItem.dispatch_status.in_(TERMINAL_ITEMS),
               GithubAttemptScopeRevision.status.not_in(TERMINAL_REVISIONS))
        .order_by(GithubWorkItem.id, GithubAttemptScopeRevision.id).limit(REPORT_LIMIT + 1)
        .execution_options(populate_existing=True))).all()
    return {"revisions": [{"work_item_id": item.id, "issue_number": item.issue_number,
        "dispatch_status": item.dispatch_status, "revision_id": revision.id, "revision": revision.revision,
        "revision_status": revision.status, "current_attempt": _current(item, revision),
        "proposed_status": _outcome(item, revision),
        "context_sha256": _digest([_values(item), _values(revision), _values(scope)])}
        for item, revision, scope in rows[:REPORT_LIMIT]], "truncated": len(rows) > REPORT_LIMIT,
        "updated_at": format_utc_time(datetime.utcnow()),
        "limits": "Read-only report. Reconcile one inspected row explicitly. No retry, lease, approval, merge or delivery authority."}


async def reconcile_terminal_revision(db, item, revision_id, expected_context, operation_id, reason):
    """Apply one operator decision after a full context check under the item writer."""
    item_id = item.id
    operation = f"terminal_revision_reconcile:{operation_id}"
    request_digest = _digest([item_id, revision_id, expected_context, reason])
    old = await db.scalar(select(FactoryAuditEvent).where(FactoryAuditEvent.operation_id == operation))
    if old is not None:
        if old.item_id != item_id or old.revision_id != revision_id or old.correlation_id != request_digest:
            raise ValueError("terminal_revision_replay_conflict")
        return {"status": "already_reconciled", "revision_id": revision_id}
    await lock_terminal_transition(db, item)
    await db.refresh(item)
    revision = await db.get(GithubAttemptScopeRevision, revision_id, populate_existing=True)
    scope = await db.get(TeamGithubScope, item.scope_id, populate_existing=True)
    if (revision is None or scope is None or revision.work_item_id != item_id
            or item.dispatch_status not in TERMINAL_ITEMS or revision.status in TERMINAL_REVISIONS
            or _digest([_values(item), _values(revision), _values(scope)]) != expected_context):
        raise ValueError("terminal_revision_context_changed")
    before = revision.status
    outcome = _outcome(item, revision)
    revision.status = outcome
    if outcome == "completed":
        revision.completed_at = datetime.utcnow()
    else:
        revision.cancelled_at = datetime.utcnow()
        revision.cancellation_reason = "The operator reconciled a revision on a terminal work item."
    # The existing maintenance table gives the request a global unique key.
    # A concurrent use of this key rolls back both the revision and its audit.
    db.add(GithubMaintenanceEvent(operation_id=operation, work_item_id=item_id,
        outcome="terminal_revision_reconciled", request_sha256=request_digest))
    await audit.record_revision_outcome(db, item_id=item_id, revision_id=revision.id, status=outcome,
        source="factory_maintenance.reconcile_terminal_revision", actor=audit.derive_actor(actor_kind="operator"),
        operation_id=operation, correlation_id=request_digest, before_values={"status": before},
        sanitized_reason=audit.sanitize_reason(reason))
    await db.commit()
    return {"status": "reconciled", "revision_id": revision_id, "revision_status": outcome}
