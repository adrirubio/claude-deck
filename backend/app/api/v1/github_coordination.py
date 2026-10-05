"""Operator configuration, safe observation, and current-Leader assessments."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Response
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_mail_session, require_mail_session_or_operator, require_operator
from app.database import get_db
from app.models.coordination import CoordinationAssessment, CoordinationPolicy, OperatorActionContextPreparation
from app.models.database import MailAgentSession
from app.services.github_coordination_service import CoordinationError, github_coordination_service as service
from app.services.github_operator_attention_service import github_operator_attention_service

router = APIRouter()


def conflict(error: CoordinationError):
    return HTTPException(status_code=error.status, detail=error.code)


@router.get("/presets/{preset_id}/human-actions")
async def human_actions(preset_id: int, response: Response, include_templates: bool = False,
                        db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await asyncio.wait_for(github_operator_attention_service.summary(
            db, preset_id, include_templates=include_templates), timeout=9)
    except CoordinationError as error:
        raise conflict(error) from error
    except TimeoutError:
        raise HTTPException(status_code=409, detail="human_action_observations_unavailable") from None


@router.post("/github-scopes/{scope_id}/operator-action-contexts/prepare")
async def prepare_operator_action_contexts(
    scope_id: int, request: OperatorActionContextPreparation, response: Response,
    principal: MailAgentSession = Depends(require_mail_session), db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await asyncio.wait_for(service.prepare_operator_contexts(
            db, scope_id, principal, request.entries), timeout=9)
    except CoordinationError as error:
        raise conflict(error) from error
    except (TimeoutError, OSError, httpx.HTTPError):
        raise HTTPException(status_code=409, detail="human_action_context_unavailable") from None


@router.get("/github-scopes/{scope_id}/coordination")
async def coordination_summary(scope_id: int, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await service.summary(db, scope_id)
    except CoordinationError as error:
        raise conflict(error) from error


@router.put("/github-scopes/{scope_id}/coordination-policy", dependencies=[Depends(require_operator)])
async def coordination_policy(scope_id: int, request: CoordinationPolicy, db: AsyncSession = Depends(get_db)):
    try:
        await service.configure(db, scope_id, request)
        return await service.summary(db, scope_id)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="coordination_policy_changed")
    except CoordinationError as error:
        raise conflict(error) from error


@router.get("/github-scopes/{scope_id}/coordination-request")
async def coordination_request(
    scope_id: int, response: Response,
    principal: MailAgentSession | None = Depends(require_mail_session_or_operator),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        if principal is not None:
            await service.require_leader(db, scope_id, principal)
        return await service.request(db, scope_id, principal=principal)
    except CoordinationError as error:
        raise conflict(error) from error


@router.post("/github-scopes/{scope_id}/coordination-assessments")
async def coordination_assessment(
    scope_id: int, request: CoordinationAssessment,
    principal: MailAgentSession = Depends(require_mail_session),
    db: AsyncSession = Depends(get_db),
):
    try:
        await service.assess(db, scope_id, principal, request)
        return await service.summary(db, scope_id)
    except CoordinationError as error:
        raise conflict(error) from error
    except (TimeoutError, OSError, httpx.HTTPError):
        raise HTTPException(status_code=409, detail="backlog_unavailable")
