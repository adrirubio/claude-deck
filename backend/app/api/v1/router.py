"""Main API router for v1 endpoints."""
from fastapi import APIRouter
from .config import router as config_router
from .projects import router as projects_router
from .cli import router as cli_router
from .mcp import router as mcp_router
from .commands import router as commands_router
from .plugins import router as plugins_router
from .hooks import router as hooks_router
from .permissions import router as permissions_router
from .agents import router as agents_router
from .backup import router as backup_router
from .output_styles import router as output_styles_router
from .statusline import router as statusline_router
from .sessions import router as sessions_router
from .usage import router as usage_router
from .memory import router as memory_router
from .context import router as context_router

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        dict: Status information
    """
    return {"status": "ok"}


# Include sub-routers
router.include_router(config_router)
router.include_router(projects_router)
router.include_router(cli_router)
router.include_router(mcp_router, prefix="/mcp", tags=["MCP Servers"])
router.include_router(commands_router)
router.include_router(plugins_router, tags=["Plugins"])
router.include_router(hooks_router, tags=["Hooks"])
router.include_router(permissions_router, tags=["Permissions"])
router.include_router(agents_router, tags=["Agents"])
router.include_router(backup_router, tags=["Backup"])
router.include_router(output_styles_router, tags=["Output Styles"])
router.include_router(statusline_router, tags=["Status Line"])
router.include_router(sessions_router, tags=["Sessions"])
router.include_router(usage_router, tags=["Usage"])
router.include_router(memory_router, tags=["Memory"])
router.include_router(context_router, tags=["Context"])
