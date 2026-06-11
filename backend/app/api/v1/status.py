"""System status endpoint for header indicators."""
import asyncio
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.constants import SessionStatus
from app.models.schemas import SystemStatusResponse
from app.services.instance_identity import get_instance_identity
from app.services.presence_service import PresenceService
from app.services.providers import get_provider, get_providers

router = APIRouter()

# Cache CC version for 5 minutes
_version_cache: tuple[Optional[str], float] = (None, 0.0)
_version_lock = asyncio.Lock()
_CACHE_TTL = 300  # seconds


async def _get_claude_code_version() -> Optional[str]:
    global _version_cache
    cached_version, cached_at = _version_cache
    if time.time() - cached_at < _CACHE_TTL:
        return cached_version

    async with _version_lock:
        # Re-check after acquiring lock (another request may have refreshed)
        cached_version, cached_at = _version_cache
        if time.time() - cached_at < _CACHE_TTL:
            return cached_version

        version = await asyncio.to_thread(get_provider("claude-code").get_version)

        _version_cache = (version, time.time())
        return version


async def _get_active_count(db: AsyncSession) -> int:
    service = PresenceService()
    sessions = await service.get_all_sessions(db)
    return sum(1 for s in sessions if s.status == SessionStatus.ACTIVE)


async def _get_provider_statuses() -> dict[str, Any]:
    statuses = await asyncio.gather(
        *(asyncio.to_thread(provider.get_status) for provider in get_providers())
    )
    return {status["id"]: status for status in statuses}


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """Return system status for header indicators."""
    version, active_count, provider_statuses = await asyncio.gather(
        _get_claude_code_version(),
        _get_active_count(db),
        _get_provider_statuses(),
    )

    return SystemStatusResponse(
        claude_code_version=version,
        active_sessions=active_count,
        providers=provider_statuses,
        instance=get_instance_identity(),
    )
