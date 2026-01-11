"""API endpoints for status line configuration."""
from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

from app.models.schemas import (
    StatusLineConfig,
    StatusLinePresetsResponse,
    StatusLineUpdate,
    PowerlinePresetsResponse,
    NodejsCheckResponse,
)
from app.services.statusline_service import StatusLineService


class StatusLinePreviewRequest(BaseModel):
    """Request to preview a status line script."""

    script: str


class StatusLinePreviewResponse(BaseModel):
    """Response from status line preview execution."""

    success: bool
    output: str
    error: str | None = None

router = APIRouter(prefix="/statusline", tags=["Status Line"])

# Initialize service
service = StatusLineService()


@router.get("", response_model=StatusLineConfig)
async def get_statusline_config():
    """
    Get the current status line configuration.

    Returns:
        Current status line configuration
    """
    return service.get_config()


@router.put("", response_model=StatusLineConfig)
async def update_statusline_config(update: StatusLineUpdate):
    """
    Update the status line configuration.

    Args:
        update: Fields to update

    Returns:
        Updated status line configuration
    """
    try:
        return service.update_config(update)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update status line config: {str(e)}",
        )


@router.get("/presets", response_model=StatusLinePresetsResponse)
async def get_statusline_presets():
    """
    Get available status line presets.

    Returns:
        List of available presets
    """
    presets = service.get_presets()
    return StatusLinePresetsResponse(presets=presets)


@router.post("/apply-preset/{preset_id}", response_model=StatusLineConfig)
async def apply_statusline_preset(preset_id: str):
    """
    Apply a preset status line configuration.

    Args:
        preset_id: ID of the preset to apply

    Returns:
        Updated status line configuration
    """
    try:
        return service.apply_preset(preset_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply preset: {str(e)}",
        )


@router.post("/script", response_model=StatusLineConfig)
async def save_custom_script(script_content: str):
    """
    Save a custom status line script.

    Args:
        script_content: The script content to save

    Returns:
        Updated status line configuration
    """
    try:
        service.write_script(script_content)
        return service.update_config(
            StatusLineUpdate(
                type="command",
                command=str(service.default_script_path),
                enabled=True,
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save script: {str(e)}",
        )


@router.post("/preview", response_model=StatusLinePreviewResponse)
async def preview_statusline_script(request: StatusLinePreviewRequest):
    """
    Execute a status line script with mock data and return the rendered output.

    This endpoint is used for previewing how a status line will look
    before applying it.

    Args:
        request: StatusLinePreviewRequest containing the script to preview

    Returns:
        StatusLinePreviewResponse with the rendered output or error
    """
    try:
        success, output, error = service.preview_script(request.script)
        return StatusLinePreviewResponse(success=success, output=output, error=error)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview script: {str(e)}",
        )


# Powerline endpoints


@router.get("/check-nodejs", response_model=NodejsCheckResponse)
async def check_nodejs():
    """
    Check if Node.js is available on the system.

    Returns:
        NodejsCheckResponse with availability and version info
    """
    available, version = service.check_nodejs()
    return NodejsCheckResponse(available=available, version=version)


@router.get("/powerline-presets", response_model=PowerlinePresetsResponse)
async def get_powerline_presets():
    """
    Get available powerline theme presets.

    Returns:
        List of available powerline presets
    """
    presets = service.get_powerline_presets()
    return PowerlinePresetsResponse(presets=presets)


@router.post("/apply-powerline/{preset_id}", response_model=StatusLineConfig)
async def apply_powerline_preset(preset_id: str):
    """
    Apply a powerline preset status line configuration.

    Args:
        preset_id: ID of the powerline preset to apply

    Returns:
        Updated status line configuration
    """
    try:
        return service.apply_powerline_preset(preset_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply powerline preset: {str(e)}",
        )
