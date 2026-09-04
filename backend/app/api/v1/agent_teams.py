"""Agent Team Preset endpoints."""
from __future__ import annotations

import logging
import ipaddress
from datetime import datetime, timedelta, timezone
from string import Formatter
from typing import NamedTuple

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.deps import (
    mail_session,
    require_mail_session_or_operator,
    require_operator,
    require_session_slot,
    resolve_request_pane_detailed,
)
from app.config import settings
from app.database import get_db
from app.models.database import (
    AgentTeamSlot,
    AgentPaneBinding,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.models.schemas import (
    AgentTeamCreateFromBridgeRequest,
    AgentTeamCreateFromMailRequest,
    AgentTeamLaunchPlan,
    AgentTeamLaunchRequest,
    AgentTeamLaunchResult,
    AgentTeamPresetCreate,
    AgentTeamPresetListResponse,
    AgentTeamPresetResponse,
    AgentTeamPresetUpdate,
    AgentTeamSlotCreate,
    AgentTeamSlotReorderRequest,
    AgentTeamSlotUpdate,
    DispatchStatusReport,
    GithubActiveContinuationCancelRequest,
    GithubApprovalRequestResponse,
    GithubContinuationProposalCreate,
    GithubContinuationAckRequest,
    GithubContinuationRequestResponse,
    GithubScopeRevisionResponse,
    GithubWorkItemAbandonRequest,
    GithubWorkItemContinuationResponse,
    GithubWorkItemListResponse,
    GithubWorkItemResumeAttemptRequest,
    GithubWorkItemRetryRequest,
    GithubWorkItemResponse,
    GithubWorkspaceCreate,
    GithubCredentialRequest,
    GithubCredentialResponse,
    GithubWorkspaceForceReleaseRequest,
    GithubWorkspaceForceReleaseResponse,
    GithubWorkspaceListResponse,
    GithubWorkspaceResponse,
    MailMessageCreate,
    TeamGithubScopeCreate,
    TeamGithubContinuationPolicyUpdate,
    TeamGithubScopeListResponse,
    TeamGithubScopeResponse,
    TeamGithubScopeUpdate,
)
from app.services.agent_mail_service import (
    MailAuthorityError,
    MailDeliveryIntegrityError,
    agent_mail_service,
)
from app.services.github_approval_service import (
    CONTINUABLE_ESCALATIONS,
    GithubApprovalError,
    github_approval_service,
)
from app.services.github_dispatch_scheduler import github_dispatch_scheduler
from app.services.github_dispatch_service import ResumeAttemptError, github_dispatch_service
from app.services.github_client import GithubClientResponseError, github_client
from app.services.github_app_auth_service import (
    GithubAppAuthError,
    GithubAppMintRejected,
    GithubAppNotInstalled,
    GithubAppUnconfigured,
    github_app_auth_service,
)
from app.services.github_workspace_service import (
    _RELEASABLE_STATUSES,
    GithubWorkspaceCredentialRevokeError,
    GithubWorkspaceError,
    GithubWorkspaceResetError,
    github_workspace_service,
)
from app.services.github_verification_service import (
    ContinuationCompletionError,
    github_verification_service,
)
from app.services.agent_team_service import PlanConflictError, agent_team_service
from app.services.providers.base import ProviderLaunchError

router = APIRouter()

logger = logging.getLogger(__name__)

_WORKSPACE_CONFLICT_CODES = {
    "workspace_path_registered",
    "workspace_path_outside_root",
    "workspace_not_a_worktree",
    "workspace_is_primary",
    "workspace_dirty",
    "workspace_occupied",
    "workspace_leased",
    "workspace_reset_failed",
    "work_item_not_abandonable",
}


def _is_loopback_request(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return False


def _normalized_credential_repo(path: str) -> str:
    normalized = path[1:] if path.startswith("/") else path
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def _bad_request(exc: ValueError) -> HTTPException:
    if isinstance(exc, ProviderLaunchError):
        return HTTPException(
            status_code=400,
            detail={"message": str(exc), "block_code": exc.block_code},
        )
    return HTTPException(status_code=400, detail=str(exc))


def _conflict(message: str, block_code: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": message, "block_code": block_code},
    )


def _clean_required(value: str | None, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _clean_repo_part(value: str | None, label: str) -> str:
    text = _clean_required(value, label)
    if any(char.isspace() for char in text) or "/" in text:
        raise ValueError(f"{label} must not contain whitespace or slash")
    return text


def _clean_label(value: str | None, label: str) -> str:
    return _clean_required(value, label)


def _validate_template(
    value: str,
    *,
    label: str,
    allowed_fields: set[str],
    render_values: dict[str, object],
) -> str:
    try:
        for _, field_name, format_spec, conversion in Formatter().parse(value):
            if field_name is None:
                continue
            if (
                field_name not in allowed_fields
                or format_spec
                or conversion is not None
            ):
                raise ValueError
        value.format(**render_values)
    except (KeyError, IndexError, ValueError) as exc:
        allowed = ", ".join(f"{{{field}}}" for field in sorted(allowed_fields))
        raise ValueError(f"{label} may only use placeholders: {allowed}") from exc
    return value


def _scope_response(scope: TeamGithubScope) -> TeamGithubScopeResponse:
    return TeamGithubScopeResponse(
        id=scope.id,
        preset_id=scope.preset_id,
        repo_owner=scope.repo_owner,
        repo_name=scope.repo_name,
        repo_path=scope.repo_path,
        dispatch_label=scope.dispatch_label,
        design_label=scope.design_label,
        merge_policy=scope.merge_policy,
        max_approval_rounds=scope.max_approval_rounds,
        max_concurrent_dispatched=scope.max_concurrent_dispatched,
        max_verification_retries=scope.max_verification_retries,
        max_auto_merges_per_day=scope.max_auto_merges_per_day,
        base_ref=scope.base_ref,
        builds_out_of_tree=scope.builds_out_of_tree,
        build_dir_template=scope.build_dir_template,
        build_command_hint=scope.build_command_hint,
        max_build_parallelism=scope.max_build_parallelism,
        continuation_enabled=scope.continuation_enabled,
        max_continuation_revisions=scope.max_continuation_revisions,
        max_continuation_failed_heads=scope.max_continuation_failed_heads,
        max_failed_heads_per_revision=scope.max_failed_heads_per_revision,
        max_scope_paths=scope.max_scope_paths,
        max_scope_commands=scope.max_scope_commands,
        enabled=scope.enabled,
        last_polled_at=scope.last_polled_at,
        created_at=scope.created_at,
        updated_at=scope.updated_at,
    )


def _workspace_lease_state(workspace: GithubWorkspace) -> str:
    if workspace.leased_item_id is not None:
        return "leased"
    if not workspace.enabled:
        return "disabled"
    if not workspace.dispatchable:
        return "disabled_for_dispatch"
    return "available"


def _workspace_response(workspace: GithubWorkspace) -> GithubWorkspaceResponse:
    lease_age_seconds = None
    if workspace.leased_item_id is not None and workspace.leased_at is not None:
        lease_age_seconds = max(
            0, int((datetime.utcnow() - workspace.leased_at).total_seconds())
        )
    return GithubWorkspaceResponse(
        id=workspace.id,
        scope_id=workspace.scope_id,
        path=workspace.path,
        kind=workspace.kind,
        lease_state=_workspace_lease_state(workspace),
        dispatchable=workspace.dispatchable,
        leased_item_id=workspace.leased_item_id,
        leased_at=workspace.leased_at,
        released_at=workspace.released_at,
        lease_last_owner_contact_at=workspace.lease_last_owner_contact_at,
        lease_release_reminded_at=workspace.lease_release_reminded_at,
        lease_age_seconds=lease_age_seconds,
        provision_error=workspace.provision_error,
        enabled=workspace.enabled,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


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


def _approval_authority_response(
    approval: GithubApprovalRequest,
) -> GithubApprovalRequestResponse:
    return GithubApprovalRequestResponse(
        id=approval.id,
        work_item_id=approval.work_item_id,
        request_kind=approval.request_kind,
        dispatch_nonce=approval.dispatch_nonce,
        approval_round=approval.approval_round,
        owner_member_id=approval.owner_member_id,
        leader_member_id=approval.leader_member_id,
        request_message_id=approval.request_message_id,
        decision_message_id=approval.decision_message_id,
        scope_revision_id=approval.scope_revision_id,
        status=approval.status,
        reason=approval.reason,
        created_at=approval.created_at,
        decided_at=approval.decided_at,
        superseded_at=approval.superseded_at,
    )


def _scope_revision_response(
    revision: GithubAttemptScopeRevision,
    *,
    include_commands: bool = True,
    approval: GithubApprovalRequest | None = None,
) -> GithubScopeRevisionResponse:
    return GithubScopeRevisionResponse(
        id=revision.id,
        work_item_id=revision.work_item_id,
        dispatch_nonce=revision.dispatch_nonce,
        revision=revision.revision,
        owner_slot_id=revision.owner_slot_id,
        owner_member_id=revision.owner_member_id,
        phase=revision.phase,
        execution_target=revision.execution_target,
        summary=revision.summary,
        allowed_paths=revision.allowed_paths,
        allowed_actions=revision.allowed_actions,
        allowed_commands=revision.allowed_commands if include_commands else [],
        prohibited_actions=revision.prohibited_actions,
        tool_fallbacks=revision.tool_fallbacks,
        baseline_head_sha=revision.baseline_head_sha,
        baseline_tree_sha=revision.baseline_tree_sha,
        originating_escalation_reason=revision.originating_escalation_reason,
        expected_workspace_id=revision.expected_workspace_id,
        max_failed_heads=revision.max_failed_heads,
        failed_head_count=revision.failed_head_count,
        last_failed_head_sha=revision.last_failed_head_sha,
        status=revision.status,
        approval_request_id=revision.approval_request_id,
        delivery_message_id=revision.delivery_message_id,
        approved_at=revision.approved_at,
        delivered_at=revision.delivered_at,
        acknowledged_at=revision.acknowledged_at,
        last_delivery_attempt_at=revision.last_delivery_attempt_at,
        delivery_attempt_count=revision.delivery_attempt_count,
        last_ack_nudge_at=revision.last_ack_nudge_at,
        result_summary=revision.result_summary,
        evidence=revision.evidence,
        submitted_head_sha=revision.submitted_head_sha,
        submitted_at=revision.submitted_at,
        completed_at=revision.completed_at,
        cancelled_at=revision.cancelled_at,
        cancellation_reason=revision.cancellation_reason,
        expires_at=revision.expires_at,
        created_at=revision.created_at,
        approval_request=(
            _approval_authority_response(approval) if approval is not None else None
        ),
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


def _retry_conflict(item: GithubWorkItem, block_code: str) -> HTTPException:
    if block_code == "not_escalated":
        message = "Only escalated work items can be retried"
    elif block_code == "active_continuation":
        message = (
            f"Work item has active continuation revision "
            f"{item.active_scope_revision}; continue or cancel that attempt first."
        )
    elif block_code == "approval_pending":
        message = "Work item has a pending approval request; resolve it before retrying."
    elif block_code == "pr_preserved":
        message = (
            f"Work item has PR #{item.pr_number} already open; retry would orphan it. "
            "Resolve or close the PR first."
        )
    else:
        message = "Work item cannot be retried safely"
    return _conflict(message, block_code)


async def _sync_github_jobs(db: AsyncSession) -> None:
    await github_dispatch_scheduler.sync_jobs(db)


async def _scope_identity_in_use(db: AsyncSession, scope_id: int) -> bool:
    leased_workspace = (
        await db.execute(
            select(GithubWorkspace.id)
            .where(
                GithubWorkspace.scope_id == scope_id,
                GithubWorkspace.leased_item_id.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if leased_workspace is not None:
        return True
    active_attempt = (
        await db.execute(
            select(GithubWorkItem.id)
            .where(
                GithubWorkItem.scope_id == scope_id,
                GithubWorkItem.dispatch_status.in_(
                    (
                        "pending",
                        "dispatched",
                        "verifying",
                        "ready_for_review",
                        "awaiting_human_review",
                        "escalated",
                        "failed",
                    )
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return active_attempt is not None


def _apply_scope_create(
    scope: TeamGithubScope,
    request: TeamGithubScopeCreate | TeamGithubScopeUpdate,
) -> None:
    if request.repo_owner is not None:
        scope.repo_owner = _clean_repo_part(request.repo_owner, "Repo owner")
    if request.repo_name is not None:
        scope.repo_name = _clean_repo_part(request.repo_name, "Repo name")
    if request.repo_path is not None:
        repo_path, _ = agent_team_service.normalize_repo_path(request.repo_path)
        scope.repo_path = repo_path
    if request.dispatch_label is not None:
        scope.dispatch_label = _clean_label(request.dispatch_label, "Dispatch label")
    if request.design_label is not None:
        scope.design_label = _clean_label(request.design_label, "Design label")
    if request.merge_policy is not None:
        scope.merge_policy = request.merge_policy
    if request.max_approval_rounds is not None:
        scope.max_approval_rounds = request.max_approval_rounds
    if request.max_concurrent_dispatched is not None:
        scope.max_concurrent_dispatched = request.max_concurrent_dispatched
    if request.max_verification_retries is not None:
        scope.max_verification_retries = request.max_verification_retries
    if request.max_auto_merges_per_day is not None:
        scope.max_auto_merges_per_day = request.max_auto_merges_per_day
    if request.base_ref is not None:
        scope.base_ref = _clean_required(request.base_ref, "Base ref")
    if request.builds_out_of_tree is not None:
        scope.builds_out_of_tree = request.builds_out_of_tree
    if request.build_dir_template is not None:
        scope.build_dir_template = _validate_template(
            request.build_dir_template,
            label="Build directory template",
            allowed_fields={"issue_number"},
            render_values={"issue_number": 1},
        )
    if request.build_command_hint is not None:
        scope.build_command_hint = _validate_template(
            request.build_command_hint,
            label="Build command hint",
            allowed_fields={"build_dir", "parallelism"},
            render_values={"build_dir": "build", "parallelism": 4},
        )
    if request.max_build_parallelism is not None:
        scope.max_build_parallelism = request.max_build_parallelism
    if request.enabled is not None:
        scope.enabled = request.enabled
    scope.updated_at = datetime.utcnow()


class _StatusRule(NamedTuple):
    """Who may report a status and whether its lease token is required."""

    role: str
    refusal: str
    lease_token_required: bool = False


_OWNER = _StatusRule("owner", "not_item_owner")

_DISPATCH_STATUS_RULES: dict[str, _StatusRule] = {
    "triaging": _OWNER,
    "in_progress": _OWNER,
    "blocked": _OWNER,
    "ack_received": _OWNER,
    "handoff_initiated": _OWNER,
    "revision_requested": _OWNER,
    "handoff_accepted": _StatusRule("target", "not_handoff_target"),
    "pr_opened": _StatusRule("owner", "not_item_owner", lease_token_required=True),
    "pr_ready": _StatusRule("owner", "not_item_owner", lease_token_required=True),
    "continuation_completed": _StatusRule(
        "owner",
        "not_item_owner",
        lease_token_required=True,
    ),
    "diagnostic_completed": _StatusRule(
        "owner",
        "not_item_owner",
        lease_token_required=True,
    ),
    "workspace_released": _StatusRule(
        "owner",
        "not_item_owner",
        lease_token_required=True,
    ),
}


async def _authorize_dispatch_report(
    db: AsyncSession,
    item: GithubWorkItem,
    report: DispatchStatusReport,
    session: MailAgentSession | None,
) -> None:
    """Authorize a dispatch report before any status branch mutates state."""
    if session is None:
        raise HTTPException(status_code=401, detail="session_token_required")

    slot_id = require_session_slot(session)
    if report.reporting_slot_id is not None and report.reporting_slot_id != slot_id:
        raise HTTPException(status_code=403, detail="slot_claim_mismatch")
    report.reporting_slot_id = slot_id

    rule = _DISPATCH_STATUS_RULES.get(report.status)
    if rule is None:
        raise HTTPException(status_code=400, detail=f"unknown status {report.status}")

    authorized = item.owner_slot_id if rule.role == "owner" else item.handoff_target_slot_id
    if authorized is None or slot_id != authorized:
        raise HTTPException(status_code=403, detail=rule.refusal)

    if rule.lease_token_required:
        if report.lease_token is None:
            raise HTTPException(status_code=400, detail="lease_token required")
        if report.status == "workspace_released":
            return
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if workspace is None or workspace.lease_token != report.lease_token:
            raise HTTPException(
                status_code=409,
                detail=f"lease_token does not match the current lease for item {item.id}",
            )


@router.post("/git-credential", response_model=GithubCredentialResponse)
async def get_github_credential(
    credential: GithubCredentialRequest,
    http_request: Request,
    http_response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Mint a repository-scoped credential for the kernel-derived owner."""
    if not _is_loopback_request(http_request):
        raise HTTPException(status_code=403, detail="loopback_required")
    if credential.path is None or not credential.path.strip():
        raise HTTPException(status_code=400, detail="credential_path_required")
    if credential.protocol != "https" or credential.host != "github.com":
        raise HTTPException(status_code=403, detail="credential_target_refused")

    leased = (
        await db.execute(
            select(GithubWorkspace, GithubWorkItem, TeamGithubScope)
            .join(GithubWorkItem, GithubWorkspace.leased_item_id == GithubWorkItem.id)
            .join(TeamGithubScope, GithubWorkspace.scope_id == TeamGithubScope.id)
            .where(GithubWorkspace.lease_token == credential.workspace_token)
        )
    ).one_or_none()
    if leased is None:
        raise HTTPException(status_code=403, detail="workspace_lease_not_current")
    workspace, item, scope = leased
    requested_repo = _normalized_credential_repo(credential.path)
    expected_repo = f"{scope.repo_owner}/{scope.repo_name}"
    if requested_repo != expected_repo:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "credential_repo_mismatch",
                "message": (
                    f"Credential requested for {requested_repo}; lease covers "
                    f"{expected_repo}"
                ),
            },
        )
    if scope.github_auth_mode != "app" or scope.github_app_installation_id is None:
        raise HTTPException(status_code=501, detail="app_auth_not_available")
    try:
        github_app_auth_service.require_configuration(require_bot_login=True)
    except GithubAppAuthError as exc:
        raise HTTPException(status_code=503, detail="app_auth_unconfigured") from exc

    resolution = resolve_request_pane_detailed(http_request, max_parent_walk=16)
    if resolution.pane is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "pane_unresolved",
                "stop_reason": resolution.stop_reason,
                "max_parent_walk": resolution.max_parent_walk,
                "walked_pids": list(resolution.walked_pids),
            },
        )
    pane = resolution.pane

    async with github_workspace_service.config_lock(workspace.id):
        current = (
            await db.execute(
                select(GithubWorkspace, GithubWorkItem, TeamGithubScope)
                .join(
                    GithubWorkItem,
                    GithubWorkspace.leased_item_id == GithubWorkItem.id,
                )
                .join(TeamGithubScope, GithubWorkspace.scope_id == TeamGithubScope.id)
                .where(
                    GithubWorkspace.id == workspace.id,
                    GithubWorkspace.lease_token == credential.workspace_token,
                )
            )
        ).one_or_none()
        if current is None:
            raise HTTPException(status_code=403, detail="workspace_lease_not_current")
        current_workspace, current_item, current_scope = current
        if (
            current_scope.github_auth_mode != "app"
            or current_scope.github_app_installation_id is None
        ):
            raise HTTPException(status_code=501, detail="app_auth_not_available")
        binding = (
            await db.execute(
                select(AgentPaneBinding).where(
                    AgentPaneBinding.pane_pid == pane.pane_pid,
                    AgentPaneBinding.pane_proc_start == pane.pane_proc_start,
                )
            )
        ).scalar_one_or_none()
        if binding is None or binding.slot_id != current_item.owner_slot_id:
            raise HTTPException(status_code=403, detail="not_item_owner")
        cache_subject = github_workspace_service.push_token_subject(
            current_workspace.id,
            credential.workspace_token,
            binding.slot_id,
        )
        previous_quarantine = current_workspace.push_token_expires_at

        async def restore_preexisting_quarantine() -> None:
            cached_expiry = github_app_auth_service.cached_repository_token_expiry(
                int(current_scope.github_app_installation_id),
                current_scope.repo_owner,
                current_scope.repo_name,
                purpose="push",
                cache_subject=cache_subject,
            )
            cached_quarantine = (
                cached_expiry.astimezone(timezone.utc).replace(tzinfo=None)
                + timedelta(minutes=1)
                if cached_expiry is not None
                else None
            )
            current_workspace.push_token_expires_at = max(
                (
                    expiry
                    for expiry in (previous_quarantine, cached_quarantine)
                    if expiry is not None
                ),
                default=None,
            )
            current_workspace.updated_at = datetime.utcnow()
            await db.commit()

        current_workspace.push_token_expires_at = datetime.utcnow() + timedelta(
            minutes=65
        )
        current_workspace.updated_at = datetime.utcnow()
        await db.commit()
        try:
            password = await github_app_auth_service.mint_repository_token(
                int(current_scope.github_app_installation_id),
                current_scope.repo_owner,
                current_scope.repo_name,
                purpose="push",
                cache_subject=cache_subject,
            )
        except GithubAppNotInstalled as exc:
            await restore_preexisting_quarantine()
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except GithubAppUnconfigured as exc:
            await restore_preexisting_quarantine()
            raise HTTPException(status_code=503, detail=exc.code) from exc
        except GithubAppMintRejected as exc:
            await restore_preexisting_quarantine()
            raise HTTPException(status_code=502, detail=exc.code) from exc
        except GithubAppAuthError as exc:
            raise HTTPException(status_code=502, detail=exc.code) from exc

        after = (
            await db.execute(
                select(
                    GithubWorkspace.lease_token,
                    GithubWorkspace.leased_item_id,
                    GithubWorkItem.owner_slot_id,
                )
                .join(
                    GithubWorkItem,
                    GithubWorkspace.leased_item_id == GithubWorkItem.id,
                )
                .where(GithubWorkspace.id == current_workspace.id)
            )
        ).one_or_none()
        if (
            after is None
            or after.lease_token != credential.workspace_token
            or after.leased_item_id != current_item.id
        ):
            raise HTTPException(status_code=409, detail="workspace_lease_changed")
        if after.owner_slot_id != binding.slot_id:
            raise HTTPException(status_code=403, detail="not_item_owner")
        token_expiry = github_app_auth_service.cached_repository_token_expiry(
            int(current_scope.github_app_installation_id),
            current_scope.repo_owner,
            current_scope.repo_name,
            purpose="push",
            cache_subject=cache_subject,
        )
        if token_expiry is None:
            raise HTTPException(status_code=502, detail="app_token_expiry_missing")
        current_workspace.push_token_expires_at = (
            token_expiry.astimezone(timezone.utc).replace(tzinfo=None)
            + timedelta(minutes=1)
        )
        current_workspace.updated_at = datetime.utcnow()
        await db.commit()
    http_response.headers["Cache-Control"] = "no-store"
    return GithubCredentialResponse(username="x-access-token", password=password)


@router.post("/dispatch-status")
async def report_dispatch_status(
    report: DispatchStatusReport,
    session: MailAgentSession | None = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, report.work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work item not found")
    if not settings.mail_capability_tokens_required:
        raise HTTPException(status_code=409, detail="tokens_not_enforced")
    if report.status == "revision_requested":
        raise HTTPException(status_code=409, detail="use_deck_approve_work_item")
    scope = await db.get(TeamGithubScope, item.scope_id)
    await _authorize_dispatch_report(db, item, report, session)

    if report.status == "triaging":
        if report.note is not None:
            item.status_note = report.note
            item.updated_at = datetime.utcnow()
            await db.commit()
    elif report.status == "handoff_initiated":
        if report.reassign_to_slot_id is None:
            raise HTTPException(status_code=400, detail="reassign_to_slot_id required")
        if session is None:
            raise HTTPException(status_code=401, detail="session_token_required")
        try:
            await github_dispatch_service.initiate_handoff(
                db,
                item,
                scope,
                initiating_slot_id=require_session_slot(session),
                target_slot_id=report.reassign_to_slot_id,
            )
        except ResumeAttemptError as exc:
            status_code = 403 if exc.block_code == "not_item_owner" else 409
            raise HTTPException(status_code=status_code, detail=exc.block_code) from exc
    elif report.status == "handoff_accepted":
        if session is None:
            raise HTTPException(status_code=401, detail="session_token_required")
        accepting_slot_id = require_session_slot(session)
        if session.bound_pane_pid is None or session.bound_pane_proc_start is None:
            raise HTTPException(status_code=403, detail="bind_unverifiable")
        try:
            await github_dispatch_service.accept_handoff(
                db,
                item,
                accepting_slot_id,
                accepting_pane_pid=session.bound_pane_pid,
                accepting_pane_proc_start=session.bound_pane_proc_start,
            )
        except GithubWorkspaceCredentialRevokeError as exc:
            raise HTTPException(status_code=503, detail=exc.block_code) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif report.status == "blocked":
        await github_dispatch_service.escalate(db, item, "plan_blocked", report.note)
        await db.commit()
    elif report.status == "ack_received":
        evidence = await github_dispatch_service.record_ack_received(db, item, scope)
        if not evidence.ok:
            raise HTTPException(status_code=409, detail=evidence.reason)
    elif report.status == "pr_opened":
        if report.pr_number is None:
            raise HTTPException(status_code=400, detail="pr_number required")
        if report.head_ref is not None:
            raise HTTPException(status_code=400, detail="head_ref is not valid for pr_opened")
        try:
            await github_verification_service.report_pr_opened(
                db, item, scope, report.pr_number, github_client
            )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=503,
                detail="github_upstream_timeout",
            ) from exc
        except (httpx.HTTPError, GithubClientResponseError) as exc:
            raise HTTPException(
                status_code=502,
                detail="github_upstream_error",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif report.status == "pr_ready":
        if report.pr_number is not None:
            raise HTTPException(status_code=400, detail="pr_number is not valid for pr_ready")
        if report.head_ref is None or not report.head_ref.strip():
            raise HTTPException(status_code=400, detail="head_ref required")
        try:
            await github_verification_service.report_pr_ready(
                db,
                item,
                scope,
                report.head_ref,
                report.lease_token or "",
                github_client,
            )
        except GithubAppNotInstalled as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except GithubAppUnconfigured as exc:
            raise HTTPException(status_code=503, detail=exc.code) from exc
        except GithubAppAuthError as exc:
            raise HTTPException(status_code=502, detail=exc.code) from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=503,
                detail="github_upstream_timeout",
            ) from exc
        except (httpx.HTTPError, GithubClientResponseError) as exc:
            raise HTTPException(
                status_code=502,
                detail="github_upstream_error",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif report.status == "continuation_completed":
        if report.revision is None:
            raise HTTPException(status_code=400, detail="revision_required")
        if not report.dispatch_nonce:
            raise HTTPException(status_code=400, detail="dispatch_nonce_required")
        if not report.current_head_sha:
            raise HTTPException(status_code=400, detail="current_head_sha_required")
        if not report.summary or not report.summary.strip():
            raise HTTPException(status_code=400, detail="summary_required")
        if report.lease_token is None:
            raise HTTPException(status_code=400, detail="lease_token_required")
        try:
            await github_verification_service.submit_continuation_completion(
                db,
                item,
                scope,
                authenticated_owner_member_id=session.member_id,
                authenticated_owner_slot_id=int(report.reporting_slot_id),
                revision_number=report.revision,
                dispatch_nonce=report.dispatch_nonce,
                current_head_sha=report.current_head_sha,
                result_summary=report.summary.strip(),
                evidence=report.evidence or {},
                lease_token=report.lease_token,
            )
        except ContinuationCompletionError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except GithubAppAuthError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except GithubClientResponseError as exc:
            raise HTTPException(status_code=409, detail="github_snapshot_invalid") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="github_snapshot_failed") from exc
    elif report.status == "diagnostic_completed":
        if report.revision is None:
            raise HTTPException(status_code=400, detail="revision_required")
        if not report.dispatch_nonce:
            raise HTTPException(status_code=400, detail="dispatch_nonce_required")
        if not report.current_head_sha:
            raise HTTPException(status_code=400, detail="current_head_sha_required")
        if not report.summary or not report.summary.strip():
            raise HTTPException(status_code=400, detail="summary_required")
        if not report.evidence:
            raise HTTPException(status_code=400, detail="evidence_required")
        if report.lease_token is None:
            raise HTTPException(status_code=400, detail="lease_token_required")
        try:
            await github_verification_service.submit_diagnostic_completion(
                db,
                item,
                scope,
                authenticated_owner_member_id=session.member_id,
                authenticated_owner_slot_id=int(report.reporting_slot_id),
                revision_number=report.revision,
                dispatch_nonce=report.dispatch_nonce,
                current_head_sha=report.current_head_sha,
                result_summary=report.summary.strip(),
                evidence=report.evidence,
                lease_token=report.lease_token,
            )
        except ContinuationCompletionError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except GithubAppAuthError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except GithubClientResponseError as exc:
            raise HTTPException(status_code=409, detail="github_snapshot_invalid") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="github_snapshot_failed") from exc
    elif report.status == "in_progress":
        now = datetime.utcnow()
        item.last_nudge_at = None
        item.updated_at = now
        await db.commit()
    elif report.status == "workspace_released":
        item_id = item.id
        owner_slot_id = item.owner_slot_id
        if report.reporting_slot_id != owner_slot_id:
            raise HTTPException(
                status_code=403,
                detail="only the owner slot may release its workspace",
            )
        if report.lease_token is None:
            raise HTTPException(status_code=400, detail="lease_token required")
        if item.dispatch_status not in _RELEASABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"workspace cannot be released while the item is "
                    f"{item.dispatch_status}; release is legal only from "
                    f"{', '.join(_RELEASABLE_STATUSES)}"
                ),
            )
        workspace = await github_workspace_service.get_leased_workspace(db, item_id)
        if workspace is None:
            current_owner = (
                await db.execute(
                    select(GithubWorkItem.owner_slot_id).where(
                        GithubWorkItem.id == item_id
                    )
                )
            ).scalar_one()
            if current_owner != report.reporting_slot_id:
                raise HTTPException(status_code=403, detail="not_item_owner")
        else:
            blocker = await github_workspace_service.release_blocker(scope, workspace)
            if blocker is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"workspace will not be released: {blocker}. Commit and "
                        "push, or report the situation in status_note and leave "
                        "the lease held."
                    ),
                )
            try:
                released = await github_workspace_service.release_by_owner(
                    db,
                    item_id,
                    lease_token=report.lease_token,
                    workspace_id=workspace.id,
                    scope_id=scope.id,
                    owner_slot_id=int(report.reporting_slot_id),
                    expected_leased_at=workspace.leased_at,
                )
            except GithubWorkspaceCredentialRevokeError as exc:
                raise HTTPException(status_code=503, detail=exc.block_code) from exc
            if not released:
                current_owner = (
                    await db.execute(
                        select(GithubWorkItem.owner_slot_id).where(
                            GithubWorkItem.id == item_id
                        )
                    )
                ).scalar_one()
                current_lease = (
                    await db.execute(
                        select(GithubWorkspace.id).where(
                            GithubWorkspace.leased_item_id == item_id
                        )
                    )
                ).scalar_one_or_none()
                if current_lease is None and current_owner == report.reporting_slot_id:
                    pass
                else:
                    raise _conflict(
                        "The workspace lease or owner changed before release",
                        "lease_changed",
                    )
    else:
        raise HTTPException(status_code=400, detail=f"unknown status {report.status}")

    if (
        report.status != "workspace_released"
        and report.reporting_slot_id == item.owner_slot_id
    ):
        await github_workspace_service.touch_owner_contact(
            db,
            item.id,
            lease_token=report.lease_token,
            owner_slot_id=int(report.reporting_slot_id),
        )

    await db.refresh(item)
    return {
        "work_item_id": item.id,
        "dispatch_status": item.dispatch_status,
        "escalation_reason": item.escalation_reason,
        "handoff_state": item.handoff_state,
        "pr_number": item.pr_number,
    }


@router.post(
    "/github-work-items/{item_id}/continuation-requests",
    response_model=GithubContinuationRequestResponse,
)
async def request_github_work_item_continuation(
    item_id: int,
    request: GithubContinuationProposalCreate,
    session: MailAgentSession | None = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    if session is None:
        raise HTTPException(status_code=401, detail="session_token_required")
    slot_id = require_session_slot(session)
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work_item_not_found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="scope_not_found")
    try:
        revision, approval, _created = (
            await github_approval_service.create_continuation_request(
                db,
                item,
                scope,
                authenticated_owner_member_id=session.member_id,
                authenticated_owner_slot_id=slot_id,
                dispatch_nonce=request.dispatch_nonce,
                phase=request.phase,
                execution_target=request.execution_target,
                summary=request.summary,
                allowed_paths=request.allowed_paths,
                allowed_actions=request.allowed_actions,
                allowed_commands=request.allowed_commands,
                prohibited_actions=request.prohibited_actions,
                max_failed_heads=request.max_failed_heads,
                tool_fallbacks={
                    name: fallback.model_dump()
                    for name, fallback in request.tool_fallbacks.items()
                },
                lease_token=request.lease_token,
            )
        )
        async with github_approval_service.continuation_transport_lock(approval.id):
            if await github_approval_service.expire_continuation_if_needed(
                db,
                approval,
                revision,
            ):
                raise GithubApprovalError("continuation_request_expired")
            _root, linked = (
                await github_approval_service.ensure_continuation_request_message(
                    db,
                    item,
                    approval,
                    revision,
                )
            )
            if approval.status != "pending":
                raise GithubApprovalError("request_not_pending")
            if linked:
                await github_approval_service.nudge_pending_continuation_leader(
                    db,
                    approval,
                    revision,
                    cooldown=timedelta(
                        seconds=(
                            settings.github_continuation_leader_nudge_cooldown_seconds
                        )
                    ),
                )
        return GithubContinuationRequestResponse(
            approval=_approval_authority_response(approval),
            revision=_scope_revision_response(revision),
        )
    except GithubApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except GithubAppAuthError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    except GithubClientResponseError as exc:
        raise HTTPException(status_code=409, detail="github_snapshot_invalid") from exc
    except MailAuthorityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except MailDeliveryIntegrityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="github_snapshot_failed") from exc


@router.get(
    "/github-work-items/{item_id}/scope-revisions",
    response_model=list[GithubScopeRevisionResponse],
)
async def list_github_work_item_scope_revisions(
    item_id: int,
    principal: MailAgentSession | None = Depends(require_mail_session_or_operator),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work_item_not_found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="scope_not_found")
    if principal is not None and principal.team_preset_id != scope.preset_id:
        raise HTTPException(status_code=403, detail="not_team_member")
    revisions = (
        await db.execute(
            select(GithubAttemptScopeRevision)
            .where(GithubAttemptScopeRevision.work_item_id == item.id)
            .order_by(
                GithubAttemptScopeRevision.dispatch_nonce,
                GithubAttemptScopeRevision.revision,
            )
        )
    ).scalars().all()
    revision_ids = [revision.id for revision in revisions]
    approvals = (
        (
            await db.execute(
                select(GithubApprovalRequest).where(
                    GithubApprovalRequest.scope_revision_id.in_(revision_ids)
                )
            )
        )
        .scalars()
        .all()
        if revision_ids
        else []
    )
    approval_by_revision_id = {
        approval.scope_revision_id: approval
        for approval in approvals
        if approval.scope_revision_id is not None
    }
    return [
        _scope_revision_response(
            revision,
            include_commands=(
                principal is None
                or (
                    principal.member_id == revision.owner_member_id
                    and principal.team_slot_id == revision.owner_slot_id
                    and item.owner_slot_id == revision.owner_slot_id
                )
            ),
            approval=approval_by_revision_id.get(revision.id),
        )
        for revision in revisions
    ]


@router.post(
    "/github-work-items/{item_id}/continuation-requests/{request_id}/cancel",
    response_model=GithubApprovalRequestResponse,
)
async def cancel_github_work_item_continuation_request(
    item_id: int,
    request_id: int,
    principal: MailAgentSession | None = Depends(require_mail_session_or_operator),
    db: AsyncSession = Depends(get_db),
):
    approval = await db.get(GithubApprovalRequest, request_id)
    if (
        approval is None
        or approval.work_item_id != item_id
        or approval.request_kind != "continuation"
    ):
        raise HTTPException(status_code=404, detail="approval_request_not_found")
    try:
        if principal is None:
            cancelled, _changed = await github_approval_service._cancel_authorized(
                db,
                approval,
            )
        else:
            cancelled, _changed = await github_approval_service.cancel(
                db,
                approval,
                requester_member_id=principal.member_id,
            )
        return _approval_authority_response(cancelled)
    except GithubApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/github-work-items/{item_id}/scope-revisions/{revision_number}/cancel",
    response_model=GithubWorkItemResponse,
)
async def cancel_active_github_work_item_scope_revision(
    item_id: int,
    revision_number: int,
    request: GithubActiveContinuationCancelRequest,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work_item_not_found")
    try:
        await github_approval_service.cancel_active_continuation(
            db,
            item,
            revision_number=revision_number,
            dispatch_nonce=request.dispatch_nonce,
            reason=request.reason,
        )
    except GithubApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except MailDeliveryIntegrityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return await _reload_work_item_response(db, item.id)


@router.post(
    "/github-work-items/{item_id}/scope-revisions/{revision_number}/ack",
    response_model=GithubWorkItemResponse,
)
async def acknowledge_github_work_item_scope_revision(
    item_id: int,
    revision_number: int,
    request: GithubContinuationAckRequest,
    session: MailAgentSession | None = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    if session is None:
        raise HTTPException(status_code=401, detail="session_token_required")
    slot_id = require_session_slot(session)
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work_item_not_found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="scope_not_found")
    revision = (
        await db.execute(
            select(GithubAttemptScopeRevision).where(
                GithubAttemptScopeRevision.work_item_id == item.id,
                GithubAttemptScopeRevision.dispatch_nonce == request.dispatch_nonce,
                GithubAttemptScopeRevision.revision == revision_number,
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=404, detail="scope_revision_not_found")
    try:
        await github_dispatch_service.activate_continuation_revision(
            db,
            item,
            scope,
            revision,
            authenticated_owner_member_id=session.member_id,
            authenticated_owner_slot_id=slot_id,
            dispatch_nonce=request.dispatch_nonce,
            lease_token=request.lease_token,
        )
    except GithubAppAuthError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    except GithubClientResponseError as exc:
        raise HTTPException(status_code=409, detail="github_snapshot_invalid") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="github_snapshot_failed") from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 403 if detail in {"not_item_owner", "lease_token_mismatch"} else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return await _reload_work_item_response(db, item.id)


@router.post(
    "/github-work-items/{item_id}/claim-continuation",
    response_model=GithubWorkItemContinuationResponse,
)
async def claim_github_work_item_continuation(
    item_id: int,
    response: Response,
    session: MailAgentSession | None = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    if not settings.mail_capability_tokens_required:
        raise HTTPException(status_code=409, detail="tokens_not_enforced")
    if session is None:
        raise HTTPException(status_code=401, detail="session_token_required")
    slot_id = require_session_slot(session)
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work item not found")
    if item.owner_slot_id != slot_id:
        raise HTTPException(status_code=403, detail="not_item_owner")
    owner_member = await github_dispatch_service._owner_member(db, item)
    if owner_member is None or owner_member.id != session.member_id:
        raise HTTPException(status_code=403, detail="not_item_owner")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    workspace = await github_workspace_service.get_leased_workspace(db, item.id)
    if workspace is not None:
        if session.bound_pane_pid is None or session.bound_pane_proc_start is None:
            raise HTTPException(status_code=403, detail="bind_unverifiable")
        now = datetime.utcnow()
        current_member = aliased(MailTeamMember)
        newer_member = aliased(MailTeamMember)
        current_owner_exists = exists(
            select(GithubWorkItem.id).where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.owner_slot_id == slot_id,
                exists(
                    select(current_member.id).where(
                        current_member.id == session.member_id,
                        current_member.team_slot_id == slot_id,
                        ~exists(
                            select(newer_member.id).where(
                                newer_member.team_slot_id == current_member.team_slot_id,
                                or_(
                                    newer_member.updated_at > current_member.updated_at,
                                    and_(
                                        newer_member.updated_at
                                        == current_member.updated_at,
                                        newer_member.id > current_member.id,
                                    ),
                                ),
                            )
                        ),
                    )
                ),
            )
        )
        claimed = await db.execute(
            update(GithubWorkspace)
            .where(
                GithubWorkspace.id == workspace.id,
                GithubWorkspace.scope_id == item.scope_id,
                GithubWorkspace.leased_item_id == item.id,
                GithubWorkspace.lease_token == workspace.lease_token,
                current_owner_exists,
            )
            .values(
                leased_owner_pid=session.bound_pane_pid,
                leased_owner_proc_start=session.bound_pane_proc_start,
                lease_last_owner_contact_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            raise HTTPException(status_code=409, detail="continuation_context_changed")
    leader = github_dispatch_service._leader_slot(
        list(
            (
                await db.execute(
                    select(AgentTeamSlot)
                    .where(AgentTeamSlot.preset_id == scope.preset_id)
                    .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                )
            ).scalars().all()
        )
    )
    leader_member = (
        await github_dispatch_service._slot_member(db, leader.id)
        if leader is not None
        else None
    )
    active_revision = None
    if item.active_scope_revision > 0 and item.dispatch_nonce is not None:
        active_revision = (
            await db.execute(
                select(GithubAttemptScopeRevision).where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == item.dispatch_nonce,
                    GithubAttemptScopeRevision.revision == item.active_scope_revision,
                )
            )
        ).scalar_one_or_none()
    pending_approval = (
        await db.execute(
            select(GithubApprovalRequest).where(
                GithubApprovalRequest.work_item_id == item.id,
                GithubApprovalRequest.status == "pending",
            )
        )
    ).scalar_one_or_none()
    pending_revision = None
    if pending_approval is not None and pending_approval.scope_revision_id is not None:
        pending_revision = await db.get(
            GithubAttemptScopeRevision,
            pending_approval.scope_revision_id,
        )
    elif active_revision is None:
        pending_revision = (
            await db.execute(
                select(GithubAttemptScopeRevision)
                .where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == item.dispatch_nonce,
                    GithubAttemptScopeRevision.status == "approved",
                )
                .order_by(GithubAttemptScopeRevision.revision.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    revision_count, failed_head_count = (
        await db.execute(
            select(
                func.count(GithubAttemptScopeRevision.id),
                func.coalesce(func.sum(GithubAttemptScopeRevision.failed_head_count), 0),
            ).where(
                GithubAttemptScopeRevision.work_item_id == item.id,
                GithubAttemptScopeRevision.dispatch_nonce == item.dispatch_nonce,
            )
        )
    ).one()
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
    elif workspace is None:
        continuation_block_code = "workspace_lease_required"
    elif (
        revision_count >= scope.max_continuation_revisions
        or failed_head_count >= scope.max_continuation_failed_heads
    ):
        continuation_block_code = "continuation_budget_exhausted"
    else:
        continuation_block_code = None
    result = GithubWorkItemContinuationResponse(
        work_item_id=item.id,
        issue_number=item.issue_number,
        issue_title=item.issue_title,
        issue_url=item.issue_url,
        issue_type=item.issue_type,
        repo_owner=scope.repo_owner,
        repo_name=scope.repo_name,
        dispatch_status=item.dispatch_status,
        attempt_phase=item.attempt_phase,
        active_scope_revision=item.active_scope_revision,
        approval_round_count=item.approval_round_count,
        dispatch_nonce=item.dispatch_nonce,
        dispatch_head_ref=item.dispatch_head_ref,
        workspace_path=workspace.path if workspace is not None else None,
        lease_token=workspace.lease_token if workspace is not None else None,
        leader_member_id=leader_member.id if leader_member is not None else None,
        status_note=item.status_note,
        active_revision=(
            _scope_revision_response(active_revision)
            if active_revision is not None
            else None
        ),
        pending_approval=(
            _approval_authority_response(pending_approval)
            if pending_approval is not None
            else None
        ),
        pending_revision=(
            _scope_revision_response(pending_revision)
            if pending_revision is not None
            else None
        ),
        continuation_block_code=continuation_block_code,
        continuation_budget={
            "max_revisions": scope.max_continuation_revisions,
            "used_revisions": int(revision_count),
            "max_failed_heads": scope.max_continuation_failed_heads,
            "used_failed_heads": int(failed_head_count),
            "max_failed_heads_per_revision": scope.max_failed_heads_per_revision,
            "max_paths": scope.max_scope_paths,
            "max_commands": scope.max_scope_commands,
        },
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/presets", response_model=AgentTeamPresetListResponse)
async def list_presets(db: AsyncSession = Depends(get_db)):
    return AgentTeamPresetListResponse(presets=await agent_team_service.list_presets(db))


@router.post("/presets", response_model=AgentTeamPresetResponse)
async def create_preset(
    request: AgentTeamPresetCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.create_preset(db, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/from-agent-mail", response_model=AgentTeamPresetResponse)
async def create_preset_from_agent_mail(
    request: AgentTeamCreateFromMailRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.create_from_agent_mail(db, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/from-agent-bridge", response_model=AgentTeamPresetResponse)
async def create_preset_from_agent_bridge(
    request: AgentTeamCreateFromBridgeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.create_from_agent_bridge(db, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/presets/{preset_id}", response_model=AgentTeamPresetResponse)
async def get_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_team_service.get_preset(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/presets/{preset_id}", response_model=AgentTeamPresetResponse)
async def update_preset(
    preset_id: int,
    request: AgentTeamPresetUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        response = await agent_team_service.update_preset(
            db,
            preset_id,
            name=request.name,
            description=request.description,
            autonomy_enabled=request.autonomy_enabled,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if request.autonomy_enabled is not None:
        await _sync_github_jobs(db)
    return response


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await agent_team_service.delete_preset(db, preset_id)
        await _sync_github_jobs(db)
        return Response(status_code=204)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/presets/{preset_id}/github-scopes",
    response_model=TeamGithubScopeListResponse,
)
async def list_github_scopes(preset_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await agent_team_service.require_preset_row(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scopes = (
        await db.execute(
            select(TeamGithubScope)
            .where(TeamGithubScope.preset_id == preset_id)
            .order_by(TeamGithubScope.repo_owner, TeamGithubScope.repo_name, TeamGithubScope.id)
        )
    ).scalars().all()
    return TeamGithubScopeListResponse(scopes=[_scope_response(scope) for scope in scopes])


@router.post(
    "/presets/{preset_id}/github-scopes",
    response_model=TeamGithubScopeResponse,
)
async def create_github_scope(
    preset_id: int,
    request: TeamGithubScopeCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        await agent_team_service.require_preset_row(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        scope = TeamGithubScope(
            preset_id=preset_id,
            repo_owner="",
            repo_name="",
            repo_path="",
        )
        _apply_scope_create(scope, request)
        db.add(scope)
        await db.commit()
        await db.refresh(scope)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="GitHub scope already exists for this repo") from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc
    await _sync_github_jobs(db)
    return _scope_response(scope)


@router.patch("/github-scopes/{scope_id}", response_model=TeamGithubScopeResponse)
async def update_github_scope(
    scope_id: int,
    request: TeamGithubScopeUpdate,
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    identity_change = any(
        value is not None
        for value in (
            request.repo_owner,
            request.repo_name,
            request.repo_path,
            request.base_ref,
        )
    )
    if identity_change:
        if await _scope_identity_in_use(db, scope_id):
            raise HTTPException(status_code=409, detail="scope_identity_in_use")
    try:
        _apply_scope_create(scope, request)
        await db.commit()
        await db.refresh(scope)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="GitHub scope already exists for this repo") from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc
    await _sync_github_jobs(db)
    return _scope_response(scope)


@router.patch(
    "/github-scopes/{scope_id}/continuation-policy",
    response_model=TeamGithubScopeResponse,
)
async def update_github_scope_continuation_policy(
    scope_id: int,
    request: TeamGithubContinuationPolicyUpdate,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    scope.continuation_enabled = request.continuation_enabled
    scope.max_continuation_revisions = request.max_continuation_revisions
    scope.max_continuation_failed_heads = request.max_continuation_failed_heads
    scope.max_failed_heads_per_revision = request.max_failed_heads_per_revision
    scope.max_scope_paths = request.max_scope_paths
    scope.max_scope_commands = request.max_scope_commands
    await db.commit()
    await db.refresh(scope)
    return _scope_response(scope)


@router.delete("/github-scopes/{scope_id}", status_code=204)
async def delete_github_scope(scope_id: int, db: AsyncSession = Depends(get_db)):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    if await _scope_identity_in_use(db, scope_id):
        raise HTTPException(status_code=409, detail="scope_identity_in_use")
    await db.delete(scope)
    await db.commit()
    await _sync_github_jobs(db)
    return Response(status_code=204)


@router.get(
    "/github-scopes/{scope_id}/workspaces",
    response_model=GithubWorkspaceListResponse,
)
async def list_github_workspaces(
    scope_id: int,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    workspaces = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope_id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().all()
    return GithubWorkspaceListResponse(
        workspaces=[_workspace_response(workspace) for workspace in workspaces]
    )


@router.post(
    "/github-scopes/{scope_id}/workspaces",
    response_model=GithubWorkspaceResponse,
    status_code=201,
)
async def create_github_workspace(
    scope_id: int,
    request: GithubWorkspaceCreate,
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    if request.kind not in {"primary", "worktree"}:
        raise HTTPException(status_code=400, detail="Workspace kind must be primary or worktree")
    try:
        path, _ = agent_team_service.normalize_repo_path(request.path)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    existing = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.path == path))
    ).scalar_one_or_none()
    if existing is not None:
        raise _conflict(
            "Workspace path already registered",
            block_code="workspace_path_registered",
        )
    dispatchable = (
        request.dispatchable
        if request.dispatchable is not None
        else request.kind == "worktree"
    )
    try:
        workspace = await github_workspace_service.register_workspace(
            db,
            scope,
            path,
            kind=request.kind,
            dispatchable=dispatchable,
            enabled=request.enabled,
        )
    except GithubWorkspaceError as exc:
        block_code = (
            exc.block_code
            if exc.block_code in _WORKSPACE_CONFLICT_CODES
            else "workspace_not_a_worktree"
        )
        raise _conflict(str(exc), block_code=block_code) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict(
            "Workspace path already registered",
            block_code="workspace_path_registered",
        ) from exc
    return _workspace_response(workspace)


@router.post(
    "/github-scopes/{scope_id}/workspaces/{workspace_id}/reprobe",
    response_model=GithubWorkspaceResponse,
)
async def reprobe_github_workspace(
    scope_id: int,
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    workspace = await db.get(GithubWorkspace, workspace_id)
    if workspace is None or workspace.scope_id != scope_id:
        raise HTTPException(status_code=404, detail="GitHub workspace not found")
    if workspace.leased_item_id is not None:
        raise _conflict(
            "Workspace is currently leased",
            block_code="workspace_leased",
        )
    if workspace.kind == "primary":
        raise _conflict(
            "Primary workspaces are never reset",
            block_code="workspace_is_primary",
        )
    was_enabled = workspace.enabled
    try:
        await github_workspace_service.reset_workspace(db, scope, workspace)
    except GithubWorkspaceResetError as exc:
        workspace.enabled = was_enabled if exc.transient else False
        workspace.provision_error = str(exc)
        workspace.updated_at = datetime.utcnow()
        await db.commit()
        raise _conflict(str(exc), block_code="workspace_reset_failed") from exc
    workspace.enabled = True
    workspace.provision_error = None
    workspace.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(workspace)
    return _workspace_response(workspace)


@router.post(
    "/github-scopes/{scope_id}/workspaces/{workspace_id}/force-release",
    response_model=GithubWorkspaceForceReleaseResponse,
)
async def force_release_github_workspace(
    scope_id: int,
    workspace_id: int,
    request: GithubWorkspaceForceReleaseRequest,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    workspace = await db.get(GithubWorkspace, workspace_id)
    if workspace is None or workspace.scope_id != scope_id:
        raise HTTPException(status_code=404, detail="GitHub workspace not found")
    if workspace.leased_item_id is None:
        raise _conflict(
            "Workspace is not leased",
            block_code="workspace_not_leased",
        )

    released_item_id = workspace.leased_item_id
    inspected_lease_token = workspace.lease_token

    discarded_paths, unpushed_commits = await github_workspace_service.pending_work(
        scope, workspace
    )

    try:
        released = await github_workspace_service.force_release_acquisition(
            db,
            workspace_id=workspace_id,
            scope_id=scope_id,
            item_id=released_item_id,
            expected_leased_at=request.expected_leased_at,
            lease_token=inspected_lease_token,
        )
    except GithubWorkspaceCredentialRevokeError as exc:
        raise HTTPException(status_code=503, detail=exc.block_code) from exc
    if not released:
        await db.refresh(workspace)
        if workspace.leased_item_id is None:
            current = "the workspace is no longer leased"
        else:
            current = f"it now reports leased_at {workspace.leased_at.isoformat()}"
        raise _conflict(
            "The workspace lease changed between inspection and release, so "
            f"nothing was released. You confirmed leased_at "
            f"{request.expected_leased_at.isoformat()}, but {current}. "
            "Refresh the workspace and confirm again.",
            block_code="lease_changed",
        )

    logger.warning(
        "force-release workspace %s (item %s) by %s: %s; discarding: %s dirty "
        "path(s), %s unpushed commit(s)",
        workspace_id,
        released_item_id,
        request.requested_by or "unknown",
        request.reason,
        len((discarded_paths or "").splitlines()),
        unpushed_commits if unpushed_commits is not None else "unknown",
    )
    await db.refresh(workspace)
    return GithubWorkspaceForceReleaseResponse(
        workspace=_workspace_response(workspace),
        released_item_id=released_item_id,
        discarded_paths=discarded_paths,
        unpushed_commits=unpushed_commits,
    )


@router.get(
    "/presets/{preset_id}/github-work-items",
    response_model=GithubWorkItemListResponse,
)
async def list_github_work_items(
    preset_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    try:
        await agent_team_service.require_preset_row(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rows = (
        await db.execute(
            select(GithubWorkItem, TeamGithubScope, GithubWorkspace.path)
            .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
            .outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
            .where(TeamGithubScope.preset_id == preset_id)
            .order_by(GithubWorkItem.updated_at.desc(), GithubWorkItem.id.desc())
            .limit(limit)
        )
    ).all()
    authority_by_item = await _load_work_item_authority(
        db,
        [item for item, _scope, _workspace_path in rows],
    )
    return GithubWorkItemListResponse(
        items=[
            _work_item_response(
                item,
                scope,
                workspace_path,
                active_revision=authority_by_item[item.id].active_revision,
                pending_approval=authority_by_item[item.id].pending_approval,
                pending_revision=authority_by_item[item.id].pending_revision,
                continuation_revision_count=authority_by_item[item.id].revision_count,
                continuation_failed_head_count=authority_by_item[item.id].failed_head_count,
            )
            for item, scope, workspace_path in rows
        ]
    )


@router.post(
    "/github-work-items/{work_item_id}/retry",
    response_model=GithubWorkItemResponse,
)
async def retry_github_work_item(
    work_item_id: int,
    request: GithubWorkItemRetryRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    authority = (await _load_work_item_authority(db, [item]))[item.id]
    eligibility = github_dispatch_service.retry_eligibility(
        item,
        pending_approval=authority.pending_approval is not None,
    )
    if not eligibility.allowed:
        raise _retry_conflict(item, eligibility.block_code or "retry_blocked")
    await github_dispatch_service.reset_for_retry(db, item)
    if request is not None and request.reason:
        item.pending_reason = f"retry requested: {request.reason}"
    await db.commit()
    return await _reload_work_item_response(db, item.id)


@router.post(
    "/presets/{preset_id}/work-items/{item_id}/resume-attempt",
    response_model=GithubWorkItemResponse,
)
async def resume_github_work_item_attempt(
    preset_id: int,
    item_id: int,
    request: GithubWorkItemResumeAttemptRequest,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    try:
        await agent_team_service.require_preset_row(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None or scope.preset_id != preset_id:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    slots = (
        await db.execute(
            select(AgentTeamSlot)
            .where(AgentTeamSlot.preset_id == preset_id)
            .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
        )
    ).scalars().all()
    try:
        await github_dispatch_service.resume_prepared_attempt(
            db,
            item,
            scope,
            list(slots),
            reassign_to_slot_id=request.reassign_to_slot_id,
        )
    except ResumeAttemptError as exc:
        raise _conflict(str(exc), exc.block_code) from exc
    return await _reload_work_item_response(db, item.id)


@router.post(
    "/github-work-items/{work_item_id}/abandon",
    response_model=GithubWorkItemResponse,
)
async def abandon_github_work_item(
    work_item_id: int,
    request: GithubWorkItemAbandonRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    if item.dispatch_status not in {
        "ready_for_review",
        "awaiting_human_review",
        "dispatched",
        "verifying",
    }:
        raise _conflict(
            f"Work item in status {item.dispatch_status} cannot be abandoned",
            block_code="work_item_not_abandonable",
        )
    note = (
        request.reason
        if request is not None and request.reason
        else (
            "Abandoned by operator; workspace lease will be reclaimed once the "
            "owner session is offline."
        )
    )
    await github_dispatch_service.escalate(
        db,
        item,
        "abandoned_by_operator",
        note=note,
    )
    await db.commit()
    return await _reload_work_item_response(db, item.id)


@router.post("/presets/{preset_id}/duplicate", response_model=AgentTeamPresetResponse)
async def duplicate_preset(
    preset_id: int,
    request: AgentTeamPresetUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.duplicate_preset(db, preset_id, name=request.name)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/{preset_id}/slots", response_model=AgentTeamPresetResponse)
async def add_slot(
    preset_id: int,
    request: AgentTeamSlotCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.add_slot(db, preset_id, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/slots/{slot_id}", response_model=AgentTeamPresetResponse)
async def update_slot(
    slot_id: int,
    request: AgentTeamSlotUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.update_slot(db, slot_id, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/slots/{slot_id}", response_model=AgentTeamPresetResponse)
async def delete_slot(slot_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_team_service.delete_slot(db, slot_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/{preset_id}/slots/reorder", response_model=AgentTeamPresetResponse)
async def reorder_slots(
    preset_id: int,
    request: AgentTeamSlotReorderRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.reorder_slots(db, preset_id, request.slot_ids)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/{preset_id}/plan-launch", response_model=AgentTeamLaunchPlan)
async def plan_launch(
    preset_id: int,
    request: AgentTeamLaunchRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.plan_launch(db, preset_id, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post(
    "/presets/{preset_id}/launch/plan",
    response_model=AgentTeamLaunchPlan,
    include_in_schema=False,
)
async def plan_launch_compat(
    preset_id: int,
    request: AgentTeamLaunchRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await plan_launch(preset_id, request, db)


@router.post("/presets/{preset_id}/launch", response_model=AgentTeamLaunchResult)
async def launch_preset(
    preset_id: int,
    request: AgentTeamLaunchRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.launch(db, preset_id, request)
    except PlanConflictError as exc:
        detail: dict[str, object] = {"message": str(exc)}
        if exc.plan is not None:
            detail["plan"] = jsonable_encoder(exc.plan)
        raise HTTPException(status_code=409, detail=detail) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc
