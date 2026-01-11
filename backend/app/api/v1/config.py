"""Configuration API endpoints."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ...services.config_service import ConfigService
from ...models.schemas import ConfigFileListResponse, MergedConfig, RawFileContent, ConfigFile

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
