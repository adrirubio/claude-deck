"""GitHub PR verification and merge loop for autonomous dispatch."""
from __future__ import annotations

import asyncio
import hmac
import logging
import subprocess
from collections.abc import Mapping
from datetime import datetime, timedelta

import httpx
from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import (
    AgentTeamSlot,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_app_auth_service import github_app_auth_service
from app.services.agent_mail_service import agent_mail_service
from app.services.github_approval_service import github_approval_service
from app.services.github_client import (
    GithubClient,
    GithubClientResponseError,
    GithubTreeEntry,
    github_client,
)
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_workspace_service import github_workspace_service

_SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
_STATUS_SUCCESS_STATES = {"success"}
_STATUS_FAILURE_STATES = {"failure", "error"}
_TRANSIENT_MERGE_STATES = {"unstable", "blocked"}
_HUMAN_MERGE_NOTE_PREFIXES = (
    "Auto-merge blocked",
    "Auto-merge budget exhausted",
    "Auto-merge failed",
    "Auto-merge retry budget exhausted",
)
_MERGE_TRANSIENT_STATUS_CODES = {405, 409, 422}
# Escalations a late PR legitimately resolves: the agent said it was stuck, or Deck
# inferred it from a timer. Anything not listed stays rejected by default.
_PR_OPENED_RECOVERABLE_ESCALATIONS = frozenset(
    {
        "plan_blocked",
        "owner_idle_timeout",
        "owner_offline",
        "leader_offline",
        "leader_ack_timeout",
        "brief_unread",
    }
)

logger = logging.getLogger(__name__)


class ContinuationCompletionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class GithubVerificationService:
    def __init__(self) -> None:
        self._pr_ready_locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def _changed_tree_paths(
        baseline: Mapping[str, GithubTreeEntry],
        current: Mapping[str, GithubTreeEntry],
    ) -> set[str]:
        def snapshot(
            entries: Mapping[str, GithubTreeEntry],
        ) -> dict[str, tuple[str, str, str]]:
            return {
                entry.path: (entry.mode, entry.object_type, entry.sha)
                for entry in entries.values()
                if entry.object_type != "tree"
            }

        baseline_paths = snapshot(baseline)
        current_paths = snapshot(current)
        return {
            path
            for path in baseline_paths.keys() | current_paths.keys()
            if baseline_paths.get(path) != current_paths.get(path)
        }

    async def submit_continuation_completion(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        *,
        authenticated_owner_member_id: int,
        authenticated_owner_slot_id: int,
        revision_number: int,
        dispatch_nonce: str,
        current_head_sha: str,
        result_summary: str,
        evidence: dict,
        lease_token: str,
        client: GithubClient | None = None,
    ) -> bool:
        client = client or github_client
        await db.refresh(item)
        if item.scope_id != scope.id:
            raise ContinuationCompletionError("scope_mismatch")
        if item.dispatch_nonce != dispatch_nonce:
            raise ContinuationCompletionError("stale_nonce")
        if item.owner_slot_id != authenticated_owner_slot_id:
            raise ContinuationCompletionError("not_item_owner")
        owner, _leader = await agent_mail_service._dispatch_participants(db, item)
        if owner is None or owner.id != authenticated_owner_member_id:
            raise ContinuationCompletionError("not_item_owner")
        revision = (
            await db.execute(
                select(GithubAttemptScopeRevision).where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                    GithubAttemptScopeRevision.revision == revision_number,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise ContinuationCompletionError("scope_revision_not_found")
        await db.refresh(revision)
        if (
            item.active_scope_revision != revision.revision
            or revision.owner_slot_id != authenticated_owner_slot_id
            or revision.owner_member_id != authenticated_owner_member_id
            or revision.phase != "implementation"
        ):
            raise ContinuationCompletionError("stale_scope_revision")
        if revision.status not in {"active", "submitted"}:
            raise ContinuationCompletionError("scope_revision_not_active")
        required_actions = {"push_pr_head", "request_verification"}
        if not required_actions.issubset(set(revision.allowed_actions)):
            raise ContinuationCompletionError("continuation_actions_missing")
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if (
            workspace is None
            or workspace.id != revision.expected_workspace_id
            or workspace.lease_token is None
        ):
            raise ContinuationCompletionError("workspace_lease_changed")
        if not hmac.compare_digest(workspace.lease_token, lease_token):
            raise ContinuationCompletionError("lease_token_mismatch")
        if not github_approval_service.lease_token_matches(
            lease_token,
            revision.expected_lease_token_hash,
        ):
            raise ContinuationCompletionError("workspace_lease_changed")
        if item.pr_number is None:
            raise ContinuationCompletionError("continuation_pr_required")
        token = await github_approval_service.github_read_token(scope)
        pull = await client.get_pull(
            scope.repo_owner,
            scope.repo_name,
            item.pr_number,
            token=token,
        )
        head = pull.get("head")
        github_head_sha = head.get("sha") if isinstance(head, dict) else None
        if pull.get("state") != "open":
            raise ContinuationCompletionError("continuation_pr_not_open")
        if github_head_sha != current_head_sha:
            raise ContinuationCompletionError("continuation_head_changed")
        current_snapshot = await client.get_commit_snapshot(
            scope.repo_owner,
            scope.repo_name,
            current_head_sha,
            token=token,
        )
        try:
            baseline_tree = await client.get_recursive_tree(
                scope.repo_owner,
                scope.repo_name,
                revision.baseline_tree_sha,
                token=token,
            )
            current_tree = await client.get_recursive_tree(
                scope.repo_owner,
                scope.repo_name,
                current_snapshot.tree_sha,
                token=token,
            )
        except GithubClientResponseError as exc:
            raise ContinuationCompletionError(
                "continuation_diff_inconclusive"
            ) from exc
        changed_paths = self._changed_tree_paths(baseline_tree, current_tree)
        if not changed_paths.issubset(set(revision.allowed_paths)):
            raise ContinuationCompletionError("continuation_paths_out_of_scope")
        if (
            revision.status == "submitted"
            and item.dispatch_status == "verifying"
            and revision.submitted_head_sha == current_head_sha
            and revision.result_summary == result_summary
            and revision.evidence == evidence
        ):
            return False
        if revision.status != "active" or item.dispatch_status != "dispatched":
            raise ContinuationCompletionError("stale_continuation_context")

        now = datetime.utcnow()
        item_result = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status == "dispatched",
                GithubWorkItem.dispatch_nonce == dispatch_nonce,
                GithubWorkItem.owner_slot_id == authenticated_owner_slot_id,
                GithubWorkItem.active_scope_revision == revision.revision,
                GithubWorkItem.pr_number.is_not(None),
                exists(
                    select(GithubWorkspace.id).where(
                        GithubWorkspace.id == workspace.id,
                        GithubWorkspace.leased_item_id == item.id,
                        GithubWorkspace.lease_token == lease_token,
                    )
                ),
            )
            .values(dispatch_status="verifying", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        revision_result = await db.execute(
            update(GithubAttemptScopeRevision)
            .where(
                GithubAttemptScopeRevision.id == revision.id,
                GithubAttemptScopeRevision.status == "active",
                GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                GithubAttemptScopeRevision.owner_slot_id
                == authenticated_owner_slot_id,
                GithubAttemptScopeRevision.owner_member_id
                == authenticated_owner_member_id,
                GithubAttemptScopeRevision.expected_workspace_id == workspace.id,
            )
            .values(
                status="submitted",
                result_summary=result_summary,
                evidence=evidence,
                submitted_head_sha=current_head_sha,
                submitted_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if item_result.rowcount != 1 or revision_result.rowcount != 1:
            await db.rollback()
            raise ContinuationCompletionError("stale_continuation_context")
        await db.commit()
        await db.refresh(item)
        return True

    async def submit_diagnostic_completion(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        *,
        authenticated_owner_member_id: int,
        authenticated_owner_slot_id: int,
        revision_number: int,
        dispatch_nonce: str,
        current_head_sha: str,
        result_summary: str,
        evidence: dict,
        lease_token: str,
        client: GithubClient | None = None,
    ) -> bool:
        client = client or github_client
        await db.refresh(item)
        if item.scope_id != scope.id:
            raise ContinuationCompletionError("scope_mismatch")
        if item.dispatch_nonce != dispatch_nonce:
            raise ContinuationCompletionError("stale_nonce")
        if item.owner_slot_id != authenticated_owner_slot_id:
            raise ContinuationCompletionError("not_item_owner")
        owner, _leader = await agent_mail_service._dispatch_participants(db, item)
        if owner is None or owner.id != authenticated_owner_member_id:
            raise ContinuationCompletionError("not_item_owner")
        revision = (
            await db.execute(
                select(GithubAttemptScopeRevision).where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                    GithubAttemptScopeRevision.revision == revision_number,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise ContinuationCompletionError("scope_revision_not_found")
        await db.refresh(revision)
        if (
            revision.owner_slot_id != authenticated_owner_slot_id
            or revision.owner_member_id != authenticated_owner_member_id
            or revision.phase != "diagnostic"
        ):
            raise ContinuationCompletionError("stale_scope_revision")
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if (
            workspace is None
            or workspace.id != revision.expected_workspace_id
            or workspace.lease_token is None
        ):
            raise ContinuationCompletionError("workspace_lease_changed")
        if not hmac.compare_digest(workspace.lease_token, lease_token):
            raise ContinuationCompletionError("lease_token_mismatch")
        if not github_approval_service.lease_token_matches(
            lease_token,
            revision.expected_lease_token_hash,
        ):
            raise ContinuationCompletionError("workspace_lease_changed")
        if item.pr_number is None:
            raise ContinuationCompletionError("continuation_pr_required")
        token = await github_approval_service.github_read_token(scope)
        pull = await client.get_pull(
            scope.repo_owner,
            scope.repo_name,
            item.pr_number,
            token=token,
        )
        head = pull.get("head")
        github_head_sha = head.get("sha") if isinstance(head, dict) else None
        if pull.get("state") != "open":
            raise ContinuationCompletionError("continuation_pr_not_open")
        if github_head_sha != current_head_sha:
            raise ContinuationCompletionError("continuation_head_changed")
        snapshot = await client.get_commit_snapshot(
            scope.repo_owner,
            scope.repo_name,
            current_head_sha,
            token=token,
        )
        if snapshot.tree_sha != revision.baseline_tree_sha:
            raise ContinuationCompletionError("diagnostic_tree_not_restored")
        confirmed_pull = await client.get_pull(
            scope.repo_owner,
            scope.repo_name,
            item.pr_number,
            token=token,
        )
        confirmed_head = confirmed_pull.get("head")
        confirmed_head_sha = (
            confirmed_head.get("sha") if isinstance(confirmed_head, dict) else None
        )
        if (
            confirmed_pull.get("state") != "open"
            or confirmed_head_sha != current_head_sha
        ):
            raise ContinuationCompletionError("continuation_head_changed")

        envelope = dict(revision.evidence) if isinstance(revision.evidence, dict) else {}
        envelope["version"] = 1
        envelope["diagnostic_completion"] = dict(evidence)
        if (
            revision.status == "completed"
            and item.dispatch_status == "escalated"
            and item.attempt_phase == "implementation"
            and item.active_scope_revision == 0
            and revision.result_summary == result_summary
            and revision.evidence == envelope
        ):
            return False
        if (
            revision.status != "active"
            or item.dispatch_status != "dispatched"
            or item.attempt_phase != "diagnostic"
            or item.active_scope_revision != revision.revision
        ):
            raise ContinuationCompletionError("stale_continuation_context")

        now = datetime.utcnow()
        item_result = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status == "dispatched",
                GithubWorkItem.dispatch_nonce == dispatch_nonce,
                GithubWorkItem.owner_slot_id == authenticated_owner_slot_id,
                GithubWorkItem.active_scope_revision == revision.revision,
                GithubWorkItem.attempt_phase == "diagnostic",
                GithubWorkItem.pr_number.is_not(None),
                exists(
                    select(GithubWorkspace.id).where(
                        GithubWorkspace.id == workspace.id,
                        GithubWorkspace.leased_item_id == item.id,
                        GithubWorkspace.lease_token == lease_token,
                    )
                ),
            )
            .values(
                dispatch_status="escalated",
                escalation_reason=revision.originating_escalation_reason,
                status_note=(
                    "Diagnostic restoration verified. Propose the smallest bounded "
                    "implementation continuation supported by the evidence."
                ),
                active_scope_revision=0,
                attempt_phase="implementation",
                continuation_nudged_at=None,
                continuation_activated_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        revision_result = await db.execute(
            update(GithubAttemptScopeRevision)
            .where(
                GithubAttemptScopeRevision.id == revision.id,
                GithubAttemptScopeRevision.status == "active",
                GithubAttemptScopeRevision.phase == "diagnostic",
                GithubAttemptScopeRevision.dispatch_nonce == dispatch_nonce,
                GithubAttemptScopeRevision.owner_slot_id
                == authenticated_owner_slot_id,
                GithubAttemptScopeRevision.owner_member_id
                == authenticated_owner_member_id,
                GithubAttemptScopeRevision.expected_workspace_id == workspace.id,
            )
            .values(
                status="completed",
                result_summary=result_summary,
                evidence=envelope,
                completed_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if item_result.rowcount != 1 or revision_result.rowcount != 1:
            await db.rollback()
            raise ContinuationCompletionError("stale_continuation_context")
        await db.commit()
        await db.refresh(item)
        await github_dispatch_service.notify_owner(
            db,
            item,
            subject="Diagnostic restoration verified",
            body_markdown=(
                f"Diagnostic revision {revision.revision} restored the baseline tree. "
                "Propose the smallest bounded implementation continuation supported "
                "by the recorded evidence."
            ),
            payload={
                "kind": "github_dispatch_diagnostic_completed",
                "work_item_id": item.id,
                "pr_number": item.pr_number,
                "scope_revision": revision.revision,
            },
            delivery_key=f"github-diagnostic:{revision.id}:completed",
        )
        return True

    async def normalize_base_ref(
        self,
        scope: TeamGithubScope,
        client: GithubClient,
        *,
        token: str | None,
        base_ref: str | None = None,
    ) -> str:
        base_ref = scope.base_ref if base_ref is None else base_ref
        if base_ref == "origin/HEAD":
            repository = await client.get_repository(
                scope.repo_owner, scope.repo_name, token=token
            )
            candidate = repository.get("default_branch")
            if not isinstance(candidate, str) or not candidate:
                raise ValueError("GitHub repository has no default branch")
        elif base_ref.startswith("origin/"):
            candidate = base_ref.removeprefix("origin/")
        else:
            candidate = base_ref
        if not candidate or candidate == "HEAD" or candidate.startswith("refs/"):
            raise ValueError(f"Unsupported GitHub base ref: {base_ref}")
        try:
            result = subprocess.run(
                ["git", "check-ref-format", "--branch", candidate],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Unable to validate GitHub base branch") from exc
        if result.returncode != 0:
            raise ValueError(f"Invalid GitHub base branch: {candidate}")
        return candidate

    @staticmethod
    def pull_title(item: GithubWorkItem, owner_slot: AgentTeamSlot) -> str:
        return (
            f"[{owner_slot.display_name}] {item.issue_title} "
            f"(#{item.issue_number})"
        )

    @staticmethod
    def pull_body(item: GithubWorkItem, *, head_ref: str) -> str:
        return (
            f"Closes #{item.issue_number}\n\n"
            f"{item.issue_title}\n\n"
            "---\n"
            "Claude Deck provenance\n"
            f"- Work item: {item.id}\n"
            f"- Owner slot: {item.owner_slot_id}\n"
            f"- Dispatch nonce: {item.dispatch_nonce}\n"
            f"- Head ref: {head_ref}"
        )

    @staticmethod
    def pull_is_draft(item: GithubWorkItem) -> bool:
        return item.issue_type != "design"

    @staticmethod
    def _classify_pull(pull: dict) -> str | None:
        """Classify fields present in both list and single-pull responses."""
        if "merged_at" not in pull:
            return None
        state = pull.get("state")
        merged_at = pull["merged_at"]
        if state == "open" and merged_at is None:
            return "open"
        if state == "closed" and merged_at is not None:
            return "merged"
        if state == "closed" and merged_at is None:
            return "closed_unmerged"
        return None

    @staticmethod
    def _verify_pull_identity(
        pull: dict,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        *,
        expected_base: str,
        verify_author: bool = True,
    ) -> None:
        expected_repo = f"{scope.repo_owner}/{scope.repo_name}"
        base_repo = ((pull.get("base") or {}).get("repo") or {}).get("full_name")
        head = pull.get("head") or {}
        head_repo = (head.get("repo") or {}).get("full_name")
        if base_repo != expected_repo or head_repo != expected_repo:
            raise ValueError(
                f"PR repository does not match {expected_repo}"
            )
        if item.dispatch_head_ref is None or head.get("ref") != item.dispatch_head_ref:
            raise ValueError("PR head does not match the prepared dispatch head")
        if (pull.get("base") or {}).get("ref") != expected_base:
            raise ValueError("PR base does not match the prepared dispatch base")
        if verify_author and scope.github_auth_mode == "app":
            if not settings.github_app_bot_login:
                raise ValueError("app_mode_bot_login_unset")
            if (pull.get("user") or {}).get("login") != settings.github_app_bot_login:
                raise ValueError("PR author does not match the configured GitHub App bot")

    async def report_pr_opened(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        pr_number: int,
        client: GithubClient,
    ) -> None:
        recoverable = (
            item.dispatch_status == "escalated"
            and item.escalation_reason in _PR_OPENED_RECOVERABLE_ESCALATIONS
        )
        if item.dispatch_status != "dispatched" and not recoverable:
            raise ValueError(
                f"pr_opened is only valid for dispatched work items, or escalated "
                f"items with a recoverable reason; current status is "
                f"{item.dispatch_status} ({item.escalation_reason})"
            )
        if item.dispatch_base_ref is None:
            raise ValueError("prepared dispatch base is missing")
        expected_base = await self.normalize_base_ref(
            scope,
            client,
            token=None,
            base_ref=item.dispatch_base_ref,
        )
        pull = await client.get_pull(scope.repo_owner, scope.repo_name, pr_number)
        self._verify_pull_identity(
            pull,
            scope,
            item,
            expected_base=expected_base,
        )
        verdict = self._classify_pull(pull)
        if verdict is None:
            raise ValueError("GitHub returned a pull request state Deck cannot classify")
        if verdict == "closed_unmerged":
            await github_dispatch_service.escalate_without_notification(
                db,
                item,
                "pr_closed_unmerged",
                f"PR #{pr_number} was closed without being merged.",
            )
            return
        if recoverable:
            item.escalation_reason = None
            item.retry_requested_at = None
        await self._record_selected_pull(db, scope, item, pull, verdict)

    async def report_pr_ready(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        head_ref: str,
        lease_token: str,
        client: GithubClient,
    ) -> int:
        lock = self._pr_ready_locks.setdefault(item.id, asyncio.Lock())
        async with lock:
            item = (
                await db.execute(
                    select(GithubWorkItem)
                    .where(GithubWorkItem.id == item.id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            workspace = (
                await db.execute(
                    select(GithubWorkspace).where(
                        GithubWorkspace.scope_id == scope.id,
                        GithubWorkspace.leased_item_id == item.id,
                        GithubWorkspace.lease_token == lease_token,
                    )
                )
            ).scalar_one_or_none()
            if workspace is None:
                raise ValueError("workspace_lease_changed")
            if item.dispatch_head_ref is None:
                raise ValueError("prepared dispatch head is missing")
            if item.dispatch_base_ref is None:
                raise ValueError("prepared dispatch base is missing")
            if head_ref != item.dispatch_head_ref:
                raise ValueError("reported head does not match the prepared dispatch head")
            if item.pr_number is not None:
                return int(item.pr_number)
            if item.dispatch_status != "dispatched":
                raise ValueError(
                    f"pr_ready is only valid for dispatched work items; current status is "
                    f"{item.dispatch_status}"
                )
            if scope.github_auth_mode != "app":
                raise ValueError("pr_ready requires GitHub App authentication")
            if scope.github_app_installation_id is None:
                raise ValueError("app_installation_id_missing")
            if not settings.github_app_bot_login:
                raise ValueError("app_mode_bot_login_unset")

            github_app_auth_service.require_configuration(require_bot_login=True)
            token = await github_app_auth_service.mint_repository_token(
                scope.github_app_installation_id,
                scope.repo_owner,
                scope.repo_name,
                purpose="pull_request",
                cache_subject="backend",
            )

            remote_ref = await client.get_ref(
                scope.repo_owner,
                scope.repo_name,
                head_ref,
                token=token,
            )
            if remote_ref is None:
                raise ValueError("remote_head_not_found")
            if remote_ref.get("ref") != f"refs/heads/{head_ref}":
                raise ValueError("remote_head_mismatch")

            base = await self.normalize_base_ref(
                scope,
                client,
                token=token,
                base_ref=item.dispatch_base_ref,
            )
            pulls = await self._list_attempt_pulls(
                scope,
                client,
                head_ref=head_ref,
                base=base,
                token=token,
            )
            selected = await self._reconcile_attempt_pulls(
                db,
                scope,
                item,
                pulls,
                expected_base=base,
                verify_author=True,
            )
            if selected is not None:
                return selected

            owner_slot = await db.get(AgentTeamSlot, item.owner_slot_id)
            if owner_slot is None:
                raise ValueError("owner_slot_missing")
            try:
                created = await client.create_pull(
                    scope.repo_owner,
                    scope.repo_name,
                    title=self.pull_title(item, owner_slot),
                    head=head_ref,
                    base=base,
                    body=self.pull_body(item, head_ref=head_ref),
                    draft=self.pull_is_draft(item),
                    token=token,
                )
            except httpx.TimeoutException:
                created = None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 422:
                    raise
                created = None

            if created is None:
                pulls = await self._list_attempt_pulls(
                    scope,
                    client,
                    head_ref=head_ref,
                    base=base,
                    token=token,
                )
                selected = await self._reconcile_attempt_pulls(
                    db,
                    scope,
                    item,
                    pulls,
                    expected_base=base,
                    verify_author=True,
                )
                if selected is None:
                    raise ValueError("pull_creation_outcome_unresolved")
                return selected

            selected = await self._reconcile_attempt_pulls(
                db,
                scope,
                item,
                [created],
                expected_base=base,
                verify_author=False,
            )
            if selected is None:
                raise ValueError("pull_creation_returned_no_pull")
            return selected

    async def _list_attempt_pulls(
        self,
        scope: TeamGithubScope,
        client: GithubClient,
        *,
        head_ref: str,
        base: str,
        token: str,
    ) -> list[dict]:
        return await client.list_pulls_for_head(
            scope.repo_owner,
            scope.repo_name,
            head=f"{scope.repo_owner}:{head_ref}",
            base=base,
            state="all",
            token=token,
        )

    @staticmethod
    def _pull_number(pull: dict) -> int:
        number = pull.get("number")
        if not isinstance(number, int) or number <= 0:
            raise ValueError("GitHub returned a pull request without a valid number")
        return number

    async def _reconcile_attempt_pulls(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        pulls: list[dict],
        *,
        expected_base: str,
        verify_author: bool,
    ) -> int | None:
        unique_pulls: dict[int, dict] = {}
        for pull in pulls:
            number = self._pull_number(pull)
            previous = unique_pulls.get(number)
            if previous is not None and previous != pull:
                raise ValueError(
                    f"GitHub returned conflicting representations for PR #{number}"
                )
            unique_pulls[number] = pull

        classified: list[tuple[dict, str]] = []
        invalid: list[str] = []
        for pull in unique_pulls.values():
            verdict = self._classify_pull(pull)
            if verdict is None:
                invalid.append(str(pull["number"]))
            else:
                classified.append((pull, verdict))
        if invalid:
            raise ValueError(
                "GitHub returned unclassifiable pull request(s): " + ", ".join(invalid)
            )

        for verdict in ("open", "merged", "closed_unmerged"):
            selected = [pull for pull, state in classified if state == verdict]
            if not selected:
                continue
            for pull in selected:
                self._verify_pull_identity(
                    pull,
                    scope,
                    item,
                    expected_base=expected_base,
                    verify_author=verify_author,
                )
                self._pull_number(pull)

            numbers = sorted(self._pull_number(pull) for pull in selected)
            if verdict == "open":
                if len(selected) > 1:
                    item.status_note = (
                        "Multiple open pull requests match this dispatch head: "
                        + ", ".join(f"#{number}" for number in numbers)
                    )
                    item.updated_at = datetime.utcnow()
                    await db.commit()
                    raise ValueError(item.status_note)
                await self._record_selected_pull(
                    db,
                    scope,
                    item,
                    selected[0],
                    "open",
                )
                return numbers[0]
            if verdict == "merged":
                chosen = max(selected, key=self._pull_number)
                item.pr_number = self._pull_number(chosen)
                self._mark_merged(item)
                item.status_note = (
                    "Merged pull requests found for this dispatch head: "
                    + ", ".join(f"#{number}" for number in numbers)
                )
                await db.commit()
                await self._notify_blocker_merged(db, scope, item)
                return int(item.pr_number)

            await github_dispatch_service.escalate_without_notification(
                db,
                item,
                "pr_closed_unmerged",
                "Pull requests closed without merge for this dispatch head: "
                + ", ".join(f"#{number}" for number in numbers),
            )
            raise ValueError(item.status_note or "pr_closed_unmerged")
        return None

    async def _record_selected_pull(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        pull: dict,
        verdict: str,
    ) -> None:
        pr_number = self._pull_number(pull)
        item.pr_number = pr_number
        item.last_verified_sha = None
        if verdict == "merged":
            self._mark_merged(item)
            await db.commit()
            await self._notify_blocker_merged(db, scope, item)
            return
        if item.issue_type == "design":
            item.dispatch_status = "awaiting_human_review"
            item.status_note = f"Design PR #{pr_number} is ready for human review."
            await github_dispatch_service.notify_team(
                db,
                subject="Design PR ready for review",
                body_markdown=(
                    f"Design PR #{pr_number} is ready for human review for "
                    f"issue #{item.issue_number}: {item.issue_title}"
                ),
                payload={
                    "kind": "github_dispatch_design_pr_ready",
                    "work_item_id": item.id,
                    "pr_number": pr_number,
                },
            )
        else:
            item.dispatch_status = "verifying"
            item.status_note = None
        item.updated_at = datetime.utcnow()
        await db.commit()

    async def process_scope(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        client: GithubClient | None = None,
    ) -> None:
        client = client or github_client
        items = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.pr_number.is_not(None),
                    GithubWorkItem.dispatch_status.in_(
                        (
                            "dispatched",
                            "verifying",
                            "ready_for_review",
                            "awaiting_human_review",
                        )
                    ),
                )
            )
        ).scalars().all()

        for item in items:
            try:
                if item.dispatch_status in ("dispatched", "verifying"):
                    revision = await self._active_scope_revision(db, item)
                    if item.active_scope_revision > 0:
                        if revision is None:
                            logger.warning(
                                "Skipping continuation verification for work item %s: "
                                "active continuation revision is inconsistent",
                                item.id,
                            )
                            continue
                        if revision.phase == "diagnostic":
                            if item.dispatch_status != "dispatched":
                                revision.status = "exhausted"
                                await github_dispatch_service.escalate(
                                    db,
                                    item,
                                    "continuation_invalid_state",
                                    "An active diagnostic continuation entered a review state.",
                                )
                                await db.commit()
                                continue
                            await self._observe_diagnostic_checks(
                                db,
                                scope,
                                item,
                                revision,
                                client,
                            )
                            continue
                        if item.dispatch_status == "dispatched":
                            continue
                    await self._verify_item(
                        db,
                        scope,
                        item,
                        client,
                        revision=revision,
                    )
                else:
                    await self._process_review_item(db, scope, item, client)
            except httpx.HTTPError as exc:
                logger.exception(
                    "GitHub verification failed for work item %s", item.id
                )
                self._set_failure_note(
                    item, f"GitHub verification failed; will retry: {exc}"
                )
                item.updated_at = datetime.utcnow()
                await db.commit()

    async def _active_scope_revision(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
    ) -> GithubAttemptScopeRevision | None:
        if item.active_scope_revision == 0:
            return None
        revision = (
            await db.execute(
                select(GithubAttemptScopeRevision)
                .where(
                    GithubAttemptScopeRevision.work_item_id == item.id,
                    GithubAttemptScopeRevision.dispatch_nonce == item.dispatch_nonce,
                    GithubAttemptScopeRevision.revision
                    == item.active_scope_revision,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            revision is None
            or item.attempt_phase != revision.phase
            or revision.phase not in {"implementation", "diagnostic"}
            or revision.status not in {"active", "submitted"}
        ):
            return None
        return revision

    @staticmethod
    def _diagnostic_check_evidence(checks: list[dict]) -> list[dict]:
        fields = ("id", "name", "status", "conclusion", "html_url", "details_url")
        return [
            {field: check.get(field) for field in fields if check.get(field) is not None}
            for check in checks
        ]

    @staticmethod
    def _diagnostic_status_evidence(status: dict) -> list[dict]:
        fields = ("context", "state", "target_url", "description")
        return [
            {field: context.get(field) for field in fields if context.get(field) is not None}
            for context in status.get("statuses") or []
            if isinstance(context, dict)
        ]

    async def _claim_current_diagnostic_context(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        revision: GithubAttemptScopeRevision,
    ) -> bool:
        current_revision = exists(
            select(GithubAttemptScopeRevision.id).where(
                GithubAttemptScopeRevision.id == revision.id,
                GithubAttemptScopeRevision.work_item_id == item.id,
                GithubAttemptScopeRevision.dispatch_nonce == revision.dispatch_nonce,
                GithubAttemptScopeRevision.revision == revision.revision,
                GithubAttemptScopeRevision.owner_slot_id == revision.owner_slot_id,
                GithubAttemptScopeRevision.phase == "diagnostic",
                GithubAttemptScopeRevision.status == "active",
            )
        )
        claim = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status == "dispatched",
                GithubWorkItem.dispatch_nonce == revision.dispatch_nonce,
                GithubWorkItem.owner_slot_id == revision.owner_slot_id,
                GithubWorkItem.active_scope_revision == revision.revision,
                GithubWorkItem.attempt_phase == "diagnostic",
                current_revision,
            )
            .values(updated_at=GithubWorkItem.updated_at)
            .execution_options(synchronize_session=False)
        )
        if claim.rowcount == 1:
            return True
        await db.rollback()
        return False

    async def _observe_diagnostic_checks(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        revision: GithubAttemptScopeRevision,
        client: GithubClient,
    ) -> None:
        pull = await client.get_pull(
            scope.repo_owner,
            scope.repo_name,
            int(item.pr_number),
        )
        try:
            if item.dispatch_base_ref is None:
                raise ValueError("prepared dispatch base is missing")
            expected_base = await self.normalize_base_ref(
                scope,
                client,
                token=None,
                base_ref=item.dispatch_base_ref,
            )
            self._verify_pull_identity(
                pull,
                scope,
                item,
                expected_base=expected_base,
            )
        except ValueError as exc:
            if not await self._claim_current_diagnostic_context(db, item, revision):
                return
            revision.status = "exhausted"
            await github_dispatch_service.escalate(
                db,
                item,
                "continuation_pr_identity_invalid",
                f"Diagnostic PR identity verification failed: {exc}",
            )
            await db.commit()
            return

        verdict = self._classify_pull(pull)
        if verdict == "merged":
            if not await self._claim_current_diagnostic_context(db, item, revision):
                return
            revision.status = "completed"
            revision.completed_at = datetime.utcnow()
            self._mark_merged(item)
            await db.commit()
            await self._notify_blocker_merged(db, scope, item)
            return
        if verdict != "open":
            if not await self._claim_current_diagnostic_context(db, item, revision):
                return
            revision.status = "superseded"
            await github_dispatch_service.escalate_without_notification(
                db,
                item,
                "pr_closed_unmerged",
                f"PR #{item.pr_number} was closed without being merged.",
            )
            return

        head_sha = self._head_sha(pull)
        if not head_sha:
            if not await self._claim_current_diagnostic_context(db, item, revision):
                return
            revision.status = "exhausted"
            await github_dispatch_service.escalate(
                db,
                item,
                "continuation_pr_identity_invalid",
                "Diagnostic PR head is missing.",
            )
            await db.commit()
            return
        checks = await client.list_check_runs_for_ref(
            scope.repo_owner,
            scope.repo_name,
            head_sha,
        )
        signal = "check_runs"
        evidence_rows = self._diagnostic_check_evidence(checks)
        if checks:
            pending = [
                check
                for check in checks
                if check.get("status") != "completed"
                or check.get("conclusion") is None
            ]
            failed = [
                check
                for check in checks
                if check not in pending
                and check.get("conclusion") not in _SUCCESS_CONCLUSIONS
            ]
            state = "red" if failed else "pending" if pending else "green"
        else:
            combined = await client.get_combined_status_for_ref(
                scope.repo_owner,
                scope.repo_name,
                head_sha,
            )
            signal = "combined_status"
            evidence_rows = self._diagnostic_status_evidence(combined)
            combined_state = combined.get("state")
            if combined_state in _STATUS_FAILURE_STATES:
                state = "red"
            elif combined_state in _STATUS_SUCCESS_STATES and evidence_rows:
                state = "green"
            else:
                state = "pending"

        if not await self._claim_current_diagnostic_context(db, item, revision):
            return

        envelope = dict(revision.evidence) if isinstance(revision.evidence, dict) else {}
        observations = dict(envelope.get("diagnostic_observations") or {})
        observation = {
            "head_sha": head_sha,
            "signal": signal,
            "state": state,
            "checks": evidence_rows,
        }
        if observations.get(head_sha) != observation:
            observations[head_sha] = observation
            envelope["version"] = 1
            envelope["diagnostic_observations"] = observations
            revision.evidence = envelope

        if state == "pending":
            item.status_note = "Diagnostic checks are still running."
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        if state == "green":
            item.status_note = (
                "Diagnostic checks are green; restore the baseline tree before completion."
            )
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        await db.flush()
        await self._record_diagnostic_failure(
            db,
            scope,
            item,
            revision,
            head_sha,
        )

    async def _record_diagnostic_failure(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        revision: GithubAttemptScopeRevision,
        head_sha: str,
    ) -> None:
        await db.refresh(item)
        await db.refresh(revision)
        if (
            item.dispatch_status != "dispatched"
            or item.active_scope_revision != revision.revision
            or item.dispatch_nonce != revision.dispatch_nonce
            or item.attempt_phase != "diagnostic"
            or revision.phase != "diagnostic"
            or revision.status != "active"
        ):
            raise ContinuationCompletionError("stale_continuation_context")
        if item.diagnostic_last_verified_sha != head_sha:
            total_failed_heads = int(
                (
                    await db.execute(
                        select(
                            func.coalesce(
                                func.sum(GithubAttemptScopeRevision.failed_head_count),
                                0,
                            )
                        ).where(
                            GithubAttemptScopeRevision.work_item_id == item.id,
                            GithubAttemptScopeRevision.dispatch_nonce
                            == item.dispatch_nonce,
                        )
                    )
                ).scalar_one()
            )
            revision.failed_head_count += 1
            revision.last_failed_head_sha = head_sha
            item.diagnostic_retry_count += 1
            item.diagnostic_last_verified_sha = head_sha
            item.status_note = "Diagnostic checks produced failure evidence."
            item.updated_at = datetime.utcnow()
            exhausted = (
                revision.failed_head_count >= revision.max_failed_heads
                or total_failed_heads + 1 >= scope.max_continuation_failed_heads
            )
            if exhausted:
                revision.status = "exhausted"
                await github_dispatch_service.escalate(
                    db,
                    item,
                    "continuation_budget_exhausted",
                    "Diagnostic failed-head budget was exhausted.",
                )
            await db.commit()
        await github_dispatch_service.notify_owner(
            db,
            item,
            subject="Diagnostic checks produced evidence",
            body_markdown=(
                f"Diagnostic checks failed for issue #{item.issue_number} / "
                f"PR #{item.pr_number} at head {head_sha}."
            ),
            payload={
                "kind": "github_dispatch_diagnostic_check_failed",
                "work_item_id": item.id,
                "pr_number": item.pr_number,
                "head_sha": head_sha,
                "scope_revision": revision.revision,
                "diagnostic_retry_count": item.diagnostic_retry_count,
                "revision_failed_head_count": revision.failed_head_count,
            },
            delivery_key=(
                f"github-diagnostic:{revision.id}:check-failure:{head_sha}"
            ),
        )

    async def _preset_slots(
        self, db: AsyncSession, scope: TeamGithubScope
    ) -> list[AgentTeamSlot]:
        return (
            await db.execute(
                select(AgentTeamSlot)
                .where(AgentTeamSlot.preset_id == scope.preset_id)
                .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
            )
        ).scalars().all()

    async def _notify_blocker_merged(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
    ) -> None:
        try:
            slots = await self._preset_slots(db, scope)
            await github_dispatch_service.notify_blocker_merged(
                db, scope, item, slots
            )
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to send blocker-merged notification for work item %s",
                item.id,
            )
            await db.rollback()

    async def _verify_item(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
        *,
        revision: GithubAttemptScopeRevision | None = None,
    ) -> None:
        pull = await client.get_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
        if not await self._validate_polled_pull_identity(
            db,
            scope,
            item,
            client,
            pull,
            retry_status="dispatched",
            revision=revision,
        ):
            return
        verdict = self._classify_pull(pull)
        if verdict is None:
            note = f"PR #{item.pr_number} returned a state Deck cannot classify."
            await self._record_product_verification_failure(
                db,
                scope,
                item,
                self._head_sha(pull) if revision is not None else None,
                note,
                subject="GitHub verification could not classify the PR",
                body_markdown=note,
                payload={
                    "kind": "github_dispatch_pr_unclassifiable",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                    "pull_state": pull.get("state"),
                },
                retry_status="dispatched",
                revision=revision,
            )
            return
        if verdict == "merged":
            if revision is not None:
                revision.status = "completed"
                revision.completed_at = datetime.utcnow()
            self._mark_merged(item)
            await db.commit()
            await self._notify_blocker_merged(db, scope, item)
            return
        if verdict == "closed_unmerged":
            if revision is not None:
                revision.status = "superseded"
            await github_dispatch_service.escalate_without_notification(
                db,
                item,
                "pr_closed_unmerged",
                f"PR #{item.pr_number} was closed without being merged.",
            )
            return

        if revision is not None and not await self._submitted_head_is_current(
            db,
            item,
            revision,
            self._head_sha(pull),
        ):
            return

        head_sha = self._head_sha(pull)
        checks = await client.list_check_runs_for_ref(
            scope.repo_owner,
            scope.repo_name,
            head_sha or "",
        )
        if not checks:
            if await self._process_combined_status(
                db,
                scope,
                item,
                client,
                pull,
                revision=revision,
            ):
                return
            await self._handle_no_check_signal(
                db,
                scope,
                item,
                head_sha,
                revision=revision,
            )
            return

        pending = [
            check
            for check in checks
            if check.get("status") != "completed" or check.get("conclusion") is None
        ]
        failed = [
            check
            for check in checks
            if check not in pending and check.get("conclusion") not in _SUCCESS_CONCLUSIONS
        ]
        if failed:
            await self._record_product_verification_failure(
                db,
                scope,
                item,
                head_sha,
                self._failed_check_note(failed),
                subject="GitHub checks failed",
                body_markdown=(
                    f"GitHub checks failed for issue #{item.issue_number} / "
                    f"PR #{item.pr_number}.\n\n{self._failed_check_note(failed)}"
                ),
                payload={
                    "kind": "github_dispatch_check_failed",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                },
                retry_status="dispatched",
                revision=revision,
            )
            return
        if pending:
            item.status_note = "GitHub checks are still running."
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        if all(check.get("conclusion") in _SUCCESS_CONCLUSIONS for check in checks):
            await self._promote_verified_item(
                db,
                scope,
                item,
                client,
                pull,
                head_sha,
                revision=revision,
            )

    async def _process_review_item(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
        pull: dict | None = None,
    ) -> None:
        pull = pull or await client.get_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
        if not await self._validate_polled_pull_identity(
            db,
            scope,
            item,
            client,
            pull,
            retry_status=item.dispatch_status,
        ):
            return
        verdict = self._classify_pull(pull)
        if verdict is None:
            note = f"PR #{item.pr_number} returned a state Deck cannot classify."
            await self._record_failed_verification_attempt(
                db,
                scope,
                item,
                None,
                note,
                subject="GitHub review could not classify the PR",
                body_markdown=note,
                payload={
                    "kind": "github_dispatch_pr_unclassifiable",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                    "pull_state": pull.get("state"),
                },
                retry_status=item.dispatch_status,
            )
            return
        if verdict == "merged":
            self._mark_merged(item)
            await db.commit()
            await self._notify_blocker_merged(db, scope, item)
            return
        if verdict == "closed_unmerged":
            await github_dispatch_service.escalate_without_notification(
                db,
                item,
                "pr_closed_unmerged",
                f"PR #{item.pr_number} was closed without being merged.",
            )
            return
        if item.issue_type == "design" or scope.merge_policy != "auto":
            return
        if item.status_note and item.status_note.startswith(_HUMAN_MERGE_NOTE_PREFIXES):
            return
        approval_reason = await self._approval_gate_reason(db, scope, item)
        if approval_reason is not None:
            await self._fallback_to_human_merge(
                db,
                item,
                "Auto-merge blocked: distinct current-round leader approval is "
                f"required ({approval_reason}).",
            )
            return
        if await self._auto_merge_budget_exhausted(db, scope):
            await self._fallback_to_human_merge(
                db,
                item,
                "Auto-merge budget exhausted; PR is ready for human merge.",
            )
            return
        merge_state = pull.get("mergeable_state")
        if merge_state in _TRANSIENT_MERGE_STATES:
            await self._record_transient_merge_failure(
                db,
                scope,
                item,
                f"mergeable_state={merge_state}",
            )
            return
        current_head = self._head_sha(pull)
        if current_head != item.last_verified_sha or not await self._head_is_green(
            scope, client, current_head
        ):
            item.dispatch_status = "verifying"
            item.status_note = (
                "Head changed or is no longer green since promotion; re-verifying "
                "before auto-merge."
            )
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        try:
            await client.merge_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in _MERGE_TRANSIENT_STATUS_CODES or status_code >= 500:
                await self._record_transient_merge_failure(db, scope, item, str(exc))
            elif status_code == 403:
                await self._fallback_to_human_merge(
                    db,
                    item,
                    "Auto-merge blocked by repository policy; requires human merge.",
                )
            else:
                await self._fallback_to_human_merge(
                    db,
                    item,
                    f"Auto-merge failed with GitHub status {status_code}; requires human merge.",
                )
            return

        self._mark_merged(item)
        item.auto_merged_at = datetime.utcnow()
        await db.commit()
        await self._notify_blocker_merged(db, scope, item)

    async def _validate_polled_pull_identity(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
        pull: dict,
        *,
        retry_status: str,
        revision: GithubAttemptScopeRevision | None = None,
    ) -> bool:
        try:
            if item.dispatch_base_ref is None:
                raise ValueError("prepared dispatch base is missing")
            expected_base = await self.normalize_base_ref(
                scope,
                client,
                token=None,
                base_ref=item.dispatch_base_ref,
            )
            self._verify_pull_identity(
                pull,
                scope,
                item,
                expected_base=expected_base,
            )
        except ValueError as exc:
            note = f"PR #{item.pr_number} identity verification failed: {exc}"
            await self._record_product_verification_failure(
                db,
                scope,
                item,
                self._head_sha(pull) if revision is not None else None,
                note,
                subject="GitHub pull request identity verification failed",
                body_markdown=note,
                payload={
                    "kind": "github_dispatch_pr_identity_invalid",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                },
                retry_status=retry_status,
                revision=revision,
            )
            return False
        return True

    async def _approval_gate_reason(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
    ) -> str | None:
        if not settings.mail_capability_tokens_required:
            return "capability token enforcement is disabled"
        if item.ack_enforcement_epoch != 1:
            return "approval was not recorded under enforced identity"
        if item.ack_approval_round != item.approval_round_count:
            return "approval is missing or belongs to a stale round"
        leader_slot = (
            await db.execute(
                select(AgentTeamSlot)
                .where(
                    AgentTeamSlot.preset_id == scope.preset_id,
                    AgentTeamSlot.enabled.is_(True),
                )
                .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if leader_slot is None:
            return "no enabled leader slot exists"
        leader_member = await github_dispatch_service._slot_member(db, leader_slot.id)
        if leader_member is None or item.ack_approver_member_id != leader_member.id:
            return "approver is not the current designated leader"
        owner_member = await github_dispatch_service._owner_member(db, item)
        if owner_member is None:
            return "current owner is not registered"
        if owner_member.id == item.ack_approver_member_id:
            return "owner and approver are not distinct"
        return None

    async def _record_transient_merge_failure(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        note: str,
    ) -> None:
        item.retry_count += 1
        if item.retry_count > scope.max_verification_retries:
            await self._fallback_to_human_merge(
                db,
                item,
                f"Auto-merge retry budget exhausted after transient merge failure: {note}",
            )
        else:
            self._set_failure_note(
                item, f"Transient merge failure; will retry: {note}"
            )
            item.updated_at = datetime.utcnow()
        await db.commit()

    async def _process_combined_status(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
        pull: dict,
        *,
        revision: GithubAttemptScopeRevision | None = None,
    ) -> bool:
        head_sha = self._head_sha(pull)
        status = await client.get_combined_status_for_ref(
            scope.repo_owner,
            scope.repo_name,
            head_sha or "",
        )
        contexts = status.get("statuses") or []
        if not contexts:
            return False
        state = status.get("state")
        if state in _STATUS_SUCCESS_STATES:
            await self._promote_verified_item(
                db,
                scope,
                item,
                client,
                pull,
                head_sha,
                revision=revision,
            )
            return True
        if state in _STATUS_FAILURE_STATES:
            note = f"GitHub commit status failed: {state}"
            await self._record_product_verification_failure(
                db,
                scope,
                item,
                head_sha,
                note,
                subject="GitHub commit status failed",
                body_markdown=(
                    f"GitHub commit status failed for issue #{item.issue_number} / "
                    f"PR #{item.pr_number}.\n\n{note}"
                ),
                payload={
                    "kind": "github_dispatch_status_failed",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                },
                retry_status="dispatched",
                revision=revision,
            )
            return True
        item.status_note = "GitHub commit statuses are still pending."
        item.updated_at = datetime.utcnow()
        await db.commit()
        return True

    async def _handle_no_check_signal(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        head_sha: str | None,
        *,
        revision: GithubAttemptScopeRevision | None = None,
    ) -> None:
        grace_started_at = (
            revision.submitted_at
            if revision is not None and revision.submitted_at is not None
            else item.updated_at or item.created_at
        )
        grace_age = datetime.utcnow() - grace_started_at
        if grace_age < timedelta(seconds=settings.github_check_signal_grace_seconds):
            item.status_note = "Waiting for GitHub check-runs or commit statuses to appear."
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        if revision is not None:
            await self._record_product_verification_failure(
                db,
                scope,
                item,
                head_sha,
                "No GitHub check-runs or commit statuses found for PR.",
                subject="GitHub verification found no check signal",
                body_markdown=(
                    f"No GitHub check-runs or commit statuses appeared for issue "
                    f"#{item.issue_number} / PR #{item.pr_number}."
                ),
                payload={
                    "kind": "github_dispatch_no_check_signal",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                },
                retry_status="dispatched",
                revision=revision,
            )
            return
        await github_dispatch_service.escalate(
            db,
            item,
            "retry_count_exhausted",
            "No GitHub check-runs or commit statuses found for PR.",
        )
        await db.commit()

    async def _promote_verified_item(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
        pull: dict,
        head_sha: str | None,
        *,
        revision: GithubAttemptScopeRevision | None = None,
    ) -> None:
        was_draft = bool(pull.get("draft") and pull.get("node_id"))
        if was_draft:
            await client.mark_pull_ready_for_review(str(pull["node_id"]))
        if was_draft or revision is not None:
            pull = await client.get_pull(
                scope.repo_owner,
                scope.repo_name,
                int(item.pr_number),
            )
        if revision is not None:
            if not await self._submitted_head_is_current(
                db,
                item,
                revision,
                self._head_sha(pull),
            ):
                return
            revision.status = "completed"
            revision.completed_at = datetime.utcnow()
        item.last_verified_sha = head_sha
        item.dispatch_status = "ready_for_review"
        item.status_note = f"PR #{item.pr_number} is ready for review."
        item.updated_at = datetime.utcnow()
        if scope.merge_policy == "human":
            await self._notify_code_pr_ready_for_review(db, item)
        await db.commit()
        await self._process_review_item(db, scope, item, client, pull=pull)

    async def _submitted_head_is_current(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        revision: GithubAttemptScopeRevision,
        current_head_sha: str | None,
    ) -> bool:
        if (
            revision.status == "submitted"
            and revision.submitted_head_sha is not None
            and hmac.compare_digest(revision.submitted_head_sha, current_head_sha or "")
        ):
            return True

        now = datetime.utcnow()
        revision.status = "active"
        revision.submitted_head_sha = None
        revision.submitted_at = None
        item.dispatch_status = "dispatched"
        item.continuation_activated_at = now
        item.continuation_nudged_at = None
        item.status_note = (
            "The PR head changed after continuation completion; submit the current "
            "head again so Deck can revalidate the approved paths."
        )
        item.updated_at = now
        await github_dispatch_service.notify_owner(
            db,
            item,
            subject="Continuation head changed before verification",
            body_markdown=(
                f"PR #{item.pr_number} changed after scope revision "
                f"{revision.revision} was submitted. Re-run the approved checks and "
                "report continuation_completed for the current head; Deck will "
                "revalidate the exact approved paths before verification resumes."
            ),
            payload={
                "kind": "github_continuation_head_changed",
                "work_item_id": item.id,
                "pr_number": item.pr_number,
                "scope_revision": revision.revision,
                "current_head_sha": current_head_sha,
            },
        )
        await db.commit()
        return False

    async def _auto_merge_budget_exhausted(
        self, db: AsyncSession, scope: TeamGithubScope
    ) -> bool:
        since = datetime.utcnow() - timedelta(days=1)
        count = (
            await db.execute(
                select(GithubWorkItem.id).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.auto_merged_at.is_not(None),
                    GithubWorkItem.auto_merged_at >= since,
                )
            )
        ).all()
        return len(count) >= scope.max_auto_merges_per_day

    def _mark_merged(self, item: GithubWorkItem) -> None:
        item.dispatch_status = "merged"
        item.escalation_reason = None
        item.status_note = None
        item.updated_at = datetime.utcnow()

    async def _fallback_to_human_merge(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        note: str,
    ) -> None:
        item.dispatch_status = "ready_for_review"
        item.escalation_reason = None
        item.status_note = note
        item.updated_at = datetime.utcnow()
        await self._notify_code_pr_ready_for_review(db, item, fallback_note=note)
        await db.commit()

    async def _notify_code_pr_ready_for_review(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        fallback_note: str | None = None,
    ) -> None:
        body = (
            f"Code PR #{item.pr_number} is ready for human review for "
            f"issue #{item.issue_number}: {item.issue_title}"
        )
        payload = {
            "kind": "github_dispatch_code_pr_ready",
            "work_item_id": item.id,
            "pr_number": item.pr_number,
        }
        if fallback_note:
            body = f"{body}\n\nAuto-merge fell back to human merge: {fallback_note}"
            payload["auto_merge_fallback"] = True
            payload["fallback_note"] = fallback_note
        await github_dispatch_service.notify_team(
            db,
            subject="Code PR ready for review",
            body_markdown=body,
            payload=payload,
        )

    def _failed_check_note(self, checks: list[dict]) -> str:
        names = ", ".join(str(check.get("name") or check.get("id")) for check in checks)
        return f"GitHub check failed: {names}"

    @staticmethod
    def _set_failure_note(item: GithubWorkItem, note: str) -> str:
        if item.status_note and item.status_note.startswith(_HUMAN_MERGE_NOTE_PREFIXES):
            return item.status_note
        item.status_note = note
        return note

    async def _record_product_verification_failure(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        head_sha: str | None,
        note: str,
        *,
        subject: str,
        body_markdown: str,
        payload: dict,
        retry_status: str,
        revision: GithubAttemptScopeRevision | None,
    ) -> None:
        if revision is None:
            await self._record_failed_verification_attempt(
                db,
                scope,
                item,
                head_sha,
                note,
                subject=subject,
                body_markdown=body_markdown,
                payload=payload,
                retry_status=retry_status,
            )
            return

        await db.refresh(item)
        await db.refresh(revision)
        if (
            item.active_scope_revision != revision.revision
            or item.dispatch_nonce != revision.dispatch_nonce
            or item.attempt_phase != "implementation"
            or revision.phase != "implementation"
            or revision.status not in {"active", "submitted"}
        ):
            raise ContinuationCompletionError("stale_continuation_context")

        same_head = (
            revision.failed_head_count > 0
            and revision.last_failed_head_sha == head_sha
        )
        total_failed_heads = int(
            (
                await db.execute(
                    select(
                        func.coalesce(
                            func.sum(GithubAttemptScopeRevision.failed_head_count),
                            0,
                        )
                    ).where(
                        GithubAttemptScopeRevision.work_item_id == item.id,
                        GithubAttemptScopeRevision.dispatch_nonce
                        == item.dispatch_nonce,
                    )
                )
            ).scalar_one()
        )
        if same_head:
            exhausted = (
                revision.failed_head_count >= revision.max_failed_heads
                or total_failed_heads >= scope.max_continuation_failed_heads
            )
            if exhausted:
                revision.status = "exhausted"
                await github_dispatch_service.escalate(
                    db,
                    item,
                    "continuation_budget_exhausted",
                    note,
                )
                await db.commit()
            elif item.dispatch_status != retry_status or revision.status != "active":
                now = datetime.utcnow()
                item.dispatch_status = retry_status
                item.continuation_activated_at = now
                item.continuation_nudged_at = None
                item.updated_at = now
                revision.status = "active"
                revision.submitted_head_sha = None
                revision.submitted_at = None
                self._set_failure_note(item, note)
                await db.commit()
            await github_dispatch_service.notify_owner(
                db,
                item,
                subject=subject,
                body_markdown=body_markdown,
                payload={
                    **payload,
                    "retry_count": item.retry_count,
                    "head_sha": head_sha,
                    "scope_revision": revision.revision,
                    "revision_failed_head_count": revision.failed_head_count,
                },
                delivery_key=(
                    f"github-continuation:{revision.id}:verification-failure:"
                    f"{head_sha or 'no-head'}"
                ),
            )
            return
        revision.failed_head_count += 1
        revision.last_failed_head_sha = head_sha
        item.retry_count += 1
        item.last_verified_sha = head_sha
        self._set_failure_note(item, note)
        exhausted = (
            revision.failed_head_count >= revision.max_failed_heads
            or total_failed_heads + 1 >= scope.max_continuation_failed_heads
        )
        if exhausted:
            revision.status = "exhausted"
            await github_dispatch_service.escalate(
                db,
                item,
                "continuation_budget_exhausted",
                note,
            )
        else:
            now = datetime.utcnow()
            revision.status = "active"
            revision.submitted_head_sha = None
            revision.submitted_at = None
            item.dispatch_status = retry_status
            item.continuation_activated_at = now
            item.continuation_nudged_at = None
            item.updated_at = now
        await db.commit()
        await github_dispatch_service.notify_owner(
            db,
            item,
            subject=subject,
            body_markdown=body_markdown,
            payload={
                **payload,
                "retry_count": item.retry_count,
                "head_sha": head_sha,
                "scope_revision": revision.revision,
                "revision_failed_head_count": revision.failed_head_count,
            },
            delivery_key=(
                f"github-continuation:{revision.id}:verification-failure:"
                f"{head_sha or 'no-head'}"
            ),
        )

    async def _record_failed_verification_attempt(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        head_sha: str | None,
        note: str,
        *,
        subject: str,
        body_markdown: str,
        payload: dict,
        retry_status: str,
    ) -> None:
        if head_sha and item.last_verified_sha == head_sha:
            if item.dispatch_status != retry_status:
                item.dispatch_status = retry_status
                self._set_failure_note(item, note)
                item.updated_at = datetime.utcnow()
                await db.commit()
            return

        item.last_verified_sha = head_sha
        item.retry_count += 1
        self._set_failure_note(item, note)
        await github_dispatch_service.notify_owner(
            db,
            item,
            subject=subject,
            body_markdown=body_markdown,
            payload={
                **payload,
                "retry_count": item.retry_count,
                "head_sha": head_sha,
            },
        )
        if item.retry_count > scope.max_verification_retries:
            await github_dispatch_service.escalate(
                db,
                item,
                "retry_count_exhausted",
                note,
            )
        else:
            item.dispatch_status = retry_status
            item.updated_at = datetime.utcnow()
        await db.commit()

    def _head_sha(self, pull: dict) -> str | None:
        sha = (pull.get("head") or {}).get("sha")
        return str(sha) if sha else None

    async def _head_is_green(
        self, scope: TeamGithubScope, client: GithubClient, head_sha: str | None
    ) -> bool:
        if not head_sha:
            return False
        checks = await client.list_check_runs_for_ref(
            scope.repo_owner, scope.repo_name, head_sha
        )
        if not checks:
            return False
        if any(
            check.get("status") != "completed" or check.get("conclusion") is None
            for check in checks
        ):
            return False
        return all(check.get("conclusion") in _SUCCESS_CONCLUSIONS for check in checks)


github_verification_service = GithubVerificationService()
