"""Project management service for discovering and managing Claude Code projects."""
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Project
from app.models.schemas import ProjectBase, ProjectCreate, ProjectResponse
from app.services.config_service import ConfigService
from app.utils.path_utils import get_project_claude_dir, get_project_mcp_config_file


class ProjectService:
    """Service for managing Claude Code projects."""

    def __init__(self, db: AsyncSession):
        """Initialize the project service."""
        self.db = db

    async def list_projects(self) -> List[ProjectResponse]:
        """List all tracked projects from the database."""
        result = await self.db.execute(select(Project).order_by(Project.last_accessed.desc()))
        projects = result.scalars().all()

        return [
            ProjectResponse(
                id=p.id,
                name=p.name,
                path=p.path,
                is_active=p.is_active,
                last_accessed=p.last_accessed.isoformat(),
                created_at=p.created_at.isoformat(),
            )
            for p in projects
        ]

    async def add_project(self, project_data: ProjectCreate) -> ProjectResponse:
        """Add a project manually to the database."""
        # Check if project already exists
        result = await self.db.execute(
            select(Project).where(Project.path == project_data.path)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing project
            existing.name = project_data.name
            existing.last_accessed = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(existing)

            return ProjectResponse(
                id=existing.id,
                name=existing.name,
                path=existing.path,
                is_active=existing.is_active,
                last_accessed=existing.last_accessed.isoformat(),
                created_at=existing.created_at.isoformat(),
            )

        # Create new project
        new_project = Project(
            name=project_data.name,
            path=project_data.path,
            is_active=False,
            last_accessed=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )

        self.db.add(new_project)
        await self.db.commit()
        await self.db.refresh(new_project)

        return ProjectResponse(
            id=new_project.id,
            name=new_project.name,
            path=new_project.path,
            is_active=new_project.is_active,
            last_accessed=new_project.last_accessed.isoformat(),
            created_at=new_project.created_at.isoformat(),
        )

    async def remove_project(self, project_id: int) -> bool:
        """Remove a project from the database."""
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if not project:
            return False

        await self.db.delete(project)
        await self.db.commit()
        return True

    def discover_projects(self, base_path: str) -> List[ProjectBase]:
        """
        Scan a directory for Claude Code projects.

        A project is identified by the presence of:
        - .claude/ directory
        - .mcp.json file
        """
        discovered = []
        base_dir = Path(base_path).expanduser().resolve()

        if not base_dir.exists() or not base_dir.is_dir():
            return []

        # Scan the base directory and its immediate subdirectories
        dirs_to_check = [base_dir]

        # Add subdirectories (one level deep)
        try:
            for item in base_dir.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    dirs_to_check.append(item)
        except PermissionError:
            pass

        for directory in dirs_to_check:
            try:
                # Check for .claude/ directory or .mcp.json file
                claude_dir = get_project_claude_dir(str(directory))
                mcp_file = get_project_mcp_config_file(str(directory))

                if claude_dir.exists() or mcp_file.exists():
                    project_name = directory.name
                    discovered.append(
                        ProjectBase(
                            name=project_name,
                            path=str(directory),
                        )
                    )
            except (PermissionError, OSError):
                continue

        return discovered

    async def set_active_project(self, project_id: int) -> Optional[ProjectResponse]:
        """Set a project as the active project context."""
        # First, deactivate all projects
        result = await self.db.execute(select(Project))
        all_projects = result.scalars().all()

        for p in all_projects:
            p.is_active = False

        # Then activate the requested project
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if not project:
            await self.db.commit()
            return None

        project.is_active = True
        project.last_accessed = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(project)

        return ProjectResponse(
            id=project.id,
            name=project.name,
            path=project.path,
            is_active=project.is_active,
            last_accessed=project.last_accessed.isoformat(),
            created_at=project.created_at.isoformat(),
        )

    async def clear_active_project(self) -> bool:
        """Clear the active project (deactivate all projects)."""
        result = await self.db.execute(select(Project))
        all_projects = result.scalars().all()

        for p in all_projects:
            p.is_active = False

        await self.db.commit()
        return True

    async def get_project_config(self, project_id: int) -> Optional[dict]:
        """Get project-specific configuration."""
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if not project:
            return None

        # Use ConfigService to get merged config for this project
        config_service = ConfigService()
        merged = config_service.get_merged_config(project_path=project.path)

        return {
            "project": ProjectResponse(
                id=project.id,
                name=project.name,
                path=project.path,
                is_active=project.is_active,
                last_accessed=project.last_accessed.isoformat(),
                created_at=project.created_at.isoformat(),
            ).model_dump(),
            "config": merged.model_dump(),
        }

    async def get_active_project(self) -> Optional[ProjectResponse]:
        """Get the currently active project."""
        result = await self.db.execute(
            select(Project).where(Project.is_active == True)
        )
        project = result.scalar_one_or_none()

        if not project:
            return None

        return ProjectResponse(
            id=project.id,
            name=project.name,
            path=project.path,
            is_active=project.is_active,
            last_accessed=project.last_accessed.isoformat(),
            created_at=project.created_at.isoformat(),
        )
