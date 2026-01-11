"""API endpoints for hook management."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import Hook, HookCreate, HookListResponse, HookUpdate
from app.services.hook_service import HookService

router = APIRouter(prefix="/hooks", tags=["Hooks"])


@router.get("", response_model=HookListResponse)
async def list_hooks(
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    List all hooks from user and project settings files.

    Args:
        project_path: Optional project directory path

    Returns:
        List of all hooks
    """
    service = HookService()
    hooks = service.list_hooks(project_path)
    return HookListResponse(hooks=hooks)


@router.get("/{event}", response_model=HookListResponse)
async def get_hooks_by_event(
    event: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Get hooks for a specific event type.

    Args:
        event: Event type (e.g., PreToolUse, PostToolUse, Stop)
        project_path: Optional project directory path

    Returns:
        List of hooks for the specified event
    """
    service = HookService()
    hooks = service.get_hooks_by_event(event, project_path)
    return HookListResponse(hooks=hooks)


@router.post("", response_model=Hook, status_code=201)
async def create_hook(
    hook: HookCreate,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Create a new hook.

    Args:
        hook: Hook creation data
        project_path: Optional project directory path (required for project scope)

    Returns:
        Created hook
    """
    # Validate hook type
    if hook.type not in ["command", "prompt"]:
        raise HTTPException(
            status_code=400,
            detail="Hook type must be 'command' or 'prompt'"
        )

    # Validate scope
    if hook.scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    # Validate required fields based on type
    if hook.type == "command" and not hook.command:
        raise HTTPException(
            status_code=400,
            detail="Command is required for command-type hooks"
        )

    if hook.type == "prompt" and not hook.prompt:
        raise HTTPException(
            status_code=400,
            detail="Prompt is required for prompt-type hooks"
        )

    try:
        service = HookService()
        created_hook = service.add_hook(hook, project_path)
        return created_hook
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create hook: {str(e)}"
        )


@router.put("/{hook_id}", response_model=Hook)
async def update_hook(
    hook_id: str,
    hook_update: HookUpdate,
    scope: str = Query(..., description="Scope (user or project)"),
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Update an existing hook.

    Args:
        hook_id: ID of the hook to update
        hook_update: Hook update data
        scope: Scope of the hook (user or project)
        project_path: Optional project directory path (required for project scope)

    Returns:
        Updated hook
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    # Validate hook type if provided
    if hook_update.type and hook_update.type not in ["command", "prompt"]:
        raise HTTPException(
            status_code=400,
            detail="Hook type must be 'command' or 'prompt'"
        )

    try:
        service = HookService()
        updated_hook = service.update_hook(hook_id, hook_update, scope, project_path)

        if not updated_hook:
            raise HTTPException(
                status_code=404,
                detail=f"Hook with ID {hook_id} not found in {scope} scope"
            )

        return updated_hook
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update hook: {str(e)}"
        )


@router.delete("/{hook_id}", status_code=204)
async def delete_hook(
    hook_id: str,
    scope: str = Query(..., description="Scope (user or project)"),
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Delete a hook.

    Args:
        hook_id: ID of the hook to delete
        scope: Scope of the hook (user or project)
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
        service = HookService()
        removed = service.remove_hook(hook_id, scope, project_path)

        if not removed:
            raise HTTPException(
                status_code=404,
                detail=f"Hook with ID {hook_id} not found in {scope} scope"
            )

        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete hook: {str(e)}"
        )
