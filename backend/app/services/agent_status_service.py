"""Shared display facts. Never use this projection for delivery or authority."""
from __future__ import annotations

import asyncio
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
        from app.services.agent_activity_service import observe_team

        if not members:
            return {}
        ids = [member.id for member in members]
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
        return self._project(members, slots, sessions, native, utc_now())

    async def for_snapshot(self, db, members, slots, sessions, bindings, lifecycles, *, now=None):
        """Reuse the factory read snapshot. Native observations do not save identity."""
        from app.services.agent_activity_service import _inputs_from_rows, _observe

        options = (await db.execute(select(AgentTeamSlot.launch_options).where(
            AgentTeamSlot.provider.in_(["codex-cli", "claude-code"])))).all()
        retired = {identity for identity, retired_at in lifecycles.items() if retired_at is not None}
        bound_rows = [(binding, session) for binding in bindings for session in sessions
                      if session.source == "mcp" and session.closed_at is None
                      and session.mailbox_status == "connected"
                      and session.capability_token_hash is not None
                      and session.bound_pane_pid == binding.pane_pid
                      and session.bound_pane_proc_start == binding.pane_proc_start
                      and session.team_slot_id == binding.slot_id
                      and session.team_preset_id == binding.preset_id
                      and (binding.pane_pid, binding.pane_proc_start) not in retired]
        inputs = _inputs_from_rows(slots, options, members, bound_rows)
        now = now or utc_now()
        observations = await asyncio.to_thread(lambda: [_observe(*entry, now) for entry in inputs])
        return self._project(members, {slot.id: slot for slot in slots}, sessions,
                             {entry.slot_id: entry for entry in observations}, now)

    def _project(self, members, slots, sessions, native, now):
        from app.services.agent_mail_service import (
            MCP_HEARTBEAT_TTL_SECONDS, TMUX_WAKE_PROVIDERS, MailWakeError, agent_mail_service,
        )

        naive_now = now.replace(tzinfo=None)
        member_counts = {}
        for member in members:
            if member.team_slot_id is not None:
                member_counts[member.team_slot_id] = member_counts.get(member.team_slot_id, 0) + 1
        result = {}
        for member in members:
            status = unknown_status(now)
            if member_counts.get(member.team_slot_id, 0) > 1:
                result[member.id] = status
                continue
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
            effective = {agent_mail_service._effective_status(s, naive_now)
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
                # Keep the exact query filters used by the delivery resolver.
                observed_sessions = [s for s in sessions if s.member_id == member.id
                                     and s.source == "observed" and s.provider in TMUX_WAKE_PROVIDERS
                                     and s.tmux_target is not None]
                registered = [s for s in sessions if s.member_id == member.id and s.source == "mcp"
                              and s.mailbox_status == "connected" and s.closed_at is None
                              and s.capability_token_hash is not None
                              and s.last_seen_at >= naive_now - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS)
                              and s.bound_pane_pid is not None and s.bound_pane_proc_start is not None]
                agent_mail_service._nudge_from_sessions(observed_sessions, registered, member, naive_now)
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
