"""Operator recovery for initial approvals stranded before execution."""

import logging
from datetime import datetime

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    GithubApprovalRequest,
    GithubWorkItem,
    GithubWorkspace,
    MailMessage,
)
from app.services.github_approval_service import (
    GithubApprovalError,
    github_approval_service,
)

logger = logging.getLogger(__name__)


async def cancel_stranded_initial_approval(
    db: AsyncSession,
    *,
    work_item_id: int,
    request_id: int,
    dispatch_nonce: str,
    reason: str,
) -> GithubApprovalRequest:
    """Supersede pending authority and its Mail without resetting the attempt.

    The route must authenticate the operator. The item claim serializes this
    transition with dispatch/approval writes; the approval CAS preserves decisions.
    """
    if not reason.strip():
        raise GithubApprovalError("cancellation_reason_required", status_code=400)
    item = await db.get(GithubWorkItem, work_item_id, populate_existing=True)
    approval = await db.get(GithubApprovalRequest, request_id, populate_existing=True)
    if (
        item is None
        or approval is None
        or approval.work_item_id != work_item_id
        or approval.request_kind != "initial_plan"
    ):
        raise GithubApprovalError("approval_request_not_found", status_code=404)
    if item.dispatch_nonce != dispatch_nonce or approval.dispatch_nonce != dispatch_nonce:
        raise GithubApprovalError("stale_nonce")
    if approval.approval_round != item.approval_round_count:
        raise GithubApprovalError("stale_approval_context")
    if item.dispatch_status != "escalated":
        raise GithubApprovalError("initial_approval_not_escalated")
    if item.pr_number is not None:
        raise GithubApprovalError("pr_preserved")
    if item.active_scope_revision != 0 or approval.scope_revision_id is not None:
        raise GithubApprovalError("active_continuation")
    if any(
        value is not None
        for value in (
            item.ack_received_at,
            item.ack_approver_member_id,
            item.ack_evidence_message_id,
            item.ack_enforcement_epoch,
            item.ack_approval_round,
        )
    ):
        raise GithubApprovalError("initial_approval_already_acknowledged")

    # A released pool must not retain lease/push authority. Other valid leases
    # in this scope do not prevent this independent item from being recovered.
    workspace_authority_exists = exists(
        select(GithubWorkspace.id).where(
            or_(
                GithubWorkspace.leased_item_id == work_item_id,
                and_(
                    GithubWorkspace.scope_id == item.scope_id,
                    GithubWorkspace.leased_item_id.is_(None),
                    or_(
                        GithubWorkspace.lease_token.is_not(None),
                        GithubWorkspace.push_token_expires_at.is_not(None),
                    ),
                ),
            )
        )
    )
    claim = await db.execute(
        update(GithubWorkItem)
        .where(
            GithubWorkItem.id == work_item_id,
            GithubWorkItem.scope_id == item.scope_id,
            GithubWorkItem.dispatch_status == "escalated",
            GithubWorkItem.dispatch_nonce == dispatch_nonce,
            GithubWorkItem.approval_round_count == approval.approval_round,
            GithubWorkItem.pr_number.is_(None),
            GithubWorkItem.active_scope_revision == 0,
            GithubWorkItem.ack_received_at.is_(None),
            GithubWorkItem.ack_approver_member_id.is_(None),
            GithubWorkItem.ack_evidence_message_id.is_(None),
            GithubWorkItem.ack_enforcement_epoch.is_(None),
            GithubWorkItem.ack_approval_round.is_(None),
            ~workspace_authority_exists,
        )
        .values(updated_at=GithubWorkItem.updated_at)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        raise GithubApprovalError("initial_approval_cancel_conflict")
    await db.refresh(approval)
    cancellation_reason = f"Operator cancelled initial approval: {reason.strip()}"
    if (
        approval.status == "superseded"
        and approval.superseded_at is not None
        and approval.reason == cancellation_reason
    ):
        await db.commit()
        return approval
    if approval.status != "pending":
        raise GithubApprovalError("request_not_pending")

    delivery_key = f"github-approval:{approval.id}:request"
    mail_filter = MailMessage.delivery_key == delivery_key
    if approval.request_message_id is not None:
        mail_filter = or_(mail_filter, MailMessage.id == approval.request_message_id)
    roots = (await db.execute(select(MailMessage).where(mail_filter))).scalars().all()
    if approval.request_message_id is not None and not any(
        root.id == approval.request_message_id for root in roots
    ):
        raise GithubApprovalError("approval_request_link_mismatch")
    for root in roots:
        if not github_approval_service.matches_linked_request_message(
            approval, root, delivery_key=delivery_key
        ):
            raise GithubApprovalError("approval_request_link_mismatch")

    now = datetime.utcnow()
    cancelled = await db.execute(
        update(GithubApprovalRequest)
        .where(
            GithubApprovalRequest.id == request_id,
            GithubApprovalRequest.work_item_id == work_item_id,
            GithubApprovalRequest.request_kind == "initial_plan",
            GithubApprovalRequest.dispatch_nonce == dispatch_nonce,
            GithubApprovalRequest.approval_round == item.approval_round_count,
            GithubApprovalRequest.status == "pending",
            GithubApprovalRequest.scope_revision_id.is_(None),
            GithubApprovalRequest.decision_message_id.is_(None),
            GithubApprovalRequest.decided_at.is_(None),
        )
        .values(status="superseded", superseded_at=now, reason=cancellation_reason)
        .execution_options(synchronize_session=False)
    )
    if cancelled.rowcount != 1:
        raise GithubApprovalError("initial_approval_cancel_conflict")
    for root in roots:
        root.request_status = "superseded"
    await db.flush()
    await db.refresh(approval)
    await db.commit()
    logger.info(
        "initial_approval_cancelled work_item_id=%s request_id=%s actor=operator",
        work_item_id, request_id,
    )
    return approval
