"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.api.v1.router import router as api_v1_router
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup: Initialize database
    await init_db()
    # Clean up any orphaned relay processes from previous runs
    from app.services.cc_bridge.pty_relay import close_all_relays, cleanup_orphaned_relays
    cleanup_orphaned_relays()
    yield
    # Shutdown: Cleanup
    await close_all_relays()
    from app.services.codex_app_server_service import codex_app_server_service
    codex_app_server_service.stop()


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# Configure CORS
# Accept any origin reaching the dev (5173) or prod (8000) ports — this lets
# the UI load over localhost, LAN, or tailnet without requiring env config.
# allow_credentials must be False when using a wildcard regex (browsers reject
# "*"-style wildcards with credentials); our API does not rely on cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://[^/]+(:\d+)?$",
    allow_credentials=False,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

# Include API routers
app.include_router(api_v1_router, prefix=settings.api_v1_prefix)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running"
    }

# Serve static files from the frontend build directory
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

    @app.exception_handler(404)
    async def not_found_exception_handler(request, exc):
        """Standard 404 handler to serve index.html for SPA routing."""
        if not request.url.path.startswith(settings.api_v1_prefix):
            return FileResponse(os.path.join(frontend_path, "index.html"), status_code=200)
        return JSONResponse({"detail": "Not Found"}, status_code=404)
else:
    @app.get("/")
    async def root():
        """Root endpoint fallback when frontend is not built."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "message": "Frontend not found. Please build the frontend."
        }
