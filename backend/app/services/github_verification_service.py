"""GitHub PR verification and merge loop for autonomous dispatch."""
from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import (
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_app_auth_service import (
    GithubAppAuthError,
    github_app_auth_service,
)
from app.services.github_client import GithubClient, github_client
from app.services.github_dispatch_service import github_dispatch_service

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


class GithubVerificationService:
    def __init__(self) -> None:
        self._pr_ready_locks: dict[int, asyncio.Lock] = {}

    async def normalize_base_ref(
        self,
        scope: TeamGithubScope,
        client: GithubClient,
        *,
        token: str,
    ) -> str:
        base_ref = scope.base_ref
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
        pull = await client.get_pull(scope.repo_owner, scope.repo_name, pr_number)
        self._verify_pull_identity(pull, scope, item)
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

            try:
                github_app_auth_service.require_configuration(require_bot_login=True)
                token = await github_app_auth_service.mint_repository_token(
                    scope.github_app_installation_id,
                    scope.repo_owner,
                    scope.repo_name,
                )
            except GithubAppAuthError as exc:
                raise ValueError(exc.code) from exc

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

            base = await self.normalize_base_ref(scope, client, token=token)
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
        verify_author: bool,
    ) -> int | None:
        classified: list[tuple[dict, str]] = []
        invalid: list[str] = []
        for index, pull in enumerate(pulls):
            verdict = self._classify_pull(pull)
            if verdict is None:
                invalid.append(str(pull.get("number", f"index {index}")))
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
                    await self._verify_item(db, scope, item, client)
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
    ) -> None:
        pull = await client.get_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
        verdict = self._classify_pull(pull)
        if verdict is None:
            note = f"PR #{item.pr_number} returned a state Deck cannot classify."
            await self._record_failed_verification_attempt(
                db,
                scope,
                item,
                None,
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

        head_sha = self._head_sha(pull)
        checks = await client.list_check_runs_for_ref(
            scope.repo_owner,
            scope.repo_name,
            head_sha or "",
        )
        if not checks:
            if await self._process_combined_status(db, scope, item, client, pull):
                return
            await self._handle_no_check_signal(db, item)
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
            await self._record_failed_verification_attempt(
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
            )
            return
        if pending:
            item.status_note = "GitHub checks are still running."
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        if all(check.get("conclusion") in _SUCCESS_CONCLUSIONS for check in checks):
            await self._promote_verified_item(db, scope, item, client, pull, head_sha)

    async def _process_review_item(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
        pull: dict | None = None,
    ) -> None:
        pull = pull or await client.get_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
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
            await self._promote_verified_item(db, scope, item, client, pull, head_sha)
            return True
        if state in _STATUS_FAILURE_STATES:
            note = f"GitHub commit status failed: {state}"
            await self._record_failed_verification_attempt(
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
            )
            return True
        item.status_note = "GitHub commit statuses are still pending."
        item.updated_at = datetime.utcnow()
        await db.commit()
        return True

    async def _handle_no_check_signal(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
    ) -> None:
        grace_started_at = item.updated_at or item.created_at
        grace_age = datetime.utcnow() - grace_started_at
        if grace_age < timedelta(seconds=settings.github_check_signal_grace_seconds):
            item.status_note = "Waiting for GitHub check-runs or commit statuses to appear."
            item.updated_at = datetime.utcnow()
            await db.commit()
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
    ) -> None:
        if pull.get("draft") and pull.get("node_id"):
            await client.mark_pull_ready_for_review(str(pull["node_id"]))
            pull = await client.get_pull(
                scope.repo_owner,
                scope.repo_name,
                int(item.pr_number),
            )
        item.last_verified_sha = head_sha
        item.dispatch_status = "ready_for_review"
        item.status_note = f"PR #{item.pr_number} is ready for review."
        item.updated_at = datetime.utcnow()
        if scope.merge_policy == "human":
            await self._notify_code_pr_ready_for_review(db, item)
        await db.commit()
        await self._process_review_item(db, scope, item, client, pull=pull)

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
