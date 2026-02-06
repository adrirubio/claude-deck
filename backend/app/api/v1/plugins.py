"""
Plugin API endpoints for Claude Deck
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...services.plugin_service import PluginService
from ...models.schemas import (
    PluginListResponse,
    Plugin,
    PluginInstallRequest,
    PluginInstallResponse,
    PluginToggleRequest,
    PluginToggleResponse,
    MarketplaceCreate,
    MarketplaceResponse,
    MarketplaceListResponse,
    MarketplacePluginListResponse,
    PluginUpdatesResponse,
    PluginUpdateResponse,
    PluginUpdateAllResponse,
    PluginValidationResult,
    PluginValidateRequest,
    AvailablePluginsResponse,
)

router = APIRouter()


@router.get("/plugins", response_model=PluginListResponse)
def list_plugins(
    project_path: Optional[str] = Query(None, description="Optional project path")
):
    """
    List all installed plugins from user and project scopes.

    Scans for directories containing .claude-plugin/plugin.json files.
    """
    try:
        service = PluginService()
        return service.list_installed_plugins(project_path=project_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list plugins: {str(e)}")


# Marketplace Management Endpoints (must come before /plugins/{name})


@router.get("/plugins/marketplaces")
def list_marketplaces():
    """
    List all configured plugin marketplaces.

    Reads from Claude's known_marketplaces.json file.
    """
    try:
        service = PluginService()
        marketplaces = service.list_marketplaces_from_files()
        return {"marketplaces": marketplaces}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list marketplaces: {str(e)}"
        )


@router.post("/plugins/marketplaces", status_code=201)
def add_marketplace(marketplace: MarketplaceCreate):
    """
    Add a new plugin marketplace via Claude CLI.

    Uses `claude plugin marketplace add` to clone the repo and discover plugins.
    Accepts GitHub repo (owner/repo) format.
    """
    if not marketplace.input:
        raise HTTPException(status_code=400, detail="Marketplace input is required")

    try:
        service = PluginService()
        result = service.add_marketplace_via_cli(marketplace.input)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to add marketplace: {str(e)}"
        )


@router.delete("/plugins/marketplaces/{name}")
def remove_marketplace(name: str):
    """
    Remove a plugin marketplace via Claude CLI.

    Uses `claude plugin marketplace remove` to remove the marketplace.
    """
    try:
        service = PluginService()
        result = service.remove_marketplace_via_cli(name)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to remove marketplace: {str(e)}"
        )


@router.get("/plugins/marketplace/{name}/browse")
def browse_marketplace(name: str):
    """
    Browse plugins available in a marketplace.

    Reads from the marketplace's local clone (.claude-plugin/marketplace.json).
    """
    try:
        service = PluginService()
        plugins = service.browse_marketplace_from_files(name)
        return {"plugins": plugins}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to browse marketplace: {str(e)}"
        )


@router.post("/plugins/marketplace/{name}/update", status_code=200)
def update_marketplace(name: str):
    """
    Update a marketplace via Claude CLI.

    Uses `claude plugin marketplace update` to fetch the latest from the repo.
    """
    try:
        service = PluginService()
        result = service.update_marketplace_via_cli(name)

        if not result["success"]:
            raise HTTPException(
                status_code=400,
                detail=result["message"]
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update marketplace: {str(e)}"
        )


@router.put("/plugins/marketplace/{name}/auto-update", status_code=200)
def set_marketplace_auto_update(name: str, request: dict):
    """
    Set auto-update preference for a marketplace.

    Args:
        name: Marketplace name
        request: { "enabled": bool }
    """
    try:
        enabled = request.get("enabled", False)
        service = PluginService()
        success = service.set_marketplace_auto_update(name, enabled)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to save auto-update setting"
            )

        return {"success": True, "name": name, "auto_update": enabled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to set auto-update: {str(e)}"
        )


# Plugin Updates Endpoints


@router.get("/plugins/updates", response_model=PluginUpdatesResponse)
def check_plugin_updates():
    """
    Check for available plugin updates.

    Compares installed plugins with marketplace versions and returns
    plugins that have available updates.
    """
    try:
        service = PluginService()
        return service.check_for_updates()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to check for updates: {str(e)}"
        )


@router.get("/plugins/available", response_model=AvailablePluginsResponse)
def get_all_available_plugins():
    """
    Get all available plugins from all configured marketplaces.

    Returns a combined list of plugins from all marketplaces.
    """
    try:
        service = PluginService()
        plugins = service.get_all_available_plugins()
        return AvailablePluginsResponse(plugins=plugins)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get available plugins: {str(e)}"
        )


@router.post("/plugins/validate", response_model=PluginValidationResult)
def validate_plugin(request: PluginValidateRequest):
    """
    Validate a plugin at the given path.

    Checks for required files and valid plugin.json structure.
    """
    try:
        service = PluginService()
        return service.validate_plugin(request.path)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to validate plugin: {str(e)}"
        )


@router.post("/plugins/update-all", response_model=PluginUpdateAllResponse)
def update_all_plugins():
    """
    Update all plugins that have available updates.
    """
    try:
        service = PluginService()
        return service.update_all_plugins()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update plugins: {str(e)}"
        )


@router.post("/plugins/{name}/update", response_model=PluginUpdateResponse)
def update_plugin(name: str):
    """
    Update a specific plugin.

    Uses the Claude CLI to update the plugin.
    """
    try:
        service = PluginService()
        return service.update_plugin(name)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update plugin: {str(e)}"
        )


# Plugin Management Endpoints (must come after marketplace endpoints)


@router.post("/plugins/install", response_model=PluginInstallResponse)
def install_plugin(request: PluginInstallRequest):
    """
    Install a plugin from a marketplace.

    Uses the Claude CLI to execute the installation.
    """
    try:
        service = PluginService()
        return service.install_plugin(request)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to install plugin: {str(e)}"
        )


@router.post("/plugins/{name}/toggle", response_model=PluginToggleResponse)
async def toggle_plugin(name: str, request: PluginToggleRequest):
    """
    Toggle a plugin's enabled/disabled state.

    Updates the enabledPlugins setting in ~/.claude/settings.json.
    """
    try:
        service = PluginService()
        return await service.toggle_plugin(
            name=name,
            enabled=request.enabled,
            source=request.source,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to toggle plugin: {str(e)}"
        )


@router.get("/plugins/{name}", response_model=Plugin)
def get_plugin(
    name: str,
    project_path: Optional[str] = Query(None, description="Optional project path")
):
    """
    Get details about a specific installed plugin.

    Returns plugin metadata and components list.
    """
    try:
        service = PluginService()
        plugin = service.get_plugin_details(name, project_path=project_path)

        if not plugin:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

        return plugin
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get plugin details: {str(e)}"
        )


@router.delete("/plugins/{name}", status_code=204)
def uninstall_plugin(
    name: str,
    project_path: Optional[str] = Query(None, description="Optional project path")
):
    """
    Uninstall a plugin by removing its directory.

    Returns 204 No Content on success, 404 if plugin not found.
    """
    try:
        service = PluginService()
        success = service.uninstall_plugin(name, project_path=project_path)

        if not success:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to uninstall plugin: {str(e)}"
        )
