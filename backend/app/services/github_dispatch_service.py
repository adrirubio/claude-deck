"""Routing and dispatch lifecycle for autonomous GitHub dispatch."""
from __future__ import annotations

import enum
import hmac
import logging
import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import (
    AgentPaneBinding,
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkspace,
    MailReceipt,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.models.schemas import AgentTeamLaunchRequest
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service
from app.services.agent_team_service import agent_team_service
from app.services.github_app_auth_service import (
    GithubAppAuthError,
    github_app_auth_service,
)
from app.services.github_approval_service import (
    CONTINUABLE_ESCALATIONS,
    GithubApprovalError,
    github_approval_service,
)
from app.services.github_client import github_client
from app.services.github_workspace_service import (
    _RELEASABLE_STATUSES,
    GithubWorkspaceConfigError,
    GithubWorkspaceCredentialRevokeError,
    GithubWorkspaceRemoteError,
    github_workspace_service,
)

_BUSY_STATUSES = ("dispatched", "verifying")
_SCOPE_CONCURRENCY_STATUSES = ("dispatched", "verifying")
_LAUNCH_FAILED_STATUSES = {
    "failed",
    "blocked",
    "blocked_provider_unavailable",
    "blocked_agent_mail_not_configured",
    "skipped_disabled",
}
_ATTEMPT_MARKERS = ("dispatch_nonce", "dispatch_head_ref", "dispatch_base_ref")

DISPATCH_STATUSES = frozenset(
    {
        "pending",
        "dispatched",
        "verifying",
        "ready_for_review",
        "awaiting_human_review",
        "merged",
        "completed",
        "escalated",
        "failed",
    }
)

ESCALATION_REASONS = frozenset(
    {
        "plan_blocked",
        "launch_outcome_unknown",
        "approval_rounds_exhausted",
        "leader_offline",
        "owner_offline",
        "brief_unread",
        "leader_ack_timeout",
        "owner_idle_timeout",
        "retry_count_exhausted",
        "continuation_budget_exhausted",
        "continuation_invalid_state",
        "continuation_pr_identity_invalid",
        "dispatch_label_removed",
        "abandoned_by_operator",
        "prepared_owner_unavailable",
        "pr_closed_unmerged",
    }
)

PENDING_REASONS = frozenset(
    {
        "queued_repo_cap",
        "queued_low_memory",
        "queued_slot_busy",
        "queued_ambiguous_sessions",
        "queued_no_workspace",
        "queued_auth_mode_unresolved",
    }
)

logger = logging.getLogger(__name__)


class AttemptState(enum.Enum):
    UNPREPARED = "unprepared"
    PREPARED = "prepared"


class PartiallyPreparedAttempt(ValueError):
    def __init__(self, item_id: int, detail: str):
        self.item_id = item_id
        self.detail = detail
        super().__init__(f"work item {item_id} has a partial dispatch attempt: {detail}")


class ResumeAttemptError(ValueError):
    def __init__(self, block_code: str, detail: str):
        self.block_code = block_code
        super().__init__(detail)


class GithubAuthModeUnresolved(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedAttempt:
    owner_slot_id: int
    routing_method: str
    dispatch_nonce: str
    dispatch_head_ref: str
    dispatch_base_ref: str
    approval_round: int


@dataclass(frozen=True)
class AckEvidence:
    ok: bool
    reason: str
    approver_member_id: int | None = None
    evidence_message_id: int | None = None
    approval_round: int | None = None


@dataclass(frozen=True)
class RetryEligibility:
    allowed: bool
    block_code: str | None = None


def attempt_state(item: GithubWorkItem) -> AttemptState:
    markers = [getattr(item, column) for column in _ATTEMPT_MARKERS]
    if all(marker is None for marker in markers) and item.approval_round_count == 0:
        return AttemptState.UNPREPARED
    markers_complete = (
        all(marker is not None for marker in markers)
        and item.approval_round_count >= 1
    )
    identity_complete = item.owner_slot_id is not None and bool(item.routing_method)
    if markers_complete and identity_complete:
        return AttemptState.PREPARED
    raise PartiallyPreparedAttempt(
        item.id,
        f"nonce={markers[0] is not None} head={markers[1] is not None} "
        f"base={markers[2] is not None} "
        f"round={item.approval_round_count} owner={item.owner_slot_id} "
        f"routing={item.routing_method!r}",
    )


def attempt_head_ref(item: GithubWorkItem, owner_slot_id: int) -> str:
    if item.dispatch_nonce is None:
        raise PartiallyPreparedAttempt(item.id, "head requested before nonce mint")
    return (
        f"deck/slot-{owner_slot_id}/issue-{item.issue_number}-"
        f"{item.dispatch_nonce}"
    )


def prepared_attempt_from_row(item: GithubWorkItem) -> PreparedAttempt:
    if attempt_state(item) is not AttemptState.PREPARED:
        raise AssertionError("attempt state changed during prepared-row validation")
    owner_slot_id = item.owner_slot_id
    routing_method = item.routing_method
    dispatch_nonce = item.dispatch_nonce
    dispatch_head_ref = item.dispatch_head_ref
    dispatch_base_ref = item.dispatch_base_ref
    if (
        owner_slot_id is None
        or not routing_method
        or dispatch_nonce is None
        or dispatch_head_ref is None
        or dispatch_base_ref is None
    ):
        raise PartiallyPreparedAttempt(item.id, "prepared attempt fields became incomplete")
    return PreparedAttempt(
        owner_slot_id=owner_slot_id,
        routing_method=routing_method,
        dispatch_nonce=dispatch_nonce,
        dispatch_head_ref=dispatch_head_ref,
        dispatch_base_ref=dispatch_base_ref,
        approval_round=item.approval_round_count,
    )


class GithubDispatchService:
    @staticmethod
    def retry_eligibility(
        item: GithubWorkItem,
        *,
        pending_approval: bool,
    ) -> RetryEligibility:
        if item.dispatch_status != "escalated":
            return RetryEligibility(False, "not_escalated")
        if item.active_scope_revision > 0:
            return RetryEligibility(False, "active_continuation")
        if pending_approval:
            return RetryEligibility(False, "approval_pending")
        if item.pr_number is not None:
            return RetryEligibility(False, "pr_preserved")
        return RetryEligibility(True)

    async def activate_continuation_revision(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        revision: GithubAttemptScopeRevision,
        *,
        authenticated_owner_member_id: int,
        authenticated_owner_slot_id: int,
        dispatch_nonce: str,
        lease_token: str,
    ) -> bool:
        await db.refresh(item)
        await db.refresh(revision)
        if item.scope_id != scope.id or revision.work_item_id != item.id:
            raise ValueError("scope_revision_not_found")
        if item.dispatch_nonce != dispatch_nonce or revision.dispatch_nonce != dispatch_nonce:
            raise ValueError("stale_nonce")
        owner = await self._owner_member(db, item)
        if (
            owner is None
            or owner.id != authenticated_owner_member_id
            or item.owner_slot_id != authenticated_owner_slot_id
            or revision.owner_member_id != authenticated_owner_member_id
            or revision.owner_slot_id != authenticated_owner_slot_id
        ):
            raise ValueError("not_item_owner")
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if (
            workspace is None
            or workspace.id != revision.expected_workspace_id
            or workspace.lease_token is None
        ):
            raise ValueError("workspace_lease_changed")
        if not hmac.compare_digest(workspace.lease_token, lease_token):
            raise ValueError("lease_token_mismatch")
        if not github_approval_service.lease_token_matches(
            lease_token,
            revision.expected_lease_token_hash,
        ):
            raise ValueError("workspace_lease_changed")
        if (
            revision.status == "active"
            and item.active_scope_revision == revision.revision
            and item.attempt_phase == revision.phase
            and item.dispatch_status == "dispatched"
        ):
            return False
        now = datetime.utcnow()
        if (
            revision.status == "expired"
            or revision.expires_at is not None
            and revision.expires_at <= now
        ):
            raise ValueError("continuation_request_expired")
        if revision.status != "approved":
            raise ValueError("continuation_not_approved")
        if revision.delivery_message_id is None or revision.delivered_at is None:
            raise ValueError("continuation_delivery_pending")
        if item.dispatch_status != "escalated":
            raise ValueError("continuation_not_escalated")
        if item.escalation_reason != revision.originating_escalation_reason:
            raise ValueError("continuation_escalation_changed")
        if item.pr_number is None:
            raise ValueError("continuation_pr_required")

        token = await github_approval_service.github_read_token(scope)
        pull = await github_client.get_pull(
            scope.repo_owner,
            scope.repo_name,
            item.pr_number,
            token=token,
        )
        if pull.get("state") != "open":
            raise ValueError("continuation_pr_not_open")
        head = pull.get("head")
        head_sha = head.get("sha") if isinstance(head, dict) else None
        snapshot = await github_client.get_commit_snapshot(
            scope.repo_owner,
            scope.repo_name,
            head_sha,
            token=token,
        )
        if snapshot.sha != revision.baseline_head_sha:
            raise ValueError("continuation_head_changed")

        item_result = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status == "escalated",
                GithubWorkItem.dispatch_nonce == dispatch_nonce,
                GithubWorkItem.owner_slot_id == authenticated_owner_slot_id,
                GithubWorkItem.pr_number.is_not(None),
                GithubWorkItem.escalation_reason
                == revision.originating_escalation_reason,
                GithubWorkItem.active_scope_revision < revision.revision,
            )
            .values(
                active_scope_revision=revision.revision,
                attempt_phase=revision.phase,
                dispatch_status="dispatched",
                continuation_activated_at=now,
                continuation_nudged_at=None,
                pending_reason=None,
                escalation_reason=None,
                last_nudge_at=None,
                status_note=(
                    f"Active continuation revision {revision.revision}: "
                    f"{revision.summary}"
                ),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        revision_result = await db.execute(
            update(GithubAttemptScopeRevision)
            .where(
                GithubAttemptScopeRevision.id == revision.id,
                GithubAttemptScopeRevision.status == "approved",
                GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                GithubAttemptScopeRevision.owner_slot_id
                == authenticated_owner_slot_id,
                GithubAttemptScopeRevision.owner_member_id
                == authenticated_owner_member_id,
                GithubAttemptScopeRevision.expected_workspace_id == workspace.id,
            )
            .values(status="active", acknowledged_at=now)
            .execution_options(synchronize_session=False)
        )
        workspace_result = await db.execute(
            update(GithubWorkspace)
            .where(
                GithubWorkspace.id == workspace.id,
                GithubWorkspace.scope_id == scope.id,
                GithubWorkspace.leased_item_id == item.id,
                GithubWorkspace.lease_token == lease_token,
                exists(
                    select(GithubWorkItem.id).where(
                        GithubWorkItem.id == item.id,
                        GithubWorkItem.owner_slot_id == authenticated_owner_slot_id,
                        GithubWorkItem.dispatch_nonce == dispatch_nonce,
                    )
                ),
            )
            .values(lease_last_owner_contact_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            update(MailReceipt)
            .where(
                MailReceipt.message_id == revision.delivery_message_id,
                MailReceipt.member_id == authenticated_owner_member_id,
            )
            .values(
                read_at=func.coalesce(MailReceipt.read_at, now),
                acked_at=func.coalesce(MailReceipt.acked_at, now),
            )
            .execution_options(synchronize_session=False)
        )
        if (
            item_result.rowcount != 1
            or revision_result.rowcount != 1
            or workspace_result.rowcount != 1
        ):
            await db.rollback()
            raise ValueError("stale_continuation_context")
        await db.commit()
        await db.refresh(item)
        await db.refresh(revision)
        return True

    async def _resolve_scope_auth_mode(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
    ) -> str:
        mode = scope.github_auth_mode
        installation_id = scope.github_app_installation_id
        if mode not in {"unknown", "app", "ambient"}:
            raise GithubAuthModeUnresolved(f"Unsupported GitHub auth mode: {mode}")
        if mode in {"unknown", "ambient"} and installation_id is not None:
            scope.github_app_installation_id = None
            scope.updated_at = datetime.utcnow()
            await db.commit()
            installation_id = None
        if mode == "ambient":
            return mode
        if mode == "app":
            if installation_id is None:
                raise GithubAuthModeUnresolved(
                    "Stored App authentication has no installation id"
                )
            try:
                github_app_auth_service.require_configuration(require_bot_login=True)
            except GithubAppAuthError as exc:
                raise GithubAuthModeUnresolved(str(exc)) from exc
            return mode

        app_id = settings.github_app_id
        key_path = settings.github_app_private_key_path
        bot_login = settings.github_app_bot_login
        if not app_id and not key_path:
            scope.github_auth_mode = "ambient"
            scope.github_app_installation_id = None
            scope.updated_at = datetime.utcnow()
            await db.commit()
            return "ambient"
        if not app_id or not key_path or not bot_login:
            raise GithubAuthModeUnresolved(
                "GitHub App settings are only partially configured"
            )
        try:
            github_app_auth_service.require_configuration(require_bot_login=True)
            resolved_id = await github_app_auth_service.resolve_installation(
                scope.repo_owner, scope.repo_name
            )
        except GithubAppAuthError as exc:
            raise GithubAuthModeUnresolved(str(exc)) from exc
        scope.github_auth_mode = "app" if resolved_id is not None else "ambient"
        scope.github_app_installation_id = resolved_id
        scope.updated_at = datetime.utcnow()
        await db.commit()
        return scope.github_auth_mode

    async def _release_auth_refusal(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        workspace: GithubWorkspace,
        detail: str,
        *,
        keep_lease: bool = False,
    ) -> None:
        item.pending_reason = "queued_auth_mode_unresolved"
        item.status_note = f"GitHub authentication unresolved for {scope.repo_owner}/{scope.repo_name}: {detail}"
        item.updated_at = datetime.utcnow()
        if not keep_lease and workspace.leased_at is not None:
            try:
                await github_workspace_service.force_release_acquisition(
                    db,
                    workspace_id=workspace.id,
                    scope_id=scope.id,
                    item_id=item.id,
                    expected_leased_at=workspace.leased_at,
                    lease_token=workspace.lease_token,
                )
            except GithubWorkspaceCredentialRevokeError as exc:
                item.status_note = str(exc)
        await db.commit()

    async def reset_for_retry(self, db: AsyncSession, item: GithubWorkItem) -> None:
        """Request re-dispatch, deferring while the item still holds a lease.

        The deferred path must preserve the escalation reason because PR recovery
        and escalation idempotence both depend on it while the item remains
        escalated.
        """
        held = (
            await db.execute(
                select(GithubWorkspace).where(
                    GithubWorkspace.leased_item_id == item.id
                )
            )
        ).scalar_one_or_none()
        now = datetime.utcnow()
        if held is not None:
            item.retry_requested_at = now
            item.status_note = (
                "Re-dispatch requested; waiting for the current owner to release "
                f"workspace {held.path}."
            )
            item.updated_at = now
            return
        item.dispatch_status = "pending"
        item.escalation_reason = None
        item.pending_reason = None
        item.handoff_state = None
        item.handoff_target_slot_id = None
        item.pr_number = None
        for column in _ATTEMPT_MARKERS:
            setattr(item, column, None)
        item.ack_received_at = None
        item.ack_approver_member_id = None
        item.ack_evidence_message_id = None
        item.ack_enforcement_epoch = None
        item.ack_approval_round = None
        item.last_verified_sha = None
        item.retry_count = 0
        item.approval_round_count = 0
        item.retry_requested_at = None
        item.updated_at = now

    async def can_auto_retry_from_issue_update(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
    ) -> bool:
        if (
            item.pr_number is not None
            or item.active_scope_revision != 0
            or item.retry_requested_at is not None
        ):
            return False
        pending_approval = (
            await db.execute(
                select(GithubApprovalRequest.id)
                .where(
                    GithubApprovalRequest.work_item_id == item.id,
                    GithubApprovalRequest.status == "pending",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return pending_approval is None

    async def prepare_attempt(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        owner_slot_id: int,
        routing_method: str,
        base_ref: str,
    ) -> PreparedAttempt:
        state = attempt_state(item)
        if state is AttemptState.PREPARED:
            return prepared_attempt_from_row(item)
        item.owner_slot_id = owner_slot_id
        item.routing_method = routing_method
        item.dispatch_nonce = secrets.token_hex(8)
        item.dispatch_head_ref = attempt_head_ref(item, owner_slot_id)
        item.dispatch_base_ref = base_ref
        item.approval_round_count = 1
        item.updated_at = datetime.utcnow()
        await db.commit()
        return prepared_attempt_from_row(item)

    async def promote_deferred_retries(
        self, db: AsyncSession, scope: TeamGithubScope
    ) -> int:
        """Complete deferred retries whose workspace lease has been released."""
        candidates = (
            await db.execute(
                select(GithubWorkItem)
                .outerjoin(
                    GithubWorkspace,
                    GithubWorkspace.leased_item_id == GithubWorkItem.id,
                )
                .where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(("escalated", "failed")),
                    GithubWorkItem.retry_requested_at.is_not(None),
                    GithubWorkItem.pr_number.is_(None),
                    GithubWorkItem.active_scope_revision == 0,
                    ~exists(
                        select(GithubApprovalRequest.id).where(
                            GithubApprovalRequest.work_item_id == GithubWorkItem.id,
                            GithubApprovalRequest.status == "pending",
                        )
                    ),
                    GithubWorkspace.id.is_(None),
                )
                .order_by(GithubWorkItem.id)
            )
        ).scalars().all()
        for item in candidates:
            await self.reset_for_retry(db, item)
        if candidates:
            await db.commit()
        return len(candidates)

    async def route_item(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        preset_slots: list[AgentTeamSlot],
        issue_labels: list[str],
        classify=None,
    ) -> tuple[int | None, str]:
        enabled = [slot for slot in preset_slots if slot.enabled]
        enabled.sort(key=lambda slot: slot.position)
        if not enabled:
            return None, "leader_fallback"

        issue_label_set = set(issue_labels)
        for slot in enabled:
            slot_areas = set(slot.area_labels or [])
            if slot_areas & issue_label_set:
                return slot.id, "label"

        classifiable = [slot for slot in enabled if slot.expertise]
        if classifiable and classify is not None:
            chosen = await classify(item, classifiable)
            if chosen is not None:
                return chosen, "classified"

        return enabled[0].id, "leader_fallback"

    async def slot_is_busy(self, db: AsyncSession, slot_id: int) -> bool:
        active = (
            await db.execute(
                select(GithubWorkItem.id).where(
                    GithubWorkItem.owner_slot_id == slot_id,
                    GithubWorkItem.dispatch_status.in_(_BUSY_STATUSES),
                )
            )
        ).first()
        if active is not None:
            return True
        pending_handoff = (
            await db.execute(
                select(GithubWorkItem.id).where(
                    GithubWorkItem.handoff_state == "pending",
                    (GithubWorkItem.owner_slot_id == slot_id)
                    | (GithubWorkItem.handoff_target_slot_id == slot_id),
                )
            )
        ).first()
        return pending_handoff is not None

    async def scope_active_count(self, db: AsyncSession, scope_id: int) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(GithubWorkItem)
                    .where(
                        GithubWorkItem.scope_id == scope_id,
                        GithubWorkItem.dispatch_status.in_(_SCOPE_CONCURRENCY_STATUSES),
                    )
                )
            ).scalar_one()
        )

    def _available_memory_mb(self) -> int | None:
        try:
            with open("/proc/meminfo", encoding="utf-8") as meminfo:
                for line in meminfo:
                    name, separator, value = line.partition(":")
                    if name != "MemAvailable" or not separator:
                        continue
                    amount, unit = value.split()
                    if unit.lower() != "kb":
                        return None
                    return int(amount) // 1024
        except (OSError, ValueError):
            return None
        return None

    def _resolve_pane_pid(self, tmux_target: str | None) -> int | None:
        """Resolve a tmux target to its pane pid on a best-effort basis."""
        if not tmux_target:
            return None
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "-t", tmux_target, "#{pane_pid}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            logger.warning("could not resolve pane pid for %s", tmux_target)
            return None
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw.isdigit():
            logger.warning(
                "tmux returned no pane pid for %s (stdout=%r) — the lease will "
                "not be auto-reclaimable",
                tmux_target,
                raw,
            )
            return None
        return int(raw)

    async def dispatch_pending(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
        client=None,
        classify=None,
        launcher=None,
        issue_labels_by_number: dict[int, list[str]] | None = None,
        issue_details_by_number: dict[int, dict] | None = None,
    ) -> None:
        launcher = launcher or agent_team_service.launch
        issue_labels_by_number = issue_labels_by_number or {}
        issue_details_are_authoritative = issue_details_by_number is not None
        issue_details_by_number = issue_details_by_number or {}
        slots_by_id = {slot.id: slot for slot in preset_slots}
        slots_dispatched_this_batch: set[int] = set()
        scope_dispatched_this_batch = 0
        await github_workspace_service.reclaim_stale(db, scope)
        scope_active = await self.scope_active_count(db, scope.id)

        pending = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "pending",
                ).order_by(GithubWorkItem.created_at, GithubWorkItem.id)
            )
        ).scalars().all()

        for item in pending:
            issue_labels = issue_labels_by_number.get(item.issue_number, [])
            if issue_details_are_authoritative and (
                item.issue_number not in issue_details_by_number
                or scope.dispatch_label not in issue_labels
            ):
                note = (
                    f"Required dispatch label `{scope.dispatch_label}` is absent "
                    "or could not be verified while the item was pending. This poll "
                    "did not acquire a workspace or launch an agent."
                )
                if any(getattr(item, marker) is not None for marker in _ATTEMPT_MARKERS):
                    note += (
                        " This item has prepared dispatch-attempt state, so its "
                        "workspace may still be leased and its agent pane may still "
                        "be live. Do NOT retry or release the workspace until the "
                        "owner is confirmed stopped."
                    )
                await self.escalate(
                    db,
                    item,
                    "dispatch_label_removed",
                    note,
                )
                await db.commit()
                continue
            if scope_active + scope_dispatched_this_batch >= scope.max_concurrent_dispatched:
                item.pending_reason = "queued_repo_cap"
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
            available_memory_mb = self._available_memory_mb()
            if (
                available_memory_mb is not None
                and available_memory_mb < settings.github_min_available_memory_mb
            ):
                item.pending_reason = "queued_low_memory"
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
            try:
                state = attempt_state(item)
            except PartiallyPreparedAttempt as exc:
                await self.escalate(db, item, "plan_blocked", exc.detail)
                await db.commit()
                continue
            if state is AttemptState.PREPARED:
                prepared = prepared_attempt_from_row(item)
                owner_slot_id = prepared.owner_slot_id
                method = prepared.routing_method
                owner_slot = slots_by_id.get(owner_slot_id)
                if owner_slot is None or not owner_slot.enabled:
                    await self._escalate_prepared_owner_unavailable(
                        db, item, owner_slot
                    )
                    continue
            else:
                owner_slot_id, method = await self.route_item(
                    db, item, preset_slots, issue_labels, classify=classify
                )
            if owner_slot_id is None:
                await self.escalate(db, item, "plan_blocked")
                await db.commit()
                continue
            owner_slot = slots_by_id.get(owner_slot_id)
            if owner_slot_id in slots_dispatched_this_batch or await self.slot_is_busy(
                db, owner_slot_id
            ):
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_slot_busy"
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
            ambiguity_note = await self._session_ambiguity_note(db, owner_slot_id)
            if ambiguity_note is not None:
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_ambiguous_sessions"
                item.status_note = ambiguity_note
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
            workspace = await github_workspace_service.acquire(db, scope, item)
            if workspace is None:
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_no_workspace"
                skipped_primary = await github_workspace_service.skipped_primary_count(
                    db, scope.id
                )
                item.status_note = (
                    f"No dispatch worktree is available; skipped {skipped_primary} "
                    "dispatchable primary workspace(s)."
                    if skipped_primary
                    else item.status_note
                )
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
            try:
                auth_mode = await self._resolve_scope_auth_mode(db, scope)
                if auth_mode == "app":
                    await github_workspace_service.validate_app_remote(scope, workspace)
                if owner_slot is None:
                    raise GithubWorkspaceConfigError(
                        f"Owner slot {owner_slot_id} is unavailable"
                    )
                await github_workspace_service.configure_dispatch_worktree(
                    workspace,
                    display_name=owner_slot.display_name,
                    slot_id=owner_slot.id,
                    app_mode=auth_mode == "app",
                )
                attempt_base_ref = (
                    await github_workspace_service.resolve_attempt_base_ref(
                        scope,
                        workspace,
                    )
                )
            except GithubWorkspaceRemoteError as exc:
                workspace.enabled = False
                workspace.provision_error = str(exc)
                workspace.updated_at = datetime.utcnow()
                await db.commit()
                await self._release_auth_refusal(db, scope, item, workspace, str(exc))
                continue
            except GithubAuthModeUnresolved as exc:
                await self._release_auth_refusal(db, scope, item, workspace, str(exc))
                continue
            except GithubWorkspaceConfigError as exc:
                await self._release_auth_refusal(
                    db,
                    scope,
                    item,
                    workspace,
                    str(exc),
                    keep_lease=exc.restoration_failed,
                )
                continue
            attempt = await self.prepare_attempt(
                db,
                item,
                owner_slot_id=owner_slot_id,
                routing_method=method,
                base_ref=attempt_base_ref,
            )
            try:
                leader = self._leader_slot(preset_slots)
                leader_member = (
                    await self._slot_member(db, leader.id) if leader is not None else None
                )
                brief = self._dispatch_brief(
                    item,
                    scope,
                    workspace,
                    owner_slot_id=attempt.owner_slot_id,
                    preset_slots=preset_slots,
                    leader_member=leader_member,
                    issue_details=issue_details_by_number.get(item.issue_number),
                )
                await self._send_dispatch_brief_to_slot(
                    db,
                    item,
                    preset_slots=preset_slots,
                    owner_slot_id=attempt.owner_slot_id,
                    brief=brief,
                )
                result = await launcher(
                    db,
                    scope.preset_id,
                    AgentTeamLaunchRequest(
                        slot_ids=[attempt.owner_slot_id],
                        reuse_existing=True,
                        skip_plan_confirmation=True,
                        repo_path_override=workspace.path,
                        slot_prompt_overrides={attempt.owner_slot_id: brief},
                    ),
                )
            except ValueError:
                item.pending_reason = None
                await self.escalate(db, item, "plan_blocked")
                try:
                    await github_workspace_service.release(db, item.id)
                except GithubWorkspaceCredentialRevokeError as exc:
                    item.status_note = str(exc)
                await db.commit()
                continue
            except Exception:
                item.pending_reason = None
                await self.escalate(db, item, "launch_outcome_unknown")
                await db.commit()
                raise
            item.launch_id = getattr(result, "launch_id", None)
            launch_item = next(iter(getattr(result, "items", []) or []), None)
            launch_status = getattr(launch_item, "status", None)
            tmux_target = getattr(launch_item, "tmux_target", None)
            if launch_status in _LAUNCH_FAILED_STATUSES:
                item.dispatch_status = "failed"
                if tmux_target is None:
                    try:
                        await github_workspace_service.release(db, item.id)
                    except GithubWorkspaceCredentialRevokeError as exc:
                        item.status_note = str(exc)
            else:
                item.dispatch_status = "dispatched"
                item.dispatched_at = datetime.utcnow()
                pane_pid = getattr(launch_item, "pane_pid", None) or self._resolve_pane_pid(
                    tmux_target
                )
                if pane_pid is not None:
                    try:
                        proc_start = github_workspace_service._read_proc_start(pane_pid)
                    except OSError:
                        proc_start = None
                    if proc_start is not None:
                        workspace.leased_owner_pid = pane_pid
                        workspace.leased_owner_proc_start = proc_start
                        workspace.updated_at = datetime.utcnow()
                    else:
                        logger.warning(
                            "captured pane pid %s for item %s but could not read "
                            "its start time; lease will not be auto-reclaimable",
                            pane_pid,
                            item.id,
                        )
                slots_dispatched_this_batch.add(attempt.owner_slot_id)
                scope_dispatched_this_batch += 1
            item.pending_reason = None
            item.updated_at = datetime.utcnow()
            await db.commit()

    def _dispatch_brief(
        self,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        workspace: GithubWorkspace,
        *,
        owner_slot_id: int,
        preset_slots: list[AgentTeamSlot],
        leader_member: MailTeamMember | None = None,
        issue_details: dict | None = None,
    ) -> str:
        leader = self._leader_slot(preset_slots)
        owner = next((slot for slot in preset_slots if slot.id == owner_slot_id), None)
        issue_body = (issue_details or {}).get("body") or ""
        labels = [
            label["name"]
            for label in (issue_details or {}).get("labels", [])
            if isinstance(label, dict) and "name" in label
        ]
        body = issue_body.strip() or "(No issue body provided.)"
        if len(body) > 12000:
            body = f"{body[:12000]}\n\n[Issue body truncated by Claude Deck.]"

        lines = [
            "You are handling an autonomous GitHub dispatch from Claude Deck.",
            "",
            f"- Work item ID: {item.id}",
            f"- Repo: {scope.repo_owner}/{scope.repo_name}",
            f"- Workspace: {workspace.path}",
            "- This workspace is leased exclusively to this work item. No other "
            "dispatched agent will be working in it.",
            f"- Issue: #{item.issue_number} — {item.issue_title}",
            f"- Issue URL: {item.issue_url}",
            f"- Pipeline: {item.issue_type}",
            f"- Owner slot: {owner.display_name if owner else owner_slot_id}",
        ]
        if workspace.kind == "worktree":
            lines.extend(
                [
                    "- It is a git worktree on a detached HEAD at "
                    f"{item.dispatch_base_ref}. "
                    "Create the assigned branch before committing.",
                    f"- Assigned branch: `{item.dispatch_head_ref}`. Run "
                    f"`git switch -c {item.dispatch_head_ref}` and do not rename or "
                    "recompose it.",
                    "- Do NOT create, move or remove git worktrees yourself. Claude Deck "
                    "provisions the workspace; you work inside the one you were given.",
                    "- Do NOT work in any other checkout of this repository.",
                ]
            )
        else:
            lines.extend(
                [
                    "- This is a shared human checkout, not a Deck-managed worktree. Its "
                    "current branch is not Deck's to change; confirm with the team leader "
                    "before switching branches.",
                    "- Do NOT work in any other checkout of this repository.",
                ]
            )
        if leader is not None:
            if leader_member is not None:
                lines.append(
                    "- Team leader / approver: "
                    f"{leader.display_name} (Agent Mail member_id={leader_member.id})"
                )
            else:
                lines.append(f"- Team leader / approver: {leader.display_name}")
                lines.append(
                    "- The Leader Agent Mail member is not registered yet. The approval "
                    "request route derives the current designated Leader server-side; "
                    "do not guess or supply a member id."
                )
        if labels:
            lines.append(f"- Labels: {', '.join(labels)}")
        lines.extend(["", "Issue body:", body, "", "Required status reporting:"])
        lines.append(
            f"- When triaging, call `deck_report_dispatch_status(work_item_id={item.id}, "
            f"status=\"triaging\", lease_token=\"{workspace.lease_token}\", note=\"...\")`."
        )
        if scope.github_auth_mode == "app":
            lines.extend(
                [
                    "- Claude Deck opens the pull request with its GitHub App identity; "
                    "do not create the PR yourself.",
                    f"- Add commit trailers `Deck-Agent-Slot: {owner_slot_id} "
                    f"({owner.display_name if owner else owner_slot_id})` and "
                    f"`Deck-Work-Item: {item.id}`.",
                    f"- Push the exact assigned branch with `git push -u origin "
                    f"{item.dispatch_head_ref}`.",
                    f"- After the push, call `deck_report_dispatch_status(work_item_id={item.id}, "
                    f"status=\"pr_ready\", lease_token=\"{workspace.lease_token}\", "
                    f"head_ref=\"{item.dispatch_head_ref}\")`. Deck owns the PR title and body.",
                ]
            )
        else:
            lines.append(
                f"- When you open a PR, call `deck_report_dispatch_status(work_item_id={item.id}, "
                f"status=\"pr_opened\", lease_token=\"{workspace.lease_token}\", "
                "pr_number=<PR number>)`."
            )
        lines.extend(
            [
                f"- If blocked, call `deck_report_dispatch_status(work_item_id={item.id}, "
                f"status=\"blocked\", lease_token=\"{workspace.lease_token}\", note=\"...\")`.",
                f"- Once the item reaches a terminal state, commit and push all work, then call "
                f"`deck_report_dispatch_status(work_item_id={item.id}, "
                f"status=\"workspace_released\", lease_token=\"{workspace.lease_token}\")`.",
            ]
        )
        if item.issue_type == "design":
            lines.extend(
                [
                    "",
                    "Design pipeline instructions:",
                    "- Treat this as a design/documentation task.",
                    "- Prepare a human-reviewed PR; do not rely on CI or auto-merge.",
                    self._leader_ack_instruction(
                        leader,
                        leader_member,
                        before="opening the PR",
                        item=item,
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "Code pipeline instructions:",
                    "- Triage this issue and prepare a short implementation plan.",
                    self._leader_ack_instruction(
                        leader,
                        leader_member,
                        before="starting implementation",
                        item=item,
                    ),
                    "- Use `deck_request_context` when you need an explicit answer from the leader/approver.",
                ]
            )
            if scope.github_auth_mode == "app":
                lines.extend(
                    [
                        "- Keep the change inside the issue scope and run the issue's "
                        "requested local verification commands.",
                        "- Push the assigned branch and report `pr_ready`; Claude Deck "
                        "creates the draft PR and starts CI verification.",
                    ]
                )
            else:
                lines.extend(
                    [
                        "- Keep the change inside the issue scope, run the issue's "
                        "requested local verification commands, then open a draft PR.",
                        "- After opening the draft PR, report `pr_opened` with the PR "
                        "number and wait for CI verification.",
                    ]
                )
            lines.extend(self._build_instructions(item, scope))
        return "\n".join(lines)

    async def _escalate_prepared_owner_unavailable(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        owner_slot: AgentTeamSlot | None,
    ) -> None:
        if owner_slot is None:
            condition = "is no longer part of this preset"
        else:
            condition = "is disabled"
        note = (
            f"Prepared owner slot {item.owner_slot_id} {condition}. The preserved "
            f"attempt uses head {item.dispatch_head_ref} at approval round "
            f"{item.approval_round_count}. Do not retry or recreate this attempt. "
            "An operator must use the resume-attempt route after resolving or "
            "reassigning the owner."
        )
        await self.escalate(
            db,
            item,
            "prepared_owner_unavailable",
            note,
        )
        await db.commit()

    async def resume_prepared_attempt(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
        *,
        reassign_to_slot_id: int | None,
    ) -> None:
        if (
            item.dispatch_status != "escalated"
            or item.escalation_reason != "prepared_owner_unavailable"
        ):
            raise ResumeAttemptError(
                "not_a_resumable_attempt",
                "Only a prepared_owner_unavailable attempt can be resumed",
            )
        try:
            prepared = prepared_attempt_from_row(item)
        except PartiallyPreparedAttempt as exc:
            raise ResumeAttemptError("not_a_resumable_attempt", exc.detail) from exc

        slots_by_id = {
            slot.id: slot
            for slot in preset_slots
            if slot.preset_id == scope.preset_id
        }
        effective_owner_id = (
            reassign_to_slot_id
            if reassign_to_slot_id is not None
            else prepared.owner_slot_id
        )
        effective_owner = slots_by_id.get(effective_owner_id)
        if reassign_to_slot_id is not None and (
            effective_owner is None or not effective_owner.enabled
        ):
            raise ResumeAttemptError(
                "invalid_resume_target",
                "The requested resume target is missing, disabled, or outside the preset",
            )
        if effective_owner is None or not effective_owner.enabled:
            raise ResumeAttemptError(
                "owner_still_unavailable",
                "The prepared owner is still unavailable",
            )

        reassigned = effective_owner_id != prepared.owner_slot_id
        if reassigned:
            workspace = (
                await db.execute(
                    select(GithubWorkspace).where(
                        GithubWorkspace.leased_item_id == item.id
                    )
                )
            ).scalar_one_or_none()
            if (
                workspace is None
                or workspace.leased_owner_pid is None
                or workspace.leased_owner_proc_start is None
            ):
                raise ResumeAttemptError(
                    "previous_owner_liveness_unknown",
                    "The previous owner's pane identity cannot be resolved safely",
                )
            binding = (
                await db.execute(
                    select(AgentPaneBinding).where(
                        AgentPaneBinding.pane_pid == workspace.leased_owner_pid,
                        AgentPaneBinding.pane_proc_start
                        == workspace.leased_owner_proc_start,
                    )
                )
            ).scalar_one_or_none()
            if binding is None or binding.slot_id is None:
                raise ResumeAttemptError(
                    "previous_owner_liveness_unknown",
                    "The previous owner's pane identity cannot be resolved safely",
                )
            if (
                binding.slot_id != effective_owner_id
                and github_workspace_service._owner_process_is_alive(workspace)
            ):
                raise ResumeAttemptError(
                    "previous_owner_still_alive",
                    "The previous owner process is still alive",
                )

        item.dispatch_status = "pending"
        item.escalation_reason = None
        item.pending_reason = None
        if reassigned:
            item.owner_slot_id = effective_owner_id
            item.routing_method = "operator_resume"
        item.updated_at = datetime.utcnow()
        await db.commit()

    def _build_instructions(
        self,
        item: GithubWorkItem,
        scope: TeamGithubScope,
    ) -> list[str]:
        instructions: list[str] = []
        try:
            if scope.build_command_hint:
                if scope.builds_out_of_tree:
                    build_dir = (scope.build_dir_template or "build").format(
                        issue_number=item.issue_number
                    )
                    command = scope.build_command_hint.format(
                        build_dir=build_dir,
                        parallelism=scope.max_build_parallelism,
                    )
                    instructions.extend(
                        [
                            f"- Build directory: {build_dir}",
                            f"- Build command: `{command}`",
                        ]
                    )
                else:
                    command = scope.build_command_hint.format(
                        build_dir="",
                        parallelism=scope.max_build_parallelism,
                    )
                    instructions.extend(
                        [
                            f"- Build command: `{command}`",
                            "- Only one build may run in this workspace at a time; this "
                            "project's build system does not support out-of-tree builds.",
                        ]
                    )
        except (KeyError, IndexError, ValueError):
            logger.exception(
                "Invalid build template for GitHub scope %s; omitting build hints",
                scope.id,
            )
        if scope.max_build_parallelism:
            instructions.append(
                f"- Cap build parallelism at -j{scope.max_build_parallelism}. "
                "Higher values have OOM-killed this host."
            )
        return instructions

    def _leader_slot(self, preset_slots: list[AgentTeamSlot]) -> AgentTeamSlot | None:
        enabled = sorted(
            [slot for slot in preset_slots if slot.enabled],
            key=lambda slot: slot.position,
        )
        return enabled[0] if enabled else None

    def _leader_ack_instruction(
        self,
        leader: AgentTeamSlot | None,
        leader_member: MailTeamMember | None,
        *,
        before: str,
        item: GithubWorkItem | None = None,
    ) -> str:
        linkage = ""
        if item is not None:
            linkage = (
                f" with work_item_id={item.id} and dispatch_nonce="
                f'"{item.dispatch_nonce}"'
            )
        report = (
            " Approval exists only when the designated leader calls "
            f"`deck_approve_work_item`{linkage} for the current round. A prose "
            "reply is not approval, and self-approval is refused. After approval, "
            "call `deck_report_dispatch_status(status=\"ack_received\")` before "
            f"{before}. A rejection opens the next round automatically; revise the "
            "plan and call `deck_request_work_item_approval` again with the same work "
            "item and nonce. Do not report `revision_requested`."
        )
        if leader_member is not None:
            return (
                "- Submit the short plan for Leader approval using "
                f"`deck_request_work_item_approval(work_item_id="
                f"{item.id if item is not None else '<id>'}, dispatch_nonce=\""
                f"{item.dispatch_nonce if item is not None else '<nonce>'}\", ...)`, "
                f"then wait for the explicit decision before {before}." + report
            )
        if leader is not None:
            return (
                "- Submit the short plan with `deck_request_work_item_approval` and wait "
                f"for an explicit decision before {before}."
                + report
            )
        return (
            "- Submit the short plan with `deck_request_work_item_approval` and wait for "
            f"an explicit decision before {before}; if no leader is registered, report blocked."
            + report
        )

    def _leader_unblock_instructions(self) -> str:
        return (
            "DEPENDENCY UNBLOCKING (leader duty):\n"
            "- On team start, scan the roadmap issues and build a dependency map "
            "(parse 'Blocked by #N' / 'Dependencies' from each issue body): "
            "issue -> [blocker issues]. Note which blockers are already closed.\n"
            "- ALSO at team start (cold-start recovery): call `deck_list_work_items"
            "(status=\"escalated\")` to get the current escalated items with their "
            "work_item_ids. For each escalated dependent whose blockers are ALL already "
            "closed (per your map), call `deck_retry_work_item(work_item_id=<id>, "
            "reason=\"prerequisite #<n> already merged\")`. This handles blockers that "
            "merged before you started (resume/respawn), where no notification arrives.\n"
            "- When you receive a `github_dispatch_blocker_merged` notification, mark "
            "that blocker satisfied in your map. For each ESCALATED dependent in the "
            "notification's `escalated_items`, check whether ALL of its blockers are now "
            "resolved.\n"
            "- For each dependent whose blockers are ALL resolved, call "
            "`deck_retry_work_item(work_item_id=<id from escalated_items>, "
            "reason=\"prerequisite #<n> merged\")` to re-dispatch it.\n"
            "- Only retry when ALL blockers are resolved (never on a single blocker for a "
            "multi-blocker issue). Do not retry the same dependent twice for one event. If "
            "a dependency is ambiguous, leave it escalated for a human."
        )

    async def _send_dispatch_brief_to_slot(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        preset_slots: list[AgentTeamSlot],
        owner_slot_id: int,
        brief: str,
    ) -> None:
        owner_slot = next((slot for slot in preset_slots if slot.id == owner_slot_id), None)
        if owner_slot is None:
            return
        try:
            from app.services.agent_mail_service import agent_mail_service

            member = await agent_mail_service.get_or_create_slot_member(db, owner_slot)
            message = await agent_mail_service.send_direct_message(
                db,
                recipient_member_id=member.id,
                subject=f"Autonomous dispatch: issue #{item.issue_number}",
                body_markdown=brief,
                payload={
                    "kind": "github_dispatch_assignment",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                    "scope_id": item.scope_id,
                },
                bypass_nudge_cooldown=True,
                nudge_prompt=(
                    "Claude Deck autonomous dispatch: call "
                    "`deck_check_inbox(unread_only=False)` now, find the "
                    f"`Autonomous dispatch: issue #{item.issue_number}` message for "
                    f"work item {item.id}, and execute that assignment now. Follow "
                    "its leader-ack and status-reporting instructions."
                ),
            )
            item.brief_message_id = message.id
            item.brief_delivery_nudge_at = None
            item.brief_delivery_nudge_count = None
        except Exception:
            logger.exception("Failed to send autonomous dispatch brief for item %s", item.id)

    async def _session_ambiguity_note(
        self, db: AsyncSession, owner_slot_id: int
    ) -> str | None:
        """Return why a slot cannot be safely briefed, if ambiguous."""
        member = await self._slot_member(db, owner_slot_id)
        if member is None:
            return None
        known_before = len(
            await agent_mail_service.nudgeable_sessions_for_slot(db, owner_slot_id)
        )
        try:
            await agent_mail_service.sync_observed_sessions(db, strict=True)
        except Exception:
            logger.exception(
                "session discovery failed while checking slot %s for ambiguity",
                owner_slot_id,
            )
            return (
                "Session discovery failed, so the owning pane could not be "
                "confirmed. Holding rather than briefing an unknown session."
            )
        candidates = await agent_mail_service.nudgeable_sessions_for_slot(
            db, owner_slot_id
        )
        if len(candidates) > 1:
            targets = ", ".join(sorted(str(session.tmux_target) for session in candidates))
            return (
                f"{len(candidates)} nudgeable sessions on this slot ({targets}). "
                "The dispatch brief would reach an arbitrary one. Converge the "
                "slot to a single session, then this item dispatches itself."
            )
        if not candidates and known_before:
            return (
                f"Discovery found no sessions for this slot, but {known_before} "
                "was expected. Treating zero as unverified rather than empty."
            )
        return None

    async def apply_approval_decision(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        *,
        decision: str,
        approval_round: int,
        dispatch_nonce: str,
        owner_member_id: int,
    ) -> bool:
        current_owner_exists = exists(
            select(MailTeamMember.id).where(
                MailTeamMember.id == owner_member_id,
                MailTeamMember.team_slot_id == GithubWorkItem.owner_slot_id,
            )
        )
        if decision == "approved":
            result = await db.execute(
                update(GithubWorkItem)
                .where(
                    GithubWorkItem.id == item.id,
                    GithubWorkItem.dispatch_status != "escalated",
                    GithubWorkItem.dispatch_nonce == dispatch_nonce,
                    GithubWorkItem.approval_round_count == approval_round,
                    current_owner_exists,
                )
                .values(updated_at=datetime.utcnow())
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            await db.refresh(item)
            if result.rowcount == 1:
                return True
            if item.dispatch_status == "escalated":
                return False
            if item.dispatch_nonce != dispatch_nonce:
                raise ValueError("stale_nonce")
            owner = await db.get(MailTeamMember, owner_member_id)
            if owner is None or owner.team_slot_id != item.owner_slot_id:
                raise ValueError("stale_approval_owner")
            raise ValueError("approval_round_mismatch")

        now = datetime.utcnow()
        exhausted = approval_round >= scope.max_approval_rounds
        statement = update(GithubWorkItem).where(
            GithubWorkItem.id == item.id,
            GithubWorkItem.dispatch_status != "escalated",
            GithubWorkItem.dispatch_nonce == dispatch_nonce,
            GithubWorkItem.approval_round_count == approval_round,
            current_owner_exists,
        )
        if exhausted:
            statement = statement.values(
                ack_received_at=None,
                ack_approver_member_id=None,
                ack_evidence_message_id=None,
                ack_enforcement_epoch=None,
                ack_approval_round=None,
                last_nudge_at=None,
                dispatch_status="escalated",
                escalation_reason="approval_rounds_exhausted",
                pending_reason=None,
                updated_at=now,
            )
        else:
            statement = statement.values(
                ack_received_at=None,
                ack_approver_member_id=None,
                ack_evidence_message_id=None,
                ack_enforcement_epoch=None,
                ack_approval_round=None,
                last_nudge_at=None,
                approval_round_count=approval_round + 1,
                updated_at=now,
            )
        result = await db.execute(
            statement.execution_options(synchronize_session=False)
        )
        await db.commit()
        await db.refresh(item)
        if result.rowcount != 1:
            if (
                item.approval_round_count == approval_round + 1
                or item.dispatch_status == "escalated"
                and item.escalation_reason == "approval_rounds_exhausted"
            ):
                return False
            if item.dispatch_status == "escalated":
                return False
            if item.dispatch_nonce != dispatch_nonce:
                raise ValueError("stale_nonce")
            owner = await db.get(MailTeamMember, owner_member_id)
            if owner is None or owner.team_slot_id != item.owner_slot_id:
                raise ValueError("stale_approval_owner")
            raise ValueError("approval_round_mismatch")
        if not exhausted:
            return True
        try:
            await self._send_escalation_broadcast(
                db,
                item,
                "approval_rounds_exhausted",
                None,
                owner_may_be_active=True,
            )
        except Exception:
            logger.exception(
                "Failed to notify after approval rounds exhausted for item %s",
                item.id,
            )
        return True

    async def _ack_evidence(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        preset_slots: list[AgentTeamSlot],
    ) -> AckEvidence:
        if not settings.mail_capability_tokens_required:
            return AckEvidence(False, "tokens_not_enforced")
        leader = self._leader_slot(preset_slots)
        leader_member = (
            await self._slot_member(db, leader.id) if leader is not None else None
        )
        if leader_member is None:
            return AckEvidence(False, "no_leader")
        owner_member = await self._owner_member(db, item)
        if owner_member is None:
            return AckEvidence(False, "no_owner")
        if owner_member.id == leader_member.id:
            return AckEvidence(False, "self_ack")
        request = (
            await db.execute(
                select(GithubApprovalRequest)
                .where(
                    GithubApprovalRequest.work_item_id == item.id,
                    GithubApprovalRequest.request_kind == "initial_plan",
                )
                .order_by(GithubApprovalRequest.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if request is None or request.request_message_id is None:
            return AckEvidence(False, "no_linkage")
        if item.dispatch_nonce is None:
            return AckEvidence(False, "stale_nonce")
        if request.dispatch_nonce != item.dispatch_nonce:
            return AckEvidence(False, "stale_nonce")
        if item.approval_round_count < 1:
            return AckEvidence(False, "stale_round")
        if request.approval_round != item.approval_round_count:
            return AckEvidence(False, "stale_round")
        if request.owner_member_id != owner_member.id:
            return AckEvidence(False, "stale_approval_owner")
        if request.leader_member_id != leader_member.id:
            return AckEvidence(False, "not_designated_approver")
        if request.status == "rejected":
            return AckEvidence(False, "rejected")
        if request.status != "approved" or request.decision_message_id is None:
            return AckEvidence(False, "no_decision")
        answer = await db.get(MailMessage, request.decision_message_id)
        if answer is None:
            return AckEvidence(False, "no_decision")
        if answer.sender_member_id != leader_member.id:
            return AckEvidence(False, "not_designated_approver")
        if (
            answer.kind != "answer"
            or answer.thread_root_id != request.request_message_id
            or answer.decision != "approved"
            or answer.approval_round != item.approval_round_count
            or answer.delivery_key != f"github-approval:{request.id}:decision"
            or not isinstance(answer.payload, dict)
            or answer.payload.get("approval_request_id") != request.id
        ):
            return AckEvidence(False, "no_decision")
        return AckEvidence(
            True,
            "ok",
            approver_member_id=leader_member.id,
            evidence_message_id=answer.id,
            approval_round=item.approval_round_count,
        )

    async def record_ack_received(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
    ) -> AckEvidence:
        preset_slots = (
            await db.execute(
                select(AgentTeamSlot)
                .where(AgentTeamSlot.preset_id == scope.preset_id)
                .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
            )
        ).scalars().all()
        evidence = await self._ack_evidence(db, item, list(preset_slots))
        if not evidence.ok:
            return evidence
        item.ack_received_at = datetime.utcnow()
        item.ack_approver_member_id = evidence.approver_member_id
        item.ack_evidence_message_id = evidence.evidence_message_id
        item.ack_enforcement_epoch = 1
        item.ack_approval_round = evidence.approval_round
        item.last_nudge_at = None
        item.updated_at = datetime.utcnow()
        await db.commit()
        return evidence

    async def initiate_handoff(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        *,
        initiating_slot_id: int,
        target_slot_id: int,
    ) -> None:
        if item.owner_slot_id != initiating_slot_id:
            raise ResumeAttemptError("not_item_owner", "Only the current owner may initiate a handoff")
        target = await db.get(AgentTeamSlot, target_slot_id)
        if (
            target is None
            or target.preset_id != scope.preset_id
            or not target.enabled
        ):
            raise ResumeAttemptError(
                "invalid_handoff_target",
                "Handoff target must be an enabled slot in the same preset",
            )
        item.handoff_state = "pending"
        item.handoff_target_slot_id = target_slot_id
        item.updated_at = datetime.utcnow()
        await db.commit()
        target_member = await agent_mail_service.get_or_create_slot_member(db, target)
        await agent_mail_service.send_direct_message(
            db,
            recipient_member_id=target_member.id,
            subject=f"GitHub dispatch handoff: work item {item.id}",
            body_markdown=(
                f"Work item {item.id} is being handed to your slot. Do not work in "
                "the workspace yet. First call "
                f"`deck_report_dispatch_status(work_item_id={item.id}, "
                "status=\"handoff_accepted\")` and wait for a 200 response. Then "
                "call `deck_get_work_item_context` to receive the preserved branch "
                "and lease capability."
            ),
            payload={
                "kind": "github_dispatch_handoff",
                "work_item_id": item.id,
                "target_slot_id": target_slot_id,
            },
            bypass_nudge_cooldown=True,
        )

    async def accept_handoff(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        accepting_slot_id: int,
        *,
        accepting_pane_pid: int,
        accepting_pane_proc_start: str,
    ) -> None:
        if item.handoff_target_slot_id != accepting_slot_id:
            raise ValueError(
                f"slot {accepting_slot_id} cannot accept a handoff targeted at "
                f"{item.handoff_target_slot_id}"
            )
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        target = await db.get(AgentTeamSlot, accepting_slot_id)
        if workspace is None or target is None:
            raise ValueError("handoff workspace or target slot is unavailable")
        item_id = item.id
        expected_old_owner_slot_id = item.owner_slot_id
        workspace_id = workspace.id
        await db.commit()
        async with github_workspace_service.config_lock(workspace.id):
            workspace = (
                await db.execute(
                    select(GithubWorkspace)
                    .where(GithubWorkspace.id == workspace_id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            item = (
                await db.execute(
                    select(GithubWorkItem)
                    .where(GithubWorkItem.id == item_id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if workspace is None or item is None:
                raise ValueError("handoff workspace or work item is unavailable")
            scope = (
                await db.execute(
                    select(TeamGithubScope)
                    .where(TeamGithubScope.id == item.scope_id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if scope is None:
                raise ValueError("handoff scope is unavailable")
            active_revision = None
            if item.active_scope_revision > 0:
                active_revision = (
                    await db.execute(
                        select(GithubAttemptScopeRevision)
                        .where(
                            GithubAttemptScopeRevision.work_item_id == item.id,
                            GithubAttemptScopeRevision.dispatch_nonce
                            == item.dispatch_nonce,
                            GithubAttemptScopeRevision.revision
                            == item.active_scope_revision,
                            GithubAttemptScopeRevision.status.in_(
                                ("active", "submitted")
                            ),
                        )
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one_or_none()
            old_owner_slot_id = expected_old_owner_slot_id
            expected_leased_at = workspace.leased_at
            lease_token = workspace.lease_token
            config_workspace = GithubWorkspace(
                id=workspace.id,
                path=workspace.path,
                kind=workspace.kind,
            )
            snapshot = (
                None
                if workspace.kind == "primary"
                else await github_workspace_service.snapshot_worktree_config(
                    config_workspace
                )
            )
            now = datetime.utcnow()
            item_update = (
                update(GithubWorkItem)
                .where(
                    GithubWorkItem.id == item.id,
                    GithubWorkItem.owner_slot_id == old_owner_slot_id,
                    GithubWorkItem.handoff_state == "pending",
                    GithubWorkItem.handoff_target_slot_id == accepting_slot_id,
                )
                .values(
                    owner_slot_id=accepting_slot_id,
                    handoff_state="accepted",
                    handoff_target_slot_id=None,
                    routing_method="reassigned",
                    ack_received_at=None,
                    ack_approver_member_id=None,
                    ack_evidence_message_id=None,
                    ack_enforcement_epoch=None,
                    ack_approval_round=None,
                    last_nudge_at=None,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if active_revision is not None:
                item_update = item_update.values(
                    dispatch_status="escalated",
                    escalation_reason=active_revision.originating_escalation_reason,
                    pending_reason=None,
                    continuation_nudged_at=None,
                    status_note=(
                        "The active continuation was superseded by handoff. The new "
                        "owner must propose and receive approval for a fresh revision."
                    ),
                )
            item_result = await db.execute(item_update)
            workspace_result = await db.execute(
                update(GithubWorkspace)
                .where(
                    GithubWorkspace.id == workspace.id,
                    GithubWorkspace.scope_id == item.scope_id,
                    GithubWorkspace.leased_item_id == item.id,
                    GithubWorkspace.lease_token == lease_token,
                    GithubWorkspace.leased_at == expected_leased_at,
                )
                .values(
                    leased_owner_pid=accepting_pane_pid,
                    leased_owner_proc_start=accepting_pane_proc_start,
                    lease_last_owner_contact_at=now,
                    push_token_expires_at=None,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            owner_bound_revisions = (
                await db.execute(
                    select(GithubAttemptScopeRevision).where(
                        GithubAttemptScopeRevision.work_item_id == item.id,
                        GithubAttemptScopeRevision.dispatch_nonce
                        == item.dispatch_nonce,
                        GithubAttemptScopeRevision.owner_slot_id
                        == old_owner_slot_id,
                        GithubAttemptScopeRevision.status.in_(
                            ("proposed", "approved", "active", "submitted")
                        ),
                    )
                )
            ).scalars().all()
            revision_ids = [revision.id for revision in owner_bound_revisions]
            if revision_ids:
                await db.execute(
                    update(GithubAttemptScopeRevision)
                    .where(
                        GithubAttemptScopeRevision.id.in_(revision_ids),
                        GithubAttemptScopeRevision.status.in_(
                            ("proposed", "approved", "active", "submitted")
                        ),
                    )
                    .values(status="superseded")
                    .execution_options(synchronize_session=False)
                )
                pending_requests = (
                    await db.execute(
                        select(GithubApprovalRequest).where(
                            GithubApprovalRequest.scope_revision_id.in_(revision_ids),
                            GithubApprovalRequest.request_kind == "continuation",
                            GithubApprovalRequest.status == "pending",
                        )
                    )
                ).scalars().all()
                if pending_requests:
                    request_ids = [request.id for request in pending_requests]
                    request_message_ids = [
                        request.request_message_id
                        for request in pending_requests
                        if request.request_message_id is not None
                    ]
                    await db.execute(
                        update(GithubApprovalRequest)
                        .where(
                            GithubApprovalRequest.id.in_(request_ids),
                            GithubApprovalRequest.status == "pending",
                        )
                        .values(status="superseded", superseded_at=now)
                        .execution_options(synchronize_session=False)
                    )
                    if request_message_ids:
                        await db.execute(
                            update(MailMessage)
                            .where(
                                MailMessage.id.in_(request_message_ids),
                                MailMessage.request_status == "pending",
                            )
                            .values(request_status="superseded")
                            .execution_options(synchronize_session=False)
                        )
                remaining_authority = (
                    await db.execute(
                        select(func.count(GithubAttemptScopeRevision.id)).where(
                            GithubAttemptScopeRevision.id.in_(revision_ids),
                            GithubAttemptScopeRevision.status.in_(
                                ("proposed", "approved", "active", "submitted")
                            ),
                        )
                    )
                ).scalar_one()
                if remaining_authority:
                    await db.rollback()
                    raise ValueError("handoff continuation authority changed")
            if (
                item_result.rowcount != 1
                or workspace_result.rowcount != 1
            ):
                await db.rollback()
                raise ValueError("handoff state changed before acceptance")
            try:
                await github_workspace_service.revoke_push_token(
                    scope,
                    workspace,
                    owner_slot_id=old_owner_slot_id,
                )
                if workspace.kind != "primary":
                    await github_workspace_service.apply_slot_identity(
                        config_workspace,
                        display_name=target.display_name,
                        slot_id=target.id,
                    )
                await db.commit()
            except BaseException as exc:
                await db.rollback()
                if snapshot is not None:
                    try:
                        await github_workspace_service.restore_worktree_config(
                            config_workspace,
                            snapshot,
                        )
                    except GithubWorkspaceConfigError as restore_exc:
                        detail = (
                            "Handoff failed and the prior worktree identity could "
                            f"not be restored: {restore_exc}"
                        )
                        await github_workspace_service._record_config_repair_note(
                            db,
                            workspace_id=workspace_id,
                            item_id=item_id,
                            detail=detail,
                        )
                        if not isinstance(exc, Exception):
                            raise exc from restore_exc
                        raise ValueError(detail) from restore_exc
                if not isinstance(exc, Exception):
                    raise
                if isinstance(exc, GithubWorkspaceCredentialRevokeError):
                    raise
                raise ValueError(f"handoff identity update failed: {exc}") from exc
        await db.refresh(item)
        await db.refresh(workspace)

    async def monitor_dispatched(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
        wake_state_by_slot: dict[int, str] | None = None,
    ) -> None:
        enabled = sorted(
            [slot for slot in preset_slots if slot.enabled],
            key=lambda slot: slot.position,
        )
        if not enabled:
            return
        leader = enabled[0]

        if wake_state_by_slot is None:
            from app.services.agent_mail_service import agent_mail_service

            members = await agent_mail_service.list_team(db)
            wake_state_by_slot = {
                member.team_slot_id: member.wake_state
                for member in members
                if member.team_slot_id is not None
            }
        leader_wake = wake_state_by_slot.get(leader.id)

        dispatched = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "dispatched",
                    GithubWorkItem.pr_number.is_(None),
                    GithubWorkItem.active_scope_revision == 0,
                )
            )
        ).scalars().all()

        for item in dispatched:
            if self._within_registration_grace(item):
                continue
            if leader_wake == "offline":
                await self.escalate(db, item, "leader_offline")
                continue
            owner_wake = (
                wake_state_by_slot.get(item.owner_slot_id)
                if item.owner_slot_id is not None
                else None
            )
            if owner_wake == "offline":
                await self.escalate(db, item, "owner_offline")
                continue
            if not await self._brief_delivered(db, item):
                anchor = item.brief_delivery_nudge_at
                if anchor is None:
                    await self._nudge_owner_for_brief(db, item)
                    continue
                if datetime.utcnow() - anchor <= timedelta(
                    seconds=settings.github_nudge_grace_seconds
                ):
                    continue
                if (
                    item.brief_delivery_nudge_count or 0
                ) < settings.github_brief_delivery_max_nudges:
                    await self._nudge_owner_for_brief(db, item)
                    continue
                await self.escalate(db, item, "brief_unread")
                continue
            if not self._ack_satisfied(item):
                anchor = item.dispatched_at or item.updated_at or item.created_at
                overdue = datetime.utcnow() - anchor > timedelta(
                    seconds=self._ack_deadline_seconds(item)
                )
                if not overdue:
                    continue
                if item.last_nudge_at is None:
                    await self._nudge_leader_for_ack(db, item, leader)
                elif datetime.utcnow() - item.last_nudge_at > timedelta(
                    seconds=settings.github_nudge_grace_seconds
                ):
                    await self.escalate(db, item, "leader_ack_timeout")
                continue
            idle_anchor = item.updated_at or item.created_at
            idle_overdue = datetime.utcnow() - idle_anchor > timedelta(
                seconds=settings.github_owner_idle_timeout_seconds
            )
            if not idle_overdue:
                continue
            if item.last_nudge_at is None or item.last_nudge_at < idle_anchor:
                await self._nudge_owner_for_progress(db, item)
            elif datetime.utcnow() - item.last_nudge_at > timedelta(
                seconds=settings.github_nudge_grace_seconds
            ):
                await self.escalate(db, item, "owner_idle_timeout")
        await db.commit()

    @staticmethod
    def _log_continuation_monitor(
        item: GithubWorkItem,
        *,
        anchor: datetime | None,
        elapsed_seconds: float | None,
        action: str,
        block_code: str | None = None,
    ) -> None:
        logger.debug(
            "github continuation monitor",
            extra={
                "monitor_name": "monitor_continuation",
                "work_item_id": item.id,
                "active_scope_revision": item.active_scope_revision,
                "attempt_phase": item.attempt_phase,
                "dispatch_status": item.dispatch_status,
                "grace_anchor": anchor.isoformat() if anchor is not None else None,
                "elapsed_grace_seconds": elapsed_seconds,
                "monitor_action": action,
                "block_code": block_code,
            },
        )

    @staticmethod
    def _log_recovery_monitor(
        item: GithubWorkItem,
        *,
        revision: GithubAttemptScopeRevision | None,
        anchor: datetime | None,
        now: datetime,
        action: str,
        block_code: str | None = None,
    ) -> None:
        logger.debug(
            "github recovery monitor",
            extra={
                "monitor_name": "monitor_recovery",
                "work_item_id": item.id,
                "active_scope_revision": item.active_scope_revision,
                "attempt_phase": item.attempt_phase,
                "dispatch_status": item.dispatch_status,
                "scope_revision": revision.revision if revision is not None else None,
                "revision_phase": revision.phase if revision is not None else None,
                "revision_status": revision.status if revision is not None else None,
                "grace_anchor": anchor.isoformat() if anchor is not None else None,
                "elapsed_grace_seconds": (
                    max((now - anchor).total_seconds(), 0)
                    if anchor is not None
                    else None
                ),
                "monitor_action": action,
                "block_code": block_code,
            },
        )

    async def monitor_continuation(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
    ) -> None:
        enabled_slot_ids = {slot.id for slot in preset_slots if slot.enabled}
        items = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "dispatched",
                    GithubWorkItem.pr_number.is_not(None),
                    GithubWorkItem.active_scope_revision > 0,
                )
            )
        ).scalars().all()
        now = datetime.utcnow()
        idle_timeout = timedelta(
            seconds=settings.github_owner_idle_timeout_seconds
        )
        nudge_grace = timedelta(seconds=settings.github_nudge_grace_seconds)

        for item in items:
            revision = (
                await db.execute(
                    select(GithubAttemptScopeRevision).where(
                        GithubAttemptScopeRevision.work_item_id == item.id,
                        GithubAttemptScopeRevision.dispatch_nonce
                        == item.dispatch_nonce,
                        GithubAttemptScopeRevision.revision
                        == item.active_scope_revision,
                        GithubAttemptScopeRevision.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if revision is None:
                self._log_continuation_monitor(
                    item,
                    anchor=item.continuation_activated_at,
                    elapsed_seconds=None,
                    action="skip",
                    block_code="active_revision_missing",
                )
                continue
            if item.owner_slot_id not in enabled_slot_ids:
                self._log_continuation_monitor(
                    item,
                    anchor=item.continuation_activated_at,
                    elapsed_seconds=None,
                    action="skip",
                    block_code="owner_slot_unavailable",
                )
                continue
            owner_member = await self._owner_member(db, item)
            if owner_member is None:
                self._log_continuation_monitor(
                    item,
                    anchor=item.continuation_activated_at,
                    elapsed_seconds=None,
                    action="skip",
                    block_code="owner_member_unavailable",
                )
                continue
            workspace = await github_workspace_service.get_leased_workspace(db, item.id)
            anchors = [
                value
                for value in (
                    item.continuation_activated_at,
                    workspace.lease_last_owner_contact_at
                    if workspace is not None
                    else None,
                )
                if value is not None
            ]
            if not anchors:
                self._log_continuation_monitor(
                    item,
                    anchor=None,
                    elapsed_seconds=None,
                    action="skip",
                    block_code="continuation_anchor_missing",
                )
                continue
            anchor = max(anchors)
            elapsed = now - anchor
            if elapsed <= idle_timeout:
                continue
            if (
                item.continuation_nudged_at is None
                or item.continuation_nudged_at < anchor
            ):
                await self.notify_owner(
                    db,
                    item,
                    subject=f"Continuation progress check: issue #{item.issue_number}",
                    body_markdown=(
                        f"Continuation revision {item.active_scope_revision} for issue "
                        f"#{item.issue_number} has not reported recent progress. "
                        "Continue within the approved scope or request new approval; "
                        "do not reset the preserved attempt."
                    ),
                    payload={
                        "kind": "github_dispatch_continuation_idle_nudge",
                        "work_item_id": item.id,
                        "scope_revision": item.active_scope_revision,
                    },
                    delivery_key=(
                        f"github-continuation:{item.id}:"
                        f"{item.active_scope_revision}:idle:{anchor.isoformat()}"
                    ),
                )
                item.continuation_nudged_at = now
                item.updated_at = now
                await db.commit()
                self._log_continuation_monitor(
                    item,
                    anchor=anchor,
                    elapsed_seconds=elapsed.total_seconds(),
                    action="nudge_owner",
                )
                continue
            if now - item.continuation_nudged_at <= nudge_grace:
                continue
            revision.status = "superseded"
            await self.escalate(
                db,
                item,
                "owner_idle_timeout",
                (
                    f"Continuation revision {revision.revision} became idle after "
                    "one progress nudge. The PR, workspace, nonce, and attempt "
                    "history remain preserved."
                ),
            )
            await db.commit()
            self._log_continuation_monitor(
                item,
                anchor=anchor,
                elapsed_seconds=elapsed.total_seconds(),
                action="escalate_idle",
            )

    async def monitor_recovery(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
    ) -> None:
        preset = await db.get(AgentTeamPreset, scope.preset_id)
        if (
            preset is None
            or not preset.autonomy_enabled
            or not scope.enabled
            or not scope.continuation_enabled
        ):
            return
        enabled_slot_ids = {slot.id for slot in preset_slots if slot.enabled}
        items = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "escalated",
                )
            )
        ).scalars().all()
        now = datetime.utcnow()
        recovery_nudge_cooldown = timedelta(
            seconds=settings.github_recovery_nudge_cooldown_seconds
        )
        leader_nudge_cooldown = timedelta(
            seconds=settings.github_continuation_leader_nudge_cooldown_seconds
        )
        owner_ack_nudge_cooldown = timedelta(
            seconds=settings.github_continuation_owner_ack_nudge_cooldown_seconds
        )

        for item in items:
            if item.escalation_reason not in CONTINUABLE_ESCALATIONS:
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="skip",
                    block_code="continuation_reason_not_allowed",
                )
                continue
            if (
                item.pr_number is None
                or item.owner_slot_id is None
                or item.owner_slot_id not in enabled_slot_ids
                or not item.dispatch_nonce
            ):
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="skip",
                    block_code="attempt_identity_incomplete",
                )
                continue
            workspace = await github_workspace_service.get_leased_workspace(db, item.id)
            if workspace is None or workspace.lease_token is None:
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="skip",
                    block_code="workspace_lease_required",
                )
                continue
            owner = await self._owner_member(db, item)
            if owner is None or owner.team_slot_id != item.owner_slot_id:
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="skip",
                    block_code="owner_member_unavailable",
                )
                continue
            transport = (
                await db.execute(
                    select(GithubApprovalRequest, GithubAttemptScopeRevision)
                    .join(
                        GithubAttemptScopeRevision,
                        GithubAttemptScopeRevision.id
                        == GithubApprovalRequest.scope_revision_id,
                    )
                    .where(
                        GithubApprovalRequest.work_item_id == item.id,
                        GithubApprovalRequest.request_kind == "continuation",
                        or_(
                            (
                                (GithubApprovalRequest.status == "pending")
                                & (GithubAttemptScopeRevision.status == "proposed")
                            ),
                            (
                                (GithubApprovalRequest.status == "approved")
                                & (GithubAttemptScopeRevision.status == "approved")
                            ),
                            (
                                (GithubApprovalRequest.status == "rejected")
                                & GithubApprovalRequest.decision_message_id.is_(None)
                                & (GithubAttemptScopeRevision.status == "rejected")
                            ),
                        ),
                    )
                    .order_by(GithubApprovalRequest.id.desc())
                    .limit(1)
                )
            ).one_or_none()
            if transport is not None:
                request, revision = transport
                try:
                    repair_action = (
                        await github_approval_service.repair_continuation_transport(
                            db,
                            item,
                            request,
                            revision,
                            leader_nudge_cooldown=leader_nudge_cooldown,
                            owner_ack_nudge_cooldown=owner_ack_nudge_cooldown,
                        )
                    )
                except GithubApprovalError as exc:
                    logger.exception(
                        "Recovery monitor could not repair continuation transport "
                        "for work item %s",
                        item.id,
                    )
                    self._log_recovery_monitor(
                        item,
                        revision=revision,
                        anchor=None,
                        now=now,
                        action="skip",
                        block_code=exc.detail,
                    )
                    continue
                self._log_recovery_monitor(
                    item,
                    revision=revision,
                    anchor=(
                        revision.last_ack_nudge_at
                        if request.status == "approved"
                        else revision.last_delivery_attempt_at
                    ),
                    now=now,
                    action=repair_action,
                )
                continue
            revision_count, failed_head_count = (
                await github_approval_service.continuation_budget_usage(
                    db,
                    item.id,
                    item.dispatch_nonce,
                )
            )
            if (
                revision_count >= scope.max_continuation_revisions
                or failed_head_count >= scope.max_continuation_failed_heads
            ):
                note = (
                    "Automatic continuation stopped because the attempt-wide "
                    "revision or failed-head budget was exhausted."
                )
                self._apply_escalation(
                    item,
                    "continuation_budget_exhausted",
                    note,
                    preserve_existing_reason=False,
                )
                await db.commit()
                try:
                    await self._send_escalation_broadcast(
                        db,
                        item,
                        "continuation_budget_exhausted",
                        note,
                        owner_may_be_active=False,
                    )
                except Exception:
                    logger.exception(
                        "Failed to send continuation budget escalation for item %s",
                        item.id,
                    )
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="escalate_budget",
                    block_code="continuation_budget_exhausted",
                )
                continue
            sessions = await agent_mail_service.nudgeable_sessions_for_slot(
                db,
                item.owner_slot_id,
            )
            authenticated_sessions = [
                session
                for session in sessions
                if session.member_id == owner.id
                and session.capability_token_hash is not None
            ]
            if not authenticated_sessions:
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="skip",
                    block_code="owner_session_unavailable",
                )
                continue
            if (
                item.continuation_nudged_at is not None
                and now - item.continuation_nudged_at < recovery_nudge_cooldown
            ):
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=item.continuation_nudged_at,
                    now=now,
                    action="skip",
                    block_code="recovery_nudge_cooldown",
                )
                continue
            try:
                token = await github_approval_service.github_read_token(scope)
                pull = await github_client.get_pull(
                    scope.repo_owner,
                    scope.repo_name,
                    item.pr_number,
                    token=token,
                )
            except Exception:
                logger.exception(
                    "Recovery monitor could not validate PR for work item %s",
                    item.id,
                )
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="skip",
                    block_code="github_pr_lookup_failed",
                )
                continue
            if pull.get("state") != "open" or pull.get("merged_at") is not None:
                self._log_recovery_monitor(
                    item,
                    revision=None,
                    anchor=None,
                    now=now,
                    action="skip",
                    block_code="continuation_pr_not_open",
                )
                continue
            evidence = {
                "escalation_reason": item.escalation_reason,
                "status_note": item.status_note,
                "retry_count": item.retry_count,
                "diagnostic_retry_count": item.diagnostic_retry_count,
                "last_verified_sha": item.last_verified_sha,
                "diagnostic_last_verified_sha": item.diagnostic_last_verified_sha,
            }
            await agent_mail_service.send_direct_message(
                db,
                recipient_member_id=owner.id,
                subject=f"Recovery proposal requested: issue #{item.issue_number}",
                body_markdown=(
                    f"Work item {item.id} is preserving PR #{item.pr_number}, its "
                    "workspace, branch, owner, nonce, and history after escalation "
                    f"`{item.escalation_reason}`. Perform read-only diagnosis first. "
                    "Do not edit, build, push, or report completion yet. Then call "
                    "`deck_request_continuation` with the smallest exact paths, actions, "
                    "commands, execution target, failed-head budget, and tool fallbacks "
                    "needed for the next step. Wait for Leader approval and acknowledge "
                    "the delivered revision before acting."
                ),
                payload={
                    "kind": "github_dispatch_recovery_proposal_requested",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                    "pr_number": item.pr_number,
                    "dispatch_nonce": item.dispatch_nonce,
                    "failure_evidence": evidence,
                },
                auto_nudge=False,
                delivery_key=(
                    f"github-recovery:{item.id}:{item.dispatch_nonce}:proposal"
                ),
            )
            await agent_mail_service.auto_nudge_members(db, {owner.id})
            item.continuation_nudged_at = now
            item.updated_at = now
            await db.commit()
            self._log_recovery_monitor(
                item,
                revision=None,
                anchor=now,
                now=now,
                action="nudge_owner_proposal",
            )

    async def _brief_delivered(self, db: AsyncSession, item: GithubWorkItem) -> bool:
        """Return whether this attempt's brief reached its owner."""
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if workspace is not None and workspace.lease_last_owner_contact_at is not None:
            return True
        if item.brief_message_id is None:
            return False
        member = await self._owner_member(db, item)
        if member is None:
            return False
        receipt = (
            await db.execute(
                select(MailReceipt).where(
                    MailReceipt.message_id == item.brief_message_id,
                    MailReceipt.member_id == member.id,
                )
            )
        ).scalar_one_or_none()
        return receipt is not None and receipt.read_at is not None

    async def remind_held_leases(
        self, db: AsyncSession, scope: TeamGithubScope
    ) -> int:
        """Remind owners of terminal items that still hold a workspace lease.

        This never escalates: the work is already terminal for the owner, and
        the reminder exists only to bound a forgotten release. Its clock lives
        on the workspace so it cannot interfere with acknowledgment timers.
        """
        grace = timedelta(seconds=settings.github_nudge_grace_seconds)
        now = datetime.utcnow()
        held = (
            await db.execute(
                select(GithubWorkspace, GithubWorkItem)
                .join(
                    GithubWorkItem,
                    GithubWorkspace.leased_item_id == GithubWorkItem.id,
                )
                .where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_RELEASABLE_STATUSES),
                )
                .order_by(GithubWorkspace.id)
            )
        ).all()
        reminded = 0
        for workspace, item in held:
            if (
                workspace.lease_release_reminded_at is not None
                and now - workspace.lease_release_reminded_at < grace
            ):
                continue
            if item.retry_requested_at is not None:
                urgency = (
                    "\n\n**A re-dispatch of this issue is queued behind this "
                    "release.** It cannot start until you release the workspace."
                )
            else:
                urgency = ""
            await self.notify_owner(
                db,
                item,
                subject=f"Release needed: issue #{item.issue_number}",
                body_markdown=(
                    f"Issue #{item.issue_number} ({item.issue_title}) is "
                    f"`{item.dispatch_status}` but still holds workspace "
                    f"`{workspace.path}`. Commit and push anything you want to "
                    "keep, then release it:\n\n"
                    "```\n"
                    "deck_report_dispatch_status(\n"
                    f"    work_item_id={item.id},\n"
                    '    status="workspace_released",\n'
                    f'    lease_token="{workspace.lease_token}",\n'
                    ")\n"
                    "```"
                    f"{urgency}"
                ),
                payload={
                    "kind": "github_lease_release_reminder",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                    "workspace_path": workspace.path,
                },
            )
            workspace.lease_release_reminded_at = now
            workspace.updated_at = now
            reminded += 1
        if reminded:
            await db.commit()
        return reminded

    def _within_registration_grace(self, item: GithubWorkItem) -> bool:
        grace_started_at = item.dispatched_at or item.updated_at or item.created_at
        grace_age = datetime.utcnow() - grace_started_at
        return grace_age < timedelta(seconds=settings.github_owner_registration_grace_seconds)

    def _ack_satisfied(self, item: GithubWorkItem) -> bool:
        if item.pr_number is not None:
            return True
        if item.ack_received_at is None:
            return False
        if (
            item.dispatched_at is not None
            and item.ack_received_at < item.dispatched_at
        ):
            return False
        return True

    def _ack_deadline_seconds(self, item: GithubWorkItem) -> int:
        base = settings.github_leader_ack_timeout_seconds
        if item.issue_type == "design":
            return base * settings.github_design_ack_multiplier
        return base

    async def _nudge_leader_for_ack(
        self, db: AsyncSession, item: GithubWorkItem, leader: AgentTeamSlot
    ) -> None:
        member = await self._slot_member(db, leader.id)
        item.last_nudge_at = datetime.utcnow()
        if member is not None:
            from app.services.agent_mail_service import agent_mail_service

            await agent_mail_service.send_direct_message(
                db,
                recipient_member_id=member.id,
                subject=f"Ack needed: issue #{item.issue_number}",
                body_markdown=(
                    f"The owner is waiting on your explicit decision for issue "
                    f"#{item.issue_number} ({item.issue_title}). Review the plan, then "
                    f"call `deck_approve_work_item(work_item_id={item.id}, "
                    f'dispatch_nonce="{item.dispatch_nonce}", decision="approved", '
                    "reason=...)` or use `decision=\"rejected\"`. A prose reply does not "
                    "approve the work."
                ),
                payload={
                    "kind": "github_dispatch_ack_nudge",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                },
            )
        await db.commit()

    async def _nudge_owner_for_brief(
        self, db: AsyncSession, item: GithubWorkItem
    ) -> None:
        """Re-wake the owner without changing ack or idle timers."""
        item.brief_delivery_nudge_at = datetime.utcnow()
        item.brief_delivery_nudge_count = (item.brief_delivery_nudge_count or 0) + 1
        await self.notify_owner(
            db,
            item,
            subject=f"Unread dispatch brief: issue #{item.issue_number}",
            body_markdown=(
                f"You were assigned issue #{item.issue_number} ({item.issue_title}) "
                "but the brief is still unread. Call `deck_check_inbox` now and "
                "report your status."
            ),
            payload={
                "kind": "github_dispatch_brief_nudge",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
            },
        )
        await db.commit()

    async def _nudge_owner_for_progress(
        self, db: AsyncSession, item: GithubWorkItem
    ) -> None:
        item.last_nudge_at = datetime.utcnow()
        await self.notify_owner(
            db,
            item,
            subject=f"Progress check: issue #{item.issue_number}",
            body_markdown=(
                f"No PR yet for issue #{item.issue_number} ({item.issue_title}). "
                "Are you still making progress? Reply or report your status. If you "
                "are blocked, report `blocked` so a human can help."
            ),
            payload={
                "kind": "github_dispatch_idle_nudge",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
            },
        )
        await db.commit()

    async def escalate(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        reason: str,
        note: str | None = None,
    ) -> None:
        owner_may_be_active = (
            item.dispatch_status == "dispatched" and item.owner_slot_id is not None
        )
        applied = self._apply_escalation(item, reason, note)
        if not applied:
            return
        try:
            await self._send_escalation_broadcast(
                db,
                item,
                reason,
                note,
                owner_may_be_active=owner_may_be_active,
            )
            if reason == "dispatch_label_removed":
                await self._send_label_removed_owner_message(db, item)
        except Exception:
            logger.exception(
                "Failed to send autonomous dispatch escalation notification for item %s",
                item.id,
            )
            await db.rollback()
            self._apply_escalation(item, reason, note, preserve_existing_reason=False)

    async def escalate_without_notification(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        reason: str,
        note: str | None = None,
    ) -> None:
        """Persist an escalation whose contract explicitly forbids mail."""
        self._apply_escalation(item, reason, note, preserve_existing_reason=False)
        await db.commit()

    def _apply_escalation(
        self,
        item: GithubWorkItem,
        reason: str,
        note: str | None = None,
        *,
        preserve_existing_reason: bool = True,
    ) -> bool:
        if reason not in ESCALATION_REASONS:
            raise ValueError(f"undeclared escalation reason: {reason}")
        if (
            preserve_existing_reason
            and item.dispatch_status == "escalated"
            and item.escalation_reason
        ):
            return False
        item.dispatch_status = "escalated"
        item.escalation_reason = reason
        item.pending_reason = None
        if note is not None:
            item.status_note = note
        item.updated_at = datetime.utcnow()
        return True

    async def notify_owner(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        subject: str,
        body_markdown: str,
        payload: dict | None = None,
        delivery_key: str | None = None,
    ) -> None:
        member = await self._owner_member(db, item)
        if member is None:
            return
        from app.services.agent_mail_service import agent_mail_service

        await agent_mail_service.send_direct_message(
            db,
            recipient_member_id=member.id,
            subject=subject,
            body_markdown=body_markdown,
            payload=payload,
            delivery_key=delivery_key,
        )

    async def notify_team(
        self,
        db: AsyncSession,
        *,
        subject: str,
        body_markdown: str,
        payload: dict | None = None,
    ) -> None:
        from app.services.agent_mail_service import agent_mail_service

        await agent_mail_service.send_broadcast(
            db,
            subject=subject,
            body_markdown=body_markdown,
            payload=payload,
        )

    async def _send_escalation_broadcast(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        reason: str,
        note: str | None,
        *,
        owner_may_be_active: bool = False,
    ) -> None:
        scope = await db.get(TeamGithubScope, item.scope_id)
        repo = f"{scope.repo_owner}/{scope.repo_name}" if scope is not None else "unknown repo"
        lines = [
            f"Autonomous GitHub dispatch escalated issue #{item.issue_number}.",
            "",
            f"- Repo: {repo}",
            f"- Reason: {reason}",
            f"- Issue: {item.issue_title}",
        ]
        if item.issue_url:
            lines.append(f"- URL: {item.issue_url}")
        if owner_may_be_active:
            lines.extend(
                [
                    "",
                    "- NOTE: this item's owner session may still be working. Do NOT "
                    "retry it — retrying clears any PR it has opened. Confirm with the "
                    "coordinator first.",
                ]
            )
        if note:
            lines.extend(["", note])
        await self.notify_team(
            db,
            subject=f"Autonomy escalation: {reason}",
            body_markdown="\n".join(lines),
            payload={
                "kind": "github_dispatch_escalation",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
                "scope_id": item.scope_id,
                "reason": reason,
                "owner_may_be_active": owner_may_be_active,
            },
        )

    async def _send_label_removed_owner_message(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
    ) -> None:
        await self.notify_owner(
            db,
            item,
            subject="Dispatch label removed",
            body_markdown=(
                f"The triggering label was removed from issue #{item.issue_number}. "
                "A human wants this stopped or reconsidered. Finish or discard your "
                "current work at your discretion, but do not open or merge a PR without "
                "re-confirming with the team leader."
            ),
            payload={
                "kind": "github_dispatch_label_removed",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
            },
        )

    async def _escalated_items_payload(
        self, db: AsyncSession, scope: TeamGithubScope
    ) -> list[dict]:
        rows = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "escalated",
                )
            )
        ).scalars().all()
        return [
            {
                "work_item_id": row.id,
                "issue_number": row.issue_number,
                "escalation_reason": row.escalation_reason,
                "status_note": row.status_note,
            }
            for row in rows
        ]

    async def notify_blocker_merged(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        preset_slots: list[AgentTeamSlot],
    ) -> None:
        leader = self._leader_slot(preset_slots)
        if leader is None:
            return
        member = await self._slot_member(db, leader.id)
        if member is None:
            return
        escalated = await self._escalated_items_payload(db, scope)
        lines = [
            f"Blocker merged: issue #{item.issue_number} ({item.issue_title}).",
            "",
            "Currently escalated items (candidate dependents):",
        ]
        if escalated:
            for entry in escalated:
                lines.append(
                    f"- #{entry['issue_number']} (work_item {entry['work_item_id']}): "
                    f"{entry['status_note'] or entry['escalation_reason']}"
                )
        else:
            lines.append("- (none)")
        lines += [
            "",
            "If any of these were blocked ONLY by the merged issue (and all their "
            "other blockers are resolved), call "
            "`deck_retry_work_item(work_item_id=<id>, reason=\"prerequisite #"
            f"{item.issue_number} merged\")` to re-dispatch them.",
        ]
        from app.services.agent_mail_service import agent_mail_service

        await agent_mail_service.send_direct_message(
            db,
            recipient_member_id=member.id,
            subject=f"Blocker merged: issue #{item.issue_number}",
            body_markdown="\n".join(lines),
            payload={
                "kind": "github_dispatch_blocker_merged",
                "issue_number": item.issue_number,
                "work_item_id": item.id,
                "scope_id": item.scope_id,
                "escalated_items": escalated,
            },
        )

    async def _owner_member(self, db: AsyncSession, item: GithubWorkItem) -> MailTeamMember | None:
        if item.owner_slot_id is None:
            return None
        return await self._slot_member(db, item.owner_slot_id)

    async def _slot_member(self, db: AsyncSession, slot_id: int) -> MailTeamMember | None:
        return (
            await db.execute(
                select(MailTeamMember)
                .where(MailTeamMember.team_slot_id == slot_id)
                .order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


github_dispatch_service = GithubDispatchService()
