"""Shared display facts. Never use this projection for delivery or authority."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.database import AgentTeamSlot, MailAgentSession, MailTeamMember
from app.models.schemas import AgentStatus


def utc_now():
    return datetime.now(timezone.utc)


def unknown_status(now=None):
    now = now or utc_now()
    return AgentStatus(checked_at=now, valid_until=now + timedelta(seconds=15))


class AgentStatusService:
    async def for_members(self, db, members, *, activities=None):
        # Import at the call boundary. Mail and native reads also use this service.
        from app.services.agent_mail_service import MailWakeError, agent_mail_service
        from app.services.agent_activity_service import observe_team

        now = utc_now()
        if not members:
            return {}
        ids = [member.id for member in members]
        sessions = list((await db.scalars(select(MailAgentSession).where(
            MailAgentSession.member_id.in_(ids)).execution_options(populate_existing=True))).all())
        slots = {slot.id: slot for slot in (await db.scalars(select(AgentTeamSlot).where(
            AgentTeamSlot.id.in_([m.team_slot_id for m in members if m.team_slot_id])))).all()}
        native = dict(activities or {})
        if activities is None:
            for team_id in sorted({m.team_preset_id for m in members if m.team_preset_id}):
                try:
                    observed = await observe_team(db, team_id, include_agent_status=False,
                                                  persist_identities=False)
                except (OSError, ValueError):
                    continue
                native.update({entry.slot_id: entry for entry in observed.slots})
        # Native reads can await. Reload session facts before the final projection.
        sessions = list((await db.scalars(select(MailAgentSession).where(
            MailAgentSession.member_id.in_(ids)).execution_options(populate_existing=True))).all())
        result = {}
        for member in members:
            status = unknown_status(now)
            slot = slots.get(member.team_slot_id)
            selected = []
            for session in sessions:
                if session.member_id != member.id:
                    continue
                if member.participant_kind == "team_slot":
                    if (slot is None or slot.preset_id != member.team_preset_id
                            or session.team_slot_id != member.team_slot_id
                            or session.team_preset_id != member.team_preset_id
                            or session.provider != slot.provider):
                        continue
                elif session.team_slot_id is not None or session.team_preset_id is not None:
                    continue
                selected.append(session)
            effective = {agent_mail_service._effective_status(s, now.replace(tzinfo=None))
                         for s in selected}
            status.session_state = "online" if effective & {"connected", "observed"} else "offline"
            observed = native.get(member.team_slot_id) if slot is not None else None
            if observed is not None:
                status.activity_state = observed.state
                status.activity_reason = observed.reason
                if observed.state == "idle" and observed.observed_at is not None:
                    stamp = observed.observed_at
                    stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
                    if stamp <= now:
                        status.idle_since = stamp
            try:
                await agent_mail_service._nudge_session_for_member(db, member.id, now.replace(tzinfo=None))
            except MailWakeError as error:
                status.wake_state = "cannot_wake"
                status.wake_reason = error.code if error.code in {
                    "wake_target_unbound", "wake_target_stale", "wake_target_ambiguous", "wake_opted_out"
                } else "observation_unavailable"
            else:
                status.wake_state = "can_wake"
                status.wake_reason = None
            result[member.id] = status
        return result

    async def for_team(self, db, preset_id, *, activities=None):
        members = list((await db.scalars(select(MailTeamMember).where(
            MailTeamMember.team_preset_id == preset_id,
            MailTeamMember.participant_kind == "team_slot",
        ).execution_options(populate_existing=True))).all())
        statuses = await self.for_members(db, members, activities=activities)
        grouped = {}
        for member in members:
            grouped.setdefault(member.team_slot_id, []).append(statuses[member.id])
        return {slot_id: values[0] if len(values) == 1 else unknown_status()
                for slot_id, values in grouped.items()}


agent_status_service = AgentStatusService()
