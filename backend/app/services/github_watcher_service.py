"""Polling watcher for autonomous GitHub dispatch."""
from __future__ import annotations

import logging
import re
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

# A30/T01: revision states that no longer continue an attempt.
_TERMINAL_REVISION_STATUSES = (
    "completed", "cancelled", "rejected", "exhausted", "expired", "superseded")

# A34: at most this many unresolved attempts are read per poll.
_PROVISIONAL_BATCH = 20
_ARTIFACT_PR = re.compile(r"^(.+)/pull/(\d+)$")
_ATTEMPT_KEY = re.compile(r"^item:(\d+):launch:(\d+|None):revision:(\d+|None)$")


def _attempt_identity(item: GithubWorkItem) -> tuple:
    """A30: the in-memory identity that a guarded terminal write rechecks."""
    return (item.id, item.dispatch_nonce, item.launch_id, item.active_scope_revision,
            item.pr_number, item.dispatch_head_ref)


def _pull_in_repository(pull: dict, repository: str) -> bool:
    """A34: the pull's base and head both belong to the scope repository."""
    for side in ("base", "head"):
        part = pull.get(side)
        repo = part.get("repo") if isinstance(part, dict) else None
        if not isinstance(repo, dict) or repo.get("full_name") != repository:
            return False
    return True


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
        try:
            await self._reconcile_provisional_results(db, scope, client)
        except Exception:
            # A34: a later-result read never blocks the poll. It runs after the
            # poll commit, so a failure here discards nothing else; its
            # results stay unresolved until a later poll.
            logger.info("Later-result reconciliation unavailable for scope %s", scope.id,
                        exc_info=True)
            await db.rollback()
            await db.refresh(scope)

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
                # T01: active work completes only when no continuing authority
                # exists at the terminal write.
                await self._complete_and_notify(
                    db, scope, item,
                    fact_source="github_watcher_service._recheck_active_items", issue=issue,
                    guard_continuation=True)
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
        pending = [(item.id, item.issue_number, item.pr_number, item.escalation_reason)
                   for item in stalled]
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [issue_number for _item_id, issue_number, _pr_number, _reason in pending],
        )
        for item_id, issue_number, pr_number, _escalation_reason in pending:
            issue = current.get(issue_number)
            if issue is None or issue.get("state") != "closed":
                continue
            proof = None
            if pr_number is not None:
                # A30: a cached escalation reason is an old observation and
                # proves nothing now. Only fresh scoped proof that every pull
                # of this attempt is closed unmerged ends it without delivery.
                proof = await self._prove_closed_unmerged(db, scope, client, item_id)
                if proof is None:
                    logger.info(
                        "Work item %s (issue #%s) has a closed issue but PR #%s has no "
                        "current closed-unmerged proof; leaving it for the verification path",
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
                or (item.pr_number is not None and proof is None)
            ):
                continue
            if (proof is not None and _attempt_identity(item) != proof["identity"]) or (
                    await self._attempt_continues(db, item_id)):
                # A30/T01: a changed attempt or any continuation keeps the item.
                # The terminal claim below rechecks the same conditions at write.
                continue
            await self._complete_and_notify(
                db, scope, item,
                fact_source="github_watcher_service._reconcile_closed_issues", issue=issue,
                closed_unmerged=proof is not None, pull_proof=proof,
                guard_continuation=True)

    async def _prove_closed_unmerged(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        client: GithubClient,
        item_id: int,
    ) -> dict | None:
        """A30: fresh scoped proof that an attempt's pulls are all closed unmerged.

        The attempt identity is captured before any network read. The
        attempt's pull inventory is read through the scoped client and checked
        with the verification identity contracts. Any merged or open pull, an
        identity failure, an unclassifiable pull, a read error or an empty
        inventory returns None, so no non-delivery is recorded. Merged
        evidence stays with the verification merge paths.
        """
        from app.services.github_approval_service import github_approval_service
        from app.services.github_verification_service import (
            GithubVerificationService,
            github_verification_service,
        )

        item = await db.get(GithubWorkItem, item_id, populate_existing=True)
        if (item is None or item.pr_number is None or item.dispatch_head_ref is None
                or item.dispatch_status not in _CLOSED_ISSUE_RECONCILABLE_STATUSES):
            return None
        identity = _attempt_identity(item)
        pr_number = item.pr_number
        if await self._attempt_continues(db, item_id):
            return None
        try:
            token = await github_approval_service.github_read_token(scope)
            base = await github_verification_service.normalize_base_ref(
                scope, client, token=token, base_ref=item.dispatch_base_ref)
            pulls = await github_verification_service._list_attempt_pulls(
                scope, client, head_ref=item.dispatch_head_ref, base=base, token=token)
            item = await db.get(GithubWorkItem, item_id, populate_existing=True)
            if item is None or _attempt_identity(item) != identity:
                return None
            numbers: dict[int, dict] = {}
            for pull in pulls or []:
                number = GithubVerificationService._pull_number(pull)
                if number in numbers and numbers[number] != pull:
                    return None
                numbers[number] = pull
                if GithubVerificationService._classify_pull(pull) != "closed_unmerged":
                    return None
                GithubVerificationService._verify_pull_identity(
                    pull, scope, item, expected_base=base, verify_author=True)
        except Exception:
            logger.info("Closed-unmerged proof unavailable for work item %s", item_id,
                        exc_info=True)
            return None
        if pr_number not in numbers:
            return None
        return {
            "identity": identity,
            "pull_numbers": sorted(numbers),
            "pull_closed_at": numbers[pr_number].get("closed_at"),
            "observed_at": datetime.utcnow(),
        }

    async def _reconcile_provisional_results(
        self, db: AsyncSession, scope: TeamGithubScope, client: GithubClient
    ) -> int:
        """A34: a bounded, fair later-result reconciliation; returns attempts read.

        Candidates are retained attempts of this scope with no delivered
        fact, whose result is unknown or closed without delivery, on a work
        item that still exists. No age limit applies. A persisted round-robin
        cursor reads at most _PROVISIONAL_BATCH attempts per poll, so every
        candidate is read within ceil(N / batch) polls. A verified merged pull
        records delivery on the original attempt; nothing else is written and
        no work item field changes.
        """
        from app.models.database import FactoryAuditEvent, FactoryResultCursor
        from app.services import factory_audit_service as _audit
        from app.services.github_verification_service import GithubVerificationService

        rows = (await db.execute(
            select(FactoryAuditEvent.id, FactoryAuditEvent.item_id,
                   FactoryAuditEvent.item_context_key, FactoryAuditEvent.scope_context_key,
                   FactoryAuditEvent.team_context_key, FactoryAuditEvent.delivery_outcome,
                   FactoryAuditEvent.context_snapshot)
            .where(FactoryAuditEvent.scope_id == scope.id,
                   FactoryAuditEvent.event_kind == "delivery_evidence",
                   FactoryAuditEvent.item_id.is_not(None))
            .order_by(FactoryAuditEvent.id))).all()
        attempts: dict[str, dict] = {}
        for row in rows:
            snapshot = row.context_snapshot if isinstance(row.context_snapshot, dict) else {}
            attempt = snapshot.get("attempt")
            if not attempt or not row.item_context_key:
                continue
            # T04: the original attempt context: its lifetime keys and its
            # first recorded type. Later facts never take the current type.
            state = attempts.setdefault(f"{row.item_context_key}|{attempt}", {
                "attempt": attempt, "item_id": row.item_id, "delivered": False,
                "item_context_key": row.item_context_key,
                "scope_context_key": row.scope_context_key,
                "team_context_key": row.team_context_key,
                "issue_type": snapshot.get("issue_type")})
            if state["issue_type"] is None:
                state["issue_type"] = snapshot.get("issue_type")
            state["delivered"] = state["delivered"] or row.delivery_outcome == "delivered"
            state["latest_id"] = row.id
            state["snapshot"] = snapshot
            state["outcome"] = row.delivery_outcome
        candidates = sorted(
            (state for state in attempts.values()
             if not state["delivered"]
             and state["outcome"] in ("unknown", "closed_without_delivery")),
            key=lambda state: state["latest_id"])
        if not candidates:
            return 0
        cursor = await db.get(FactoryResultCursor, scope.id)
        after = cursor.last_event_id if cursor is not None and cursor.last_event_id else 0
        ordered = ([state for state in candidates if state["latest_id"] > after]
                   + [state for state in candidates if state["latest_id"] <= after])
        batch = ordered[:_PROVISIONAL_BATCH]
        if cursor is None:
            cursor = FactoryResultCursor(scope_id=scope.id)
            db.add(cursor)
        cursor.last_event_id = batch[-1]["latest_id"]
        cursor.updated_at = datetime.utcnow()
        await db.commit()
        repository = f"{scope.repo_owner}/{scope.repo_name}"
        captured_scope = (scope.id, scope.repo_owner, scope.repo_name)
        for state in batch:
            snapshot = state["snapshot"]
            match = _ARTIFACT_PR.match(snapshot.get("artifact") or "")
            proven_artifact = match is not None and match.group(1) == repository
            pr_number = int(match.group(2)) if proven_artifact else snapshot.get("pr_number")
            if not isinstance(pr_number, int) or pr_number <= 0:
                continue
            try:
                item = await db.get(GithubWorkItem, state["item_id"], populate_existing=True)
                if item is None or not await self._original_context_holds(
                        db, item, state, captured_scope):
                    continue
                current_attempt, _, _ = await _audit.item_attempt(db, item)
                is_current = current_attempt == state["attempt"] and item.pr_number == pr_number
                if not proven_artifact and not is_current:
                    # Without a proven artifact only the current attempt's own
                    # head can bind a pull to this attempt.
                    continue
                pull = await client.get_pull(captured_scope[1], captured_scope[2], pr_number)
                if (GithubVerificationService._classify_pull(pull) != "merged"
                        or GithubVerificationService._pull_number(pull) != pr_number
                        or not _pull_in_repository(pull, repository)):
                    continue
                # T04: recheck the original lifetime, scope and repository after
                # the external read. A deleted, replaced or moved item gets no fact.
                item = await db.get(GithubWorkItem, state["item_id"], populate_existing=True)
                if item is None or not await self._original_context_holds(
                        db, item, state, captured_scope):
                    continue
                head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
                if is_current and (item.dispatch_head_ref is None
                                   or head.get("ref") != item.dispatch_head_ref):
                    continue
                key = _ATTEMPT_KEY.match(state["attempt"])
                if key is None:
                    continue
                revision_id = None if key.group(3) == "None" else int(key.group(3))
                launch = snapshot.get("launch_attempt") or _audit.launch_attempt_key(
                    item.id, None if key.group(2) == "None" else int(key.group(2)))
                await _audit.record_merged_delivery(
                    db, item, pull,
                    source="github_watcher_service._reconcile_provisional_results",
                    attempt_identity=(state["attempt"], revision_id, launch),
                    original_context={
                        "item_context_key": state["item_context_key"],
                        "scope_context_key": state["scope_context_key"],
                        "team_context_key": state["team_context_key"],
                        "issue_type": state["issue_type"]})
                await db.commit()
            except Exception:
                logger.info("Later result unavailable for attempt %s", state["attempt"],
                            exc_info=True)
                try:
                    await db.rollback()
                    await db.refresh(scope)
                except Exception:
                    pass
        return len(batch)

    async def _original_context_holds(
        self, db: AsyncSession, item: GithubWorkItem, state: dict, captured_scope: tuple
    ) -> bool:
        """T04: the item is still the original lifetime, scope and repository."""
        from app.services import factory_audit_service as _audit

        if item.scope_id != captured_scope[0]:
            return False
        scope_row = await db.get(TeamGithubScope, item.scope_id, populate_existing=True)
        if scope_row is None or (scope_row.repo_owner, scope_row.repo_name) != captured_scope[1:]:
            return False
        if await _audit.current_context_key(db, "item", item.id) != state["item_context_key"]:
            return False
        if state["scope_context_key"] is not None and await _audit.current_context_key(
                db, "scope", item.scope_id) != state["scope_context_key"]:
            return False
        return True

    async def _attempt_continues(self, db: AsyncSession, item_id: int) -> bool:
        """R02/A30: a pending approval, live revision or requested retry continues it."""
        from app.models.database import GithubApprovalRequest

        item = await db.get(GithubWorkItem, item_id, populate_existing=True)
        if item is None or item.retry_requested_at is not None:
            return True
        pending_request = (await db.scalars(select(GithubApprovalRequest.id).where(
            GithubApprovalRequest.work_item_id == item_id,
            GithubApprovalRequest.status == "pending",
        ).limit(1))).first()
        live_revision = (await db.scalars(select(GithubAttemptScopeRevision.id).where(
            GithubAttemptScopeRevision.work_item_id == item_id,
            GithubAttemptScopeRevision.status.not_in(_TERMINAL_REVISION_STATUSES),
        ).limit(1))).first()
        return pending_request is not None or live_revision is not None

    async def _claim_terminal(
        self,
        db: AsyncSession,
        item_id: int,
        *,
        status: str,
        nonce: str | None,
        launch_id: int | None,
        revision: int | None,
        pr_number: int | None,
        guard_continuation: bool,
    ) -> bool:
        """T01: claim the terminal transition atomically; True when it holds.

        One conditional UPDATE applies the captured status and attempt
        identity. With ``guard_continuation`` it also requires no requested
        retry, no pending approval request and no live revision, evaluated
        at the write. The claim leaves the transaction open, so the caller's
        result fact commits with it or not at all.
        """
        from sqlalchemy import exists, update

        from app.models.database import GithubApprovalRequest

        def same(column, value):
            return column.is_(None) if value is None else column == value

        conditions = [
            GithubWorkItem.id == item_id,
            GithubWorkItem.dispatch_status == status,
            same(GithubWorkItem.dispatch_nonce, nonce),
            same(GithubWorkItem.launch_id, launch_id),
            same(GithubWorkItem.active_scope_revision, revision),
            same(GithubWorkItem.pr_number, pr_number),
        ]
        if guard_continuation:
            conditions += [
                GithubWorkItem.retry_requested_at.is_(None),
                ~exists().where(
                    GithubApprovalRequest.work_item_id == item_id,
                    GithubApprovalRequest.status == "pending"),
                ~exists().where(
                    GithubAttemptScopeRevision.work_item_id == item_id,
                    GithubAttemptScopeRevision.status.not_in(_TERMINAL_REVISION_STATUSES)),
            ]
        result = await db.execute(
            update(GithubWorkItem).where(*conditions).values(
                dispatch_status="completed", escalation_reason=None,
                updated_at=datetime.utcnow(),
            ).execution_options(synchronize_session=False))
        return result.rowcount == 1

    async def _complete_and_notify(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        *,
        fact_source: str = "github_watcher_service._complete_and_notify",
        issue: dict | None = None,
        closed_unmerged: bool = False,
        pull_proof: dict | None = None,
        guard_continuation: bool = False,
    ) -> None:
        """Complete a closed-issue item and notify its team.

        ``fact_source`` names the actual watcher caller. Closure alone never
        proves a merge: a non-null PR number on a closed issue does not prove
        delivery. R02: an issue that GitHub closed as not planned or
        duplicate, with no PR, is sourced terminal non-delivery at the issue
        closure time. A30: ``pull_proof`` is fresh scoped proof that every
        pull of the attempt is closed unmerged. That result is a conjunction of
        current conditions, so its result time stays unknown; the pull and
        issue closure times are kept as separate source times.
        """
        # Immutable scalars are captured before any await or commit so the
        # failure path never touches expired ORM state.
        captured_item_id = item.id
        captured_scope_id = scope.id
        captured_preset_id = scope.preset_id
        captured_launch_id = item.launch_id
        captured_active_revision = item.active_scope_revision
        captured_nonce = item.dispatch_nonce
        captured_status = item.dispatch_status
        captured_pr_number = item.pr_number
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
        # T01: one atomic guarded terminal claim. The conditional UPDATE takes
        # the SQLite writer and evaluates the captured attempt identity and,
        # for reconciled items, the absence of any continuing authority at
        # the write itself. A lost claim records no result fact and completes
        # nothing; counters, leases and notices are unchanged.
        if not await self._claim_terminal(
                db, captured_item_id, status=captured_status, nonce=captured_nonce,
                launch_id=captured_launch_id, revision=captured_active_revision,
                pr_number=captured_pr_number, guard_continuation=guard_continuation):
            await db.rollback()
            logger.info("Terminal claim lost for work item %s; nothing recorded",
                        captured_item_id)
            try:
                await db.refresh(scope)
            except Exception:
                pass
            return
        # A28-A35/C02: the terminal transition records its sourced outcome
        # fact in the same transaction. Issue closure alone is terminal
        # tracking: neither closure nor a non-null PR number proves a merge,
        # so the outcome stays unknown. Merge evidence is recorded by the
        # verification merge paths, which read the pull request.
        from app.services import factory_audit_service as _audit
        issue = issue if isinstance(issue, dict) else {}
        state_reason = issue.get("state_reason")
        closed_at = _audit._parse_time(issue.get("closed_at"))
        artifact = None
        fact_time = None
        snapshot: dict = {}
        if isinstance(issue.get("closed_at"), str):
            snapshot["issue_closed_at"] = issue["closed_at"]
        if closed_unmerged and pull_proof is not None:
            outcome, completion, source_of_fact = (
                "closed_without_delivery", "pr_closed_unmerged",
                "github_pull_request_closed_unmerged")
            artifact = f"{scope.repo_owner}/{scope.repo_name}/pull/{item.pr_number}"
            if isinstance(pull_proof.get("pull_closed_at"), str):
                snapshot["pull_closed_at"] = pull_proof["pull_closed_at"]
        elif state_reason in ("not_planned", "duplicate") and item.pr_number is None:
            outcome, completion, source_of_fact = (
                "closed_without_delivery", f"issue_closed_{state_reason}",
                "github_issue_state_reason")
            fact_time = closed_at
        else:
            outcome, completion, source_of_fact = "unknown", "closed_unproven", fact_source
        await _audit.record_delivery_fact(
            db,
            item_id=captured_item_id,
            revision_id=captured_revision_id,
            scope_id=captured_scope_id,
            delivery_outcome=outcome,
            completion_kind=completion,
            fact_source=source_of_fact,
            fact_time=fact_time,
            artifact=artifact,
            attempt=captured_attempt,
            launch_attempt=_audit.launch_attempt_key(captured_item_id, captured_launch_id),
            snapshot=snapshot or None,
            source=fact_source,
        )
        # The claim already wrote the transition; the fact and the claim
        # commit together, and an audit failure rolls both back.
        await db.commit()
        await db.refresh(item)
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
