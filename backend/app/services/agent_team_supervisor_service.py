"""Observe optional supervision. A promise grants no execution authority."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.models.api_model import utc_datetime
from app.models.database import AgentTeamPreset, MailExternalActor
from app.services import factory_audit_service as audit
from app.services.factory_audit_service import sanitize_text

MINIMUM_GRACE_SECONDS = 30 * 60
MAX_PROMISE_SECONDS = 24 * 60 * 60
MAX_NOTE_LENGTH = 200


def clean_note(note: str | None) -> str | None:
    """Remove control characters and redact credential-shaped text."""
    if note is None:
        return None
    printable = "".join(character if character.isprintable() else " " for character in note)
    return sanitize_text(" ".join(printable.split()), limit=MAX_NOTE_LENGTH) or None


def validate_promise(next_check_at: datetime, *, now: datetime) -> datetime:
    """Accept a future promise of at most 24 hours."""
    promise, current = utc_datetime(next_check_at), utc_datetime(now)
    if not current < promise <= current + timedelta(seconds=MAX_PROMISE_SECONDS):
        raise ValueError("supervisor_next_check_invalid")
    return promise


def supervisor_address(actor) -> dict | None:
    """Return a public Mail address without actor credentials."""
    if actor is None:
        return None
    return {"actor_id": actor.id, "address": f"external_actor:{actor.id}",
            "display_name": clean_note(actor.display_name)}


def supervisor_observation(team, *, now: datetime | None = None, actor=None) -> dict:
    """Derive health from the controller clock and the stored promise."""
    current = utc_datetime(now or datetime.now(timezone.utc))
    actor_id = team.supervisor_actor_id
    if actor is not None and actor.id != actor_id:
        actor = None
    checked = team.supervisor_checked_at if actor_id is not None else None
    promised = team.supervisor_next_check_at if actor_id is not None else None
    checked = utc_datetime(checked) if checked is not None else None
    promised = utc_datetime(promised) if promised is not None else None
    interval = max(0, (promised - checked).total_seconds()) if checked and promised else 0
    override = team.supervisor_grace_seconds
    grace = override if override is not None else max(MINIMUM_GRACE_SECONDS, int(2 * interval))
    if actor_id is None:
        status = "none"
    elif checked is None or promised is None:
        status = "absent"
    elif current < promised:
        status = "healthy"
    elif current < promised + timedelta(seconds=grace):
        status = "late"
    else:
        status = "absent"
    return {"status": status, "actor_id": actor_id,
            "address": supervisor_address(actor), "checked_at": checked, "next_check_at": promised,
            "grace_seconds": grace, "note": clean_note(team.supervisor_note) if actor_id is not None else None,
            "attention": "Supervisor check-in overdue" if status in {"late", "absent"} else None}


def _current_binding(team):
    """Protect observations and promises against a concurrent binding change."""
    return (AgentTeamPreset.id == team.id,
            AgentTeamPreset.supervisor_actor_id == team.supervisor_actor_id,
            AgentTeamPreset.supervisor_checked_at == team.supervisor_checked_at,
            AgentTeamPreset.supervisor_next_check_at == team.supervisor_next_check_at,
            AgentTeamPreset.supervisor_grace_seconds == team.supervisor_grace_seconds,
            AgentTeamPreset.supervisor_observed_status == team.supervisor_observed_status)


async def _team(db, preset_id):
    return await db.scalar(select(AgentTeamPreset).where(AgentTeamPreset.id == preset_id)
                           .execution_options(populate_existing=True))


async def _commit_event(db, **event):
    """Keep the supervisor mutation and its audit event in one transaction."""
    try:
        await audit.record_event(db, **event)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def observe_supervisor(db, preset_id: int, *, now: datetime | None = None) -> dict | None:
    """Record each observed clock transition once. Do not wake or run an agent."""
    current = utc_datetime(now or datetime.now(timezone.utc))
    team = await _team(db, preset_id)
    if team is None:
        return None
    actor = await db.get(MailExternalActor, team.supervisor_actor_id) if team.supervisor_actor_id else None
    observation = supervisor_observation(team, now=current, actor=actor)
    old_status, new_status = team.supervisor_observed_status, observation["status"]
    if old_status == new_status or (old_status is None and new_status == "none"):
        return observation
    result = await db.execute(update(AgentTeamPreset).where(*_current_binding(team))
        .values(supervisor_observed_status=new_status).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise ValueError("supervisor_binding_changed")
    await _commit_event(db, event_kind="policy_change", source="agent_team_supervisor.clock",
        occurred_at=current, actor=audit.derive_actor(actor_kind="system"), team_preset_id=preset_id,
        before_values={"supervisor_status": old_status}, after_values={"supervisor_status": new_status},
        sanitized_reason="supervisor_status_changed")
    return observation


async def bind_supervisor(db, preset_id: int, *, actor_id: int | None,
                          grace_seconds: int | None, set_grace: bool, now: datetime | None = None) -> dict:
    """Register an operator-selected actor without changing team permissions."""
    current = utc_datetime(now or datetime.now(timezone.utc))
    team = await _team(db, preset_id)
    if team is None:
        raise ValueError("supervisor_team_missing")
    actor = await db.get(MailExternalActor, actor_id) if actor_id is not None else None
    if actor_id is not None and actor is None:
        raise ValueError("supervisor_actor_missing")
    old_actor, old_grace = team.supervisor_actor_id, team.supervisor_grace_seconds
    values = {"supervisor_actor_id": actor_id, "updated_at": current.replace(tzinfo=None)}
    if actor_id != old_actor:
        values.update(supervisor_checked_at=None, supervisor_next_check_at=None, supervisor_note=None,
                      supervisor_observed_status="absent" if actor_id is not None else "none")
    if set_grace or actor_id is None:
        values["supervisor_grace_seconds"] = grace_seconds if actor_id is not None else None
    result = await db.execute(update(AgentTeamPreset).where(*_current_binding(team))
        .values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise ValueError("supervisor_binding_changed")
    await _commit_event(db, event_kind="policy_change", source="agent_team_supervisor.registration",
        occurred_at=current, actor=audit.derive_actor(actor_kind="operator"), team_preset_id=preset_id,
        before_values={"supervisor_actor_id": old_actor, "supervisor_grace_seconds": old_grace},
        after_values={"supervisor_actor_id": actor_id,
                      "supervisor_grace_seconds": values.get("supervisor_grace_seconds", old_grace)},
        sanitized_reason="supervisor_registered" if actor_id is not None else "supervisor_removed")
    observation = await observe_supervisor(db, preset_id, now=current)
    return observation


async def supervisor_checkin(db, actor, preset_id: int, next_check_at: datetime,
                             note: str | None = None, *, now: datetime | None = None) -> dict:
    """Accept a promise only from the currently bound external actor."""
    current = utc_datetime(now or datetime.now(timezone.utc))
    promise = validate_promise(next_check_at, now=current)
    team = await _team(db, preset_id)
    if team is None or team.supervisor_actor_id != actor.id:
        raise PermissionError("supervisor_actor_not_bound")
    await observe_supervisor(db, preset_id, now=current)
    team = await _team(db, preset_id)
    if team is None or team.supervisor_actor_id != actor.id:
        raise PermissionError("supervisor_actor_not_bound")
    previous_status = team.supervisor_observed_status
    result = await db.execute(update(AgentTeamPreset).where(*_current_binding(team))
        .values(supervisor_checked_at=current.replace(tzinfo=None),
                supervisor_next_check_at=promise.replace(tzinfo=None), supervisor_note=clean_note(note),
                supervisor_observed_status="healthy").execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise PermissionError("supervisor_actor_not_bound")
    if previous_status != "healthy":
        await _commit_event(db, event_kind="policy_change", source="agent_team_supervisor.clock",
            occurred_at=current, actor=audit.derive_actor(actor_kind="system"), team_preset_id=preset_id,
            before_values={"supervisor_status": previous_status}, after_values={"supervisor_status": "healthy"},
            sanitized_reason="supervisor_status_changed")
    else:
        await db.commit()
    team = await _team(db, preset_id)
    return supervisor_observation(team, now=current, actor=actor)
