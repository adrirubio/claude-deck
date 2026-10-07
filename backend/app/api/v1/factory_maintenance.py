"""Recorded maintenance recovery requires operator authentication."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_operator
from app.database import get_db
from app.models.database import GithubOwnerObservationPause, GithubWorkItem, TeamGithubScope
from app.services.owner_observation_pause import resume_observation_pause

router = APIRouter()


class ObservationResume(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    pause_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=240)


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
