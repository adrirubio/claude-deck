"""Shared legacy work-item projection and normalized bulk authority reads.

The extracted functions preserve the legacy wire contract. Factory responses
apply their separately reviewed field allowlist in factory_projection_service.
"""
from __future__ import annotations
from typing import NamedTuple
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import GithubApprovalRequest, GithubAttemptScopeRevision, GithubWorkItem, GithubWorkspace, TeamGithubScope
from app.models.schemas import GithubWorkItemResponse
from app.services.github_approval_service import CONTINUABLE_ESCALATIONS
from app.services.github_dispatch_service import github_dispatch_service


def _work_item_response(
    item: GithubWorkItem,
    scope: TeamGithubScope,
    workspace_path: str | None = None,
    *,
    active_revision: GithubAttemptScopeRevision | None = None,
    pending_approval: GithubApprovalRequest | None = None,
    pending_revision: GithubAttemptScopeRevision | None = None,
    continuation_revision_count: int = 0,
    continuation_failed_head_count: int = 0,
) -> GithubWorkItemResponse:
    retry_eligibility = github_dispatch_service.retry_eligibility(
        item,
        pending_approval=pending_approval is not None,
    )
    current_revision = active_revision or pending_revision
    if not scope.continuation_enabled:
        continuation_block_code = "continuation_disabled"
    elif pending_approval is not None:
        continuation_block_code = "approval_pending"
    elif pending_revision is not None and pending_revision.delivery_message_id is None:
        continuation_block_code = "continuation_delivery_pending"
    elif pending_revision is not None:
        continuation_block_code = "continuation_ack_required"
    elif active_revision is not None and active_revision.status == "active":
        continuation_block_code = None
    elif item.dispatch_status != "escalated":
        continuation_block_code = "continuation_not_escalated"
    elif item.escalation_reason not in CONTINUABLE_ESCALATIONS:
        continuation_block_code = "continuation_reason_not_allowed"
    elif item.pr_number is None:
        continuation_block_code = "continuation_pr_required"
    elif workspace_path is None:
        continuation_block_code = "workspace_lease_required"
    elif (
        continuation_revision_count >= scope.max_continuation_revisions
        or continuation_failed_head_count >= scope.max_continuation_failed_heads
    ):
        continuation_block_code = "continuation_budget_exhausted"
    else:
        continuation_block_code = None
    return GithubWorkItemResponse(
        id=item.id,
        scope_id=item.scope_id,
        repo_owner=scope.repo_owner,
        repo_name=scope.repo_name,
        issue_number=item.issue_number,
        issue_title=item.issue_title,
        issue_url=item.issue_url,
        github_updated_at=item.github_updated_at,
        issue_type=item.issue_type,
        dispatch_status=item.dispatch_status,
        pending_reason=item.pending_reason,
        launch_id=item.launch_id,
        owner_slot_id=item.owner_slot_id,
        routing_method=item.routing_method,
        handoff_state=item.handoff_state,
        handoff_target_slot_id=item.handoff_target_slot_id,
        approval_round_count=item.approval_round_count,
        ack_approver_member_id=item.ack_approver_member_id,
        ack_evidence_message_id=item.ack_evidence_message_id,
        dispatch_nonce=item.dispatch_nonce,
        ack_enforcement_epoch=item.ack_enforcement_epoch,
        ack_approval_round=item.ack_approval_round,
        dispatch_head_ref=item.dispatch_head_ref,
        pr_number=item.pr_number,
        retry_count=item.retry_count,
        last_verified_sha=item.last_verified_sha,
        retry_requested_at=item.retry_requested_at,
        escalation_reason=item.escalation_reason,
        status_note=item.status_note,
        auto_merged_at=item.auto_merged_at,
        active_scope_revision=item.active_scope_revision,
        active_scope_summary=(
            active_revision.summary if active_revision is not None else None
        ),
        active_scope_status=(
            active_revision.status if active_revision is not None else None
        ),
        pending_approval_request_id=(
            pending_approval.id if pending_approval is not None else None
        ),
        pending_approval_kind=(
            pending_approval.request_kind if pending_approval is not None else None
        ),
        pending_approval_status=(
            pending_approval.status if pending_approval is not None else None
        ),
        attempt_phase=item.attempt_phase,
        diagnostic_retry_count=item.diagnostic_retry_count,
        diagnostic_last_verified_sha=item.diagnostic_last_verified_sha,
        revision_failed_head_count=(
            current_revision.failed_head_count
            if current_revision is not None
            else None
        ),
        revision_failed_head_budget=(
            current_revision.max_failed_heads if current_revision is not None else None
        ),
        revision_approved_at=(
            current_revision.approved_at if current_revision is not None else None
        ),
        revision_delivered_at=(
            current_revision.delivered_at if current_revision is not None else None
        ),
        revision_acknowledged_at=(
            current_revision.acknowledged_at if current_revision is not None else None
        ),
        continuation_block_code=continuation_block_code,
        retry_allowed=retry_eligibility.allowed,
        retry_block_code=retry_eligibility.block_code,
        continuation_nudged_at=item.continuation_nudged_at,
        continuation_activated_at=item.continuation_activated_at,
        workspace_path=workspace_path,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class _WorkItemAuthorityProjection(NamedTuple):
    active_revision: GithubAttemptScopeRevision | None
    pending_approval: GithubApprovalRequest | None
    pending_revision: GithubAttemptScopeRevision | None
    revision_count: int
    failed_head_count: int


async def _load_work_item_authority(
    db: AsyncSession,
    items: list[GithubWorkItem],
) -> dict[int, _WorkItemAuthorityProjection]:
    if not items:
        return {}
    item_ids = [item.id for item in items]
    approvals = (
        await db.execute(
            select(GithubApprovalRequest).where(
                GithubApprovalRequest.work_item_id.in_(item_ids),
                GithubApprovalRequest.status == "pending",
            )
        )
    ).scalars().all()
    revisions = (
        await db.execute(
            select(GithubAttemptScopeRevision)
            .where(GithubAttemptScopeRevision.work_item_id.in_(item_ids))
            .order_by(
                GithubAttemptScopeRevision.work_item_id,
                GithubAttemptScopeRevision.revision.desc(),
            )
        )
    ).scalars().all()
    approval_by_item = {approval.work_item_id: approval for approval in approvals}
    revision_by_id = {revision.id: revision for revision in revisions}
    revision_by_attempt = {
        (revision.work_item_id, revision.dispatch_nonce, revision.revision): revision
        for revision in revisions
    }
    approved_by_attempt: dict[tuple[int, str], GithubAttemptScopeRevision] = {}
    revision_count_by_attempt: dict[tuple[int, str], int] = {}
    failed_head_count_by_attempt: dict[tuple[int, str], int] = {}
    for revision in revisions:
        attempt_key = (revision.work_item_id, revision.dispatch_nonce)
        revision_count_by_attempt[attempt_key] = (
            revision_count_by_attempt.get(attempt_key, 0) + 1
        )
        failed_head_count_by_attempt[attempt_key] = (
            failed_head_count_by_attempt.get(attempt_key, 0)
            + revision.failed_head_count
        )
        if revision.status == "approved":
            approved_by_attempt.setdefault(
                attempt_key,
                revision,
            )

    projections: dict[int, _WorkItemAuthorityProjection] = {}
    for item in items:
        active_revision = None
        if item.dispatch_nonce is not None and item.active_scope_revision > 0:
            active_revision = revision_by_attempt.get(
                (item.id, item.dispatch_nonce, item.active_scope_revision)
            )
        pending_approval = approval_by_item.get(item.id)
        pending_revision = None
        if (
            pending_approval is not None
            and pending_approval.scope_revision_id is not None
        ):
            pending_revision = revision_by_id.get(pending_approval.scope_revision_id)
        elif active_revision is None and item.dispatch_nonce is not None:
            pending_revision = approved_by_attempt.get((item.id, item.dispatch_nonce))
        projections[item.id] = _WorkItemAuthorityProjection(
            active_revision=active_revision,
            pending_approval=pending_approval,
            pending_revision=pending_revision,
            revision_count=(
                revision_count_by_attempt.get((item.id, item.dispatch_nonce), 0)
                if item.dispatch_nonce is not None
                else 0
            ),
            failed_head_count=(
                failed_head_count_by_attempt.get((item.id, item.dispatch_nonce), 0)
                if item.dispatch_nonce is not None
                else 0
            ),
        )
    return projections


async def _reload_work_item_response(
    db: AsyncSession,
    item_id: int,
) -> GithubWorkItemResponse:
    row = (
        await db.execute(
            select(GithubWorkItem, TeamGithubScope, GithubWorkspace.path)
            .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
            .outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
            .where(GithubWorkItem.id == item_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    item, scope, workspace_path = row
    authority = (await _load_work_item_authority(db, [item]))[item.id]
    return _work_item_response(
        item,
        scope,
        workspace_path,
        active_revision=authority.active_revision,
        pending_approval=authority.pending_approval,
        pending_revision=authority.pending_revision,
        continuation_revision_count=authority.revision_count,
        continuation_failed_head_count=authority.failed_head_count,
    )

