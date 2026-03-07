"""System status endpoint for header indicators."""
import asyncio
import re
import shutil
import time
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import SystemStatusResponse
from app.services.presence_service import PresenceService

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

        claude_bin = await asyncio.to_thread(shutil.which, "claude")
        if not claude_bin:
            _version_cache = (None, time.time())
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                claude_bin, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            match = re.search(r"(\d+\.\d+\.\d+)", stdout.decode())
            version = match.group(1) if match else None
        except (OSError, asyncio.TimeoutError):
            version = None

        _version_cache = (version, time.time())
        return version


async def _get_active_count(db: AsyncSession) -> int:
    service = PresenceService()
    sessions = await service.get_all_sessions(db)
    return sum(1 for s in sessions if s.status == "active")


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """Return system status for header indicators."""
    version, active_count = await asyncio.gather(
        _get_claude_code_version(),
        _get_active_count(db),
    )

    return SystemStatusResponse(
        claude_code_version=version,
        active_sessions=active_count,
    )
