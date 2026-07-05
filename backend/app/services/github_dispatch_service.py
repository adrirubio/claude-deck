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
        item.pr_number = None
        item.last_verified_sha = None
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
        issue_details_by_number: dict[int, dict] | None = None,
    ) -> None:
        launcher = launcher or agent_team_service.launch
        issue_labels_by_number = issue_labels_by_number or {}
        issue_details_by_number = issue_details_by_number or {}
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
                leader = self._leader_slot(preset_slots)
                leader_member = (
                    await self._slot_member(db, leader.id) if leader is not None else None
                )
                brief = self._dispatch_brief(
                    item,
                    scope,
                    owner_slot_id=owner_slot_id,
                    preset_slots=preset_slots,
                    leader_member=leader_member,
                    issue_details=issue_details_by_number.get(item.issue_number),
                )
                await self._send_dispatch_brief_to_slot(
                    db,
                    item,
                    preset_slots=preset_slots,
                    owner_slot_id=owner_slot_id,
                    brief=brief,
                )
                result = await launcher(
                    db,
                    scope.preset_id,
                    AgentTeamLaunchRequest(
                        slot_ids=[owner_slot_id],
                        reuse_existing=False,
                        skip_plan_confirmation=True,
                        repo_path_override=scope.repo_path,
                        slot_prompt_overrides={owner_slot_id: brief},
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

    def _dispatch_brief(
        self,
        item: GithubWorkItem,
        scope: TeamGithubScope,
        *,
        owner_slot_id: int,
        preset_slots: list[AgentTeamSlot],
        leader_member: MailTeamMember | None = None,
        issue_details: dict | None = None,
    ) -> str:
        leader = self._leader_slot(preset_slots)
        owner = next((slot for slot in preset_slots if slot.id == owner_slot_id), None)
        issue_body = (issue_details or {}).get("body") or ""
        labels = [
            label["name"]
            for label in (issue_details or {}).get("labels", [])
            if isinstance(label, dict) and "name" in label
        ]
        body = issue_body.strip() or "(No issue body provided.)"
        if len(body) > 12000:
            body = f"{body[:12000]}\n\n[Issue body truncated by Claude Deck.]"

        lines = [
            "You are handling an autonomous GitHub dispatch from Claude Deck.",
            "",
            f"- Work item ID: {item.id}",
            f"- Repo: {scope.repo_owner}/{scope.repo_name}",
            f"- Local checkout: {scope.repo_path}",
            f"- Issue: #{item.issue_number} — {item.issue_title}",
            f"- Issue URL: {item.issue_url}",
            f"- Pipeline: {item.issue_type}",
            f"- Owner slot: {owner.display_name if owner else owner_slot_id}",
        ]
        if leader is not None:
            if leader_member is not None:
                lines.append(
                    "- Team leader / approver: "
                    f"{leader.display_name} (Agent Mail member_id={leader_member.id})"
                )
            else:
                lines.append(f"- Team leader / approver: {leader.display_name}")
                lines.append(
                    "- Leader Agent Mail member id is not registered yet; call "
                    "`deck_list_team` and select the connected team member whose "
                    f"team slot/name is `{leader.display_name}` before requesting acknowledgment."
                )
        if labels:
            lines.append(f"- Labels: {', '.join(labels)}")
        lines.extend(
            [
                "",
                "Issue body:",
                body,
                "",
                "Required status reporting:",
                f"- When triaging, call `deck_report_dispatch_status(work_item_id={item.id}, status=\"triaging\", note=\"...\")`.",
                f"- When you open a PR, call `deck_report_dispatch_status(work_item_id={item.id}, status=\"pr_opened\", pr_number=<PR number>)`.",
                f"- If blocked, call `deck_report_dispatch_status(work_item_id={item.id}, status=\"blocked\", note=\"...\")`.",
            ]
        )
        if item.issue_type == "design":
            lines.extend(
                [
                    "",
                    "Design pipeline instructions:",
                    "- Treat this as a design/documentation task.",
                    "- Prepare a human-reviewed PR; do not rely on CI or auto-merge.",
                    self._leader_ack_instruction(leader, leader_member, before="opening the PR"),
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "Code pipeline instructions:",
                    "- Triage this issue and prepare a short implementation plan.",
                    self._leader_ack_instruction(
                        leader,
                        leader_member,
                        before="starting implementation",
                    ),
                    "- Use `deck_request_context` when you need an explicit answer from the leader/approver.",
                    "- Keep the change inside the issue scope, run the issue's requested local verification commands, then open a draft PR.",
                    "- After opening the draft PR, report `pr_opened` with the PR number and wait for CI verification.",
                ]
            )
        return "\n".join(lines)

    def _leader_slot(self, preset_slots: list[AgentTeamSlot]) -> AgentTeamSlot | None:
        enabled = sorted(
            [slot for slot in preset_slots if slot.enabled],
            key=lambda slot: slot.position,
        )
        return enabled[0] if enabled else None

    def _leader_ack_instruction(
        self,
        leader: AgentTeamSlot | None,
        leader_member: MailTeamMember | None,
        *,
        before: str,
    ) -> str:
        if leader_member is not None:
            return (
                "- Send the team leader a short plan via Agent Mail using "
                f"`deck_request_context(to_member_id={leader_member.id}, ...)` "
                "or "
                f"`deck_send_message(to_member_id={leader_member.id}, ...)`, "
                f"then wait for acknowledgment before {before}."
            )
        if leader is not None:
            return (
                "- Send the team leader a short plan via Agent Mail and wait for "
                f"acknowledgment before {before}; first call `deck_list_team` to "
                f"resolve the Agent Mail member id for `{leader.display_name}`."
            )
        return (
            "- Send the team leader a short plan via Agent Mail and wait for "
            f"acknowledgment before {before}; if no leader is registered, report blocked."
        )

    async def _send_dispatch_brief_to_slot(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        preset_slots: list[AgentTeamSlot],
        owner_slot_id: int,
        brief: str,
    ) -> None:
        owner_slot = next((slot for slot in preset_slots if slot.id == owner_slot_id), None)
        if owner_slot is None:
            return
        try:
            from app.services.agent_mail_service import agent_mail_service

            member = await agent_mail_service.get_or_create_slot_member(db, owner_slot)
            await agent_mail_service.send_direct_message(
                db,
                recipient_member_id=member.id,
                subject=f"Autonomous dispatch: issue #{item.issue_number}",
                body_markdown=brief,
                payload={
                    "kind": "github_dispatch_assignment",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                    "scope_id": item.scope_id,
                },
            )
        except Exception:
            logger.exception("Failed to send autonomous dispatch brief for item %s", item.id)

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
                continue
            owner_wake = (
                wake_state_by_slot.get(item.owner_slot_id)
                if item.owner_slot_id is not None
                else None
            )
            if owner_wake == "offline":
                await self.escalate(db, item, "owner_offline")
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
        return await self._slot_member(db, item.owner_slot_id)

    async def _slot_member(self, db: AsyncSession, slot_id: int) -> MailTeamMember | None:
        return (
            await db.execute(
                select(MailTeamMember)
                .where(MailTeamMember.team_slot_id == slot_id)
                .order_by(MailTeamMember.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


github_dispatch_service = GithubDispatchService()
