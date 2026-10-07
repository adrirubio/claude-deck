"""Polling watcher for autonomous GitHub dispatch."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AgentTeamSlot, GithubWorkItem, TeamGithubScope
from app.services.github_client import GithubClient, github_client
from app.models.database import GithubAttemptScopeRevision
from sqlalchemy import select
from app.services.github_dispatch_service import github_dispatch_service

_ACTIVE_STATUSES = ("dispatched", "verifying", "awaiting_human_review")
_RECOVERABLE_STATUSES = ("failed", "escalated")
# Kept separate from _ACTIVE_STATUSES: that tuple also drives label removal,
# which would turn failed items into retryable escalations behind the operator's back.
_CLOSED_ISSUE_RECONCILABLE_STATUSES = ("escalated", "failed")

logger = logging.getLogger(__name__)


def _parse_gh_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


async def observe_notification_uncertainty(db, *, item_id: int, revision_id: int | None = None) -> None:
    # The failed notification transaction must end before observation; the
    # observer records through the session after a clean boundary.
    try:
        await db.rollback()
    except Exception:
        pass
    """C09: the production notification failure observer.

    The action is committed but its notification transport is unsettled.
    The outcome stays explicitly uncertain; the action is never replayed
    because its audit fact is absent. Observation failure never masks the
    original failure.
    """
    try:
        from app.services import factory_audit_service as _audit
        await _audit.record_event(
            db,
            event_kind="work_lifecycle",
            source="github_watcher_service.notify_blocker_merged",
            occurred_at=datetime.utcnow(),
            actor=_audit.derive_actor(
                actor_kind="scheduler", scheduler="github_watcher"),
            item_id=item_id,
            action_outcome="uncertain",
            sanitized_reason="notification transport unsettled after commit",
            operation_id=f"notification-uncertain:{item_id}:{revision_id}",
            correlation_id=f"notification-uncertain:{item_id}:{revision_id}",
        )
        await db.commit()
    except Exception:
        await db.rollback()


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
        await self._reconcile_closed_issues(
            db,
            scope,
            client,
            open_labeled_numbers=frozenset(issue["number"] for issue in labeled),
        )
        await github_dispatch_service.promote_deferred_retries(db, scope)
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
            and await github_dispatch_service.can_auto_retry_from_issue_update(
                db,
                existing,
            )
        ):
            await github_dispatch_service.reset_for_retry(db, existing)
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
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [item.issue_number for item in active],
        )
        for item in active:
            issue = current.get(item.issue_number)
            if issue is not None and issue.get("state") == "closed":
                await self._complete_and_notify(db, scope, item)
                continue
            still_labeled = issue is not None and any(
                label["name"] == scope.dispatch_label for label in issue.get("labels", [])
            )
            if not still_labeled:
                await github_dispatch_service.escalate(
                    db,
                    item,
                    "dispatch_label_removed",
                    "The dispatch label was removed from the issue.",
                )

    async def _reconcile_closed_issues(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        client: GithubClient,
        *,
        open_labeled_numbers: frozenset[int] = frozenset(),
    ) -> None:
        stalled = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(
                        _CLOSED_ISSUE_RECONCILABLE_STATUSES
                    ),
                )
            )
        ).scalars().all()
        # Presence in the open labeled response proves an issue is open; absence
        # proves nothing, so absent issues must still be fetched by number.
        stalled = [
            item
            for item in stalled
            if item.issue_number not in open_labeled_numbers
        ]
        if not stalled:
            return
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [item.issue_number for item in stalled],
        )
        for item in stalled:
            issue = current.get(item.issue_number)
            if issue is None or issue.get("state") != "closed":
                continue
            if item.pr_number is not None:
                logger.info(
                    "Work item %s (issue #%s) has a closed issue but an unresolved "
                    "PR #%s; leaving it for the verification path",
                    item.id,
                    item.issue_number,
                    item.pr_number,
                )
                continue
            await self._complete_and_notify(db, scope, item)

    async def _complete_and_notify(
        self, db: AsyncSession, scope: TeamGithubScope, item: GithubWorkItem
    ) -> None:
        # A28-A35: the terminal transition records its sourced outcome fact.
        # A resolved PR on the closed issue is merge evidence (delivered).
        # A closure without any PR remains unknown: terminal tracking alone
        # never establishes delivery. Raw dispatch state is not rewritten.
        from app.services import factory_audit_service as _audit
        await _audit.record_delivery_fact(
            db,
            item_id=item.id,
            delivery_outcome="delivered" if item.pr_number is not None else "unknown",
            completion_kind="merged_code" if item.pr_number is not None else "closed_unproven",
            fact_source="github_watcher_service._reconcile_closed_issues",
            fact_time=datetime.utcnow(),
        )
        captured_revision_id = (await db.scalars(
            select(GithubAttemptScopeRevision.id).where(
                GithubAttemptScopeRevision.work_item_id == item.id,
            ).order_by(GithubAttemptScopeRevision.id.desc()).limit(1)
        )).first()
        item.dispatch_status = "completed"
        item.escalation_reason = None
        item.updated_at = datetime.utcnow()
        await db.commit()
        try:
            slots = (
                await db.execute(
                    select(AgentTeamSlot)
                    .where(AgentTeamSlot.preset_id == scope.preset_id)
                    .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                )
            ).scalars().all()
            await github_dispatch_service.notify_blocker_merged(db, scope, item, slots)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to send blocker-merged notification for work item %s", item.id
            )
            await observe_notification_uncertainty(
                db, item_id=item.id, revision_id=captured_revision_id)
            await db.rollback()


github_watcher_service = GithubWatcherService()
