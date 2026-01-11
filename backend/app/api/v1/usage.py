"""Usage tracking API endpoints."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.usage_service import UsageService
from app.models.schemas import (
    UsageSummaryResponse,
    DailyUsageListResponse,
    SessionUsageListResponse,
    MonthlyUsageListResponse,
    BlockUsageListResponse,
)

router = APIRouter(prefix="/usage")


@router.get("/summary", response_model=UsageSummaryResponse)
async def get_usage_summary(
    project_path: Optional[str] = Query(None, description="Filter by project path"),
    db: AsyncSession = Depends(get_db),
):
    """Get overall usage statistics."""
    try:
        service = UsageService(db)
        return await service.get_usage_summary(project_path)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get usage summary: {str(e)}"
        )


@router.get("/daily", response_model=DailyUsageListResponse)
async def get_daily_usage(
    project_path: Optional[str] = Query(None, description="Filter by project path"),
    start_date: Optional[str] = Query(
        None, description="Start date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    end_date: Optional[str] = Query(
        None, description="End date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Get daily usage breakdown."""
    try:
        service = UsageService(db)
        return await service.get_daily_usage(project_path, start_date, end_date)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get daily usage: {str(e)}"
        )


@router.get("/sessions", response_model=SessionUsageListResponse)
async def get_session_usage(
    project_path: Optional[str] = Query(None, description="Filter by project path"),
    limit: int = Query(50, ge=1, le=500, description="Max sessions to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get session-based usage breakdown."""
    try:
        service = UsageService(db)
        return await service.get_session_usage(project_path, limit)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get session usage: {str(e)}"
        )


@router.get("/monthly", response_model=MonthlyUsageListResponse)
async def get_monthly_usage(
    project_path: Optional[str] = Query(None, description="Filter by project path"),
    start_month: Optional[str] = Query(
        None, description="Start month (YYYY-MM)", pattern=r"^\d{4}-\d{2}$"
    ),
    end_month: Optional[str] = Query(
        None, description="End month (YYYY-MM)", pattern=r"^\d{4}-\d{2}$"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Get monthly usage breakdown."""
    try:
        service = UsageService(db)
        return await service.get_monthly_usage(project_path, start_month, end_month)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get monthly usage: {str(e)}"
        )


@router.get("/blocks", response_model=BlockUsageListResponse)
async def get_block_usage(
    project_path: Optional[str] = Query(None, description="Filter by project path"),
    recent: bool = Query(True, description="Only recent blocks (last 3 days) + active"),
    active: bool = Query(False, description="Only active blocks"),
    db: AsyncSession = Depends(get_db),
):
    """Get 5-hour billing block usage."""
    try:
        service = UsageService(db)
        return await service.get_block_usage(project_path, recent, active)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get block usage: {str(e)}"
        )


@router.post("/cache/invalidate")
async def invalidate_cache(
    cache_type: Optional[str] = Query(
        None, description="Cache type to invalidate (daily, session, monthly, block, summary)"
    ),
    project_path: Optional[str] = Query(None, description="Filter by project path"),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate usage cache."""
    try:
        service = UsageService(db)
        await service.invalidate_cache(cache_type, project_path)
        return {"status": "ok", "message": "Cache invalidated"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to invalidate cache: {str(e)}"
        )
