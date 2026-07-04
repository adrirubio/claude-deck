"""Routing and dispatch lifecycle for autonomous GitHub dispatch."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AgentTeamSlot, GithubWorkItem, MailTeamMember, TeamGithubScope
from app.models.schemas import AgentTeamLaunchRequest
from app.services.agent_team_service import agent_team_service

_BUSY_STATUSES = ("dispatched", "verifying")
_SCOPE_CONCURRENCY_STATUSES = ("dispatched", "verifying")

logger = logging.getLogger(__name__)


class GithubDispatchService:
    def reset_for_retry(self, item: GithubWorkItem) -> None:
        item.dispatch_status = "pending"
        item.escalation_reason = None
        item.pending_reason = None
        item.handoff_state = None
        item.handoff_target_slot_id = None
        item.retry_count = 0
        item.approval_round_count = 0
        item.updated_at = datetime.utcnow()

    async def route_item(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        preset_slots: list[AgentTeamSlot],
        issue_labels: list[str],
        classify=None,
    ) -> tuple[int | None, str]:
        enabled = [slot for slot in preset_slots if slot.enabled]
        enabled.sort(key=lambda slot: slot.position)
        if not enabled:
            return None, "leader_fallback"

        issue_label_set = set(issue_labels)
        for slot in enabled:
            slot_areas = set(slot.area_labels or [])
            if slot_areas & issue_label_set:
                return slot.id, "label"

        classifiable = [slot for slot in enabled if slot.expertise]
        if classifiable and classify is not None:
            chosen = await classify(item, classifiable)
            if chosen is not None:
                return chosen, "classified"

        return enabled[0].id, "leader_fallback"

    async def slot_is_busy(self, db: AsyncSession, slot_id: int) -> bool:
        active = (
            await db.execute(
                select(GithubWorkItem.id).where(
                    GithubWorkItem.owner_slot_id == slot_id,
                    GithubWorkItem.dispatch_status.in_(_BUSY_STATUSES),
                )
            )
        ).first()
        if active is not None:
            return True
        pending_handoff = (
            await db.execute(
                select(GithubWorkItem.id).where(
                    GithubWorkItem.handoff_state == "pending",
                    (GithubWorkItem.owner_slot_id == slot_id)
                    | (GithubWorkItem.handoff_target_slot_id == slot_id),
                )
            )
        ).first()
        return pending_handoff is not None

    async def scope_active_count(self, db: AsyncSession, scope_id: int) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(GithubWorkItem)
                    .where(
                        GithubWorkItem.scope_id == scope_id,
                        GithubWorkItem.dispatch_status.in_(_SCOPE_CONCURRENCY_STATUSES),
                    )
                )
            ).scalar_one()
        )

    async def dispatch_pending(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
        client=None,
        classify=None,
        launcher=None,
        issue_labels_by_number: dict[int, list[str]] | None = None,
    ) -> None:
        launcher = launcher or agent_team_service.launch
        issue_labels_by_number = issue_labels_by_number or {}
        slots_dispatched_this_batch: set[int] = set()
        scope_dispatched_this_batch = 0
        scope_active = await self.scope_active_count(db, scope.id)

        pending = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "pending",
                ).order_by(GithubWorkItem.created_at, GithubWorkItem.id)
            )
        ).scalars().all()

        for item in pending:
            if scope_active + scope_dispatched_this_batch >= scope.max_concurrent_dispatched:
                item.pending_reason = "queued_repo_cap"
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
            issue_labels = issue_labels_by_number.get(item.issue_number, [])
            owner_slot_id, method = await self.route_item(
                db, item, preset_slots, issue_labels, classify=classify
            )
            if owner_slot_id is None:
                await self.escalate(db, item, "plan_blocked")
                await db.commit()
                continue
            if owner_slot_id in slots_dispatched_this_batch or await self.slot_is_busy(
                db, owner_slot_id
            ):
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_slot_busy"
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
            try:
                result = await launcher(
                    db,
                    scope.preset_id,
                    AgentTeamLaunchRequest(
                        slot_ids=[owner_slot_id],
                        reuse_existing=False,
                        skip_plan_confirmation=True,
                        repo_path_override=scope.repo_path,
                    ),
                )
            except ValueError:
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = None
                await self.escalate(db, item, "plan_blocked")
                await db.commit()
                continue
            item.owner_slot_id = owner_slot_id
            item.routing_method = method
            item.launch_id = getattr(result, "launch_id", None)
            launch_item = next(iter(getattr(result, "items", []) or []), None)
            launch_status = getattr(launch_item, "status", None)
            if launch_status in {
                "failed",
                "blocked",
                "blocked_provider_unavailable",
                "blocked_agent_mail_not_configured",
            }:
                item.dispatch_status = "failed"
            else:
                item.dispatch_status = "dispatched"
                slots_dispatched_this_batch.add(owner_slot_id)
                scope_dispatched_this_batch += 1
            item.pending_reason = None
            item.updated_at = datetime.utcnow()
            await db.commit()

    async def record_approval_round(
        self, db: AsyncSession, item: GithubWorkItem, scope: TeamGithubScope
    ) -> None:
        item.approval_round_count += 1
        if item.approval_round_count >= scope.max_approval_rounds:
            await self.escalate(db, item, "approval_rounds_exhausted")
        item.updated_at = datetime.utcnow()
        await db.commit()

    async def initiate_handoff(
        self, db: AsyncSession, item: GithubWorkItem, target_slot_id: int
    ) -> None:
        item.handoff_state = "pending"
        item.handoff_target_slot_id = target_slot_id
        item.updated_at = datetime.utcnow()
        await db.commit()

    async def accept_handoff(
        self, db: AsyncSession, item: GithubWorkItem, accepting_slot_id: int
    ) -> None:
        if item.handoff_target_slot_id != accepting_slot_id:
            raise ValueError(
                f"slot {accepting_slot_id} cannot accept a handoff targeted at "
                f"{item.handoff_target_slot_id}"
            )
        item.owner_slot_id = accepting_slot_id
        item.handoff_state = "accepted"
        item.handoff_target_slot_id = None
        item.routing_method = "reassigned"
        item.updated_at = datetime.utcnow()
        await db.commit()

    async def monitor_dispatched(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
        wake_state_by_slot: dict[int, str] | None = None,
    ) -> None:
        enabled = sorted(
            [slot for slot in preset_slots if slot.enabled],
            key=lambda slot: slot.position,
        )
        if not enabled:
            return
        leader = enabled[0]

        if wake_state_by_slot is None:
            from app.services.agent_mail_service import agent_mail_service

            members = await agent_mail_service.list_team(db)
            wake_state_by_slot = {
                member.team_slot_id: member.wake_state
                for member in members
                if member.team_slot_id is not None
            }
        leader_wake = wake_state_by_slot.get(leader.id)

        dispatched = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "dispatched",
                    GithubWorkItem.pr_number.is_(None),
                )
            )
        ).scalars().all()

        for item in dispatched:
            if leader_wake == "offline":
                await self.escalate(db, item, "leader_offline")
            # Leader reachable but idle nudge/escalation is intentionally deferred;
            # it needs agent-mail last-activity plumbing beyond Phase A's backend core.
        await db.commit()

    async def escalate(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        reason: str,
        note: str | None = None,
    ) -> None:
        self._apply_escalation(item, reason, note)
        try:
            await self._send_escalation_broadcast(db, item, reason, note)
            if reason == "dispatch_label_removed":
                await self._send_label_removed_owner_message(db, item)
        except Exception:
            logger.exception(
                "Failed to send autonomous dispatch escalation notification for item %s",
                item.id,
            )
            await db.rollback()
            self._apply_escalation(item, reason, note)

    def _apply_escalation(
        self,
        item: GithubWorkItem,
        reason: str,
        note: str | None = None,
    ) -> None:
        item.dispatch_status = "escalated"
        item.escalation_reason = reason
        item.pending_reason = None
        if note is not None:
            item.status_note = note
        item.updated_at = datetime.utcnow()

    async def notify_owner(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        subject: str,
        body_markdown: str,
        payload: dict | None = None,
    ) -> None:
        member = await self._owner_member(db, item)
        if member is None:
            return
        from app.services.agent_mail_service import agent_mail_service

        await agent_mail_service.send_direct_message(
            db,
            recipient_member_id=member.id,
            subject=subject,
            body_markdown=body_markdown,
            payload=payload,
        )

    async def notify_team(
        self,
        db: AsyncSession,
        *,
        subject: str,
        body_markdown: str,
        payload: dict | None = None,
    ) -> None:
        from app.services.agent_mail_service import agent_mail_service

        await agent_mail_service.send_broadcast(
            db,
            subject=subject,
            body_markdown=body_markdown,
            payload=payload,
        )

    async def _send_escalation_broadcast(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        reason: str,
        note: str | None,
    ) -> None:
        scope = await db.get(TeamGithubScope, item.scope_id)
        repo = f"{scope.repo_owner}/{scope.repo_name}" if scope is not None else "unknown repo"
        lines = [
            f"Autonomous GitHub dispatch escalated issue #{item.issue_number}.",
            "",
            f"- Repo: {repo}",
            f"- Reason: {reason}",
            f"- Issue: {item.issue_title}",
        ]
        if item.issue_url:
            lines.append(f"- URL: {item.issue_url}")
        if note:
            lines.extend(["", note])
        await self.notify_team(
            db,
            subject=f"Autonomy escalation: {reason}",
            body_markdown="\n".join(lines),
            payload={
                "kind": "github_dispatch_escalation",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
                "scope_id": item.scope_id,
                "reason": reason,
            },
        )

    async def _send_label_removed_owner_message(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
    ) -> None:
        await self.notify_owner(
            db,
            item,
            subject="Dispatch label removed",
            body_markdown=(
                f"The triggering label was removed from issue #{item.issue_number}. "
                "A human wants this stopped or reconsidered. Finish or discard your "
                "current work at your discretion, but do not open or merge a PR without "
                "re-confirming with the team leader."
            ),
            payload={
                "kind": "github_dispatch_label_removed",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
            },
        )

    async def _owner_member(self, db: AsyncSession, item: GithubWorkItem) -> MailTeamMember | None:
        if item.owner_slot_id is None:
            return None
        return (
            await db.execute(
                select(MailTeamMember)
                .where(MailTeamMember.team_slot_id == item.owner_slot_id)
                .order_by(MailTeamMember.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


github_dispatch_service = GithubDispatchService()
