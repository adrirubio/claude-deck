"""Routing and dispatch lifecycle for autonomous GitHub dispatch."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AgentTeamSlot, GithubWorkItem, TeamGithubScope
from app.models.schemas import AgentTeamLaunchRequest
from app.services.agent_team_service import agent_team_service

_BUSY_STATUSES = ("dispatched", "verifying")


class GithubDispatchService:
    async def route_item(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        preset_slots: list[AgentTeamSlot],
        repo_labels: list[str],
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
        from app.services.github_client import github_client as _default_client

        client = client or _default_client
        launcher = launcher or agent_team_service.launch
        issue_labels_by_number = issue_labels_by_number or {}
        repo_labels = await client.list_repo_labels(scope.repo_owner, scope.repo_name)

        pending = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "pending",
                )
            )
        ).scalars().all()

        for item in pending:
            issue_labels = issue_labels_by_number.get(item.issue_number, [])
            owner_slot_id, method = await self.route_item(
                db, item, preset_slots, repo_labels, issue_labels, classify=classify
            )
            if owner_slot_id is None:
                item.dispatch_status = "escalated"
                item.escalation_reason = "plan_blocked"
                continue
            if await self.slot_is_busy(db, owner_slot_id):
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_slot_busy"
                continue
            result = await launcher(
                db,
                scope.preset_id,
                AgentTeamLaunchRequest(
                    slot_ids=[owner_slot_id],
                    skip_plan_confirmation=True,
                    repo_path_override=scope.repo_path,
                ),
            )
            item.owner_slot_id = owner_slot_id
            item.routing_method = method
            item.launch_id = getattr(result, "launch_id", None)
            item.dispatch_status = "dispatched"
            item.pending_reason = None
            item.updated_at = datetime.utcnow()
        await db.commit()

    async def record_approval_round(
        self, db: AsyncSession, item: GithubWorkItem, scope: TeamGithubScope
    ) -> None:
        item.approval_round_count += 1
        if item.approval_round_count >= scope.max_approval_rounds:
            item.dispatch_status = "escalated"
            item.escalation_reason = "approval_rounds_exhausted"
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
        leader_wake = wake_state_by_slot.get(leader.id, "offline")

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
                item.dispatch_status = "escalated"
                item.escalation_reason = "leader_offline"
                item.updated_at = datetime.utcnow()
            # Leader reachable but idle nudge/escalation is intentionally deferred;
            # it needs agent-mail last-activity plumbing beyond Phase A's backend core.
        await db.commit()


github_dispatch_service = GithubDispatchService()
