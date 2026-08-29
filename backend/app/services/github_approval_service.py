"""Normalized approval authority for autonomous GitHub work items."""

import hashlib
import hmac
import json
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    MailMessage,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service
from app.services.github_app_auth_service import github_app_auth_service
from app.services.github_client import github_client


_CONTINUABLE_ESCALATIONS = frozenset(
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
    async def _github_read_token(scope: TeamGithubScope) -> str | None:
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
        if item.escalation_reason not in _CONTINUABLE_ESCALATIONS:
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

        token = await self._github_read_token(scope)
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
    ) -> GithubApprovalRequest:
        request = await db.get(GithubApprovalRequest, request_id)
        if request is None or request.work_item_id != item.id:
            raise GithubApprovalError("approval_request_not_found", status_code=404)
        if request.request_kind != "initial_plan":
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
        request = await self.resolve_for_decision(db, item, request_id=request_id)
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
