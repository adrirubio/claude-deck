"""API endpoints for output style management."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    OutputStyle,
    OutputStyleCreate,
    OutputStyleListResponse,
    OutputStyleUpdate,
)
from app.services.output_style_service import OutputStyleService

router = APIRouter(prefix="/output-styles", tags=["Output Styles"])


@router.get("", response_model=OutputStyleListResponse)
async def list_output_styles(
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    List all output styles from user and project scopes.

    Args:
        project_path: Optional project directory path

    Returns:
        List of all output styles
    """
    styles = OutputStyleService.list_output_styles(project_path)
    return OutputStyleListResponse(output_styles=styles)


@router.get("/{scope}/{name}", response_model=OutputStyle)
async def get_output_style(
    scope: str,
    name: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Get a specific output style by scope and name.

    Args:
        scope: Style scope (user or project)
        name: Style name (without .md extension)
        project_path: Optional project directory path (required for project scope)

    Returns:
        Output style definition
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    style = OutputStyleService.get_output_style(scope, name, project_path)
    if not style:
        raise HTTPException(
            status_code=404,
            detail=f"Output style '{name}' not found in {scope} scope"
        )
    return style


@router.post("", response_model=OutputStyle, status_code=201)
async def create_output_style(
    style: OutputStyleCreate,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Create a new output style.

    Args:
        style: Output style creation data
        project_path: Optional project directory path (required for project scope)

    Returns:
        Created output style
    """
    # Validate scope
    if style.scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    # Validate project path for project scope
    if style.scope == "project" and not project_path:
        raise HTTPException(
            status_code=400,
            detail="project_path is required for project-scoped output styles"
        )

    try:
        created_style = OutputStyleService.create_output_style(style, project_path)
        return created_style
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create output style: {str(e)}"
        )


@router.put("/{scope}/{name}", response_model=OutputStyle)
async def update_output_style(
    scope: str,
    name: str,
    style_update: OutputStyleUpdate,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Update an existing output style.

    Args:
        scope: Style scope (user or project)
        name: Style name (without .md extension)
        style_update: Output style update data
        project_path: Optional project directory path (required for project scope)

    Returns:
        Updated output style
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    try:
        updated_style = OutputStyleService.update_output_style(scope, name, style_update, project_path)

        if not updated_style:
            raise HTTPException(
                status_code=404,
                detail=f"Output style '{name}' not found in {scope} scope"
            )

        return updated_style
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update output style: {str(e)}"
        )


@router.delete("/{scope}/{name}", status_code=204)
async def delete_output_style(
    scope: str,
    name: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Delete an output style.

    Args:
        scope: Style scope (user or project)
        name: Style name (without .md extension)
        project_path: Optional project directory path (required for project scope)

    Returns:
        204 No Content on success
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    try:
        deleted = OutputStyleService.delete_output_style(scope, name, project_path)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=f"Output style '{name}' not found in {scope} scope"
            )

        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete output style: {str(e)}"
        )
