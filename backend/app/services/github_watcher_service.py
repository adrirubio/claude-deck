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


async def observe_notification_uncertainty(
    db, *, item_id: int, revision_id: int | None = None, session_factory=None
) -> None:
    """C09: the production notification failure observer.

    The action is committed but its notification transport is unsettled.
    The outcome stays explicitly uncertain; the action is never replayed
    because its audit fact is absent. The failed notification transaction
    ends before observation, and the observation records through a fresh
    session bound to the same action database. Observation failure never
    masks the original failure.
    """
    try:
        await db.rollback()
    except Exception:
        pass
    fresh = None
    try:
        if session_factory is None:
            from app.database import AsyncSessionLocal as session_factory
        fresh = session_factory()
        from app.services import factory_audit_service as _audit
        await _audit.record_event(
            fresh,
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
        await fresh.commit()
    except Exception:
        logger.exception(
            "Failed to record notification uncertainty for work item %s", item_id)
    finally:
        try:
            if fresh is not None:
                await fresh.close()
        except Exception:
            pass


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
        from types import SimpleNamespace
        pending_items = [
            (item.id, item.issue_number, item.issue_title, item.pr_number,
             item.active_scope_revision, item.scope_id, item.owner_slot_id)
            for item in stalled
        ]
        stalled_by_id = {
            entry[0]: SimpleNamespace(
                id=entry[0], issue_number=entry[1], issue_title=entry[2],
                pr_number=entry[3], active_scope_revision=entry[4],
                scope_id=entry[5], owner_slot_id=entry[6],
                dispatch_status="failed", escalation_reason=None,
                updated_at=None)
            for entry in pending_items
        }
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [entry[1] for entry in pending_items],
        )
        pending_by_id = {entry[0]: entry for entry in pending_items}
        for captured_id in list(pending_by_id):
            _cid, issue_number, _title, pr_number, _rev, _scope, _owner = pending_by_id[captured_id]
            issue = current.get(issue_number)
            if issue is None or issue.get("state") != "closed":
                continue
            if pr_number is not None:
                logger.info(
                    "Work item %s (issue #%s) has a closed issue but an unresolved "
                    "PR #%s; leaving it for the verification path",
                    _cid,
                    issue_number,
                    pr_number,
                )
                continue
            await self._complete_and_notify(db, scope, stalled_by_id[captured_id])

    async def _complete_and_notify(
        self, db: AsyncSession, scope: TeamGithubScope, item: GithubWorkItem
    ) -> None:
        # Immutable scalars are captured before any await or commit so the
        # failure path never touches expired ORM state.
        captured_item_id = item.id
        captured_issue_number = item.issue_number
        captured_issue_title = item.issue_title
        captured_pr_number = item.pr_number
        captured_active_revision = item.active_scope_revision
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
                GithubAttemptScopeRevision.work_item_id == captured_item_id,
                GithubAttemptScopeRevision.revision == captured_active_revision,
            ).limit(1)
        )).first()
        from sqlalchemy import text as _sql_text
        transitioned_at = datetime.utcnow()
        await db.execute(_sql_text(
            "UPDATE github_work_items SET dispatch_status = 'completed',"
            " escalation_reason = NULL, updated_at = :ts WHERE id = :item_id"),
            {"ts": transitioned_at, "item_id": captured_item_id})
        # Keep any live ORM view consistent for callers.
        item.dispatch_status = "completed"
        item.escalation_reason = None
        item.updated_at = transitioned_at
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
                "Failed to send blocker-merged notification for work item %s",
                captured_item_id,
            )
            await observe_notification_uncertainty(
                db, item_id=captured_item_id, revision_id=captured_revision_id,
                session_factory=getattr(self, "observer_session_factory", None))
            try:
                await db.rollback()
            except Exception:
                pass


github_watcher_service = GithubWatcherService()
