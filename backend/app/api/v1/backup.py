"""API endpoints for backup management."""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from app.database import get_db
from app.models.schemas import (
    BackupCreate,
    BackupResponse,
    BackupListResponse,
    BackupContentsResponse,
    RestoreRequest,
    ExportRequest,
    ExportResponse,
)
from app.services.backup_service import BackupService

router = APIRouter(prefix="/backup", tags=["Backup"])


def _backup_to_response(backup) -> BackupResponse:
    """Convert a Backup model to BackupResponse."""
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
        backups=[_backup_to_response(b) for b in backups]
    )


@router.post("/create", response_model=BackupResponse, status_code=201)
async def create_backup(
    backup: BackupCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new backup.

    Args:
        backup: Backup creation data

    Returns:
        Created backup
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
        created_backup = await service.create_backup(
            name=backup.name,
            scope=backup.scope,
            project_path=backup.project_path,
            description=backup.description,
            project_id=backup.project_id,
        )
        return _backup_to_response(created_backup)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create backup: {str(e)}"
        )


@router.get("/{backup_id}", response_model=BackupResponse)
async def get_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a backup by ID.

    Args:
        backup_id: Backup ID

    Returns:
        Backup details
    """
    service = BackupService(db)
    backup = await service.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    return _backup_to_response(backup)


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


@router.post("/{backup_id}/restore", status_code=200)
async def restore_backup(
    backup_id: int,
    request: RestoreRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Restore from a backup.

    Args:
        backup_id: Backup ID
        request: Restore request with optional project_path

    Returns:
        Success message
    """
    service = BackupService(db)

    try:
        success = await service.restore_backup(backup_id, request.project_path)
        if not success:
            raise HTTPException(status_code=404, detail="Backup not found")
        return {"message": "Backup restored successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore backup: {str(e)}"
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
