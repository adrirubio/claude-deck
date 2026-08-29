"""Normalized approval authority for autonomous GitHub work items."""

import hashlib
import hmac
import json
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.database import (
    AgentTeamSlot,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service
from app.services.github_app_auth_service import github_app_auth_service
from app.services.github_client import github_client


CONTINUABLE_ESCALATIONS = frozenset(
    {
        "retry_count_exhausted",
        "plan_blocked",
        "owner_idle_timeout",
        "owner_offline",
        "leader_offline",
        "leader_ack_timeout",
    }
)
_CONTINUATION_ACTIONS = frozenset(
    {
        "edit_production",
        "edit_tests",
        "edit_ci_workflow",
        "install_hosted_ci_tool",
        "push_pr_head",
        "collect_hosted_logs",
        "revert_diagnostic_changes",
        "request_verification",
    }
)
_PATH_GLOB_CHARACTERS = frozenset("*?[]{}")
_LEASE_HASH_DOMAIN = b"claude-deck:github-workspace-lease:v1\x00"


class GithubApprovalError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 409):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class GithubApprovalService:
    @staticmethod
    def canonical_payload_bytes(payload: dict) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @classmethod
    def fingerprint_payload(cls, payload: dict) -> str:
        return hashlib.sha256(cls.canonical_payload_bytes(payload)).hexdigest()

    @classmethod
    def initial_request_fingerprint(
        cls,
        *,
        summary: str,
        plan_metadata: dict | None,
    ) -> str:
        return cls.fingerprint_payload(
            {
                "plan_metadata": plan_metadata or {},
                "summary": summary.strip(),
            }
        )

    @staticmethod
    def lease_token_hash(lease_token: str) -> str:
        return hashlib.sha256(
            _LEASE_HASH_DOMAIN + lease_token.encode("utf-8")
        ).hexdigest()

    @classmethod
    def lease_token_matches(cls, lease_token: str, expected_hash: str) -> bool:
        return hmac.compare_digest(cls.lease_token_hash(lease_token), expected_hash)

    @staticmethod
    def _canonical_strings(
        values: list[str],
        *,
        label: str,
        allow_empty: bool = True,
    ) -> list[str]:
        normalized: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise GithubApprovalError(f"{label}_invalid", status_code=400)
            normalized.add(value.strip())
        if not allow_empty and not normalized:
            raise GithubApprovalError(f"{label}_required", status_code=400)
        return sorted(normalized)

    @classmethod
    def _canonical_paths(cls, values: list[str]) -> list[str]:
        paths = cls._canonical_strings(
            values,
            label="allowed_paths",
            allow_empty=False,
        )
        for path in paths:
            candidate = PurePosixPath(path)
            parts = path.split("/")
            if (
                path in {".", "./"}
                or path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in parts)
                or any(character in path for character in _PATH_GLOB_CHARACTERS)
                or str(candidate) != path
            ):
                raise GithubApprovalError("allowed_paths_invalid", status_code=400)
        return paths

    @classmethod
    def canonical_continuation_payload(
        cls,
        *,
        phase: str,
        execution_target: str,
        summary: str,
        allowed_paths: list[str],
        allowed_actions: list[str],
        allowed_commands: list[str],
        prohibited_actions: list[str],
        max_failed_heads: int,
        tool_fallbacks: dict,
        baseline_head_sha: str,
        baseline_tree_sha: str,
        expected_workspace_id: int,
        originating_escalation_reason: str,
    ) -> dict:
        return {
            "allowed_actions": allowed_actions,
            "allowed_commands": allowed_commands,
            "allowed_paths": allowed_paths,
            "baseline_head_sha": baseline_head_sha,
            "baseline_tree_sha": baseline_tree_sha,
            "execution_target": execution_target,
            "expected_workspace_id": expected_workspace_id,
            "max_failed_heads": max_failed_heads,
            "originating_escalation_reason": originating_escalation_reason,
            "phase": phase,
            "prohibited_actions": prohibited_actions,
            "summary": summary,
            "tool_fallbacks": tool_fallbacks,
        }

    @staticmethod
    async def github_read_token(scope: TeamGithubScope) -> str | None:
        if scope.github_auth_mode != "app":
            return None
        if scope.github_app_installation_id is None:
            raise GithubApprovalError("app_installation_id_missing")
        return await github_app_auth_service.mint_repository_token(
            scope.github_app_installation_id,
            scope.repo_owner,
            scope.repo_name,
            purpose="pull_request",
            cache_subject="continuation",
        )

    async def create_continuation_request(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        *,
        authenticated_owner_member_id: int,
        authenticated_owner_slot_id: int | None,
        dispatch_nonce: str,
        phase: str,
        execution_target: str,
        summary: str,
        allowed_paths: list[str],
        allowed_actions: list[str],
        allowed_commands: list[str],
        prohibited_actions: list[str],
        max_failed_heads: int,
        tool_fallbacks: dict,
        lease_token: str,
    ) -> tuple[GithubAttemptScopeRevision, GithubApprovalRequest, bool]:
        if not scope.continuation_enabled:
            raise GithubApprovalError("continuation_disabled")
        if item.scope_id != scope.id:
            raise GithubApprovalError("scope_mismatch")
        if item.dispatch_status != "escalated":
            raise GithubApprovalError("continuation_not_escalated")
        if item.escalation_reason not in CONTINUABLE_ESCALATIONS:
            raise GithubApprovalError("continuation_reason_not_allowed")
        if item.pr_number is None:
            raise GithubApprovalError("continuation_pr_required")
        if item.dispatch_nonce != dispatch_nonce:
            raise GithubApprovalError("stale_nonce")
        if phase == "diagnostic":
            raise GithubApprovalError("diagnostic_continuation_not_available")
        if phase != "implementation":
            raise GithubApprovalError("continuation_phase_invalid", status_code=400)
        if execution_target not in {
            "workspace",
            "hosted_ci",
            "workspace_and_hosted_ci",
        }:
            raise GithubApprovalError("execution_target_invalid", status_code=400)
        if not summary.strip():
            raise GithubApprovalError("continuation_summary_required", status_code=400)
        if not isinstance(tool_fallbacks, dict):
            raise GithubApprovalError("tool_fallbacks_invalid", status_code=400)

        owner, leader = await self._current_participants(db, item)
        if owner.id != authenticated_owner_member_id:
            raise GithubApprovalError("not_item_owner", status_code=403)
        if (
            authenticated_owner_slot_id is None
            or owner.team_slot_id != authenticated_owner_slot_id
            or item.owner_slot_id != authenticated_owner_slot_id
        ):
            raise GithubApprovalError("stale_approval_owner", status_code=409)

        workspace = (
            await db.execute(
                select(GithubWorkspace).where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkspace.leased_item_id == item.id,
                )
            )
        ).scalar_one_or_none()
        if workspace is None or workspace.lease_token is None:
            raise GithubApprovalError("workspace_lease_required")
        if not hmac.compare_digest(workspace.lease_token, lease_token):
            raise GithubApprovalError("lease_token_mismatch", status_code=403)

        canonical_paths = self._canonical_paths(allowed_paths)
        canonical_actions = self._canonical_strings(
            allowed_actions,
            label="allowed_actions",
            allow_empty=False,
        )
        unknown_actions = set(canonical_actions) - _CONTINUATION_ACTIONS
        if unknown_actions:
            raise GithubApprovalError("allowed_actions_invalid", status_code=400)
        canonical_commands = self._canonical_strings(
            allowed_commands,
            label="allowed_commands",
        )
        canonical_prohibitions = self._canonical_strings(
            prohibited_actions,
            label="prohibited_actions",
        )
        if len(canonical_paths) > scope.max_scope_paths:
            raise GithubApprovalError("continuation_path_limit_exceeded")
        if len(canonical_commands) > scope.max_scope_commands:
            raise GithubApprovalError("continuation_command_limit_exceeded")
        if max_failed_heads > scope.max_failed_heads_per_revision:
            raise GithubApprovalError("continuation_failed_head_limit_exceeded")

        revision_count, failed_head_count = (
            await db.execute(
                select(
                    func.count(GithubAttemptScopeRevision.id),
                    func.coalesce(func.sum(GithubAttemptScopeRevision.failed_head_count), 0),
                ).where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                )
            )
        ).one()
        if revision_count >= scope.max_continuation_revisions:
            raise GithubApprovalError("continuation_budget_exhausted")
        remaining_failed_heads = (
            scope.max_continuation_failed_heads - int(failed_head_count)
        )
        if remaining_failed_heads < max_failed_heads:
            raise GithubApprovalError("continuation_budget_exhausted")

        token = await self.github_read_token(scope)
        pull = await github_client.get_pull(
            scope.repo_owner,
            scope.repo_name,
            item.pr_number,
            token=token,
        )
        if pull.get("state") != "open":
            raise GithubApprovalError("continuation_pr_not_open")
        head = pull.get("head")
        head_sha = head.get("sha") if isinstance(head, dict) else None
        snapshot = await github_client.get_commit_snapshot(
            scope.repo_owner,
            scope.repo_name,
            head_sha,
            token=token,
        )
        await github_client.get_recursive_tree(
            scope.repo_owner,
            scope.repo_name,
            snapshot.tree_sha,
            token=token,
        )

        canonical_payload = self.canonical_continuation_payload(
            phase=phase,
            execution_target=execution_target,
            summary=summary.strip(),
            allowed_paths=canonical_paths,
            allowed_actions=canonical_actions,
            allowed_commands=canonical_commands,
            prohibited_actions=canonical_prohibitions,
            max_failed_heads=max_failed_heads,
            tool_fallbacks=tool_fallbacks,
            baseline_head_sha=snapshot.sha,
            baseline_tree_sha=snapshot.tree_sha,
            expected_workspace_id=workspace.id,
            originating_escalation_reason=item.escalation_reason,
        )
        request_fingerprint = self.fingerprint_payload(canonical_payload)
        identity = {
            "request_kind": "continuation",
            "dispatch_nonce": dispatch_nonce,
            "approval_round": item.approval_round_count,
            "owner_member_id": owner.id,
            "leader_member_id": leader.id,
            "request_fingerprint": request_fingerprint,
        }
        pending = await self.current_pending(db, item.id)
        if pending is not None:
            if self._same_request(pending, **identity) and pending.scope_revision_id:
                revision = await db.get(
                    GithubAttemptScopeRevision,
                    pending.scope_revision_id,
                )
                if revision is not None:
                    return revision, pending, False
            raise GithubApprovalError("approval_request_already_pending")
        nonterminal_revision = (
            await db.execute(
                select(GithubAttemptScopeRevision)
                .where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                    GithubAttemptScopeRevision.status.in_(
                        ("proposed", "approved", "active", "submitted")
                    ),
                )
                .order_by(GithubAttemptScopeRevision.revision.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if nonterminal_revision is not None:
            if nonterminal_revision.status == "approved":
                raise GithubApprovalError("continuation_ack_required")
            if nonterminal_revision.status in {"active", "submitted"}:
                raise GithubApprovalError("active_continuation")
            raise GithubApprovalError("approval_request_already_pending")
        terminal = (
            await db.execute(
                select(GithubApprovalRequest)
                .where(
                    GithubApprovalRequest.work_item_id == item.id,
                    GithubApprovalRequest.request_kind == "continuation",
                    GithubApprovalRequest.dispatch_nonce == dispatch_nonce,
                    GithubApprovalRequest.approval_round == item.approval_round_count,
                    GithubApprovalRequest.owner_member_id == owner.id,
                    GithubApprovalRequest.leader_member_id == leader.id,
                    GithubApprovalRequest.request_fingerprint == request_fingerprint,
                    GithubApprovalRequest.status.in_({"approved", "rejected"}),
                )
                .order_by(GithubApprovalRequest.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if terminal is not None and terminal.scope_revision_id is not None:
            terminal_revision = await db.get(
                GithubAttemptScopeRevision,
                terminal.scope_revision_id,
            )
            if terminal_revision is not None:
                return terminal_revision, terminal, False

        next_revision = (
            await db.execute(
                select(
                    func.coalesce(func.max(GithubAttemptScopeRevision.revision), 0) + 1
                ).where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                )
            )
        ).scalar_one()
        lease_exists = exists(
            select(GithubWorkspace.id).where(
                GithubWorkspace.id == workspace.id,
                GithubWorkspace.scope_id == scope.id,
                GithubWorkspace.leased_item_id == item.id,
                GithubWorkspace.lease_token == lease_token,
            )
        )
        item_guard = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status == "escalated",
                GithubWorkItem.dispatch_nonce == dispatch_nonce,
                GithubWorkItem.approval_round_count == item.approval_round_count,
                GithubWorkItem.owner_slot_id == authenticated_owner_slot_id,
                GithubWorkItem.pr_number == item.pr_number,
                GithubWorkItem.escalation_reason == item.escalation_reason,
                lease_exists,
            )
            .values(updated_at=GithubWorkItem.updated_at)
            .execution_options(synchronize_session=False)
        )
        if item_guard.rowcount != 1:
            await db.rollback()
            raise GithubApprovalError("stale_continuation_context")

        revision = GithubAttemptScopeRevision(
            work_item_id=item.id,
            dispatch_nonce=dispatch_nonce,
            revision=int(next_revision),
            owner_slot_id=authenticated_owner_slot_id,
            owner_member_id=owner.id,
            phase=phase,
            execution_target=execution_target,
            summary=canonical_payload["summary"],
            allowed_paths=canonical_paths,
            allowed_actions=canonical_actions,
            allowed_commands=canonical_commands,
            prohibited_actions=canonical_prohibitions,
            tool_fallbacks=tool_fallbacks,
            baseline_head_sha=snapshot.sha,
            baseline_tree_sha=snapshot.tree_sha,
            originating_escalation_reason=item.escalation_reason,
            expected_workspace_id=workspace.id,
            expected_lease_token_hash=self.lease_token_hash(lease_token),
            max_failed_heads=max_failed_heads,
        )
        db.add(revision)
        await db.flush()
        approval = GithubApprovalRequest(
            work_item_id=item.id,
            scope_revision_id=revision.id,
            **identity,
        )
        db.add(approval)
        try:
            await db.flush()
            revision.approval_request_id = approval.id
            await db.commit()
            await db.refresh(revision)
            await db.refresh(approval)
            return revision, approval, True
        except IntegrityError:
            await db.rollback()
            winner = await self.current_pending(db, item.id)
            if winner is not None and self._same_request(winner, **identity):
                if winner.scope_revision_id is not None:
                    winner_revision = await db.get(
                        GithubAttemptScopeRevision,
                        winner.scope_revision_id,
                    )
                    if winner_revision is not None:
                        return winner_revision, winner, False
            raise GithubApprovalError("approval_request_already_pending")

    @classmethod
    def matches_linked_request_message(
        cls,
        request: GithubApprovalRequest,
        message: MailMessage,
        *,
        delivery_key: str,
    ) -> bool:
        valid_request_statuses = (
            {"pending"}
            if request.status == "pending"
            else {"pending", "answered"}
        )
        if (
            message.kind != "context_request"
            or message.thread_root_id is not None
            or message.request_status not in valid_request_statuses
            or message.sender_member_id != request.owner_member_id
            or message.recipient_member_id != request.leader_member_id
            or message.delivery_key not in {None, delivery_key}
        ):
            return False
        payload = message.payload if isinstance(message.payload, dict) else {}
        if (
            payload.get("work_item_id") != request.work_item_id
            or payload.get("dispatch_nonce") != request.dispatch_nonce
            or payload.get("approval_round") != request.approval_round
        ):
            return False
        summary = payload.get("summary")
        if not isinstance(summary, str):
            summary = message.body_markdown
        plan_metadata = payload.get("plan_metadata")
        if not isinstance(plan_metadata, dict):
            plan_metadata = {}
        return request.request_fingerprint == cls.initial_request_fingerprint(
            summary=summary,
            plan_metadata=plan_metadata,
        )

    @classmethod
    def continuation_request_payload(
        cls,
        request: GithubApprovalRequest,
        revision: GithubAttemptScopeRevision,
    ) -> dict:
        return {
            "approval_request_id": request.id,
            "approval_round": request.approval_round,
            "dispatch_nonce": request.dispatch_nonce,
            "request_kind": "continuation",
            "scope_revision": {
                "allowed_actions": revision.allowed_actions,
                "allowed_commands": revision.allowed_commands,
                "allowed_paths": revision.allowed_paths,
                "baseline_head_sha": revision.baseline_head_sha,
                "baseline_tree_sha": revision.baseline_tree_sha,
                "execution_target": revision.execution_target,
                "max_failed_heads": revision.max_failed_heads,
                "phase": revision.phase,
                "prohibited_actions": revision.prohibited_actions,
                "revision": revision.revision,
                "scope_revision_id": revision.id,
                "summary": revision.summary,
                "tool_fallbacks": revision.tool_fallbacks,
            },
            "work_item_id": request.work_item_id,
        }

    @classmethod
    def matches_linked_continuation_request_message(
        cls,
        request: GithubApprovalRequest,
        revision: GithubAttemptScopeRevision,
        message: MailMessage,
        *,
        delivery_key: str,
    ) -> bool:
        return (
            message.kind == "context_request"
            and message.thread_root_id is None
            and message.request_status
            in ({"pending"} if request.status == "pending" else {"pending", "answered"})
            and message.sender_member_id == request.owner_member_id
            and message.recipient_member_id == request.leader_member_id
            and message.delivery_key == delivery_key
            and message.body_markdown == revision.summary
            and message.payload == cls.continuation_request_payload(request, revision)
        )

    @staticmethod
    def continuation_decision_payload(
        request: GithubApprovalRequest,
        revision: GithubAttemptScopeRevision,
    ) -> dict:
        return {
            "approval_request_id": request.id,
            "request_kind": "continuation",
            "revision": revision.revision,
            "scope_revision_id": revision.id,
            "work_item_id": request.work_item_id,
        }

    @classmethod
    def matches_linked_continuation_decision_message(
        cls,
        request: GithubApprovalRequest,
        revision: GithubAttemptScopeRevision,
        message: MailMessage,
        *,
        delivery_key: str,
    ) -> bool:
        return (
            message.kind == "answer"
            and message.thread_root_id == request.request_message_id
            and message.sender_member_id == request.leader_member_id
            and message.delivery_key == delivery_key
            and message.decision == request.status
            and message.body_markdown == request.reason
            and message.payload == cls.continuation_decision_payload(request, revision)
        )

    @staticmethod
    def continuation_delivery_payload(
        request: GithubApprovalRequest,
        revision: GithubAttemptScopeRevision,
    ) -> dict:
        return {
            "ack_required": True,
            "approval_request_id": request.id,
            "dispatch_nonce": revision.dispatch_nonce,
            "request_kind": "continuation",
            "scope_revision": {
                "allowed_actions": revision.allowed_actions,
                "allowed_commands": revision.allowed_commands,
                "allowed_paths": revision.allowed_paths,
                "baseline_head_sha": revision.baseline_head_sha,
                "baseline_tree_sha": revision.baseline_tree_sha,
                "execution_target": revision.execution_target,
                "max_failed_heads": revision.max_failed_heads,
                "phase": revision.phase,
                "prohibited_actions": revision.prohibited_actions,
                "revision": revision.revision,
                "scope_revision_id": revision.id,
                "summary": revision.summary,
                "tool_fallbacks": revision.tool_fallbacks,
            },
            "work_item_id": revision.work_item_id,
        }

    @classmethod
    def matches_linked_continuation_delivery_message(
        cls,
        request: GithubApprovalRequest,
        revision: GithubAttemptScopeRevision,
        message: MailMessage,
        *,
        delivery_key: str,
    ) -> bool:
        return (
            message.kind == "message"
            and message.thread_root_id is None
            and message.sender_member_id is None
            and message.sender_actor_id is None
            and message.recipient_member_id == revision.owner_member_id
            and message.delivery_key == delivery_key
            and message.body_markdown
            == (
                f"Continuation revision {revision.revision} is approved. "
                "Acknowledge it before making changes.\n\n"
                f"{revision.summary}"
            )
            and message.payload == cls.continuation_delivery_payload(request, revision)
        )

    async def deliver_approved_continuation(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        request: GithubApprovalRequest,
        revision: GithubAttemptScopeRevision,
    ) -> tuple[GithubAttemptScopeRevision, bool]:
        if request.request_kind != "continuation" or request.status != "approved":
            raise GithubApprovalError("continuation_not_approved")
        if request.decision_message_id is None:
            raise GithubApprovalError("approval_decision_delivery_pending")
        if request.scope_revision_id != revision.id:
            raise GithubApprovalError("approval_revision_link_mismatch")
        if revision.approval_request_id != request.id or revision.status != "approved":
            raise GithubApprovalError("continuation_not_approved")
        owner, _leader = await self._current_participants(db, item)
        if (
            item.dispatch_nonce != revision.dispatch_nonce
            or item.owner_slot_id != revision.owner_slot_id
            or owner.id != revision.owner_member_id
        ):
            raise GithubApprovalError("stale_approval_owner")
        delivery_key = f"github-scope:{revision.id}:delivery"
        if revision.delivery_message_id is not None:
            linked = await db.get(MailMessage, revision.delivery_message_id)
            if linked is None or not self.matches_linked_continuation_delivery_message(
                request,
                revision,
                linked,
                delivery_key=delivery_key,
            ):
                raise GithubApprovalError("continuation_delivery_link_mismatch")
            return revision, False

        now = datetime.utcnow()
        message = await agent_mail_service.send_direct_message(
            db,
            recipient_member_id=revision.owner_member_id,
            subject=(
                f"Approved continuation revision {revision.revision} for work item "
                f"{item.id}"
            ),
            body_markdown=(
                f"Continuation revision {revision.revision} is approved. "
                "Acknowledge it before making changes.\n\n"
                f"{revision.summary}"
            ),
            payload=self.continuation_delivery_payload(request, revision),
            auto_nudge=False,
            delivery_key=delivery_key,
        )
        link_result = await db.execute(
            update(GithubAttemptScopeRevision)
            .where(
                GithubAttemptScopeRevision.id == revision.id,
                GithubAttemptScopeRevision.status == "approved",
                GithubAttemptScopeRevision.approval_request_id == request.id,
                GithubAttemptScopeRevision.delivery_message_id.is_(None),
                exists(
                    select(GithubApprovalRequest.id).where(
                        GithubApprovalRequest.id == request.id,
                        GithubApprovalRequest.status == "approved",
                        GithubApprovalRequest.decision_message_id.is_not(None),
                    )
                ),
            )
            .values(
                delivery_message_id=message.id,
                delivered_at=now,
                last_delivery_attempt_at=now,
                delivery_attempt_count=(
                    GithubAttemptScopeRevision.delivery_attempt_count + 1
                ),
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        await db.refresh(revision)
        if link_result.rowcount != 1 and revision.delivery_message_id != message.id:
            raise GithubApprovalError("continuation_delivery_link_mismatch")
        await agent_mail_service.auto_nudge_members(db, {revision.owner_member_id})
        return revision, link_result.rowcount == 1

    async def current_pending(
        self,
        db: AsyncSession,
        work_item_id: int,
    ) -> GithubApprovalRequest | None:
        return (
            await db.execute(
                select(GithubApprovalRequest).where(
                    GithubApprovalRequest.work_item_id == work_item_id,
                    GithubApprovalRequest.status == "pending",
                )
            )
        ).scalar_one_or_none()

    async def current_terminal_for_attempt(
        self,
        db: AsyncSession,
        *,
        work_item_id: int,
        dispatch_nonce: str,
        approval_round: int,
        owner_member_id: int,
        leader_member_id: int,
    ) -> GithubApprovalRequest | None:
        return (
            await db.execute(
                select(GithubApprovalRequest)
                .where(
                    GithubApprovalRequest.work_item_id == work_item_id,
                    GithubApprovalRequest.request_kind == "initial_plan",
                    GithubApprovalRequest.dispatch_nonce == dispatch_nonce,
                    GithubApprovalRequest.approval_round == approval_round,
                    GithubApprovalRequest.owner_member_id == owner_member_id,
                    GithubApprovalRequest.leader_member_id == leader_member_id,
                    GithubApprovalRequest.status.in_({"approved", "rejected"}),
                )
                .order_by(GithubApprovalRequest.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _same_request(
        request: GithubApprovalRequest,
        *,
        request_kind: str,
        dispatch_nonce: str,
        approval_round: int,
        owner_member_id: int,
        leader_member_id: int,
        request_fingerprint: str,
    ) -> bool:
        return (
            request.request_kind == request_kind
            and request.dispatch_nonce == dispatch_nonce
            and request.approval_round == approval_round
            and request.owner_member_id == owner_member_id
            and request.leader_member_id == leader_member_id
            and request.request_fingerprint == request_fingerprint
        )

    @staticmethod
    def _attempt_identity_changed(
        request: GithubApprovalRequest,
        *,
        dispatch_nonce: str,
        approval_round: int,
        owner_member_id: int,
        leader_member_id: int,
    ) -> bool:
        return (
            request.dispatch_nonce != dispatch_nonce
            or request.approval_round != approval_round
            or request.owner_member_id != owner_member_id
            or request.leader_member_id != leader_member_id
        )

    async def _current_participants(self, db: AsyncSession, item: GithubWorkItem):
        owner, leader = await agent_mail_service._dispatch_participants(db, item)
        if owner is None:
            raise GithubApprovalError("owner_not_registered", status_code=409)
        if leader is None:
            raise GithubApprovalError("leader_not_registered", status_code=409)
        if owner.id == leader.id or owner.team_slot_id == leader.team_slot_id:
            raise GithubApprovalError("owner_cannot_approve_own_work", status_code=409)
        return owner, leader

    async def create_initial_request(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        authenticated_owner_member_id: int,
        summary: str,
        plan_metadata: dict | None = None,
    ) -> tuple[GithubApprovalRequest, bool]:
        if not summary.strip():
            raise GithubApprovalError("approval_summary_required", status_code=400)
        if item.dispatch_nonce is None:
            raise GithubApprovalError("dispatch_nonce_missing", status_code=409)
        if item.approval_round_count < 1:
            raise GithubApprovalError("approval_round_not_open", status_code=409)
        if item.dispatch_status == "escalated":
            raise GithubApprovalError("item_escalated", status_code=409)
        owner, leader = await self._current_participants(db, item)
        if owner.id != authenticated_owner_member_id:
            raise GithubApprovalError("not_item_owner", status_code=403)

        request_fingerprint = self.initial_request_fingerprint(
            summary=summary,
            plan_metadata=plan_metadata,
        )
        identity = {
            "request_kind": "initial_plan",
            "dispatch_nonce": item.dispatch_nonce,
            "approval_round": item.approval_round_count,
            "owner_member_id": owner.id,
            "leader_member_id": leader.id,
            "request_fingerprint": request_fingerprint,
        }
        pending = await self.current_pending(db, item.id)
        if pending is not None:
            if self._same_request(pending, **identity):
                return pending, False
            if not self._attempt_identity_changed(
                pending,
                dispatch_nonce=item.dispatch_nonce,
                approval_round=item.approval_round_count,
                owner_member_id=owner.id,
                leader_member_id=leader.id,
            ):
                raise GithubApprovalError("approval_request_already_pending")

        terminal = await self.current_terminal_for_attempt(
            db,
            work_item_id=item.id,
            dispatch_nonce=item.dispatch_nonce,
            approval_round=item.approval_round_count,
            owner_member_id=owner.id,
            leader_member_id=leader.id,
        )
        if terminal is not None:
            if self._same_request(terminal, **identity):
                return terminal, False
            raise GithubApprovalError("approval_request_already_decided")

        if pending is not None:
            pending.status = "superseded"
            pending.superseded_at = datetime.utcnow()
            if pending.request_message_id is not None:
                root = await db.get(MailMessage, pending.request_message_id)
                if root is not None and root.request_status == "pending":
                    root.request_status = "superseded"
            await db.flush()

        work_item_id = item.id
        if owner.team_slot_id is None:
            raise GithubApprovalError("stale_approval_owner")
        terminal_exists = exists(
            select(GithubApprovalRequest.id).where(
                GithubApprovalRequest.work_item_id == work_item_id,
                GithubApprovalRequest.request_kind == "initial_plan",
                GithubApprovalRequest.dispatch_nonce == item.dispatch_nonce,
                GithubApprovalRequest.approval_round == item.approval_round_count,
                GithubApprovalRequest.owner_member_id == owner.id,
                GithubApprovalRequest.leader_member_id == leader.id,
                GithubApprovalRequest.status.in_({"approved", "rejected"}),
            )
        )
        guard = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == work_item_id,
                GithubWorkItem.dispatch_status != "escalated",
                GithubWorkItem.dispatch_nonce == item.dispatch_nonce,
                GithubWorkItem.approval_round_count == item.approval_round_count,
                GithubWorkItem.owner_slot_id == owner.team_slot_id,
                ~terminal_exists,
            )
            .values(updated_at=GithubWorkItem.updated_at)
            .execution_options(synchronize_session=False)
        )
        if guard.rowcount != 1:
            await db.rollback()
            await db.refresh(item)
            if item.dispatch_status == "escalated":
                raise GithubApprovalError("item_escalated")
            if item.dispatch_nonce != identity["dispatch_nonce"]:
                raise GithubApprovalError("stale_nonce")
            if item.approval_round_count != identity["approval_round"]:
                raise GithubApprovalError("approval_round_mismatch")
            terminal = await self.current_terminal_for_attempt(
                db,
                work_item_id=work_item_id,
                dispatch_nonce=identity["dispatch_nonce"],
                approval_round=identity["approval_round"],
                owner_member_id=identity["owner_member_id"],
                leader_member_id=identity["leader_member_id"],
            )
            if terminal is not None:
                if self._same_request(terminal, **identity):
                    return terminal, False
                raise GithubApprovalError("approval_request_already_decided")
            raise GithubApprovalError("stale_approval_owner")
        request = GithubApprovalRequest(work_item_id=work_item_id, **identity)
        db.add(request)
        try:
            await db.commit()
            await db.refresh(request)
            return request, True
        except IntegrityError:
            await db.rollback()
            winner = await self.current_pending(db, work_item_id)
            if winner is not None and self._same_request(winner, **identity):
                return winner, False
            raise GithubApprovalError("approval_request_already_pending")

    async def resolve_for_decision(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        request_id: int,
        expected_kind: str = "initial_plan",
    ) -> GithubApprovalRequest:
        request = await db.get(GithubApprovalRequest, request_id)
        if request is None or request.work_item_id != item.id:
            raise GithubApprovalError("approval_request_not_found", status_code=404)
        if request.request_kind != expected_kind:
            raise GithubApprovalError("approval_request_not_found", status_code=404)
        return request

    async def decide(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        authenticated_leader_member_id: int,
        decision: str,
        reason: str,
        request_id: int,
    ) -> tuple[GithubApprovalRequest, bool]:
        request = await self.resolve_for_decision(
            db,
            item,
            request_id=request_id,
            expected_kind="initial_plan",
        )
        owner, leader = await self._current_participants(db, item)
        if leader.id != authenticated_leader_member_id:
            raise GithubApprovalError("not_designated_leader", status_code=403)
        if request.owner_member_id != owner.id:
            raise GithubApprovalError("stale_approval_owner")
        if request.leader_member_id != leader.id:
            raise GithubApprovalError("stale_approval_recipient")
        if request.dispatch_nonce != item.dispatch_nonce:
            raise GithubApprovalError("stale_nonce")
        if request.request_message_id is None:
            raise GithubApprovalError("approval_request_delivery_pending")
        if request.status != "pending":
            if request.status not in {"approved", "rejected"}:
                raise GithubApprovalError("request_not_pending")
            if request.status == decision and request.reason == reason:
                valid_rounds = {request.approval_round}
                if decision == "rejected":
                    valid_rounds.add(request.approval_round + 1)
                if item.approval_round_count not in valid_rounds:
                    raise GithubApprovalError("approval_round_mismatch")
                return request, False
            raise GithubApprovalError("approval_request_already_decided")
        if item.dispatch_status == "escalated":
            raise GithubApprovalError("item_escalated")
        if request.approval_round != item.approval_round_count:
            raise GithubApprovalError("approval_round_mismatch")
        if owner.team_slot_id is None:
            raise GithubApprovalError("stale_approval_owner")
        item_guard = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status != "escalated",
                GithubWorkItem.dispatch_nonce == request.dispatch_nonce,
                GithubWorkItem.approval_round_count == request.approval_round,
                GithubWorkItem.owner_slot_id == owner.team_slot_id,
            )
            .values(updated_at=GithubWorkItem.updated_at)
            .execution_options(synchronize_session=False)
        )
        if item_guard.rowcount != 1:
            await db.rollback()
            await db.refresh(item)
            if item.dispatch_status == "escalated":
                raise GithubApprovalError("item_escalated")
            if item.dispatch_nonce != request.dispatch_nonce:
                raise GithubApprovalError("stale_nonce")
            if item.approval_round_count != request.approval_round:
                raise GithubApprovalError("approval_round_mismatch")
            raise GithubApprovalError("stale_approval_owner")
        result = await db.execute(
            update(GithubApprovalRequest)
            .where(
                GithubApprovalRequest.id == request.id,
                GithubApprovalRequest.status == "pending",
                GithubApprovalRequest.request_kind == "initial_plan",
                GithubApprovalRequest.dispatch_nonce == item.dispatch_nonce,
                GithubApprovalRequest.approval_round == item.approval_round_count,
                GithubApprovalRequest.owner_member_id == owner.id,
                GithubApprovalRequest.leader_member_id == leader.id,
                exists(
                    select(GithubWorkItem.id).where(
                        GithubWorkItem.id == request.work_item_id,
                        GithubWorkItem.dispatch_status != "escalated",
                        GithubWorkItem.dispatch_nonce == request.dispatch_nonce,
                        GithubWorkItem.approval_round_count
                        == request.approval_round,
                        GithubWorkItem.owner_slot_id == owner.team_slot_id,
                    )
                ),
            )
            .values(
                status=decision,
                reason=reason,
                decided_at=datetime.utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        await db.refresh(request)
        if result.rowcount == 1:
            return request, True
        if request.status == decision and request.reason == reason:
            return request, False
        await db.refresh(item)
        if item.dispatch_status == "escalated":
            raise GithubApprovalError("item_escalated")
        if item.dispatch_nonce != request.dispatch_nonce:
            raise GithubApprovalError("stale_nonce")
        if item.approval_round_count != request.approval_round:
            raise GithubApprovalError("approval_round_mismatch")
        if item.owner_slot_id != owner.team_slot_id:
            raise GithubApprovalError("stale_approval_owner")
        raise GithubApprovalError("approval_request_already_decided")

    async def decide_continuation(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        authenticated_leader_member_id: int,
        decision: str,
        reason: str,
        request_id: int,
    ) -> tuple[GithubApprovalRequest, GithubAttemptScopeRevision, bool]:
        request = await self.resolve_for_decision(
            db,
            item,
            request_id=request_id,
            expected_kind="continuation",
        )
        work_item_id = item.id
        if request.scope_revision_id is None:
            raise GithubApprovalError("scope_revision_not_found", status_code=404)
        revision = await db.get(
            GithubAttemptScopeRevision,
            request.scope_revision_id,
        )
        if revision is None or revision.work_item_id != item.id:
            raise GithubApprovalError("scope_revision_not_found", status_code=404)
        owner, leader = await self._current_participants(db, item)
        if leader.id != authenticated_leader_member_id:
            raise GithubApprovalError("not_designated_leader", status_code=403)
        if request.owner_member_id != owner.id or revision.owner_member_id != owner.id:
            raise GithubApprovalError("stale_approval_owner")
        if request.leader_member_id != leader.id:
            raise GithubApprovalError("stale_approval_recipient")
        if owner.team_slot_id is None or revision.owner_slot_id != owner.team_slot_id:
            raise GithubApprovalError("stale_approval_owner")
        if request.dispatch_nonce != item.dispatch_nonce:
            raise GithubApprovalError("stale_nonce")
        if revision.dispatch_nonce != request.dispatch_nonce:
            raise GithubApprovalError("stale_nonce")
        if request.approval_round != item.approval_round_count:
            raise GithubApprovalError("approval_round_mismatch")
        if revision.approval_request_id != request.id:
            raise GithubApprovalError("approval_revision_link_mismatch")
        if request.request_message_id is None:
            raise GithubApprovalError("approval_request_delivery_pending")
        if request.status != "pending":
            if request.status not in {"approved", "rejected"}:
                raise GithubApprovalError("request_not_pending")
            expected_revision_status = (
                "approved" if request.status == "approved" else "rejected"
            )
            if (
                request.status == decision
                and request.reason == reason
                and revision.status == expected_revision_status
            ):
                return request, revision, False
            raise GithubApprovalError("approval_request_already_decided")
        if item.dispatch_status != "escalated":
            raise GithubApprovalError("continuation_not_escalated")
        if item.escalation_reason != revision.originating_escalation_reason:
            raise GithubApprovalError("continuation_escalation_changed")
        if revision.status != "proposed":
            raise GithubApprovalError("request_not_pending")
        now = datetime.utcnow()
        if revision.expires_at is not None and revision.expires_at <= now:
            raise GithubApprovalError("continuation_request_expired")

        leader_slot = aliased(AgentTeamSlot)
        earlier_slot = aliased(AgentTeamSlot)
        leader_member = aliased(MailTeamMember)
        newer_leader_member = aliased(MailTeamMember)
        current_leader_exists = exists(
            select(leader_slot.id)
            .join(
                TeamGithubScope,
                TeamGithubScope.preset_id == leader_slot.preset_id,
            )
            .join(
                leader_member,
                leader_member.team_slot_id == leader_slot.id,
            )
            .where(
                TeamGithubScope.id == item.scope_id,
                leader_slot.enabled.is_(True),
                leader_member.id == authenticated_leader_member_id,
                ~exists(
                    select(earlier_slot.id).where(
                        earlier_slot.preset_id == leader_slot.preset_id,
                        earlier_slot.enabled.is_(True),
                        or_(
                            earlier_slot.position < leader_slot.position,
                            and_(
                                earlier_slot.position == leader_slot.position,
                                earlier_slot.id < leader_slot.id,
                            ),
                        ),
                    )
                ),
                ~exists(
                    select(newer_leader_member.id).where(
                        newer_leader_member.team_slot_id == leader_slot.id,
                        or_(
                            newer_leader_member.updated_at
                            > leader_member.updated_at,
                            and_(
                                newer_leader_member.updated_at
                                == leader_member.updated_at,
                                newer_leader_member.id > leader_member.id,
                            ),
                        ),
                    )
                ),
            )
        )

        item_guard = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status == "escalated",
                GithubWorkItem.dispatch_nonce == request.dispatch_nonce,
                GithubWorkItem.approval_round_count == request.approval_round,
                GithubWorkItem.owner_slot_id == owner.team_slot_id,
                GithubWorkItem.pr_number.is_not(None),
                GithubWorkItem.escalation_reason
                == revision.originating_escalation_reason,
            )
            .values(updated_at=GithubWorkItem.updated_at)
            .execution_options(synchronize_session=False)
        )
        if item_guard.rowcount != 1:
            await db.rollback()
            raise GithubApprovalError("stale_continuation_context")
        approval_result = await db.execute(
            update(GithubApprovalRequest)
            .where(
                GithubApprovalRequest.id == request.id,
                GithubApprovalRequest.status == "pending",
                GithubApprovalRequest.request_kind == "continuation",
                GithubApprovalRequest.scope_revision_id == revision.id,
                GithubApprovalRequest.dispatch_nonce == item.dispatch_nonce,
                GithubApprovalRequest.approval_round == item.approval_round_count,
                GithubApprovalRequest.owner_member_id == owner.id,
                GithubApprovalRequest.leader_member_id == leader.id,
                current_leader_exists,
            )
            .values(status=decision, reason=reason, decided_at=now)
            .execution_options(synchronize_session=False)
        )
        revision_result = await db.execute(
            update(GithubAttemptScopeRevision)
            .where(
                GithubAttemptScopeRevision.id == revision.id,
                GithubAttemptScopeRevision.status == "proposed",
                GithubAttemptScopeRevision.approval_request_id == request.id,
                GithubAttemptScopeRevision.dispatch_nonce == item.dispatch_nonce,
                GithubAttemptScopeRevision.owner_slot_id == owner.team_slot_id,
                GithubAttemptScopeRevision.owner_member_id == owner.id,
                GithubAttemptScopeRevision.originating_escalation_reason
                == item.escalation_reason,
            )
            .values(
                status="approved" if decision == "approved" else "rejected",
                approved_at=now if decision == "approved" else None,
            )
            .execution_options(synchronize_session=False)
        )
        if approval_result.rowcount != 1 or revision_result.rowcount != 1:
            await db.rollback()
            current_item = await db.get(GithubWorkItem, work_item_id)
            if current_item is None:
                raise GithubApprovalError("work_item_not_found", status_code=404)
            _current_owner, current_leader = await self._current_participants(
                db,
                current_item,
            )
            if current_leader.id != authenticated_leader_member_id:
                raise GithubApprovalError("stale_approval_recipient")
            raise GithubApprovalError("approval_request_already_decided")
        await db.commit()
        await db.refresh(request)
        await db.refresh(revision)
        return request, revision, True

    async def cancel(
        self,
        db: AsyncSession,
        request: GithubApprovalRequest,
        *,
        requester_member_id: int,
    ) -> tuple[GithubApprovalRequest, bool]:
        if requester_member_id != request.owner_member_id:
            raise GithubApprovalError("not_approval_requester", status_code=403)
        return await self._cancel_authorized(db, request)

    async def _cancel_authorized(
        self,
        db: AsyncSession,
        request: GithubApprovalRequest,
    ) -> tuple[GithubApprovalRequest, bool]:
        if request.status == "superseded":
            return request, False
        if request.status != "pending":
            raise GithubApprovalError("request_not_pending")
        current = await self.current_pending(db, request.work_item_id)
        if current is None or current.id != request.id:
            raise GithubApprovalError("request_not_pending")
        revision = None
        if request.scope_revision_id is not None:
            revision = await db.get(
                GithubAttemptScopeRevision,
                request.scope_revision_id,
            )
            if revision is None or revision.status != "proposed":
                raise GithubApprovalError("request_not_pending")
        now = datetime.utcnow()
        result = await db.execute(
            update(GithubApprovalRequest)
            .where(
                GithubApprovalRequest.id == request.id,
                GithubApprovalRequest.status == "pending",
            )
            .values(status="superseded", superseded_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await db.rollback()
            await db.refresh(request)
            if request.status == "superseded":
                return request, False
            raise GithubApprovalError("request_not_pending")
        if revision is not None:
            revision.status = "superseded"
        if request.request_message_id is not None:
            root = await db.get(MailMessage, request.request_message_id)
            if root is not None:
                root.request_status = "superseded"
        await db.commit()
        await db.refresh(request)
        return request, True


github_approval_service = GithubApprovalService()
