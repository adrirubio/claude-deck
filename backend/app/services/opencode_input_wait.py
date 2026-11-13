"""OpenCode 2 open-question detection and Supervisor escalation (#732).

The OpenCode plugin reports one wait per member: ``open`` when its first question or
permission prompt appears and ``clear`` when the last one closes, with the same generation.
Callers establish identity from the kernel (peer chain, OpenCode 2 gate, bound pane); the
payload only supplies the state and the generation, which is validated data, never identity.

The binding keeps a fence: ``opencode_wait_generation`` (G), the highest generation seen, which
survives a clear, and ``opencode_wait_uncertain`` (U), set when the report order cannot be proved.
Every decision is one conditional UPDATE on those columns in the shared database, so concurrent
backend workers race only on the row:

- open(T) with no wait: record it with one fixed notice. If G is unset or T > G, G becomes T and
  U is cleared; otherwise (a replayed, equal or older generation) the wait is real but its order is
  unprovable, so U is set and G is kept.
- open(T) during a wait: T > G takes over G and keeps U; T = G sets U; T < G does nothing.
- clear(T): clears the wait only when G = T and U is unset. G and U are kept.

An uncertain wait is retained, never cleared by a plugin report; nothing here clears it later.
``waiting_input_started_at`` is server time. The notice is the existing four-key "Waiting for
input" notice; it carries no question text or private context.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, MailAgentSession, MailMessage, MailPaneLifecycle,
    MailReceipt, MailTeamMember,
)

PROVIDER = "opencode-cli"
REASON = "question"
_PAST = timedelta(days=7)
_FUTURE = timedelta(days=1)


def generation_time(value: object, now: datetime) -> datetime | None:
    """A plugin generation (epoch milliseconds) as a naive UTC timestamp, or None if invalid."""
    if type(value) is not int or value <= 0:
        return None
    try:
        moment = datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None
    if not now - _PAST <= moment <= now + _FUTURE:
        return None
    return moment


async def _authority(db: AsyncSession, pane_pid: int, pane_proc_start: str):
    """The binding for the kernel-derived pane and the WHERE conditions that recheck its authority."""
    binding = await db.scalar(select(AgentPaneBinding).where(
        AgentPaneBinding.pane_pid == pane_pid, AgentPaneBinding.pane_proc_start == pane_proc_start))
    if binding is None or binding.slot_id is None or binding.preset_id is None:
        return None, []
    slot_id, preset_id = binding.slot_id, binding.preset_id
    newest_member = (select(MailTeamMember.id).where(MailTeamMember.team_preset_id == preset_id,
        MailTeamMember.team_slot_id == slot_id).order_by(MailTeamMember.updated_at.desc(),
        MailTeamMember.id.desc()).limit(1).scalar_subquery())
    authenticated = exists(select(MailAgentSession.id).where(
        MailAgentSession.member_id == newest_member, MailAgentSession.source == "mcp",
        MailAgentSession.closed_at.is_(None), MailAgentSession.mailbox_status == "connected",
        MailAgentSession.capability_token_hash.is_not(None), MailAgentSession.provider == PROVIDER,
        MailAgentSession.team_slot_id == slot_id, MailAgentSession.team_preset_id == preset_id,
        MailAgentSession.bound_pane_pid == pane_pid, MailAgentSession.bound_pane_proc_start == pane_proc_start))
    active_slot = exists(select(AgentTeamSlot.id).where(AgentTeamSlot.id == slot_id,
        AgentTeamSlot.preset_id == preset_id, AgentTeamSlot.provider == PROVIDER, AgentTeamSlot.enabled.is_(True)))
    retired = exists(select(MailPaneLifecycle.pane_pid).where(MailPaneLifecycle.pane_pid == pane_pid,
        MailPaneLifecycle.pane_proc_start == pane_proc_start, MailPaneLifecycle.retired_at.is_not(None)))
    conditions = [AgentPaneBinding.id == binding.id, AgentPaneBinding.slot_id == slot_id,
                  AgentPaneBinding.preset_id == preset_id, AgentPaneBinding.pane_pid == pane_pid,
                  AgentPaneBinding.pane_proc_start == pane_proc_start, authenticated, active_slot, ~retired]
    return binding, conditions


async def _route(db: AsyncSession, preset_id: int):
    """The current Supervisor actor, or the current Leader member when the team has none."""
    team = (await db.execute(select(AgentTeamPreset.supervisor_actor_id, AgentTeamPreset.leader_slot_id)
            .where(AgentTeamPreset.id == preset_id))).one_or_none()
    if team is None:
        return None
    actor_id, leader_slot_id = team
    recipient = None
    if actor_id is None:
        recipient = await db.scalar(select(MailTeamMember.id).join(AgentTeamSlot,
            AgentTeamSlot.id == MailTeamMember.team_slot_id).where(
            MailTeamMember.team_preset_id == preset_id, MailTeamMember.team_slot_id == leader_slot_id,
            AgentTeamSlot.preset_id == preset_id, AgentTeamSlot.enabled.is_(True))
            .order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).limit(1))
        if recipient is None:
            return None
    same_route = exists(select(AgentTeamPreset.id).where(AgentTeamPreset.id == preset_id,
        AgentTeamPreset.supervisor_actor_id.is_(None) if actor_id is None else AgentTeamPreset.supervisor_actor_id == actor_id,
        AgentTeamPreset.leader_slot_id == leader_slot_id if actor_id is None else True))
    extra = [same_route]
    if recipient is not None:
        leader_current = (select(MailTeamMember.id).where(MailTeamMember.team_preset_id == preset_id,
            MailTeamMember.team_slot_id == leader_slot_id).order_by(MailTeamMember.updated_at.desc(),
            MailTeamMember.id.desc()).limit(1).scalar_subquery())
        extra.extend([leader_current == recipient, exists(select(AgentTeamSlot.id).where(
            AgentTeamSlot.id == leader_slot_id, AgentTeamSlot.preset_id == preset_id,
            AgentTeamSlot.enabled.is_(True)))])
    return actor_id, recipient, extra


async def record(db: AsyncSession, *, pane_pid: int, pane_proc_start: str, state: str, generation: object,
                 now: datetime | None = None) -> bool:
    """Apply one plugin report. Returns True when the stored wait changed."""
    now = now or datetime.utcnow()
    if state not in {"open", "clear"} or generation_time(generation, now) is None:
        return False
    binding, conditions = await _authority(db, pane_pid, pane_proc_start)
    if binding is None:
        return False
    fence, uncertain = AgentPaneBinding.opencode_wait_generation, AgentPaneBinding.opencode_wait_uncertain
    if state == "clear":
        result = await db.execute(update(AgentPaneBinding).where(*conditions,
            AgentPaneBinding.waiting_input_reason.is_not(None), fence == generation, uncertain.is_(False))
            .values(waiting_input_reason=None, waiting_input_started_at=None, waiting_input_notice_id=None,
                    waiting_input_observed_at=now).execution_options(synchronize_session=False))
        await db.commit()
        return result.rowcount == 1

    route = await _route(db, binding.preset_id)
    if route is not None:
        actor_id, recipient, extra = route
        provable = or_(fence.is_(None), fence < generation)
        opened = await db.execute(update(AgentPaneBinding).where(*conditions, *extra,
            AgentPaneBinding.waiting_input_reason.is_(None)).values(waiting_input_reason=REASON,
            waiting_input_started_at=now, waiting_input_observed_at=now,
            opencode_wait_generation=case((provable, generation), else_=fence),
            opencode_wait_uncertain=case((provable, False), else_=True))
            .execution_options(synchronize_session=False))
        if opened.rowcount == 1:
            payload = {"notice": "native_input_wait", "slot_id": binding.slot_id, "reason": REASON}
            if actor_id is not None:
                payload["supervisor_actor_id"] = actor_id
            message = MailMessage(kind="message", subject="Waiting for input",
                body_markdown=f"Slot {binding.slot_id} waits for input. Reason: {REASON}.", payload=payload,
                audience_type="team_preset" if actor_id is not None else None,
                audience_id=str(binding.preset_id) if actor_id is not None else None, recipient_member_id=recipient)
            db.add(message)
            await db.flush()
            if recipient is not None:
                db.add(MailReceipt(message_id=message.id, member_id=recipient))
            await db.execute(update(AgentPaneBinding).where(AgentPaneBinding.id == binding.id)
                .values(waiting_input_notice_id=message.id).execution_options(synchronize_session=False))
            await db.commit()
            return True
    # A wait is already recorded: a strictly newer generation takes over G (U is kept); an equal one
    # makes the order unprovable. A legacy wait without G matches neither, so it is left as it is.
    newer = await db.execute(update(AgentPaneBinding).where(*conditions,
        AgentPaneBinding.waiting_input_reason.is_not(None), fence < generation)
        .values(opencode_wait_generation=generation, waiting_input_observed_at=now)
        .execution_options(synchronize_session=False))
    if newer.rowcount == 1:
        await db.commit()
        return True
    collided = await db.execute(update(AgentPaneBinding).where(*conditions,
        AgentPaneBinding.waiting_input_reason.is_not(None), fence == generation, uncertain.is_(False))
        .values(opencode_wait_uncertain=True, waiting_input_observed_at=now)
        .execution_options(synchronize_session=False))
    await db.commit()
    return collided.rowcount == 1
