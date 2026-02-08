"""MCP server management endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import (
    MCPServer,
    MCPServerCreate,
    MCPServerListResponse,
    MCPServerUpdate,
    MCPServerToggleRequest,
    MCPServerToggleResponse,
    MCPTestConnectionRequest,
    MCPTestConnectionResponse,
    MCPTestAllResult,
    MCPTestAllResponse,
    MCPServerApprovalSettings,
    MCPServerApprovalSettingsUpdate,
    MCPAuthStatus,
    MCPAuthStartResponse,
)
from app.services.mcp_service import MCPService
from app.services.credentials_service import CredentialsService
from app.services.oauth_service import MCPOAuthService

router = APIRouter()
mcp_service = MCPService()
credentials_service = CredentialsService()
oauth_service = MCPOAuthService()


@router.get("/servers", response_model=MCPServerListResponse)
async def list_mcp_servers(
    project_path: Optional[str] = Query(None, description="Optional project path"),
    db: AsyncSession = Depends(get_db)
):
    """List all MCP servers from user and project scopes with cached data."""
    servers = await mcp_service.list_servers(project_path, db)
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
    if server.type not in ["stdio", "http", "sse"]:
        raise HTTPException(status_code=400, detail="Server type must be 'stdio', 'http', or 'sse'")

    # Validate scope
    if server.scope not in ["user", "project"]:
        raise HTTPException(status_code=400, detail="Server scope must be 'user' or 'project'")

    # Validate stdio requirements
    if server.type == "stdio" and not server.command:
        raise HTTPException(status_code=400, detail="Command is required for stdio servers")

    # Validate http/sse requirements
    if server.type in ["http", "sse"] and not server.url:
        raise HTTPException(status_code=400, detail="URL is required for http/sse servers")

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


@router.post("/servers/{name}/toggle", response_model=MCPServerToggleResponse)
async def toggle_mcp_server(
    name: str,
    request: MCPServerToggleRequest,
):
    """Toggle an MCP server's disabled state."""
    try:
        success = await mcp_service.toggle_server(name, request.disabled)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to write settings file")
        return MCPServerToggleResponse(
            success=True,
            message=f"Server '{name}' {'disabled' if request.disabled else 'enabled'} successfully",
            server_name=name,
            disabled=request.disabled,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle server: {str(e)}")


@router.post("/servers/{name}/test", response_model=MCPTestConnectionResponse)
async def test_mcp_server_connection(
    name: str,
    scope: str = Query(..., description="Server scope (user, project, plugin, or managed)"),
    project_path: Optional[str] = Query(None, description="Optional project path"),
    db: AsyncSession = Depends(get_db)
):
    """Test connection to an MCP server and cache the results."""
    # Validate scope
    if scope not in ["user", "project", "plugin", "managed"]:
        raise HTTPException(status_code=400, detail="Server scope must be 'user', 'project', 'plugin', or 'managed'")

    result = await mcp_service.test_connection(name, scope, project_path, db)
    return MCPTestConnectionResponse(
        success=result["success"],
        message=result["message"],
        server_name=result.get("server_name"),
        server_version=result.get("server_version"),
        tools=result.get("tools"),
        resources=result.get("resources"),
        prompts=result.get("prompts"),
        resource_count=result.get("resource_count"),
        prompt_count=result.get("prompt_count"),
        capabilities=result.get("capabilities"),
    )


@router.post("/servers/test-all", response_model=MCPTestAllResponse)
async def test_all_servers(
    project_path: Optional[str] = Query(None, description="Optional project path"),
    db: AsyncSession = Depends(get_db),
):
    """Test all MCP servers sequentially and return summary results."""
    servers = await mcp_service.list_servers(project_path, db)
    results = []

    for server in servers:
        test_result = await mcp_service.test_connection(
            server.name, server.scope, project_path, db
        )
        results.append(MCPTestAllResult(
            server_name=server.name,
            scope=server.scope,
            success=test_result["success"],
            message=test_result["message"],
            tool_count=test_result.get("tool_count"),
            resource_count=test_result.get("resource_count"),
            prompt_count=test_result.get("prompt_count"),
        ))

    return MCPTestAllResponse(results=results)


@router.get("/servers/{name}/auth-status", response_model=MCPAuthStatus)
async def get_auth_status(
    name: str,
    scope: str = Query("user", description="Server scope"),
):
    """Check if server has stored OAuth token and its validity."""
    return MCPAuthStatus(**credentials_service.get_auth_status(name))


@router.post("/servers/{name}/auth/start", response_model=MCPAuthStartResponse)
async def start_auth(
    name: str,
    request: Request,
    scope: str = Query("user", description="Server scope"),
):
    """Start OAuth flow. Returns {auth_url, state} for frontend to open."""
    server = await mcp_service.get_server(name, scope)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found in '{scope}' scope")

    if not server.url:
        raise HTTPException(status_code=400, detail="OAuth authentication is only supported for HTTP/SSE servers with a URL")

    # Derive callback base URL from the incoming request
    callback_base_url = f"{request.url.scheme}://{request.url.netloc}"

    try:
        result = await oauth_service.start_auth(server.url, name, callback_base_url)
        return MCPAuthStartResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start OAuth flow: {str(e)}")


@router.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """OAuth callback. Exchanges code for token, returns HTML success page."""
    try:
        result = await oauth_service.handle_callback(code, state)
        server_name = result.get("server_name", "unknown")
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html>
<head><title>Authentication Successful</title>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0;
         background: #f8fafc; color: #1e293b; }}
  .card {{ text-align: center; padding: 2rem; border-radius: 12px;
           background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); max-width: 400px; }}
  .check {{ font-size: 3rem; margin-bottom: 1rem; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 0.5rem; }}
  p {{ color: #64748b; margin: 0; font-size: 0.875rem; }}
</style>
</head>
<body>
  <div class="card">
    <div class="check">&#10003;</div>
    <h1>Authenticated!</h1>
    <p>Server <strong>{server_name}</strong> has been authenticated.<br>You can close this tab.</p>
  </div>
  <script>
    // Notify opener and auto-close after a short delay
    if (window.opener) {{
      window.opener.postMessage({{ type: 'mcp-oauth-complete', serverName: '{server_name}' }}, '*');
    }}
    setTimeout(() => window.close(), 3000);
  </script>
</body>
</html>""")
    except ValueError as e:
        return HTMLResponse(status_code=400, content=f"""<!DOCTYPE html>
<html>
<head><title>Authentication Failed</title>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0;
         background: #fef2f2; color: #991b1b; }}
  .card {{ text-align: center; padding: 2rem; border-radius: 12px;
           background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); max-width: 400px; }}
  .x {{ font-size: 3rem; margin-bottom: 1rem; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 0.5rem; }}
  p {{ color: #64748b; margin: 0; font-size: 0.875rem; }}
</style>
</head>
<body>
  <div class="card">
    <div class="x">&#10007;</div>
    <h1>Authentication Failed</h1>
    <p>{str(e)}</p>
  </div>
</body>
</html>""")


@router.get("/approval-settings", response_model=MCPServerApprovalSettings)
async def get_approval_settings():
    """Get MCP server approval settings."""
    return mcp_service.get_approval_settings()


@router.put("/approval-settings", response_model=MCPServerApprovalSettings)
async def update_approval_settings(settings: MCPServerApprovalSettingsUpdate):
    """Update MCP server approval settings."""
    # Build full settings from update
    current = mcp_service.get_approval_settings()
    
    updated = MCPServerApprovalSettings(
        default_mode=settings.default_mode or current.default_mode,
        server_overrides=settings.server_overrides if settings.server_overrides is not None else current.server_overrides,
    )
    
    return await mcp_service.update_approval_settings(updated)
