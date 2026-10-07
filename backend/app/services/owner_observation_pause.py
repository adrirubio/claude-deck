"""Preserve approved work during a bounded observation gap. Never infer progress."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select, update

from app.models.database import (
    AgentPaneBinding, AgentTeamSlot, GithubApprovalRequest, GithubAttemptScopeRevision,
    GithubOwnerObservationPause, GithubWorkItem, GithubWorkspace, MailAgentSession,
    MailPaneLifecycle, MailTeamMember, TeamGithubScope,
)
from app.services import agent_activity_service as activity
from app.services.factory_delivery_policy import effective_policy
from app.services.github_approval_service import github_approval_service
from app.services.agent_mail_service import MCP_HEARTBEAT_TTL_SECONDS

REASON = "owner_observation_unavailable"
_GAPS = {"observation_unavailable", "observation_incomplete", "native_log_unavailable",
         "no_native_event", "history_window_exceeded"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _values(row, omitted=()):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns
            if column.name not in omitted}


def _process_identity(slot, session, workspace):
    """Check actual process lifetime and executable. Read no native transcript."""
    pid, start = workspace.leased_owner_pid, workspace.leased_owner_proc_start
    state, actual = activity._process(pid)
    if actual != start or state in activity._STOPPED_STATES or not session.pid:
        raise ValueError("owner_identity_unavailable")
    auxiliary_state, auxiliary_start = activity._process(session.pid)
    born = activity._process_started_at(auxiliary_start)
    registered = session.created_at.replace(tzinfo=timezone.utc)
    if (auxiliary_state in activity._STOPPED_STATES or born > registered
            or registered > datetime.now(timezone.utc) + timedelta(seconds=5)):
        raise ValueError("owner_generation_unavailable")
    options = slot.launch_options or {}
    if slot.provider in {"claude-code", "codex-cli"} and not activity._canonical_session_id(options.get("session_id")):
        raise ValueError("owner_native_identity_changed")
    if slot.provider == "claude-code":
        from app.services.claude_activity_service import _identity
        if not _identity(pid, options.get("session_id")):
            raise ValueError("owner_native_identity_changed")
    elif slot.provider == "codex-cli":
        native_id = activity._canonical_session_id(options.get("session_id"))
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if (not native_id or Path(os.fsdecode(argv[0])).name != "codex"
                or b"resume" not in argv or native_id.encode() not in argv):
            raise ValueError("owner_native_identity_changed")
    elif slot.provider == "pi-cli":
        from app.services.pi_activity_service import _native_process
        state, _uid = _native_process(session.pid, auxiliary_start, pid, start, session.cwd)
        if state in activity._STOPPED_STATES:
            raise ValueError("owner_native_identity_changed")
    else:
        raise ValueError("owner_provider_unsupported")
    # A process can exit or be replaced during argv inspection.
    final_state, final_start = activity._process(pid)
    auxiliary_state, final_auxiliary_start = activity._process(session.pid)
    if (final_start != start or final_state in activity._STOPPED_STATES
            or final_auxiliary_start != auxiliary_start or auxiliary_state in activity._STOPPED_STATES):
        raise ValueError("owner_identity_changed")
    return auxiliary_start


async def bound_authority(db, scope, item):
    """Capture private authority. Call under the item write lock before mutation."""
    await db.refresh(item)
    await db.refresh(scope)
    if (item.dispatch_status not in {"dispatched", "escalated"} or not item.dispatch_nonce
            or item.handoff_state == "pending" or not scope.enabled):
        raise ValueError("observation_pause_context_changed")
    slot = await db.get(AgentTeamSlot, item.owner_slot_id, populate_existing=True)
    if slot is None or not slot.enabled or slot.preset_id != scope.preset_id:
        raise ValueError("owner_slot_unavailable")
    member = (await db.scalars(select(MailTeamMember).where(
        MailTeamMember.team_preset_id == scope.preset_id, MailTeamMember.team_slot_id == slot.id,
    ).order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).limit(1)
      .execution_options(populate_existing=True))).one_or_none()
    if member is None or member.participant_kind != "team_slot":
        raise ValueError("owner_member_unavailable")
    workspace = (await db.scalars(select(GithubWorkspace).where(
        GithubWorkspace.leased_item_id == item.id).limit(2)
        .execution_options(populate_existing=True))).one_or_none()
    if (workspace is None or workspace.scope_id != scope.id or not workspace.enabled
            or not workspace.lease_token or not workspace.leased_owner_pid
            or not workspace.leased_owner_proc_start):
        raise ValueError("owner_workspace_changed")
    sessions = list((await db.scalars(select(MailAgentSession).where(
        MailAgentSession.member_id == member.id, MailAgentSession.team_preset_id == scope.preset_id,
        MailAgentSession.team_slot_id == slot.id, MailAgentSession.source == "mcp",
        MailAgentSession.closed_at.is_(None), MailAgentSession.mailbox_status == "connected",
        MailAgentSession.capability_token_hash.is_not(None),
    ).order_by(MailAgentSession.id.desc()).limit(257)
      .execution_options(populate_existing=True))).all())
    if not sessions or len(sessions) > 256:
        raise ValueError("owner_generation_unavailable")
    session = sessions[0]
    if (session.provider != slot.provider or session.bound_pane_pid != workspace.leased_owner_pid
            or session.bound_pane_proc_start != workspace.leased_owner_proc_start or not session.cwd
            or Path(session.cwd).resolve() != Path(workspace.path).resolve()
            or not session.last_seen_at or not 0 <= (datetime.utcnow() - session.last_seen_at).total_seconds() <= MCP_HEARTBEAT_TTL_SECONDS):
        raise ValueError("owner_generation_unavailable")
    bindings = list((await db.scalars(select(AgentPaneBinding).where(
        AgentPaneBinding.preset_id == scope.preset_id, AgentPaneBinding.slot_id == slot.id,
    ).execution_options(populate_existing=True))).all())
    if (len(bindings) != 1 or bindings[0].pane_pid != workspace.leased_owner_pid
            or bindings[0].pane_proc_start != workspace.leased_owner_proc_start):
        raise ValueError("owner_binding_changed")
    retired = await db.scalar(select(MailPaneLifecycle.pane_pid).where(
        MailPaneLifecycle.pane_pid == workspace.leased_owner_pid,
        MailPaneLifecycle.pane_proc_start == workspace.leased_owner_proc_start,
        MailPaneLifecycle.retired_at.is_not(None)))
    if retired:
        raise ValueError("owner_binding_retired")
    inputs = await activity._team_inputs(db, scope.preset_id, 256)
    current = [entry for entry in inputs if entry[0] == slot.id]
    if len(current) != 1 or current[0][4] or len(current[0][3]) != 1:
        raise ValueError("owner_binding_ambiguous")
    auxiliary_start = _process_identity(slot, session, workspace)
    revisions = list((await db.scalars(select(GithubAttemptScopeRevision).where(
        GithubAttemptScopeRevision.work_item_id == item.id).order_by(GithubAttemptScopeRevision.id)
        .execution_options(populate_existing=True))).all())
    approvals = list((await db.scalars(select(GithubApprovalRequest).where(
        GithubApprovalRequest.work_item_id == item.id).order_by(GithubApprovalRequest.id)
        .execution_options(populate_existing=True))).all())
    if any(row.status == "pending" for row in approvals):
        raise ValueError("owner_approval_changed")
    if item.active_scope_revision:
        selected = [row for row in revisions if row.dispatch_nonce == item.dispatch_nonce
                    and row.revision == item.active_scope_revision]
        if len(selected) != 1:
            raise ValueError("owner_revision_changed")
        revision = selected[0]
        actual = [row for row in approvals if row.id == revision.approval_request_id]
        if (revision.status != "active" or not revision.approved_at or not revision.delivered_at
                or not revision.acknowledged_at or revision.recovery_checkpoint_stage not in (None, "ack_open")
                or revision.owner_member_id != member.id or revision.owner_slot_id != slot.id
                or revision.phase != item.attempt_phase or revision.expected_workspace_id != workspace.id
                or not github_approval_service.lease_token_matches(workspace.lease_token, revision.expected_lease_token_hash)
                or len(actual) != 1 or actual[0].status != "approved"
                or actual[0].dispatch_nonce != item.dispatch_nonce
                or actual[0].scope_revision_id != revision.id):
            raise ValueError("owner_approval_changed")
    else:
        # Use the dispatch service's canonical initial ACK predicate.
        from app.services.github_dispatch_service import github_dispatch_service
        if not item.ack_received_at or not github_dispatch_service._ack_satisfied(item):
            raise ValueError("owner_ack_missing")
        actual = [row for row in approvals if row.request_kind == "initial_plan"
                  and row.dispatch_nonce == item.dispatch_nonce and row.status == "approved"
                  and row.owner_member_id == member.id]
        if len(actual) != 1:
            raise ValueError("owner_approval_changed")
    data = {"item": _values(item, ("updated_at", "github_updated_at", "issue_title", "issue_url",
                                "dispatch_status", "escalation_reason", "status_note")),
            "scope": _values(scope, ("updated_at", "last_polled_at", "last_poll_error", "auth_state")),
            "slot": _values(slot, ("updated_at",)), "member": _values(member, ("updated_at", "last_seen_at", "last_inbox_checked_at")),
            "session": _values(session, ("last_seen_at", "updated_at")), "workspace": _values(workspace, ("updated_at",)),
            "bindings": [_values(row) for row in bindings], "auxiliary_start": auxiliary_start,
            "revisions": [_values(row) for row in revisions], "approvals": [_values(row) for row in approvals]}
    return _digest(data), workspace, session


async def _lock_item(db, item):
    result = await db.execute(update(GithubWorkItem).where(
        GithubWorkItem.id == item.id, GithubWorkItem.dispatch_nonce == item.dispatch_nonce,
        GithubWorkItem.active_scope_revision == item.active_scope_revision,
        GithubWorkItem.dispatch_status == item.dispatch_status,
    ).values(updated_at=GithubWorkItem.updated_at).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ValueError("observation_pause_context_changed")


async def handle_observation_gap(db, scope, item):
    """Called after the existing nudge grace. Return True only for a recorded wait/pause."""
    policy = effective_policy(item, scope)
    if policy.owner_observation_wait_seconds is None or policy.owner_contact != "native":
        return False
    inspected = False
    try:
        expected, _workspace, _session = await bound_authority(db, scope, item)
        inspected = True
        try:
            values = await asyncio.wait_for(activity.observe_private_team(db, scope.preset_id, 256), timeout=2)
            observed = values.get(item.owner_slot_id)
            gap = observed is not None and observed.state == "unknown" and observed.reason in _GAPS
        except (TimeoutError, OSError, ValueError):
            gap = True  # Identity must still pass the independent bound checks below.
        await _lock_item(db, item)
        current, _workspace, _session = await bound_authority(db, scope, item)
        if current != expected or item.dispatch_status != "dispatched":
            raise ValueError("observation_pause_context_changed")
        if not gap:
            return False
        nudge = item.continuation_nudged_at if item.active_scope_revision else item.last_nudge_at
        if nudge is None:
            raise ValueError("observation_pause_nudge_missing")
        key = _digest([item.id, item.dispatch_nonce, item.active_scope_revision, nudge])
        record = await db.scalar(select(GithubOwnerObservationPause).where(GithubOwnerObservationPause.wait_key == key))
        now = datetime.utcnow()
        if record is None:
            record = GithubOwnerObservationPause(work_item_id=item.id, wait_key=key, authority_sha256=current,
                deadline=now + timedelta(seconds=policy.owner_observation_wait_seconds))
            db.add(record)
        elif record.status != "waiting" or record.authority_sha256 != current:
            return False
        elif now >= record.deadline:
            record.status = "paused"
            record.paused_at = now
            record.resume_deadline = now + timedelta(seconds=policy.owner_observation_resume_seconds)
            item.dispatch_status = "escalated"
            item.escalation_reason = REASON
            item.status_note = "Native observation is unavailable. The approved owner is preserved. Inspect the recorded observation pause before resuming."
            item.updated_at = now
        await db.commit()
        if record.status == "paused" and record.notice_status == "pending":
            from app.services.github_dispatch_service import github_dispatch_service
            # Persist first. A failed external notice must not roll back the pause.
            try:
                await github_dispatch_service.notify_team(db, item=item,
                    subject=f"Observation pause: issue #{item.issue_number}",
                    body_markdown=(f"Observation pause {record.id} preserves the approved owner and finite budgets. "
                        "The operator must inspect this recorded pause. Use the observation-pause API for current details. "
                        "Do not restart, retry or propose new authority. Publish the operator action in the main issue."),
                    payload={"kind": "github_owner_observation_pause", "work_item_id": item.id, "pause_id": record.id})
                record.notice_status = "sent"
            except Exception:
                await db.rollback()
                await db.refresh(record)
                # Rollback expires ORM rows. Restore callers' loaded context before return.
                for row in list(db.identity_map.values()):
                    if row is not record:
                        await db.refresh(row)
                record.notice_status = "uncertain"
            await db.commit()
        return True
    except (OSError, ValueError):
        # Checks and the item lock do not change authority. The enclosing monitor
        # owns this transaction; avoid expiring its rows with a read-only rollback.
        # The enclosing monitor must not escalate a context changed during its await.
        return inspected


async def resume_observation_pause(db, item, scope, pause_id, reason):
    """An operator resumes only the unchanged recorded pause. No new approval is created."""
    record = await db.get(GithubOwnerObservationPause, pause_id, populate_existing=True)
    if record is None or record.work_item_id != item.id:
        raise ValueError("observation_pause_not_found")
    if record.status == "resumed":
        if record.operator_reason != reason:
            raise ValueError("observation_resume_replay_conflict")
        return {"pause_id": record.id, "status": "already_resumed"}
    if (record.status != "paused" or record.resume_deadline is None
            or datetime.utcnow() >= record.resume_deadline
            or item.dispatch_status != "escalated" or item.escalation_reason != REASON):
        raise ValueError("observation_pause_not_resumable")
    await _lock_item(db, item)
    await db.refresh(record)
    current, _workspace, _session = await bound_authority(db, scope, item)
    if (record.status != "paused" or current != record.authority_sha256
            or item.dispatch_status != "escalated" or item.escalation_reason != REASON
            or record.resume_deadline is None or datetime.utcnow() >= record.resume_deadline):
        raise ValueError("observation_pause_context_changed")
    now = datetime.utcnow()
    record.status = "resumed"
    record.resumed_at = now
    record.operator_reason = reason
    item.dispatch_status = "dispatched"
    item.escalation_reason = None
    item.status_note = "The operator resumed the unchanged observation pause. Approved scope and budgets remain."
    # A bounded new nudge grace is an operator recovery interval, not agent progress.
    if item.active_scope_revision:
        item.continuation_nudged_at = now
    else:
        item.last_nudge_at = now
    item.updated_at = now
    await db.commit()
    return {"pause_id": record.id, "status": "resumed", "resumed_at": now.isoformat()}
