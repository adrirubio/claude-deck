"""Service for managing configuration backups."""
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Backup
from app.utils.path_utils import (
    get_user_home,
    get_claude_user_config_dir,
    get_claude_user_config_file,
    get_claude_user_settings_file,
    get_claude_user_settings_local_file,
    get_claude_user_commands_dir,
    get_claude_user_agents_dir,
    get_claude_user_skills_dir,
    get_claude_user_plugins_dir,
    get_project_claude_dir,
    get_project_mcp_config_file,
    get_project_claude_md_file,
)


def get_backup_storage_dir() -> Path:
    """Get the backup storage directory."""
    backup_dir = get_user_home() / ".claude-registry" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


class BackupService:
    """Service for managing configuration backups."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_user_config_paths(self) -> List[Path]:
        """Get all user-level configuration paths."""
        paths = []

        # Main config files
        for path_fn in [
            get_claude_user_config_file,
            get_claude_user_settings_file,
            get_claude_user_settings_local_file,
        ]:
            path = path_fn()
            if path.exists():
                paths.append(path)

        # Directories
        for dir_fn in [
            get_claude_user_commands_dir,
            get_claude_user_agents_dir,
            get_claude_user_skills_dir,
            get_claude_user_plugins_dir,
        ]:
            dir_path = dir_fn()
            if dir_path.exists():
                for file_path in dir_path.rglob("*"):
                    if file_path.is_file():
                        paths.append(file_path)

        return paths

    def _get_project_config_paths(self, project_path: str) -> List[Path]:
        """Get all project-level configuration paths."""
        paths = []

        # .claude directory
        claude_dir = get_project_claude_dir(project_path)
        if claude_dir.exists():
            for file_path in claude_dir.rglob("*"):
                if file_path.is_file():
                    paths.append(file_path)

        # .mcp.json
        mcp_file = get_project_mcp_config_file(project_path)
        if mcp_file.exists():
            paths.append(mcp_file)

        # CLAUDE.md
        claude_md = get_project_claude_md_file(project_path)
        if claude_md.exists():
            paths.append(claude_md)

        return paths

    def _create_archive(
        self, name: str, paths: List[Path], base_path: Optional[Path] = None
    ) -> tuple[Path, int]:
        """
        Create a zip archive from the given paths.

        Args:
            name: Backup name
            paths: List of file paths to include
            base_path: Base path for relative paths in archive

        Returns:
            Tuple of (archive_path, size_bytes)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{name}_{timestamp}.zip"
        archive_path = get_backup_storage_dir() / archive_name

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in paths:
                if base_path:
                    try:
                        arcname = str(file_path.relative_to(base_path))
                    except ValueError:
                        arcname = str(file_path)
                else:
                    # Use path relative to home for user configs
                    try:
                        arcname = str(file_path.relative_to(get_user_home()))
                    except ValueError:
                        arcname = str(file_path)

                zf.write(file_path, arcname)

        size_bytes = archive_path.stat().st_size
        return archive_path, size_bytes

    async def create_backup(
        self,
        name: str,
        scope: str,
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        project_id: Optional[int] = None,
    ) -> Backup:
        """
        Create a new backup.

        Args:
            name: Backup name
            scope: Scope ("full", "user", "project")
            project_path: Project path for project/full scope
            description: Optional description
            project_id: Optional project ID reference

        Returns:
            Created Backup record
        """
        paths = []

        if scope in ["full", "user"]:
            paths.extend(self._get_user_config_paths())

        if scope in ["full", "project"] and project_path:
            paths.extend(self._get_project_config_paths(project_path))

        if not paths:
            raise ValueError("No configuration files found to backup")

        # Determine base path for relative paths
        base_path = None
        if scope == "project" and project_path:
            base_path = Path(project_path)

        archive_path, size_bytes = self._create_archive(name, paths, base_path)

        backup = Backup(
            name=name,
            description=description,
            file_path=str(archive_path),
            scope=scope,
            project_id=project_id,
            size_bytes=size_bytes,
        )

        self.db.add(backup)
        await self.db.commit()
        await self.db.refresh(backup)

        return backup

    async def list_backups(self) -> List[Backup]:
        """List all backups."""
        result = await self.db.execute(
            select(Backup).order_by(Backup.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_backup(self, backup_id: int) -> Optional[Backup]:
        """Get a backup by ID."""
        result = await self.db.execute(select(Backup).where(Backup.id == backup_id))
        return result.scalar_one_or_none()

    async def delete_backup(self, backup_id: int) -> bool:
        """
        Delete a backup.

        Args:
            backup_id: Backup ID

        Returns:
            True if deleted, False if not found
        """
        backup = await self.get_backup(backup_id)
        if not backup:
            return False

        # Delete the archive file
        archive_path = Path(backup.file_path)
        if archive_path.exists():
            archive_path.unlink()

        # Delete the database record
        await self.db.delete(backup)
        await self.db.commit()

        return True

    async def restore_backup(
        self, backup_id: int, project_path: Optional[str] = None
    ) -> bool:
        """
        Restore from a backup.

        Args:
            backup_id: Backup ID
            project_path: Target project path for project-scoped backups

        Returns:
            True if restored successfully
        """
        backup = await self.get_backup(backup_id)
        if not backup:
            return False

        archive_path = Path(backup.file_path)
        if not archive_path.exists():
            raise ValueError(f"Backup file not found: {archive_path}")

        # Determine restore target
        if backup.scope == "project" and project_path:
            target_path = Path(project_path)
        else:
            target_path = get_user_home()

        # Extract the archive
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.namelist():
                # Determine the full target path
                member_target = target_path / member

                # Ensure parent directory exists
                member_target.parent.mkdir(parents=True, exist_ok=True)

                # Extract the file
                with zf.open(member) as source:
                    with open(member_target, "wb") as dest:
                        dest.write(source.read())

        return True

    def get_backup_contents(self, backup_id: int, file_path: str) -> List[str]:
        """
        Get the list of files in a backup.

        Args:
            backup_id: Backup ID (not used, file_path is used directly)
            file_path: Path to the backup file

        Returns:
            List of file names in the archive
        """
        archive_path = Path(file_path)
        if not archive_path.exists():
            return []

        with zipfile.ZipFile(archive_path, "r") as zf:
            return zf.namelist()

    async def export_config(
        self, paths: List[str], name: str = "export"
    ) -> tuple[Path, int]:
        """
        Export specific configuration files.

        Args:
            paths: List of absolute paths to export
            name: Export name

        Returns:
            Tuple of (archive_path, size_bytes)
        """
        valid_paths = [Path(p) for p in paths if Path(p).exists()]
        if not valid_paths:
            raise ValueError("No valid paths to export")

        return self._create_archive(name, valid_paths)
