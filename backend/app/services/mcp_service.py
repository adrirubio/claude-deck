"""Service for managing MCP server configurations."""
import asyncio
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import MCPServerCache
from app.models.schemas import (
    MCPServer,
    MCPServerCreate,
    MCPServerUpdate,
    MCPTool,
    MCPServerApprovalSettings,
    MCPServerApprovalMode,
)
from app.utils.file_utils import read_json_file, write_json_file
from app.utils.path_utils import (
    get_claude_user_config_file,
    get_claude_user_settings_file,
    get_installed_plugins_file,
    get_managed_mcp_config_file,
    get_project_mcp_config_file,
)


class MCPService:
    """Service for managing MCP server configurations."""

    SENSITIVE_PATTERNS = ["KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"]

    @staticmethod
    def _mask_sensitive_env(env: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Mask sensitive environment variables containing KEY, TOKEN, or SECRET."""
        if not env:
            return env

        masked = {}
        for key, value in env.items():
            if any(pattern in key.upper() for pattern in MCPService.SENSITIVE_PATTERNS):
                masked[key] = "***MASKED***"
            else:
                masked[key] = value

        return masked

    def _create_mcp_server(
        self, name: str, config: Dict[str, Any], scope: str
    ) -> MCPServer:
        """Create an MCPServer instance from configuration."""
        return MCPServer(
            name=name,
            type=config.get("type", "stdio"),
            scope=scope,
            command=config.get("command"),
            args=config.get("args"),
            url=config.get("url"),
            headers=config.get("headers"),
            env=self._mask_sensitive_env(config.get("env")),
        )

    @staticmethod
    def _read_user_mcp_config(project_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Read MCP configuration from user-level ~/.claude.json.

        MCP servers can be defined in two places:
        1. Top-level mcpServers (global to all projects)
        2. Per-project in projects[path].mcpServers

        Args:
            project_path: Optional project path to read project-specific servers.
                         If None, only reads global servers.

        Returns:
            Dict of MCP server configurations
        """
        user_config_path = get_claude_user_config_file()
        config = read_json_file(user_config_path)

        if not config:
            return {}

        servers = {}

        # Read top-level mcpServers (global)
        if "mcpServers" in config:
            servers.update(config.get("mcpServers", {}))

        # Read project-specific mcpServers only if a project is active
        if project_path:
            projects = config.get("projects", {})
            if project_path in projects:
                project_config = projects[project_path]
                project_servers = project_config.get("mcpServers", {})
                servers.update(project_servers)

        return servers

    @staticmethod
    def _read_project_mcp_config(project_path: Optional[str] = None) -> Dict[str, Any]:
        """Read MCP configuration from project-level .mcp.json."""
        project_config_path = get_project_mcp_config_file(project_path)
        config = read_json_file(project_config_path)

        if not config or "mcpServers" not in config:
            return {}

        return config.get("mcpServers", {})

    @staticmethod
    def _read_plugin_mcp_servers() -> List[Dict[str, Any]]:
        """
        Read MCP servers from installed plugins.

        Plugins can define MCP servers in:
        1. .mcp.json file in the plugin root
        2. .claude-plugin/plugin.json under the "mcpServers" key

        The server names are prefixed with 'plugin:{plugin_name}:{server_name}'.

        Returns:
            List of MCP server configurations with metadata
        """
        installed_plugins_path = get_installed_plugins_file()
        installed_plugins = read_json_file(installed_plugins_path)

        if not installed_plugins or "plugins" not in installed_plugins:
            return []

        plugin_servers = []
        plugins_data = installed_plugins.get("plugins", {})

        for plugin_key, installations in plugins_data.items():
            # plugin_key format: "{plugin_name}@{marketplace}"
            if "@" not in plugin_key:
                continue

            plugin_name, marketplace = plugin_key.rsplit("@", 1)

            # Get the first (usually only) installation
            if not installations or not isinstance(installations, list):
                continue

            installation = installations[0]
            install_path = installation.get("installPath")

            if not install_path:
                continue

            install_path = Path(install_path)
            mcp_servers = {}

            # Try .mcp.json first (legacy format)
            plugin_mcp_path = install_path / ".mcp.json"
            plugin_mcp_config = read_json_file(plugin_mcp_path)
            if plugin_mcp_config:
                mcp_servers.update(plugin_mcp_config)

            # Also check .claude-plugin/plugin.json for mcpServers
            plugin_json_path = install_path / ".claude-plugin" / "plugin.json"
            plugin_json = read_json_file(plugin_json_path)
            if plugin_json and "mcpServers" in plugin_json:
                mcp_servers.update(plugin_json["mcpServers"])

            if not mcp_servers:
                continue

            # Each key in mcp_servers is a server definition
            for server_name, server_config in mcp_servers.items():
                # Prefix with plugin identifier to match Claude Code's format
                # Format: plugin:{plugin_name}:{server_name}
                prefixed_name = f"plugin:{plugin_name}:{server_name}"
                plugin_servers.append({
                    "name": prefixed_name,
                    "config": server_config,
                    "plugin_name": plugin_name,
                    "marketplace": marketplace,
                })

        return plugin_servers

    @staticmethod
    def _read_managed_mcp_config() -> Dict[str, Any]:
        """
        Read MCP configuration from managed config file (read-only).
        
        This file is typically managed by enterprise/system admins and
        cannot be modified by users. Servers from this file are always
        enabled and marked with scope="managed".
        
        Returns:
            Dict of MCP server configurations
        """
        managed_config_path = get_managed_mcp_config_file()
        config = read_json_file(managed_config_path)
        
        if not config or "mcpServers" not in config:
            return {}
        
        return config.get("mcpServers", {})

    @staticmethod
    async def _write_user_mcp_config(servers: Dict[str, Any]) -> bool:
        """Write MCP configuration to user-level ~/.claude.json."""
        user_config_path = get_claude_user_config_file()
        config = read_json_file(user_config_path) or {}

        config["mcpServers"] = servers
        return await write_json_file(user_config_path, config)

    @staticmethod
    async def _write_project_mcp_config(
        servers: Dict[str, Any], project_path: Optional[str] = None
    ) -> bool:
        """Write MCP configuration to project-level .mcp.json."""
        project_config_path = get_project_mcp_config_file(project_path)
        config = read_json_file(project_config_path) or {}

        config["mcpServers"] = servers
        return await write_json_file(project_config_path, config)

    @staticmethod
    def _compute_config_hash(server_config: Dict[str, Any]) -> str:
        """Compute hash of server configuration for cache invalidation."""
        config_str = json.dumps(server_config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    async def get_cached_server_info(
        self, name: str, scope: str, db: AsyncSession
    ) -> Optional[MCPServerCache]:
        """Retrieve cached data for a server."""
        result = await db.execute(
            select(MCPServerCache).where(
                MCPServerCache.server_name == name,
                MCPServerCache.server_scope == scope,
            )
        )
        return result.scalar_one_or_none()

    async def update_server_cache(
        self,
        name: str,
        scope: str,
        test_result: Dict[str, Any],
        config_hash: str,
        db: AsyncSession,
    ) -> None:
        """Update or create cache entry after testing."""
        cache_entry = await self.get_cached_server_info(name, scope, db)

        tools_list = test_result.get("tools") or []
        is_success = test_result.get("success", False)
        now = datetime.utcnow()

        # Prepare common cache data
        cache_data = {
            "is_connected": is_success,
            "last_tested_at": now,
            "last_error": None if is_success else test_result.get("message"),
            "mcp_server_name": test_result.get("server_name"),
            "mcp_server_version": test_result.get("server_version"),
            "tools": tools_list,
            "tool_count": len(tools_list),
            "cached_at": now,
            "config_hash": config_hash,
        }

        if cache_entry:
            for key, value in cache_data.items():
                setattr(cache_entry, key, value)
        else:
            cache_entry = MCPServerCache(
                server_name=name,
                server_scope=scope,
                **cache_data,
            )
            db.add(cache_entry)

        await db.commit()

    async def invalidate_cache(
        self, name: str, scope: str, db: AsyncSession
    ) -> None:
        """Clear cache for a specific server."""
        cache_entry = await self.get_cached_server_info(name, scope, db)
        if cache_entry:
            await db.delete(cache_entry)
            await db.commit()

    async def list_servers(
        self, project_path: Optional[str] = None, db: Optional[AsyncSession] = None
    ) -> List[MCPServer]:
        """
        List all MCP servers from user, project, plugin, and managed scopes.

        Args:
            project_path: Optional path to project directory
            db: Optional database session for cache lookup

        Returns:
            List of MCPServer objects with cached data merged
        """
        servers = []

        # Read managed servers (admin-enforced, read-only)
        managed_servers = self._read_managed_mcp_config()
        for name, config in managed_servers.items():
            server = self._create_mcp_server(name, config, "managed")
            server.source = "enterprise"  # Mark source for UI
            servers.append(server)

        # Read user-level servers (including project-specific from ~/.claude.json)
        user_servers = self._read_user_mcp_config(project_path)
        for name, config in user_servers.items():
            servers.append(self._create_mcp_server(name, config, "user"))

        # Read project-level servers
        project_servers = self._read_project_mcp_config(project_path)
        for name, config in project_servers.items():
            servers.append(self._create_mcp_server(name, config, "project"))

        # Read plugin-provided servers
        plugin_servers = self._read_plugin_mcp_servers()
        for plugin_server in plugin_servers:
            server = self._create_mcp_server(
                plugin_server["name"], plugin_server["config"], "plugin"
            )
            server.source = plugin_server.get("plugin_name")
            servers.append(server)

        # Merge cached data if database session is provided
        if db:
            for server in servers:
                cache_entry = await self.get_cached_server_info(server.name, server.scope, db)
                if cache_entry:
                    server.is_connected = cache_entry.is_connected
                    server.last_tested_at = cache_entry.last_tested_at.isoformat() if cache_entry.last_tested_at else None
                    server.last_error = cache_entry.last_error
                    server.mcp_server_name = cache_entry.mcp_server_name
                    server.mcp_server_version = cache_entry.mcp_server_version
                    server.tool_count = cache_entry.tool_count
                    # Convert tools from JSON to MCPTool objects
                    if cache_entry.tools:
                        server.tools = [MCPTool(**tool) for tool in cache_entry.tools]

        return servers

    async def get_server(self, name: str, scope: str) -> Optional[MCPServer]:
        """
        Get a specific MCP server configuration.

        Args:
            name: Server name
            scope: Server scope ("user", "project", "plugin", or "managed")

        Returns:
            MCPServer object or None if not found
        """
        if scope == "managed":
            servers = self._read_managed_mcp_config()
            if name not in servers:
                return None
            server = self._create_mcp_server(name, servers[name], scope)
            server.source = "enterprise"
            return server
        elif scope == "user":
            servers = self._read_user_mcp_config()
            if name not in servers:
                return None
            return self._create_mcp_server(name, servers[name], scope)
        elif scope == "project":
            servers = self._read_project_mcp_config()
            if name not in servers:
                return None
            return self._create_mcp_server(name, servers[name], scope)
        elif scope == "plugin":
            plugin_servers = self._read_plugin_mcp_servers()
            for plugin_server in plugin_servers:
                if plugin_server["name"] == name:
                    server = self._create_mcp_server(name, plugin_server["config"], scope)
                    server.source = plugin_server.get("plugin_name")
                    return server
            return None
        else:
            return None

    async def add_server(
        self, server: MCPServerCreate, project_path: Optional[str] = None
    ) -> MCPServer:
        """
        Add a new MCP server to the appropriate config file.

        Args:
            server: MCP server configuration to add
            project_path: Optional path to project directory

        Returns:
            Created MCPServer object
        """
        # Build config from server fields, excluding None values
        config = {"type": server.type}
        for field in ("command", "args", "url", "headers", "env"):
            value = getattr(server, field)
            if value:
                config[field] = value

        # Read, update, and write config
        if server.scope == "user":
            servers = self._read_user_mcp_config()
            servers[server.name] = config
            await self._write_user_mcp_config(servers)
        else:
            servers = self._read_project_mcp_config(project_path)
            servers[server.name] = config
            await self._write_project_mcp_config(servers, project_path)

        return self._create_mcp_server(server.name, config, server.scope)

    async def update_server(
        self,
        name: str,
        server: MCPServerUpdate,
        scope: str,
        project_path: Optional[str] = None,
    ) -> Optional[MCPServer]:
        """
        Update an existing MCP server configuration.

        Args:
            name: Server name
            server: Updated server configuration
            scope: Server scope ("user" or "project")
            project_path: Optional path to project directory

        Returns:
            Updated MCPServer object or None if not found
        """
        # Read existing servers
        if scope == "user":
            servers = self._read_user_mcp_config()
        else:
            servers = self._read_project_mcp_config(project_path)

        if name not in servers:
            return None

        # Update config with non-None values
        config = servers[name]
        for field in ("type", "command", "args", "url", "headers", "env"):
            value = getattr(server, field)
            if value is not None:
                config[field] = value

        servers[name] = config

        # Write updated config
        if scope == "user":
            await self._write_user_mcp_config(servers)
        else:
            await self._write_project_mcp_config(servers, project_path)

        return self._create_mcp_server(name, config, scope)

    async def remove_server(
        self, name: str, scope: str, project_path: Optional[str] = None
    ) -> bool:
        """
        Remove an MCP server from configuration.

        Args:
            name: Server name
            scope: Server scope ("user" or "project")
            project_path: Optional path to project directory

        Returns:
            True if removed, False if not found
        """
        # Read existing servers
        if scope == "user":
            servers = self._read_user_mcp_config()
        else:
            servers = self._read_project_mcp_config(project_path)

        if name not in servers:
            return False

        # Remove server
        del servers[name]

        # Write updated config
        if scope == "user":
            await self._write_user_mcp_config(servers)
        else:
            await self._write_project_mcp_config(servers, project_path)

        return True

    async def test_connection(
        self, name: str, scope: str, project_path: Optional[str] = None, db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Test connection to an MCP server.

        Args:
            name: Server name
            scope: Server scope ("user" or "project")
            project_path: Optional path to project directory
            db: Optional database session for caching results

        Returns:
            Dictionary with success status and message
        """
        # Get server config
        server = await self.get_server(name, scope)
        if not server:
            return {"success": False, "message": f"Server '{name}' not found"}

        # Test based on type
        if server.type == "stdio":
            # Check if command exists
            if not server.command:
                return {"success": False, "message": "No command specified for stdio server"}

            # First check if command exists
            command_path = shutil.which(server.command)
            if not command_path:
                return {
                    "success": False,
                    "message": f"Command '{server.command}' not found in PATH",
                }

            # Try to actually start the MCP server and send initialize
            process = None
            try:
                cmd = [server.command] + (server.args or [])
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Send MCP initialize request
                init_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "claude-deck-test", "version": "1.0.0"},
                    },
                }
                request_str = json.dumps(init_request)
                is_npx = server.command == "npx"

                # For npx commands, wait for server to be ready by monitoring stderr
                if is_npx:
                    for _ in range(60):  # up to 30 seconds
                        await asyncio.sleep(0.5)
                        if process.returncode is not None:
                            stderr_data = await process.stderr.read(4096)
                            error_output = stderr_data.decode().strip() if stderr_data else "Process exited"
                            return {
                                "success": False,
                                "message": f"Server failed: {error_output[:300]}",
                            }
                        try:
                            stderr = await asyncio.wait_for(process.stderr.read(4096), timeout=0.3)
                            if stderr and b"running on stdio" in stderr.lower() or b"server" in stderr.lower():
                                break
                        except asyncio.TimeoutError:
                            pass
                    await asyncio.sleep(0.5)  # Small delay after ready

                # Send request as raw JSON with newline (many MCP servers use this format)
                raw_message = request_str + "\n"
                process.stdin.write(raw_message.encode())
                await process.stdin.drain()

                # Give process time to respond or fail
                await asyncio.sleep(0.5)

                # Check if process already exited with error
                if process.returncode is not None:
                    stderr_data = await process.stderr.read(4096)
                    stdout_data = await process.stdout.read(4096)
                    error_output = stderr_data.decode().strip() if stderr_data else ""
                    if not error_output:
                        error_output = stdout_data.decode().strip() if stdout_data else "Process exited"
                    return {
                        "success": False,
                        "message": f"Server failed: {error_output[:300]}",
                    }

                # Read response - try raw JSON first (newline-delimited), then Content-Length format
                read_timeout = 30.0
                try:
                    response_line = await asyncio.wait_for(
                        process.stdout.readline(), timeout=read_timeout
                    )
                    if not response_line:
                        stderr_data = await process.stderr.read(4096)
                        stderr_str = stderr_data.decode().strip() if stderr_data else "No output"
                        return {
                            "success": False,
                            "message": f"Server closed without response: {stderr_str[:300]}",
                        }

                    response_str = response_line.decode().strip()

                    # Check if it's Content-Length header (LSP format) or raw JSON
                    if response_str.startswith("Content-Length:"):
                        content_length = int(response_str.split(":")[1].strip())
                        await asyncio.wait_for(process.stdout.readline(), timeout=5.0)  # blank line
                        json_data = await asyncio.wait_for(
                            process.stdout.readexactly(content_length), timeout=5.0
                        )
                        response = json.loads(json_data.decode())
                    else:
                        # Raw JSON format
                        response = json.loads(response_str)
                    if "result" in response:
                        server_info = response.get("result", {}).get("serverInfo", {})
                        server_name = server_info.get("name", "unknown")
                        server_version = server_info.get("version")

                        # Now fetch tools list
                        tools = []
                        try:
                            tools_request = {
                                "jsonrpc": "2.0",
                                "id": 2,
                                "method": "tools/list",
                                "params": {},
                            }
                            tools_msg = json.dumps(tools_request) + "\n"
                            process.stdin.write(tools_msg.encode())
                            await process.stdin.drain()

                            # Read tools response
                            tools_response_line = await asyncio.wait_for(
                                process.stdout.readline(), timeout=10.0
                            )
                            if tools_response_line:
                                tools_str = tools_response_line.decode().strip()
                                if tools_str.startswith("Content-Length:"):
                                    content_length = int(tools_str.split(":")[1].strip())
                                    await process.stdout.readline()  # blank line
                                    tools_data = await process.stdout.readexactly(content_length)
                                    tools_response = json.loads(tools_data.decode())
                                else:
                                    tools_response = json.loads(tools_str)

                                if "result" in tools_response:
                                    tools_list = tools_response["result"].get("tools", [])
                                    for tool in tools_list:
                                        tools.append({
                                            "name": tool.get("name", "unknown"),
                                            "description": tool.get("description"),
                                            "inputSchema": tool.get("inputSchema"),
                                        })
                        except Exception:
                            pass  # Tools fetch failed, but init succeeded

                        result = {
                            "success": True,
                            "message": f"MCP server '{server_name}' initialized successfully",
                            "server_name": server_name,
                            "server_version": server_version,
                            "tools": tools if tools else None,
                        }

                        # Cache the result if database session is provided
                        if db and server:
                            config_dict = {
                                "type": server.type,
                                "command": server.command,
                                "args": server.args,
                                "url": server.url,
                            }
                            config_hash = self._compute_config_hash(config_dict)
                            await self.update_server_cache(name, scope, result, config_hash, db)

                        return result
                    elif "error" in response:
                        error_msg = response["error"].get("message", "Unknown error")
                        return {"success": False, "message": f"MCP error: {error_msg}"}

                    return {
                        "success": True,
                        "message": f"Server responded (command: {server.command})",
                    }

                except asyncio.TimeoutError:
                    # Check if process exited with error
                    if process.returncode is not None:
                        stderr_data = await process.stderr.read(1024)
                        stderr_str = stderr_data.decode().strip() if stderr_data else "Unknown error"
                        return {
                            "success": False,
                            "message": f"Server exited: {stderr_str[:200]}",
                        }
                    return {
                        "success": False,
                        "message": "Server did not respond within timeout",
                    }
                except json.JSONDecodeError as e:
                    return {
                        "success": False,
                        "message": f"Invalid JSON response: {str(e)}",
                    }

            except FileNotFoundError:
                return {
                    "success": False,
                    "message": f"Command '{server.command}' not found",
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Failed to start server: {str(e)}",
                }
            finally:
                # Always clean up the process
                if process and process.returncode is None:
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except Exception:
                        process.kill()

        elif server.type == "http":
            # Make HEAD request to URL
            if not server.url:
                return {"success": False, "message": "No URL specified for http server"}

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.head(
                        server.url,
                        headers=server.headers or {},
                        follow_redirects=True,
                    )
                    if response.status_code < 400:
                        return {
                            "success": True,
                            "message": f"HTTP server responded with status {response.status_code}",
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"HTTP server returned error status {response.status_code}",
                        }
            except httpx.TimeoutException:
                return {"success": False, "message": "Connection timeout"}
            except httpx.RequestError as e:
                return {"success": False, "message": f"Request error: {str(e)}"}
            except Exception as e:
                return {"success": False, "message": f"Unexpected error: {str(e)}"}

        elif server.type == "sse":
            # Test SSE (Server-Sent Events) connection
            if not server.url:
                return {"success": False, "message": "No URL specified for SSE server"}

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # SSE servers should respond to GET with text/event-stream
                    # First try a HEAD request to check availability
                    headers = {**(server.headers or {}), "Accept": "text/event-stream"}
                    response = await client.get(
                        server.url,
                        headers=headers,
                        follow_redirects=True,
                        timeout=5.0,
                    )
                    
                    content_type = response.headers.get("content-type", "")
                    
                    if response.status_code < 400:
                        if "text/event-stream" in content_type:
                            return {
                                "success": True,
                                "message": f"SSE server connected (status {response.status_code})",
                            }
                        else:
                            return {
                                "success": True,
                                "message": f"Server responded (status {response.status_code}, type: {content_type})",
                            }
                    else:
                        return {
                            "success": False,
                            "message": f"SSE server returned error status {response.status_code}",
                        }
            except httpx.TimeoutException:
                return {"success": False, "message": "Connection timeout"}
            except httpx.RequestError as e:
                return {"success": False, "message": f"Request error: {str(e)}"}
            except Exception as e:
                return {"success": False, "message": f"Unexpected error: {str(e)}"}

        else:
            return {"success": False, "message": f"Unknown server type: {server.type}"}

    def get_approval_settings(self) -> MCPServerApprovalSettings:
        """
        Get MCP server approval settings from user settings.

        These settings control automatic tool approval for MCP servers.

        Returns:
            MCPServerApprovalSettings object
        """
        settings_path = get_claude_user_settings_file()
        config = read_json_file(settings_path)

        if not config:
            return MCPServerApprovalSettings()

        mcp_settings = config.get("mcpServerApproval", {})
        default_mode = mcp_settings.get("defaultMode", "ask-every-time")
        server_overrides = []

        for server_name, mode in mcp_settings.get("serverOverrides", {}).items():
            server_overrides.append(
                MCPServerApprovalMode(server_name=server_name, mode=mode)
            )

        return MCPServerApprovalSettings(
            default_mode=default_mode,
            server_overrides=server_overrides,
        )

    async def update_approval_settings(
        self, settings: MCPServerApprovalSettings
    ) -> MCPServerApprovalSettings:
        """
        Update MCP server approval settings.

        Args:
            settings: New approval settings

        Returns:
            Updated MCPServerApprovalSettings object
        """
        settings_path = get_claude_user_settings_file()
        config = read_json_file(settings_path) or {}

        # Build the mcpServerApproval structure
        mcp_approval = {
            "defaultMode": settings.default_mode,
            "serverOverrides": {
                override.server_name: override.mode
                for override in settings.server_overrides
            },
        }

        config["mcpServerApproval"] = mcp_approval
        await write_json_file(settings_path, config)

        return settings
