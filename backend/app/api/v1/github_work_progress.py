"""Safe work observations. These reads grant no execution or recovery authority."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.github_work_progress_schemas import GithubWorkProgressResponse
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
