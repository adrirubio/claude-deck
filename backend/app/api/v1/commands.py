"""API endpoints for slash command management."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    SlashCommand,
    SlashCommandCreate,
    SlashCommandListResponse,
    SlashCommandUpdate,
)
from app.services.command_service import CommandService

router = APIRouter(prefix="/commands", tags=["Commands"])


@router.get("", response_model=SlashCommandListResponse)
async def list_commands(
    project_path: Optional[str] = Query(None, description="Project path for project-scoped commands")
):
    """
    List all commands from user and project scopes.

    Args:
        project_path: Optional project path for project-scoped commands

    Returns:
        List of all commands
    """
    try:
        commands = CommandService.list_commands(project_path)
        return SlashCommandListResponse(commands=commands)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list commands: {str(e)}")


@router.get("/{scope}/{path:path}", response_model=SlashCommand)
async def get_command(
    scope: str,
    path: str,
    project_path: Optional[str] = Query(None, description="Project path for project-scoped commands")
):
    """
    Get a specific command by scope and path.

    Args:
        scope: Command scope (user or project)
        path: Relative path to command file
        project_path: Optional project path for project-scoped commands

    Returns:
        Command details

    Raises:
        HTTPException: 400 if invalid scope, 404 if command not found
    """
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}. Must be 'user' or 'project'")

    try:
        command = CommandService.get_command(scope, path, project_path)
        if command is None:
            raise HTTPException(status_code=404, detail=f"Command not found: {scope}/{path}")
        return command
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get command: {str(e)}")


@router.post("", response_model=SlashCommand, status_code=201)
async def create_command(
    command: SlashCommandCreate,
    project_path: Optional[str] = Query(None, description="Project path for project-scoped commands")
):
    """
    Create a new command.

    Args:
        command: Command data
        project_path: Optional project path for project-scoped commands

    Returns:
        Created command

    Raises:
        HTTPException: 400 if validation fails or command exists
    """
    if command.scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope: {command.scope}. Must be 'user' or 'project'"
        )

    try:
        created_command = CommandService.create_command(command, project_path)
        return created_command
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create command: {str(e)}")


@router.put("/{scope}/{path:path}", response_model=SlashCommand)
async def update_command(
    scope: str,
    path: str,
    command: SlashCommandUpdate,
    project_path: Optional[str] = Query(None, description="Project path for project-scoped commands")
):
    """
    Update an existing command.

    Args:
        scope: Command scope (user or project)
        path: Relative path to command file
        command: Updated command data
        project_path: Optional project path for project-scoped commands

    Returns:
        Updated command

    Raises:
        HTTPException: 400 if invalid scope, 404 if command not found
    """
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}. Must be 'user' or 'project'")

    try:
        updated_command = CommandService.update_command(scope, path, command, project_path)
        if updated_command is None:
            raise HTTPException(status_code=404, detail=f"Command not found: {scope}/{path}")
        return updated_command
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update command: {str(e)}")


@router.delete("/{scope}/{path:path}", status_code=204)
async def delete_command(
    scope: str,
    path: str,
    project_path: Optional[str] = Query(None, description="Project path for project-scoped commands")
):
    """
    Delete a command.

    Args:
        scope: Command scope (user or project)
        path: Relative path to command file
        project_path: Optional project path for project-scoped commands

    Raises:
        HTTPException: 400 if invalid scope, 404 if command not found
    """
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}. Must be 'user' or 'project'")

    try:
        success = CommandService.delete_command(scope, path, project_path)
        if not success:
            raise HTTPException(status_code=404, detail=f"Command not found: {scope}/{path}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete command: {str(e)}")
