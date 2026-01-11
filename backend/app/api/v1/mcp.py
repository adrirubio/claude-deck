"""MCP server management endpoints."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    MCPServer,
    MCPServerCreate,
    MCPServerListResponse,
    MCPServerUpdate,
    MCPTestConnectionRequest,
    MCPTestConnectionResponse,
)
from app.services.mcp_service import MCPService

router = APIRouter()
mcp_service = MCPService()


@router.get("/servers", response_model=MCPServerListResponse)
async def list_mcp_servers(
    project_path: Optional[str] = Query(None, description="Optional project path")
):
    """List all MCP servers from user and project scopes."""
    servers = await mcp_service.list_servers(project_path)
    return MCPServerListResponse(servers=servers)


@router.get("/servers/{name}", response_model=MCPServer)
async def get_mcp_server(
    name: str,
    scope: str = Query(..., description="Server scope (user or project)"),
    project_path: Optional[str] = Query(None, description="Optional project path"),
):
    """Get a specific MCP server configuration."""
    server = await mcp_service.get_server(name, scope)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found in '{scope}' scope")
    return server


@router.post("/servers", response_model=MCPServer, status_code=201)
async def create_mcp_server(
    server: MCPServerCreate,
    project_path: Optional[str] = Query(None, description="Optional project path"),
):
    """Add a new MCP server."""
    # Validate server type
    if server.type not in ["stdio", "http"]:
        raise HTTPException(status_code=400, detail="Server type must be 'stdio' or 'http'")

    # Validate scope
    if server.scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Server scope must be 'user' or 'project'")

    # Validate stdio requirements
    if server.type == "stdio" and not server.command:
        raise HTTPException(status_code=400, detail="Command is required for stdio servers")

    # Validate http requirements
    if server.type == "http" and not server.url:
        raise HTTPException(status_code=400, detail="URL is required for http servers")

    try:
        created_server = await mcp_service.add_server(server, project_path)
        return created_server
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create server: {str(e)}")


@router.put("/servers/{name}", response_model=MCPServer)
async def update_mcp_server(
    name: str,
    server: MCPServerUpdate,
    scope: str = Query(..., description="Server scope (user or project)"),
    project_path: Optional[str] = Query(None, description="Optional project path"),
):
    """Update an existing MCP server configuration."""
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Server scope must be 'user' or 'project'")

    try:
        updated_server = await mcp_service.update_server(name, server, scope, project_path)
        if not updated_server:
            raise HTTPException(status_code=404, detail=f"Server '{name}' not found in '{scope}' scope")
        return updated_server
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update server: {str(e)}")


@router.delete("/servers/{name}", status_code=204)
async def delete_mcp_server(
    name: str,
    scope: str = Query(..., description="Server scope (user or project)"),
    project_path: Optional[str] = Query(None, description="Optional project path"),
):
    """Remove an MCP server from configuration."""
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Server scope must be 'user' or 'project'")

    success = await mcp_service.remove_server(name, scope, project_path)
    if not success:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found in '{scope}' scope")


@router.post("/servers/{name}/test", response_model=MCPTestConnectionResponse)
async def test_mcp_server_connection(
    name: str,
    scope: str = Query(..., description="Server scope (user, project, or plugin)"),
    project_path: Optional[str] = Query(None, description="Optional project path"),
):
    """Test connection to an MCP server."""
    # Validate scope
    if scope not in ["user", "project", "plugin"]:
        raise HTTPException(status_code=400, detail="Server scope must be 'user', 'project', or 'plugin'")

    result = await mcp_service.test_connection(name, scope, project_path)
    return MCPTestConnectionResponse(
        success=result["success"],
        message=result["message"],
        server_name=result.get("server_name"),
        server_version=result.get("server_version"),
        tools=result.get("tools"),
    )
