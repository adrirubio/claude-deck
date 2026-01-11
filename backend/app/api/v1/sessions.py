"""Session transcript API endpoints."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.session_service import SessionService
from app.models.schemas import (
    SessionListResponse,
    SessionProjectListResponse,
    SessionDetailResponse,
    SessionStatsResponse,
)

router = APIRouter()


@router.get("/sessions/projects", response_model=SessionProjectListResponse)
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects with session counts."""
    try:
        service = SessionService(db)
        return await service.list_projects()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list projects: {str(e)}")


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    project_folder: Optional[str] = Query(None, description="Filter by project"),
    limit: int = Query(50, ge=1, le=100, description="Max sessions to return"),
    sort_by: str = Query("date", pattern="^(date|size)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    """List session summaries."""
    try:
        service = SessionService(db)
        return await service.list_sessions(project_folder, limit, sort_by, sort_order)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {str(e)}")


@router.get("/sessions/dashboard/stats", response_model=SessionStatsResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Get session statistics for dashboard."""
    try:
        service = SessionService(db)
        return await service.get_dashboard_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/sessions/{project_folder}/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    project_folder: str,
    session_id: str,
    page: int = Query(1, ge=1, description="Page number (5 prompts per page)"),
    db: AsyncSession = Depends(get_db),
):
    """Get full session detail with pagination."""
    try:
        service = SessionService(db)
        return await service.get_session_detail(session_id, project_folder, page)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session: {str(e)}")
