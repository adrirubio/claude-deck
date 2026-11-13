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


async def _review_context(db, item, *, revision_number, dispatch_nonce, head_sha, reviewer_member_id, actor=None):
    """Bind a negative disposition to current independent assignment and source."""
    import re
    from app.models.database import GithubRequiredCheckWatch
    from app.services.github_approval_service import github_approval_service as approval, GithubApprovalError
    from app.services.github_ci_watch_service import github_ci_watch_service as watches, _digest as policy_digest
    from app.services.factory_delivery_policy import effective_policy
    scope = await db.get(TeamGithubScope, item.scope_id)
    context, owner, leader, workspace = await approval.healthy_scope_context(db, item, scope)
    await approval.bind_actor_session(db, context, actor)
    if (dispatch_nonce != context['dispatch_nonce'] or revision_number != context['active_scope_revision']
            or not isinstance(head_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', head_sha)):
        raise GithubApprovalError('stale_revision_review')
    revision = await db.scalar(select(GithubAttemptScopeRevision).where(
        GithubAttemptScopeRevision.work_item_id == item.id,
        GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
        GithubAttemptScopeRevision.revision == revision_number))
    if (not revision or revision.status != 'submitted' or revision.phase != 'implementation'
            or revision.owner_member_id != owner.id or revision.owner_slot_id != owner.team_slot_id
            or revision.submitted_head_sha != head_sha or revision.expected_workspace_id != workspace.id
            or revision.expected_lease_token_hash != approval.lease_token_hash(workspace.lease_token)):
        raise GithubApprovalError('submitted_revision_required')
    watch = await db.scalar(select(GithubRequiredCheckWatch).where(
        GithubRequiredCheckWatch.work_item_id == item.id,
        GithubRequiredCheckWatch.dispatch_nonce == dispatch_nonce,
        GithubRequiredCheckWatch.scope_revision == revision_number,
        GithubRequiredCheckWatch.head_sha == head_sha))
    if (not watch or watch.pr_number != context['pr_number'] or watch.owner_slot_id != owner.team_slot_id
            or watch.reviewer_member_id != reviewer_member_id or reviewer_member_id == owner.id
            or watch.policy_digest != policy_digest(effective_policy(item, scope))):
        raise GithubApprovalError('current_independent_reviewer_required', status_code=403)
    try:
        await watches._reviewer(db, context, reviewer_member_id)
    except ValueError as exc:
        raise GithubApprovalError('current_independent_reviewer_required', status_code=403) from exc
    from app.models.database import MailTeamMember
    reviewer = await db.get(MailTeamMember, reviewer_member_id)
    context['reviewer_binding'] = (reviewer.id, reviewer.team_slot_id)
    context['review_watch'] = _values(watch)
    context['review_revision'] = _values(revision)
    await _read_review_head(scope, context, head_sha)
    await _claim_review_context(db, context)
    return context, revision, watch, leader


async def _read_review_head(scope, context, head_sha):
    from app.services.github_approval_service import github_approval_service as approval, GithubApprovalError
    from app.services.github_client import github_client
    pull = await github_client.get_pull(scope.repo_owner, scope.repo_name, context['pr_number'],
        token=await approval.github_read_token(scope))
    head, base = pull.get('head') or {}, pull.get('base') or {}
    if (pull.get('number') != context['pr_number'] or pull.get('state') != 'open' or pull.get('merged_at')
            or head.get('sha') != head_sha or head.get('ref') != context['dispatch_head_ref']
            or (head.get('repo') or {}).get('full_name') != f"{scope.repo_owner}/{scope.repo_name}"
            or (context['dispatch_base_ref'] and base.get('ref') != context['dispatch_base_ref'])):
        raise GithubApprovalError('revision_review_head_changed')


def _review_conditions(context):
    from sqlalchemy import and_, or_
    from sqlalchemy.orm import aliased
    from app.models.database import AgentTeamSlot, MailTeamMember, GithubRequiredCheckWatch
    from app.services.github_approval_service import github_approval_service as approval
    member, newer = aliased(MailTeamMember), aliased(MailTeamMember)
    reviewer, slot = context['reviewer_binding']
    return [*approval.healthy_scope_conditions(context),
        exists(select(member.id).join(AgentTeamSlot, AgentTeamSlot.id == member.team_slot_id).where(
            member.id == reviewer, member.team_slot_id == slot, member.team_preset_id == context['team_id'],
            member.participant_kind == 'team_slot', AgentTeamSlot.preset_id == context['team_id'],
            AgentTeamSlot.enabled.is_(True),
            ~exists(select(newer.id).where(newer.team_slot_id == slot,
                or_(newer.updated_at > member.updated_at,
                    and_(newer.updated_at == member.updated_at, newer.id > member.id)))))),
        exists(select(GithubRequiredCheckWatch.id).where(*(
            _same(getattr(GithubRequiredCheckWatch, key), value)
            for key, value in context['review_watch'].items()))),
        exists(select(GithubAttemptScopeRevision.id).where(*(
            _same(getattr(GithubAttemptScopeRevision, key), value)
            for key, value in context['review_revision'].items())))]


async def _claim_review_context(db, context):
    from app.services.github_approval_service import github_approval_service as approval, GithubApprovalError
    from app.services.github_coordination_service import hold_code
    await approval.require_bound_actor_session(db, context)
    result = await db.execute(update(GithubWorkItem).where(*_review_conditions(context))
        .values(updated_at=GithubWorkItem.updated_at).execution_options(synchronize_session=False))
    if result.rowcount != 1 or hold_code():
        await db.rollback()
        raise GithubApprovalError('stale_revision_review')


async def record_revision_review(db, item, *, revision_number, dispatch_nonce, head_sha,
                                 reviewer_member_id, verdict, summary, evidence_url, actor=None):
    from urllib.parse import urlsplit
    from app.models.database import GithubRevisionReview
    from app.services.github_approval_service import GithubApprovalError, github_approval_service as approval
    if verdict != 'changes_required' or not summary.strip():
        raise GithubApprovalError('negative_structured_review_required', status_code=400)
    scope = await db.get(TeamGithubScope, item.scope_id)
    url = urlsplit(evidence_url)
    if (url.scheme != 'https' or url.netloc != 'github.com' or url.username or url.password
            or url.path != f'/{scope.repo_owner}/{scope.repo_name}/pull/{item.pr_number}'
            or not url.fragment.startswith('pullrequestreview-')):
        raise GithubApprovalError('revision_review_evidence_invalid', status_code=400)
    context, revision, watch, _ = await _review_context(db, item, revision_number=revision_number,
        dispatch_nonce=dispatch_nonce, head_sha=head_sha, reviewer_member_id=reviewer_member_id, actor=actor)
    active = list((await db.scalars(select(GithubRevisionReview).where(
        GithubRevisionReview.revision_id == revision.id, GithubRevisionReview.status == 'active'))).all())
    for row in active:
        if (row.reviewer_member_id == reviewer_member_id and row.head_sha == head_sha
                and row.summary == summary.strip() and row.evidence_url == evidence_url):
            return row
        row.status, row.ended_at = 'superseded', datetime.utcnow()
    fact = GithubRevisionReview(work_item_id=item.id, revision_id=revision.id, watch_id=watch.id,
        dispatch_nonce=dispatch_nonce, head_sha=head_sha, reviewer_member_id=reviewer_member_id,
        expected_lease_token_hash=approval.lease_token_hash(context['lease_token']), verdict=verdict,
        summary=summary.strip(), evidence_url=evidence_url)
    db.add(fact)
    await db.flush()
    await _review_audit(db, item, revision, fact, 'recorded', actor, reviewer_member_id)
    await _claim_review_context(db, context)
    await db.commit()
    return fact


async def withdraw_revision_review(db, item, *, review_id, reviewer_member_id, dispatch_nonce, actor=None):
    from app.models.database import GithubRevisionReview
    from app.services.github_approval_service import GithubApprovalError
    fact = await db.get(GithubRevisionReview, review_id, populate_existing=True)
    if (not fact or fact.work_item_id != item.id or fact.reviewer_member_id != reviewer_member_id
            or fact.dispatch_nonce != dispatch_nonce or item.dispatch_nonce != dispatch_nonce):
        raise GithubApprovalError('review_disposition_not_owned', status_code=403)
    context, revision, _, _ = await _review_context(db, item, revision_number=item.active_scope_revision,
        dispatch_nonce=dispatch_nonce, head_sha=fact.head_sha, reviewer_member_id=reviewer_member_id, actor=actor)
    if fact.status == 'withdrawn':
        return fact
    result = await db.execute(update(GithubRevisionReview).where(
        GithubRevisionReview.id == fact.id, GithubRevisionReview.status == 'active')
        .values(status='withdrawn', ended_at=datetime.utcnow()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise GithubApprovalError('review_disposition_not_active')
    await _review_audit(db, item, revision, fact, 'withdrawn', actor, reviewer_member_id)
    await _claim_review_context(db, context)
    await db.commit()
    await db.refresh(fact)
    return fact


async def end_submitted_revision(db, item, *, review_id, leader_member_id, dispatch_nonce, reason, actor=None):
    from app.models.database import GithubRevisionReview
    from app.services.github_approval_service import GithubApprovalError, github_approval_service as approval
    fact = await db.get(GithubRevisionReview, review_id, populate_existing=True)
    if (not fact or fact.work_item_id != item.id or fact.dispatch_nonce != dispatch_nonce
            or fact.verdict != 'changes_required' or not reason.strip()):
        raise GithubApprovalError('current_negative_review_required')
    if fact.status == 'consumed':
        scope = await db.get(TeamGithubScope, item.scope_id)
        context, _, leader, _ = await approval.healthy_scope_context(db, item, scope)
        await approval.bind_actor_session(db, context, actor)
        revision = await db.get(GithubAttemptScopeRevision, fact.revision_id, populate_existing=True)
        if (leader.id != leader_member_id or fact.settled_by_member_id != leader.id
                or fact.settlement_reason != reason.strip() or item.dispatch_nonce != dispatch_nonce
                or fact.expected_lease_token_hash != approval.lease_token_hash(context['lease_token'])
                or not revision or revision.status != 'superseded' or not revision.completed_at):
            raise GithubApprovalError('current_leader_and_review_required', status_code=403)
        await approval.claim_healthy_scope_context(db, context)
        return revision
    if fact.status != 'active':
        raise GithubApprovalError('current_negative_review_required')
    fact_values = _values(fact)
    context, revision, _, leader = await _review_context(db, item, revision_number=item.active_scope_revision,
        dispatch_nonce=dispatch_nonce, head_sha=fact.head_sha, reviewer_member_id=fact.reviewer_member_id, actor=actor)
    if (leader.id != leader_member_id or fact.revision_id != revision.id
            or fact.watch_id != context['review_watch']['id']
            or fact.expected_lease_token_hash != approval.lease_token_hash(context['lease_token'])):
        raise GithubApprovalError('current_leader_and_review_required', status_code=403)
    scope = await db.get(TeamGithubScope, item.scope_id)
    await _read_review_head(scope, context, fact.head_sha)
    await _claim_review_context(db, context)
    consumed = await db.execute(update(GithubRevisionReview).where(*(
        _same(getattr(GithubRevisionReview, key), value) for key, value in fact_values.items()))
        .values(status='consumed', ended_at=datetime.utcnow(), settled_by_member_id=leader_member_id,
                settlement_reason=reason.strip()).execution_options(synchronize_session=False))
    if consumed.rowcount != 1:
        await db.rollback()
        raise GithubApprovalError('stale_revision_review')
    await db.execute(update(GithubAttemptScopeRevision).where(GithubAttemptScopeRevision.id == revision.id)
        .values(status='superseded', completed_at=datetime.utcnow()).execution_options(synchronize_session=False))
    await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(
        dispatch_status='dispatched', escalation_reason=None, ack_received_at=None,
        status_note='Submitted revision ended after current independent CHANGES REQUIRED and Leader settlement. '
                    'Source work is stopped. A fresh bounded amendment, approval and owner acknowledgement are required.')
        .execution_options(synchronize_session=False))
    context['dispatch_status'], context['ack_received_at'] = 'dispatched', None
    context['review_revision']['status'] = 'superseded'
    # The completion timestamp is part of the exact revision fence.
    await db.refresh(revision)
    context['review_revision'] = _values(revision)
    await _review_audit(db, item, revision, fact, 'settled', actor, leader_member_id, reason=reason.strip())
    await _claim_review_context(db, context)
    await db.commit()
    await db.refresh(item)
    return revision


async def _review_audit(db, item, revision, fact, outcome, actor, member_id, reason=None):
    await audit.record_event(db, event_kind='revision_review', source='github_terminal_revision_service',
        occurred_at=datetime.utcnow(), actor=actor or audit.derive_actor(actor_kind='member', member_id=member_id),
        record_kind='action', action_outcome='applied', item_id=item.id, revision_id=revision.id,
        sanitized_reason=f'Negative review {outcome}' + (f': {reason}' if reason else ''),
        after_values={'review_id': fact.id, 'head_sha': fact.head_sha, 'verdict': fact.verdict,
                      'reviewer_member_id': fact.reviewer_member_id, 'outcome': outcome})
