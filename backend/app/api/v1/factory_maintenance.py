"""Recorded maintenance recovery requires operator authentication."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_operator
from app.database import get_db
from app.models.database import GithubMaintenanceEvent, GithubOwnerObservationPause, GithubWorkItem, TeamGithubScope
from app.services.owner_observation_pause import resume_observation_pause
from app.services.maintenance_operations import digest
from typing import Literal

router = APIRouter()


class ObservationResume(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    pause_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=240)


class IntegrationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    expected_dispatch_nonce: str = Field(min_length=1, max_length=200)
    expected_scope_revision: int = Field(ge=0)
    expected_owner_slot: int = Field(gt=0)
    outcome: Literal["completed", "needs_coordination"]


async def context(db, preset_id, item_id):
    item = await db.get(GithubWorkItem, item_id)
    scope = await db.get(TeamGithubScope, item.scope_id) if item is not None else None
    if scope is None or scope.preset_id != preset_id:
        raise HTTPException(status_code=404, detail="Work item not found")
    return item, scope


@router.get("/presets/{preset_id}/work-items/{item_id}/observation-pauses")
async def observation_pauses(preset_id: int, item_id: int, response: Response,
                             _operator=Depends(require_operator), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    item, _scope = await context(db, preset_id, item_id)
    records = (await db.scalars(select(GithubOwnerObservationPause).where(
        GithubOwnerObservationPause.work_item_id == item.id).order_by(GithubOwnerObservationPause.id.desc()).limit(20))).all()
    return {"work_item_id": item.id, "dispatch_status": item.dispatch_status,
            "pauses": [{"pause_id": row.id, "status": row.status, "wait_deadline": row.deadline,
                        "paused_at": row.paused_at, "resume_deadline": row.resume_deadline,
                        "resumed_at": row.resumed_at, "notice_status": row.notice_status} for row in records],
            "action": "Inspect the current owner and authority. Resume only the unchanged recorded observation pause.",
            "completion": "The resume operation returns resumed. The owner then reports actual progress within the existing nudge grace.",
            "limits": "No restart, new scope, ACK, retry, budget reset, merge or milestone acceptance."}


@router.post("/presets/{preset_id}/work-items/{item_id}/resume-observation")
async def resume_observation(preset_id: int, item_id: int, request: ObservationResume, response: Response,
                             _operator=Depends(require_operator), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    item, scope = await context(db, preset_id, item_id)
    try:
        return await resume_observation_pause(db, item, scope, request.pause_id, request.reason)
    except ValueError as error:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from None
    except (IntegrityError, OperationalError):
        await db.rollback()
        raise HTTPException(status_code=409, detail="observation_resume_context_changed") from None


@router.post("/presets/{preset_id}/work-items/{item_id}/integration-outcome")
async def integration_outcome(preset_id: int, item_id: int, request: IntegrationOutcome, response: Response,
                             _operator=Depends(require_operator), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    item, _scope = await context(db,preset_id,item_id)
    identity=digest(request.model_dump())
    old=await db.scalar(select(GithubMaintenanceEvent).where(GithubMaintenanceEvent.operation_id==request.operation_id))
    if old:
        if old.work_item_id!=item_id or old.request_sha256!=identity:
            raise HTTPException(status_code=409,detail="maintenance_replay_conflict")
        return {"status":"already_recorded","outcome":old.outcome}
    try:
        values={"updated_at":GithubWorkItem.updated_at}
        if request.outcome=="needs_coordination":
            values.update(dispatch_status="escalated",escalation_reason="integration_update_conflict",
                status_note="The accepted integration update needs coordination. Preserve the owner, commits, conflicts, approval and finite budgets.")
        claimed=await db.execute(update(GithubWorkItem).where(
            GithubWorkItem.id==item_id,GithubWorkItem.dispatch_status=="dispatched",
            GithubWorkItem.dispatch_nonce==request.expected_dispatch_nonce,
            GithubWorkItem.active_scope_revision==request.expected_scope_revision,
            GithubWorkItem.owner_slot_id==request.expected_owner_slot,
        ).values(**values).execution_options(synchronize_session=False))
        if claimed.rowcount!=1:
            await db.rollback()
            raise HTTPException(status_code=409,detail="maintenance_context_changed")
        db.add(GithubMaintenanceEvent(operation_id=request.operation_id,work_item_id=item_id,
                                     outcome=request.outcome,request_sha256=identity))
        await db.commit()
        return {"status":"recorded","outcome":request.outcome}
    except (IntegrityError,OperationalError):
        await db.rollback()
        raise HTTPException(status_code=409,detail="maintenance_context_changed") from None
