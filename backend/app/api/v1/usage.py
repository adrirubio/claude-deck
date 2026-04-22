"""Usage tracking API endpoints."""
import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
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


_EXPORT_DATASETS = {"summary", "daily", "sessions", "monthly", "blocks"}


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


def _flatten_for_csv(rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """Collapse list fields to joined strings so they survive a CSV round-trip."""
    flat: list[dict[str, Any]] = []
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        out: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, list):
                # Nested dicts (model_breakdowns) serialize as JSON; scalars join with |
                if v and isinstance(v[0], dict):
                    out[k] = json.dumps(v, default=str)
                else:
                    out[k] = "|".join(str(x) for x in v)
            elif v is None:
                out[k] = ""
            else:
                out[k] = v
            if k not in seen:
                seen.add(k)
                keys.append(k)
        flat.append(out)
    return keys, flat


async def _collect_export_rows(
    service: UsageService, dataset: str, project_path: Optional[str]
) -> list[dict[str, Any]]:
    """Dispatch to the appropriate service method and return plain dict rows."""
    if dataset == "summary":
        resp = await service.get_usage_summary(project_path)
        # Summary is a single object — wrap as a 1-row list for uniform CSV shape
        return [resp.summary.model_dump()]
    if dataset == "daily":
        resp = await service.get_daily_usage(project_path, None, None)
        return [row.model_dump() for row in resp.data]
    if dataset == "sessions":
        resp = await service.get_session_usage(project_path, 500)
        return [row.model_dump() for row in resp.data]
    if dataset == "monthly":
        resp = await service.get_monthly_usage(project_path, None, None)
        return [row.model_dump() for row in resp.data]
    if dataset == "blocks":
        resp = await service.get_block_usage(project_path, recent=False, active=False)
        return [row.model_dump() for row in resp.data]
    raise HTTPException(status_code=400, detail=f"Unknown dataset: {dataset}")


@router.get("/export")
async def export_usage(
    dataset: str = Query("daily", description="Which dataset to export"),
    format: str = Query("json", description="json or csv"),
    project_path: Optional[str] = Query(None, description="Filter by project path"),
    db: AsyncSession = Depends(get_db),
):
    """Download usage data as JSON or CSV with a descriptive filename."""
    if dataset not in _EXPORT_DATASETS:
        raise HTTPException(
            status_code=400,
            detail=f"dataset must be one of {sorted(_EXPORT_DATASETS)}",
        )
    if format not in {"json", "csv"}:
        raise HTTPException(status_code=400, detail="format must be 'json' or 'csv'")

    try:
        service = UsageService(db)
        rows = await _collect_export_rows(service, dataset, project_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to collect export data: {e}")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"claude-usage-{dataset}-{stamp}.{format}"

    if format == "json":
        body = json.dumps(rows, default=str, indent=2)
        return StreamingResponse(
            iter([body]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV
    buf = io.StringIO()
    if rows:
        keys, flat_rows = _flatten_for_csv(rows)
        writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)
    body_csv = buf.getvalue()
    return StreamingResponse(
        iter([body_csv]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
