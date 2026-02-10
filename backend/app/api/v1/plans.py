"""Plan history browser API endpoints."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.services.plan_service import PlanService
from app.models.schemas import (
    PlanDetailResponse,
    PlanListResponse,
    PlanSearchResponse,
    PlanStatsResponse,
)

router = APIRouter()


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    project_path: Optional[str] = Query(None, description="Active project path for settings resolution"),
):
    """List all plan files sorted by modification time (newest first)."""
    try:
        plans_dir = PlanService.resolve_plans_dir(project_path)
        plans = PlanService.list_plans(plans_dir)
        return {"plans": plans, "total": len(plans)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list plans: {str(e)}")


@router.get("/plans/stats", response_model=PlanStatsResponse)
async def get_plan_stats(
    project_path: Optional[str] = Query(None, description="Active project path"),
):
    """Get plan statistics for dashboard."""
    try:
        plans_dir = PlanService.resolve_plans_dir(project_path)
        return PlanService.get_plan_stats(plans_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get plan stats: {str(e)}")


@router.get("/plans/search", response_model=PlanSearchResponse)
async def search_plans(
    q: str = Query(..., min_length=1, description="Search query"),
    project_path: Optional[str] = Query(None, description="Active project path"),
):
    """Search plans by title and content."""
    try:
        plans_dir = PlanService.resolve_plans_dir(project_path)
        results = PlanService.search_plans(plans_dir, q)
        return {"results": results, "query": q, "total": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search plans: {str(e)}")


@router.get("/plans/{filename}", response_model=PlanDetailResponse)
async def get_plan_detail(
    filename: str,
    project_path: Optional[str] = Query(None, description="Active project path"),
):
    """Get full plan detail with linked sessions."""
    try:
        plans_dir = PlanService.resolve_plans_dir(project_path)
        plan_data = PlanService.get_plan(plans_dir, filename)

        if not plan_data:
            raise HTTPException(status_code=404, detail="Plan not found")

        linked_sessions = PlanService.get_plan_sessions(plan_data["slug"])
        plan_data["linked_sessions"] = linked_sessions
        return {"plan": plan_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get plan: {str(e)}")
