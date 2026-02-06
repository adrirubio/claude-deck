"""API endpoints for backup management."""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from app.database import get_db
from app.models.schemas import (
    BackupCreate,
    BackupManifest,
    BackupResponse,
    BackupListResponse,
    BackupContentsResponse,
    DependencyInstallRequest,
    DependencyInstallResult,
    RestoreOptions,
    RestorePlan,
    RestoreResult,
    ExportRequest,
    ExportResponse,
)
from app.services.backup_service import BackupService

router = APIRouter(prefix="/backup", tags=["Backup"])


class BackupCreateResponse(BackupResponse):
    """Extended backup response with manifest summary."""

    has_dependencies: bool = False
    skill_count: int = 0
    plugin_count: int = 0
    mcp_server_count: int = 0


class ValidationResponse(BaseModel):
    """Backup validation result."""

    valid: bool
    issues: List[str] = []


def _backup_to_response(backup, manifest: Optional[BackupManifest] = None) -> BackupCreateResponse:
    """Convert a Backup model to BackupCreateResponse."""
    response = BackupCreateResponse(
        id=backup.id,
        name=backup.name,
        description=backup.description,
        scope=backup.scope,
        file_path=backup.file_path,
        project_id=backup.project_id,
        created_at=backup.created_at.isoformat(),
        size_bytes=backup.size_bytes,
    )

    if manifest:
        response.skill_count = len(manifest.contents.skills)
        response.plugin_count = len(manifest.contents.plugins)
        response.mcp_server_count = len(manifest.contents.mcp_servers)
        response.has_dependencies = any(
            len(s.dependencies) > 0 or s.has_install_script
            for s in manifest.contents.skills
        ) or any(
            p.install_command is not None for p in manifest.contents.plugins
        )

    return response


def _backup_to_basic_response(backup) -> BackupResponse:
    """Convert a Backup model to basic BackupResponse."""
    return BackupResponse(
        id=backup.id,
        name=backup.name,
        description=backup.description,
        scope=backup.scope,
        file_path=backup.file_path,
        project_id=backup.project_id,
        created_at=backup.created_at.isoformat(),
        size_bytes=backup.size_bytes,
    )


@router.get("/list", response_model=BackupListResponse)
async def list_backups(db: AsyncSession = Depends(get_db)):
    """
    List all available backups.

    Returns:
        List of backups
    """
    service = BackupService(db)
    backups = await service.list_backups()
    return BackupListResponse(
        backups=[_backup_to_basic_response(b) for b in backups]
    )


@router.post("/create", response_model=BackupCreateResponse, status_code=201)
async def create_backup(
    backup: BackupCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new backup.

    Args:
        backup: Backup creation data

    Returns:
        Created backup with manifest summary
    """
    # Validate scope
    if backup.scope not in ["full", "user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'full', 'user', or 'project'"
        )

    # Validate project_path for project/full scope
    if backup.scope in ["full", "project"] and not backup.project_path:
        raise HTTPException(
            status_code=400,
            detail="project_path is required for full or project scope"
        )

    try:
        service = BackupService(db)
        created_backup, manifest = await service.create_backup(
            name=backup.name,
            scope=backup.scope,
            project_path=backup.project_path,
            description=backup.description,
            project_id=backup.project_id,
        )
        return _backup_to_response(created_backup, manifest)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create backup: {str(e)}"
        )


@router.get("/{backup_id}", response_model=BackupCreateResponse)
async def get_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a backup by ID with manifest info.

    Args:
        backup_id: Backup ID

    Returns:
        Backup details with dependency info
    """
    service = BackupService(db)
    backup = await service.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    manifest = service.get_manifest_from_backup(backup.file_path)
    return _backup_to_response(backup, manifest)


@router.get("/{backup_id}/contents", response_model=BackupContentsResponse)
async def get_backup_contents(
    backup_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the list of files in a backup.

    Args:
        backup_id: Backup ID

    Returns:
        List of files in the backup
    """
    service = BackupService(db)
    backup = await service.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    files = service.get_backup_contents(backup_id, backup.file_path)
    return BackupContentsResponse(files=files)


@router.get("/{backup_id}/manifest", response_model=BackupManifest)
async def get_backup_manifest(
    backup_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the full manifest from a backup.

    Args:
        backup_id: Backup ID

    Returns:
        BackupManifest with all dependency info
    """
    service = BackupService(db)
    backup = await service.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    manifest = service.get_manifest_from_backup(backup.file_path)
    if not manifest:
        raise HTTPException(
            status_code=404,
            detail="Manifest not found in backup (older backup format)"
        )

    return manifest


@router.get("/{backup_id}/plan", response_model=RestorePlan)
async def get_restore_plan(
    backup_id: int,
    project_path: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a restore plan for a backup.

    Analyzes the backup and shows:
    - What files will be restored
    - Dependencies that need to be installed
    - Platform compatibility warnings
    - Manual steps required

    Args:
        backup_id: Backup ID
        project_path: Optional target project path

    Returns:
        RestorePlan with full analysis
    """
    service = BackupService(db)
    plan = await service.get_restore_plan(backup_id, project_path)
    if not plan:
        raise HTTPException(status_code=404, detail="Backup not found")
    return plan


@router.post("/{backup_id}/validate", response_model=ValidationResponse)
async def validate_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate a backup before restore.

    Checks:
    - Backup file exists
    - Archive integrity
    - Manifest presence

    Args:
        backup_id: Backup ID

    Returns:
        Validation result with any issues
    """
    service = BackupService(db)
    is_valid, issues = await service.validate_backup(backup_id)
    return ValidationResponse(valid=is_valid, issues=issues)


@router.get("/{backup_id}/download")
async def download_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Download a backup archive.

    Args:
        backup_id: Backup ID

    Returns:
        Backup file download
    """
    service = BackupService(db)
    backup = await service.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    file_path = Path(backup.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/zip"
    )


@router.post("/{backup_id}/restore", response_model=RestoreResult, status_code=200)
async def restore_backup(
    backup_id: int,
    options: Optional[RestoreOptions] = None,
    project_path: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Restore from a backup.

    Args:
        backup_id: Backup ID
        options: Restore options (selective restore, dependency install, dry run)
        project_path: Target project path for project-scoped backups

    Returns:
        RestoreResult with details of what was restored
    """
    service = BackupService(db)

    try:
        result = await service.restore_backup(
            backup_id,
            project_path=project_path,
            options=options,
        )
        if not result.success and result.message == "Backup not found":
            raise HTTPException(status_code=404, detail="Backup not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore backup: {str(e)}"
        )


@router.post("/{backup_id}/install-dependencies", response_model=DependencyInstallResult)
async def install_dependencies(
    backup_id: int,
    request: DependencyInstallRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Install dependencies from a backup.

    Use this after restoring a backup to install:
    - npm dependencies for skills
    - pip dependencies for skills
    - Plugins from marketplace

    Args:
        backup_id: Backup ID
        request: What dependencies to install

    Returns:
        DependencyInstallResult with success/failure details
    """
    service = BackupService(db)

    try:
        result = await service.install_dependencies(backup_id, request)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to install dependencies: {str(e)}"
        )


@router.delete("/{backup_id}", status_code=204)
async def delete_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a backup.

    Args:
        backup_id: Backup ID

    Returns:
        204 No Content on success
    """
    service = BackupService(db)
    deleted = await service.delete_backup(backup_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Backup not found")
    return None


@router.post("/export", response_model=ExportResponse, status_code=201)
async def export_config(
    request: ExportRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Export specific configuration files.

    Args:
        request: Export request with paths and optional name

    Returns:
        Export file info
    """
    try:
        service = BackupService(db)
        archive_path, size_bytes = await service.export_config(
            paths=request.paths,
            name=request.name or "export"
        )
        return ExportResponse(
            file_path=str(archive_path),
            size_bytes=size_bytes
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export config: {str(e)}"
        )
