"""Project management API endpoints."""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import (
    ProjectCreate,
    ProjectDiscoveryRequest,
    ProjectDiscoveryResponse,
    ProjectListResponse,
    ProjectResponse,
    SetActiveProjectRequest,
)
from app.services.project_service import ProjectService

router = APIRouter()


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all tracked projects."""
    service = ProjectService(db)
    projects = await service.list_projects()
    return ProjectListResponse(projects=projects)


@router.post("/projects", response_model=ProjectResponse)
async def add_project(
    project_data: ProjectCreate,
    db: AsyncSession = Depends(get_db)
):
    """Add a project manually."""
    service = ProjectService(db)
    project = await service.add_project(project_data)
    return project


@router.post("/projects/discover", response_model=ProjectDiscoveryResponse)
async def discover_projects(
    request: ProjectDiscoveryRequest,
    db: AsyncSession = Depends(get_db)
):
    """Auto-discover Claude Code projects in the specified path."""
    service = ProjectService(db)
    discovered = service.discover_projects(request.base_path)
    return ProjectDiscoveryResponse(discovered=discovered)


@router.get("/projects/browse")
async def browse_directory(path: str = Query(default="~")):
    """Return subdirectories of the given path for the directory browser."""
    try:
        resolved = Path(os.path.expanduser(path)).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="Path is not a directory")

    try:
        subdirs = sorted(
            [e.name for e in resolved.iterdir() if e.is_dir() and not e.name.startswith(".")],
            key=str.lower,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    parent = str(resolved.parent) if resolved != resolved.parent else None
    return {"path": str(resolved), "parent": parent, "directories": subdirs}


# Active project routes - MUST be before /projects/{project_id} routes
@router.put("/projects/active", response_model=ProjectResponse)
async def set_active_project(
    request: SetActiveProjectRequest,
    db: AsyncSession = Depends(get_db)
):
    """Set the active project context."""
    service = ProjectService(db)
    project = await service.set_active_project(request.project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@router.get("/projects/active", response_model=ProjectResponse)
async def get_active_project(db: AsyncSession = Depends(get_db)):
    """Get the currently active project."""
    service = ProjectService(db)
    project = await service.get_active_project()

    if not project:
        raise HTTPException(status_code=404, detail="No active project set")

    return project


@router.delete("/projects/active")
async def clear_active_project(db: AsyncSession = Depends(get_db)):
    """Clear the active project (switch to global scope)."""
    service = ProjectService(db)
    await service.clear_active_project()
    return {"message": "Active project cleared"}


# Routes with path parameters - MUST be after /projects/active routes
@router.delete("/projects/{project_id}")
async def remove_project(
    project_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Remove a project from tracking."""
    service = ProjectService(db)
    success = await service.remove_project(project_id)

    if not success:
        raise HTTPException(status_code=404, detail="Project not found")

    return {"message": "Project removed successfully"}


@router.get("/projects/{project_id}/config")
async def get_project_config(
    project_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get project-specific configuration."""
    service = ProjectService(db)
    config = await service.get_project_config(project_id)

    if not config:
        raise HTTPException(status_code=404, detail="Project not found")

    return config
