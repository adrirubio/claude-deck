"""Fresh native work renews contact only for an unchanged, unexpired owner."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import settings
from app.models.database import (
    AgentPaneBinding, AgentTeamSlot, GithubAttemptScopeRevision, GithubWorkItem,
    GithubWorkspace, MailAgentSession, MailPaneLifecycle, MailTeamMember, TeamGithubScope,
)
from app.services import agent_activity_service as activity
from app.services.factory_delivery_policy import effective_policy
from app.services.github_approval_service import github_approval_service


async def renew_native_owner_contact(db: AsyncSession, scope: TeamGithubScope,
                                     item: GithubWorkItem,
                                     workspace: GithubWorkspace | None,
                                     revision: GithubAttemptScopeRevision | None = None) -> bool:
    policy = effective_policy(item, scope)
    if (policy.owner_contact != "native" or item.dispatch_status != "dispatched"
            or not item.dispatch_nonce or workspace is None or not workspace.lease_token
            or workspace.leased_item_id != item.id or workspace.scope_id != scope.id
            or not workspace.enabled or not workspace.leased_owner_pid
            or not workspace.leased_owner_proc_start):
        return False
    if item.active_scope_revision:
        if (revision is None or revision.status != "active" or not revision.acknowledged_at
                or revision.work_item_id != item.id or revision.revision != item.active_scope_revision
                or revision.phase != item.attempt_phase
                or revision.dispatch_nonce != item.dispatch_nonce
                or revision.owner_slot_id != item.owner_slot_id
                or revision.expected_workspace_id != workspace.id
                or not github_approval_service.lease_token_matches(
                    workspace.lease_token, revision.expected_lease_token_hash)):
            return False
        activated = item.continuation_activated_at
        nudge = item.continuation_nudged_at
    else:
        if not item.ack_received_at:
            return False
        activated = item.dispatched_at
        nudge = item.last_nudge_at
    anchors = [value for value in (activated, workspace.lease_last_owner_contact_at) if value]
    if not anchors:
        return False
    anchor = max(anchors)
    now = datetime.utcnow()
    idle = policy.owner_idle_seconds or settings.github_owner_idle_timeout_seconds
    grace = policy.owner_nudge_grace_seconds or settings.github_nudge_grace_seconds
    # A new event cannot revive work that already passed its idle and grace limit.
    if now - anchor > timedelta(seconds=idle + grace) or (
        nudge is not None and nudge >= anchor and now - nudge > timedelta(seconds=grace)
    ):
        return False
    slot = await db.get(AgentTeamSlot, item.owner_slot_id)
    if slot is None or not slot.enabled or slot.preset_id != scope.preset_id:
        return False
    owner = (await db.execute(select(MailTeamMember).where(
        MailTeamMember.team_slot_id == slot.id, MailTeamMember.team_preset_id == scope.preset_id,
    ).order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).limit(1))).scalar_one_or_none()
    if owner is None or (revision is not None and revision.owner_member_id != owner.id):
        return False
    session = (await db.execute(select(MailAgentSession).where(
        MailAgentSession.member_id == owner.id,
        MailAgentSession.team_preset_id == scope.preset_id,
        MailAgentSession.team_slot_id == slot.id,
        MailAgentSession.provider == slot.provider,
        MailAgentSession.source == "mcp", MailAgentSession.closed_at.is_(None),
        MailAgentSession.mailbox_status == "connected",
        MailAgentSession.capability_token_hash.is_not(None),
    ).order_by(MailAgentSession.id.desc()).limit(1))).scalar_one_or_none()
    if (session is None or session.bound_pane_pid != workspace.leased_owner_pid
            or session.bound_pane_proc_start != workspace.leased_owner_proc_start
            or not session.cwd or Path(session.cwd).resolve() != Path(workspace.path).resolve()):
        return False
    # Copy mutable ORM values before awaiting native observation.
    slot_options = dict(slot.launch_options or {})
    context = (item.dispatch_nonce, item.owner_slot_id, item.active_scope_revision,
               item.attempt_phase, item.delivery_policy_revision, item.delivery_policy)
    lease = (workspace.id, workspace.lease_token, workspace.leased_at,
             workspace.leased_owner_pid, workspace.leased_owner_proc_start,
             workspace.lease_last_owner_contact_at)
    workspace_path = workspace.path
    ack = revision.acknowledged_at if revision is not None else item.ack_received_at
    revision_hash = revision.expected_lease_token_hash if revision is not None else None
    member_id, session_id, provider, cwd = owner.id, session.id, slot.provider, session.cwd
    try:
        observations = await activity.observe_private_team(db, scope.preset_id, max_input_rows=256)
        observed = observations.get(slot.id)
        if (observed is None or observed.state != "working" or not observed.identity
                or observed.observed_at is None):
            return False
        when = observed.observed_at
        if when.tzinfo is None:
            return False
        now = datetime.utcnow()
        age = datetime.now(timezone.utc) - when
        contact_at = when.astimezone(timezone.utc).replace(tzinfo=None)
        if not 0 <= age.total_seconds() <= 180 or contact_at <= max(anchors):
            return False
        process_state, process_start = activity._process(lease[3])
        if process_start != lease[4] or process_state in activity._STOPPED_STATES:
            return False
    except (OSError, ValueError, TimeoutError):
        return False
    if now - anchor > timedelta(seconds=idle + grace) or (
        nudge is not None and nudge >= anchor and now - nudge > timedelta(seconds=grace)
    ):
        return False
    newer_member = aliased(MailTeamMember)
    newer_session = aliased(MailAgentSession)
    owner_current = exists(select(MailTeamMember.id).where(
        MailTeamMember.id == member_id, MailTeamMember.team_slot_id == slot.id,
        MailTeamMember.team_preset_id == scope.preset_id,
        ~exists(select(newer_member.id).where(
            newer_member.team_slot_id == slot.id,
            newer_member.team_preset_id == scope.preset_id,
            or_(newer_member.updated_at > MailTeamMember.updated_at,
                (newer_member.updated_at == MailTeamMember.updated_at) & (newer_member.id > member_id)),
        )),
    ))
    session_current = exists(select(MailAgentSession.id).where(
        MailAgentSession.id == session_id, MailAgentSession.member_id == member_id,
        MailAgentSession.team_preset_id == scope.preset_id, MailAgentSession.team_slot_id == slot.id,
        MailAgentSession.provider == provider, MailAgentSession.source == "mcp",
        MailAgentSession.bound_pane_pid == lease[3], MailAgentSession.bound_pane_proc_start == lease[4],
        MailAgentSession.cwd == cwd, MailAgentSession.closed_at.is_(None),
        MailAgentSession.mailbox_status == "connected", MailAgentSession.capability_token_hash.is_not(None),
        ~exists(select(newer_session.id).where(
            newer_session.member_id == member_id, newer_session.team_slot_id == slot.id,
            newer_session.team_preset_id == scope.preset_id, newer_session.source == "mcp",
            newer_session.closed_at.is_(None), newer_session.mailbox_status == "connected",
            newer_session.id > session_id,
        )),
    ))
    current_item = exists(select(GithubWorkItem.id).where(
        GithubWorkItem.id == item.id, GithubWorkItem.scope_id == scope.id,
        GithubWorkItem.dispatch_status == "dispatched", GithubWorkItem.dispatch_nonce == context[0],
        GithubWorkItem.owner_slot_id == context[1], GithubWorkItem.active_scope_revision == context[2],
        GithubWorkItem.attempt_phase == context[3], GithubWorkItem.delivery_policy_revision == context[4],
        GithubWorkItem.delivery_policy == context[5],
        GithubWorkItem.continuation_activated_at == activated if revision is not None else GithubWorkItem.dispatched_at == activated,
        GithubWorkItem.ack_received_at == ack if revision is None else True,
        GithubWorkItem.continuation_nudged_at == nudge if revision is not None else GithubWorkItem.last_nudge_at == nudge,
    ))
    conditions = [
        GithubWorkspace.id == lease[0], GithubWorkspace.leased_item_id == item.id,
        GithubWorkspace.scope_id == scope.id, GithubWorkspace.enabled.is_(True),
        GithubWorkspace.path == workspace_path, GithubWorkspace.lease_token == lease[1],
        GithubWorkspace.leased_at == lease[2], GithubWorkspace.leased_owner_pid == lease[3],
        GithubWorkspace.leased_owner_proc_start == lease[4], GithubWorkspace.lease_last_owner_contact_at == lease[5],
        current_item, owner_current, session_current,
        exists(select(AgentTeamSlot.id).where(
            AgentTeamSlot.id == slot.id, AgentTeamSlot.preset_id == scope.preset_id,
            AgentTeamSlot.enabled.is_(True), AgentTeamSlot.provider == provider,
            AgentTeamSlot.launch_options == slot_options,
        )),
        exists(select(AgentPaneBinding.id).where(
            AgentPaneBinding.preset_id == scope.preset_id, AgentPaneBinding.slot_id == slot.id,
            AgentPaneBinding.pane_pid == lease[3], AgentPaneBinding.pane_proc_start == lease[4],
        )),
        ~exists(select(MailPaneLifecycle.pane_pid).where(
            MailPaneLifecycle.pane_pid == lease[3], MailPaneLifecycle.pane_proc_start == lease[4],
            MailPaneLifecycle.retired_at.is_not(None),
        )),
    ]
    if revision is not None:
        conditions.append(exists(select(GithubAttemptScopeRevision.id).where(
            GithubAttemptScopeRevision.id == revision.id, GithubAttemptScopeRevision.status == "active",
            GithubAttemptScopeRevision.work_item_id == item.id, GithubAttemptScopeRevision.revision == context[2],
            GithubAttemptScopeRevision.dispatch_nonce == context[0], GithubAttemptScopeRevision.owner_slot_id == context[1],
            GithubAttemptScopeRevision.phase == context[3],
            GithubAttemptScopeRevision.owner_member_id == member_id,
            GithubAttemptScopeRevision.expected_workspace_id == lease[0],
            GithubAttemptScopeRevision.expected_lease_token_hash == revision_hash,
            GithubAttemptScopeRevision.acknowledged_at == ack,
        )))
    result = await db.execute(update(GithubWorkspace).where(*conditions).values(
        lease_last_owner_contact_at=contact_at,
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        return False
    await db.commit()
    await db.refresh(workspace)
    await db.refresh(item)
    return True
