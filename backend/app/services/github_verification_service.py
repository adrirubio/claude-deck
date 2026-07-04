"""GitHub PR verification and merge loop for autonomous dispatch."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import GithubWorkItem, TeamGithubScope
from app.services.github_client import GithubClient, github_client
from app.services.github_dispatch_service import github_dispatch_service

_SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
_STATUS_SUCCESS_STATES = {"success"}
_STATUS_FAILURE_STATES = {"failure", "error"}
_TRANSIENT_MERGE_STATES = {"unstable", "blocked"}
_HUMAN_MERGE_NOTE_PREFIXES = (
    "Auto-merge blocked",
    "Auto-merge budget exhausted",
    "Auto-merge retry budget exhausted",
)
_MERGE_TRANSIENT_STATUS_CODES = {405, 409, 422}

logger = logging.getLogger(__name__)


class GithubVerificationService:
    async def report_pr_opened(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        pr_number: int,
    ) -> None:
        if item.dispatch_status != "dispatched":
            raise ValueError(
                f"pr_opened is only valid for dispatched work items; current status is "
                f"{item.dispatch_status}"
            )
        item.pr_number = pr_number
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
                item.status_note = f"GitHub verification failed; will retry: {exc}"
                item.updated_at = datetime.utcnow()
                await db.commit()

    async def _verify_item(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
    ) -> None:
        pull = await client.get_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
        if pull.get("merged"):
            self._mark_merged(item)
            await db.commit()
            return

        checks = await client.list_check_runs_for_ref(
            scope.repo_owner,
            scope.repo_name,
            pull.get("head", {}).get("sha", ""),
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
            item.retry_count += 1
            item.status_note = self._failed_check_note(failed)
            await github_dispatch_service.notify_owner(
                db,
                item,
                subject="GitHub checks failed",
                body_markdown=(
                    f"GitHub checks failed for issue #{item.issue_number} / "
                    f"PR #{item.pr_number}.\n\n{item.status_note}"
                ),
                payload={
                    "kind": "github_dispatch_check_failed",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                    "retry_count": item.retry_count,
                },
            )
            if item.retry_count > scope.max_verification_retries:
                await github_dispatch_service.escalate(
                    db,
                    item,
                    "retry_count_exhausted",
                    item.status_note,
                )
            else:
                item.dispatch_status = "dispatched"
                item.updated_at = datetime.utcnow()
            await db.commit()
            return
        if pending:
            item.status_note = "GitHub checks are still running."
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        if all(check.get("conclusion") in _SUCCESS_CONCLUSIONS for check in checks):
            item.dispatch_status = "ready_for_review"
            item.status_note = f"PR #{item.pr_number} is ready for review."
            item.updated_at = datetime.utcnow()
            if pull.get("draft") and pull.get("node_id"):
                await client.mark_pull_ready_for_review(str(pull["node_id"]))
                pull = await client.get_pull(
                    scope.repo_owner,
                    scope.repo_name,
                    int(item.pr_number),
                )
            if scope.merge_policy == "human":
                await github_dispatch_service.notify_team(
                    db,
                    subject="Code PR ready for review",
                    body_markdown=(
                        f"Code PR #{item.pr_number} is ready for human review for "
                        f"issue #{item.issue_number}: {item.issue_title}"
                    ),
                    payload={
                        "kind": "github_dispatch_code_pr_ready",
                        "work_item_id": item.id,
                        "pr_number": item.pr_number,
                    },
                )
            await db.commit()
            await self._process_review_item(db, scope, item, client, pull=pull)

    async def _process_review_item(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        client: GithubClient,
        pull: dict | None = None,
    ) -> None:
        pull = pull or await client.get_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
        if pull.get("merged"):
            self._mark_merged(item)
            await db.commit()
            return
        if item.issue_type == "design" or scope.merge_policy != "auto":
            return
        if item.status_note and item.status_note.startswith(_HUMAN_MERGE_NOTE_PREFIXES):
            return
        if await self._auto_merge_budget_exhausted(db, scope):
            item.status_note = "Auto-merge budget exhausted; PR is ready for human merge."
            item.updated_at = datetime.utcnow()
            await db.commit()
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
        try:
            await client.merge_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in _MERGE_TRANSIENT_STATUS_CODES or status_code >= 500:
                await self._record_transient_merge_failure(db, scope, item, str(exc))
            elif status_code == 403:
                self._fallback_to_human_merge(
                    item,
                    "Auto-merge blocked by repository policy; requires human merge.",
                )
                await db.commit()
            else:
                self._fallback_to_human_merge(
                    item,
                    f"Auto-merge failed with GitHub status {status_code}; requires human merge.",
                )
                await db.commit()
            return

        self._mark_merged(item)
        item.auto_merged_at = datetime.utcnow()
        await db.commit()

    async def _record_transient_merge_failure(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        note: str,
    ) -> None:
        item.retry_count += 1
        if item.retry_count > scope.max_verification_retries:
            self._fallback_to_human_merge(
                item,
                f"Auto-merge retry budget exhausted after transient merge failure: {note}",
            )
        else:
            item.status_note = f"Transient merge failure; will retry: {note}"
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
        status = await client.get_combined_status_for_ref(
            scope.repo_owner,
            scope.repo_name,
            pull.get("head", {}).get("sha", ""),
        )
        contexts = status.get("statuses") or []
        if not contexts:
            return False
        state = status.get("state")
        if state in _STATUS_SUCCESS_STATES:
            item.dispatch_status = "ready_for_review"
            item.status_note = f"PR #{item.pr_number} is ready for review."
            item.updated_at = datetime.utcnow()
            if pull.get("draft") and pull.get("node_id"):
                await client.mark_pull_ready_for_review(str(pull["node_id"]))
                pull = await client.get_pull(
                    scope.repo_owner,
                    scope.repo_name,
                    int(item.pr_number),
                )
            if scope.merge_policy == "human":
                await github_dispatch_service.notify_team(
                    db,
                    subject="Code PR ready for review",
                    body_markdown=(
                        f"Code PR #{item.pr_number} is ready for human review for "
                        f"issue #{item.issue_number}: {item.issue_title}"
                    ),
                    payload={
                        "kind": "github_dispatch_code_pr_ready",
                        "work_item_id": item.id,
                        "pr_number": item.pr_number,
                    },
                )
            await db.commit()
            await self._process_review_item(db, scope, item, client, pull=pull)
            return True
        if state in _STATUS_FAILURE_STATES:
            item.retry_count += 1
            item.status_note = f"GitHub commit status failed: {state}"
            await github_dispatch_service.notify_owner(
                db,
                item,
                subject="GitHub commit status failed",
                body_markdown=(
                    f"GitHub commit status failed for issue #{item.issue_number} / "
                    f"PR #{item.pr_number}.\n\n{item.status_note}"
                ),
                payload={
                    "kind": "github_dispatch_status_failed",
                    "work_item_id": item.id,
                    "pr_number": item.pr_number,
                    "retry_count": item.retry_count,
                },
            )
            if item.retry_count > scope.max_verification_retries:
                await github_dispatch_service.escalate(
                    db,
                    item,
                    "retry_count_exhausted",
                    item.status_note,
                )
            else:
                item.dispatch_status = "dispatched"
                item.updated_at = datetime.utcnow()
            await db.commit()
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

    def _fallback_to_human_merge(self, item: GithubWorkItem, note: str) -> None:
        item.dispatch_status = "ready_for_review"
        item.escalation_reason = None
        item.status_note = note
        item.updated_at = datetime.utcnow()

    def _failed_check_note(self, checks: list[dict]) -> str:
        names = ", ".join(str(check.get("name") or check.get("id")) for check in checks)
        return f"GitHub check failed: {names}"


github_verification_service = GithubVerificationService()
