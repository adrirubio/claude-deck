"""Polling watcher for autonomous GitHub dispatch."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import GithubWorkItem, TeamGithubScope
from app.services.github_client import GithubClient, github_client

_ACTIVE_STATUSES = ("dispatched", "verifying", "awaiting_human_review")
_RECOVERABLE_STATUSES = ("failed", "escalated")


def _parse_gh_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


class GithubWatcherService:
    async def poll_scope(
        self, db: AsyncSession, scope: TeamGithubScope, client: GithubClient | None = None
    ) -> None:
        client = client or github_client
        labeled = await client.list_issues_with_label(
            scope.repo_owner, scope.repo_name, scope.dispatch_label
        )
        for issue in labeled:
            await self._upsert_item(db, scope, issue)
        await self._recheck_active_items(db, scope, client)
        scope.last_polled_at = datetime.utcnow()
        await db.commit()

    async def _upsert_item(self, db: AsyncSession, scope: TeamGithubScope, issue: dict) -> None:
        label_names = {label["name"] for label in issue.get("labels", [])}
        issue_type = "design" if scope.design_label in label_names else "code"
        github_updated_at = _parse_gh_ts(issue["updated_at"])
        existing = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.issue_number == issue["number"],
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            db.add(
                GithubWorkItem(
                    scope_id=scope.id,
                    issue_number=issue["number"],
                    issue_title=issue["title"],
                    issue_url=issue["html_url"],
                    github_updated_at=github_updated_at,
                    issue_type=issue_type,
                    dispatch_status="pending",
                )
            )
            return

        if (
            existing.dispatch_status in _RECOVERABLE_STATUSES
            and github_updated_at > existing.github_updated_at
        ):
            existing.dispatch_status = "pending"
            existing.escalation_reason = None
            existing.pending_reason = None
            existing.retry_count = 0
            existing.approval_round_count = 0
        if existing.dispatch_status == "pending":
            existing.issue_type = issue_type
        existing.github_updated_at = github_updated_at
        existing.issue_title = issue["title"]
        existing.updated_at = datetime.utcnow()

    async def _recheck_active_items(
        self, db: AsyncSession, scope: TeamGithubScope, client: GithubClient
    ) -> None:
        active = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_ACTIVE_STATUSES),
                )
            )
        ).scalars().all()
        if not active:
            return
        current = await client.get_open_issues_by_number(
            scope.repo_owner, scope.repo_name, [item.issue_number for item in active]
        )
        for item in active:
            issue = current.get(item.issue_number)
            still_labeled = issue is not None and any(
                label["name"] == scope.dispatch_label for label in issue.get("labels", [])
            )
            if not still_labeled:
                item.dispatch_status = "escalated"
                item.escalation_reason = "dispatch_label_removed"
                item.updated_at = datetime.utcnow()


github_watcher_service = GithubWatcherService()
