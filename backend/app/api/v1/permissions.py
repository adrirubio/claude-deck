"""Permission management API endpoints."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    PermissionListResponse,
    PermissionRule,
    PermissionRuleCreate,
    PermissionRuleUpdate,
)
from app.services.permission_service import PermissionService

router = APIRouter(prefix="/permissions", tags=["Permissions"])


@router.get("", response_model=PermissionListResponse)
def list_permissions(
    project_path: Optional[str] = Query(None, description="Path to project directory"),
) -> PermissionListResponse:
    """
    Get all permission rules from user and project scopes.

    Args:
        project_path: Optional path to project directory for project-level permissions

    Returns:
        List of all permission rules
    """
    try:
        return PermissionService.list_permissions(project_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list permissions: {str(e)}")


@router.get("/{scope}", response_model=PermissionListResponse)
def list_permissions_by_scope(
    scope: str,
    project_path: Optional[str] = Query(None, description="Path to project directory"),
) -> PermissionListResponse:
    """
    Get permission rules for a specific scope.

    Args:
        scope: Scope to filter by (user or project)
        project_path: Optional path to project directory for project-level permissions

    Returns:
        List of permission rules for the specified scope
    """
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Scope must be 'user' or 'project'")

    try:
        all_rules = PermissionService.list_permissions(project_path)
        filtered_rules = [rule for rule in all_rules.rules if rule.scope == scope]
        return PermissionListResponse(rules=filtered_rules)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list permissions for scope {scope}: {str(e)}"
        )


@router.post("", response_model=PermissionRule, status_code=201)
async def add_permission(
    rule: PermissionRuleCreate,
    project_path: Optional[str] = Query(None, description="Path to project directory"),
) -> PermissionRule:
    """
    Add a new permission rule.

    Args:
        rule: Permission rule to add
        project_path: Optional path to project directory for project-level permissions

    Returns:
        Created permission rule with generated ID
    """
    # Validate type
    if rule.type not in ["allow", "deny"]:
        raise HTTPException(status_code=400, detail="Type must be 'allow' or 'deny'")

    # Validate scope
    if rule.scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Scope must be 'user' or 'project'")

    # Validate project_path for project scope
    if rule.scope == "project" and not project_path:
        raise HTTPException(
            status_code=400,
            detail="project_path query parameter is required for project scope",
        )

    try:
        return await PermissionService.add_permission(rule, project_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add permission: {str(e)}")


@router.put("/{rule_id}", response_model=PermissionRule)
async def update_permission(
    rule_id: str,
    rule_update: PermissionRuleUpdate,
    scope: str = Query(..., description="Scope of the rule (user or project)"),
    project_path: Optional[str] = Query(None, description="Path to project directory"),
) -> PermissionRule:
    """
    Update an existing permission rule.

    Args:
        rule_id: ID of the rule to update
        rule_update: Updated rule data
        scope: Scope of the rule (user or project)
        project_path: Optional path to project directory for project-level permissions

    Returns:
        Updated permission rule
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Scope must be 'user' or 'project'")

    # Validate project_path for project scope
    if scope == "project" and not project_path:
        raise HTTPException(
            status_code=400,
            detail="project_path query parameter is required for project scope",
        )

    # Validate type if provided
    if rule_update.type and rule_update.type not in ["allow", "deny"]:
        raise HTTPException(status_code=400, detail="Type must be 'allow' or 'deny'")

    try:
        return await PermissionService.update_permission(
            rule_id, rule_update, scope, project_path
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update permission: {str(e)}")


@router.delete("/{rule_id}", status_code=204)
async def remove_permission(
    rule_id: str,
    scope: str = Query(..., description="Scope of the rule (user or project)"),
    project_path: Optional[str] = Query(None, description="Path to project directory"),
) -> None:
    """
    Remove a permission rule.

    Args:
        rule_id: ID of the rule to remove
        scope: Scope of the rule (user or project)
        project_path: Optional path to project directory for project-level permissions
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Scope must be 'user' or 'project'")

    # Validate project_path for project scope
    if scope == "project" and not project_path:
        raise HTTPException(
            status_code=400,
            detail="project_path query parameter is required for project scope",
        )

    try:
        await PermissionService.remove_permission(rule_id, scope, project_path)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove permission: {str(e)}")
