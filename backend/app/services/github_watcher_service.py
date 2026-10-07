"""Polling watcher for autonomous GitHub dispatch."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentTeamSlot,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    TeamGithubScope,
)
from app.services.github_client import GithubClient, github_client
from app.services.github_dispatch_service import github_dispatch_service

_ACTIVE_STATUSES = ("dispatched", "verifying", "awaiting_human_review")
_RECOVERABLE_STATUSES = ("failed", "escalated")
# Kept separate from _ACTIVE_STATUSES: that tuple also drives label removal,
# which would turn failed items into retryable escalations behind the operator's back.
_CLOSED_ISSUE_RECONCILABLE_STATUSES = ("escalated", "failed")

logger = logging.getLogger(__name__)


def _parse_gh_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


_WATCHER_SCHEDULER = "github_watcher"
_NOTIFICATION_SOURCE = "github_watcher_service.notify_blocker_merged"


def attempt_key(item_id: int, launch_id: int | None, revision_id: int | None) -> str:
    """Stable non-secret identity of one tracked attempt and revision.

    The dispatch nonce is a private capability, so it never enters the key.
    The launch row and the immutable revision row identify the attempt.
    """
    return f"item:{item_id}:launch:{launch_id}:revision:{revision_id}"


def notification_operation_id(key: str, outcome: str) -> str:
    """Notification identity, distinct from the committed action identity.

    An earlier applied action fact can never suppress a later notification
    result for the same attempt, and an earlier uncertain result never
    suppresses a later settled one.
    """
    return f"notification:blocker-merged:{key}:{outcome}"


async def observe_notification_uncertainty(
    db,
    *,
    item_id: int,
    revision_id: int | None = None,
    scope_id: int | None = None,
    attempt: str | None = None,
    session_factory=None,
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
    key = attempt or attempt_key(item_id, None, revision_id)
    fresh = None
    try:
        if session_factory is None:
            from app.database import AsyncSessionLocal as session_factory
        fresh = session_factory()
        from app.services import factory_audit_service as _audit
        operation_id = notification_operation_id(key, "uncertain")
        await _audit.record_event(
            fresh,
            event_kind="lifecycle_notification",
            source=_NOTIFICATION_SOURCE,
            occurred_at=datetime.utcnow(),
            actor=_audit.derive_actor(
                actor_kind="scheduler", scheduler=_WATCHER_SCHEDULER),
            scope_id=scope_id,
            item_id=item_id,
            revision_id=revision_id,
            action_outcome="uncertain",
            sanitized_reason="notification transport unsettled after commit",
            operation_id=operation_id,
            correlation_id=operation_id,
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
        # Scalars are captured before any await: a failed notification in
        # _complete_and_notify rolls back and expires the loaded rows.
        pending = [(item.id, item.issue_number) for item in active]
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [issue_number for _item_id, issue_number in pending],
        )
        for item_id, issue_number in pending:
            item = await db.get(GithubWorkItem, item_id, populate_existing=True)
            if item is None or item.dispatch_status not in _ACTIVE_STATUSES:
                continue
            issue = current.get(issue_number)
            if issue is not None and issue.get("state") == "closed":
                await self._complete_and_notify(
                    db, scope, item,
                    fact_source="github_watcher_service._recheck_active_items")
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
        # Scalars are captured before any await. A failed notification below
        # rolls the session back and expires every loaded row, so later loop
        # entries must never read attributes from the original objects.
        pending = [(item.id, item.issue_number, item.pr_number) for item in stalled]
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [issue_number for _item_id, issue_number, _pr_number in pending],
        )
        for item_id, issue_number, pr_number in pending:
            issue = current.get(issue_number)
            if issue is None or issue.get("state") != "closed":
                continue
            if pr_number is not None:
                logger.info(
                    "Work item %s (issue #%s) has a closed issue but an unresolved "
                    "PR #%s; leaving it for the verification path",
                    item_id,
                    issue_number,
                    pr_number,
                )
                continue
            # Re-read the real row: it is current even after an earlier
            # entry's notification failure rolled the session back.
            item = await db.get(GithubWorkItem, item_id, populate_existing=True)
            if (
                item is None
                or item.dispatch_status not in _CLOSED_ISSUE_RECONCILABLE_STATUSES
                or item.pr_number is not None
            ):
                continue
            await self._complete_and_notify(
                db, scope, item,
                fact_source="github_watcher_service._reconcile_closed_issues")

    async def _complete_and_notify(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        *,
        fact_source: str = "github_watcher_service._complete_and_notify",
    ) -> None:
        """Complete a closed-issue item and notify its team.

        ``fact_source`` names the actual watcher caller. The watcher reads no
        pull request state, so it never has merge evidence: a non-null PR
        number on a closed issue does not prove delivery.
        """
        # Immutable scalars are captured before any await or commit so the
        # failure path never touches expired ORM state.
        captured_item_id = item.id
        captured_scope_id = scope.id
        captured_preset_id = scope.preset_id
        captured_launch_id = item.launch_id
        captured_active_revision = item.active_scope_revision
        captured_nonce = item.dispatch_nonce
        # The original attempt is the revision row of this item, dispatch
        # attempt and active revision number. The newest row for the item
        # alone could belong to a different attempt.
        captured_revision_id = None
        if captured_nonce is not None:
            captured_revision_id = (await db.scalars(
                select(GithubAttemptScopeRevision.id).where(
                    GithubAttemptScopeRevision.work_item_id == captured_item_id,
                    GithubAttemptScopeRevision.dispatch_nonce == captured_nonce,
                    GithubAttemptScopeRevision.revision == captured_active_revision,
                ).limit(1)
            )).first()
        captured_attempt = attempt_key(
            captured_item_id, captured_launch_id, captured_revision_id)
        # A28-A35/C02: the terminal transition records its sourced outcome
        # fact in the same transaction. Issue closure is terminal tracking
        # only. Neither closure nor a non-null PR number proves a merge, so
        # the outcome stays unknown. Merge evidence is recorded only by the
        # verification path, which reads the pull request.
        from app.services import factory_audit_service as _audit
        await _audit.record_delivery_fact(
            db,
            item_id=captured_item_id,
            revision_id=captured_revision_id,
            scope_id=captured_scope_id,
            delivery_outcome="unknown",
            completion_kind="closed_unproven",
            fact_source=fact_source,
            fact_time=datetime.utcnow(),
            attempt=captured_attempt,
            launch_attempt=_audit.launch_attempt_key(captured_item_id, captured_launch_id),
        )
        item.dispatch_status = "completed"
        item.escalation_reason = None
        item.updated_at = datetime.utcnow()
        await db.commit()
        try:
            slots = (
                await db.execute(
                    select(AgentTeamSlot)
                    .where(AgentTeamSlot.preset_id == captured_preset_id)
                    .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                )
            ).scalars().all()
            await github_dispatch_service.notify_blocker_merged(db, scope, item, slots)
            operation_id = notification_operation_id(captured_attempt, "applied")
            await _audit.record_event(
                db,
                event_kind="lifecycle_notification",
                source=_NOTIFICATION_SOURCE,
                occurred_at=datetime.utcnow(),
                actor=_audit.derive_actor(
                    actor_kind="scheduler", scheduler=_WATCHER_SCHEDULER),
                scope_id=captured_scope_id,
                item_id=captured_item_id,
                revision_id=captured_revision_id,
                action_outcome="applied",
                sanitized_reason="blocker-merged notification sent",
                operation_id=operation_id,
                correlation_id=operation_id,
            )
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to send blocker-merged notification for work item %s",
                captured_item_id,
            )
            # The committed transition is never replayed. Its unsettled
            # notification is observed as uncertain in a fresh session.
            await observe_notification_uncertainty(
                db,
                item_id=captured_item_id,
                revision_id=captured_revision_id,
                scope_id=captured_scope_id,
                attempt=captured_attempt,
                session_factory=getattr(self, "observer_session_factory", None),
            )
            try:
                await db.rollback()
                # Callers keep using the scope after this entry.
                await db.refresh(scope)
            except Exception:
                pass


github_watcher_service = GithubWatcherService()
