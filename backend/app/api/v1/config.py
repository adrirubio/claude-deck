"""Configuration API endpoints."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ...services.config_service import ConfigService
from ...models.schemas import (
    ConfigFileListResponse,
    MergedConfig,
    RawFileContent,
    ConfigFile,
    SettingsUpdateRequest,
    SettingsUpdateResponse,
    SettingsValidationRequest,
    SettingsValidationResponse,
    PatternIssue,
)
from ...utils.pattern_utils import validate_permission_pattern, migrate_deprecated_pattern

router = APIRouter(prefix="/config", tags=["config"])
config_service = ConfigService()


@router.get("/files", response_model=ConfigFileListResponse)
async def list_config_files(project_path: Optional[str] = Query(None)):
    """
    List all configuration file paths with their status.

    Args:
        project_path: Optional project directory path

    Returns:
        List of configuration files
    """
    try:
        files_data = config_service.get_all_config_files(project_path)
        files = [ConfigFile(**f) for f in files_data]
        return ConfigFileListResponse(files=files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=MergedConfig)
async def get_merged_config(project_path: Optional[str] = Query(None)):
    """
    Get merged configuration from all scopes.

    Args:
        project_path: Optional project directory path

    Returns:
        Merged configuration
    """
    try:
        merged = config_service.get_merged_config(project_path)
        # Mask sensitive values
        merged_masked = config_service.mask_sensitive_values(merged)
        return MergedConfig(**merged_masked)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/raw", response_model=RawFileContent)
async def get_raw_file_content(path: str = Query(..., description="File path to read")):
    """
    Get raw file content.

    Args:
        path: Path to the file

    Returns:
        Raw file content
    """
    try:
        content_data = config_service.get_file_content(path)
        if content_data is None:
            raise HTTPException(status_code=404, detail="File not found")
        return RawFileContent(**content_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/settings", response_model=SettingsUpdateResponse)
async def update_settings(request: SettingsUpdateRequest):
    """
    Update settings for a specific scope.

    Args:
        request: Settings update request with scope, settings, and optional project_path

    Returns:
        Update result with success status and file path
    """
    try:
        result = config_service.update_settings(
            scope=request.scope,
            settings=request.settings,
            project_path=request.project_path
        )
        return SettingsUpdateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate-settings", response_model=SettingsValidationResponse)
async def validate_settings(request: SettingsValidationRequest):
    """
    Validate permission patterns in settings without saving.

    Checks permissions.allow, permissions.ask, and permissions.deny arrays
    for patterns that Claude Code would reject.
    """
    issues: list[PatternIssue] = []
    permissions = request.settings.get("permissions", {})
    if not isinstance(permissions, dict):
        return SettingsValidationResponse(valid=True, issues=[])

    for category in ("allow", "ask", "deny"):
        rules = permissions.get(category)
        if not isinstance(rules, list):
            continue
        for pattern in rules:
            if not isinstance(pattern, str):
                issues.append(PatternIssue(
                    pattern=str(pattern),
                    category=category,
                    error="Pattern is not a string",
                ))
                continue
            is_valid, error = validate_permission_pattern(pattern)
            if not is_valid:
                suggestion = migrate_deprecated_pattern(pattern)
                issues.append(PatternIssue(
                    pattern=pattern,
                    category=category,
                    error=error or "Invalid pattern",
                    suggestion=suggestion,
                ))

    return SettingsValidationResponse(
        valid=len(issues) == 0,
        issues=issues,
    )


@router.get("/settings/{scope}")
async def get_settings_by_scope(
    scope: str,
    project_path: Optional[str] = Query(None)
):
    """
    Get settings for a specific scope (not merged).

    Args:
        scope: user, user_local, project, local, or managed
        project_path: Required for project/local scope

    Returns:
        Settings dictionary for the specified scope
    """
    try:
        settings = config_service.get_settings_by_scope(scope, project_path)
        return {"settings": settings, "scope": scope}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resolved")
async def get_resolved_config(project_path: Optional[str] = Query(None)):
    """
    Get resolved configuration with effective values and source scopes.
    
    Shows the 4-level merge result: Managed (highest) → Local → Project → User (lowest)
    
    Args:
        project_path: Optional project directory path

    Returns:
        Resolved configuration with effective values and their source scopes
    """
    try:
        resolved = config_service.get_resolved_config(project_path)
        return resolved
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scopes")
async def get_all_scoped_settings(project_path: Optional[str] = Query(None)):
    """
    Get settings from all scopes separately (not merged).
    
    Returns settings from: managed, user, project, local
    
    Args:
        project_path: Optional project directory path

    Returns:
        Dictionary with settings from each scope
    """
    try:
        scoped_settings = config_service.get_all_scoped_settings(project_path)
        return {"scopes": scoped_settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
