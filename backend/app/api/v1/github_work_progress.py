"""Safe work observations. These reads grant no execution or recovery authority."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_mail_session
from app.database import get_db
from app.models.database import GithubWorkItem, MailAgentSession
from app.models.github_work_progress_schemas import GithubWorkProgressResponse
from app.services.github_coordination_service import CoordinationError, github_coordination_service
from app.services.github_work_progress_service import github_work_progress_service

router = APIRouter()


@router.get("/github-work-items/{item_id}/progress", response_model=GithubWorkProgressResponse)
async def work_progress(item_id: int, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        result = await asyncio.wait_for(github_work_progress_service.summary(db, item_id), timeout=9)
    except TimeoutError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="progress_observation_unavailable") from None
    if result is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    return result


@router.get("/github-work-items/{item_id}/remaining-work-context", response_model=GithubWorkProgressResponse)
async def remaining_work_context(item_id: int, response: Response,
                                principal: MailAgentSession = Depends(require_mail_session),
                                db: AsyncSession = Depends(get_db)):
    """Only the current team Leader prepares the public, advisory report context."""
    response.headers["Cache-Control"] = "no-store"
    principal_id = principal.id
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    scope_id = item.scope_id
    try:
        await github_coordination_service.require_leader(db, scope_id, principal)
        result = await work_progress(item_id, response, db)
        # Progress observation ends its DB snapshot. Recheck current membership
        # and scope after its asynchronous source reads.
        current = await db.get(MailAgentSession, principal_id, populate_existing=True)
        item = await db.get(GithubWorkItem, item_id, populate_existing=True)
        if current is None or item is None or item.scope_id != scope_id:
            raise HTTPException(status_code=409, detail="progress_context_changed")
        await github_coordination_service.require_leader(db, scope_id, current)
        if (result.dispatch_nonce != item.dispatch_nonce or result.owner_slot_id != item.owner_slot_id
                or result.remaining_work_context is None
                or result.remaining_work_context.scope_revision != item.active_scope_revision):
            raise HTTPException(status_code=409, detail="progress_context_unavailable")
        return result
    except CoordinationError as error:
        raise HTTPException(status_code=error.status, detail=error.code) from error
