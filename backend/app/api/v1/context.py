"""Context window analysis API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import ActiveSessionsResponse, ContextAnalysisResponse
from app.services.context_service import ContextService

router = APIRouter(prefix="/context", tags=["Context"])


@router.get("/active", response_model=ActiveSessionsResponse)
async def get_active_sessions():
    """Get context info for all recently active sessions."""
    service = ContextService()
    return await service.get_active_sessions()


@router.get("/{project_folder}/{session_id}", response_model=ContextAnalysisResponse)
async def get_session_context(
    project_folder: str, session_id: str, db: AsyncSession = Depends(get_db)
):
    """Get full context analysis for a session."""
    service = ContextService()
    try:
        return await service.analyze_session(project_folder, session_id, db=db)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
