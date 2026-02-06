"""
Plugin Service for Claude Deck

Manages plugin listing, installation, and marketplace operations.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from ..models.database import Marketplace
from ..models.schemas import (
    Plugin,
    PluginComponent,
    PluginHook,
    PluginLSPConfig,
    PluginListResponse,
    MarketplacePlugin,
    MarketplacePluginListResponse,
    MarketplaceCreate,
    MarketplaceResponse,
    MarketplaceListResponse,
    PluginInstallRequest,
    PluginInstallResponse,
    PluginToggleResponse,
    PluginUpdateInfo,
    PluginUpdatesResponse,
    PluginValidationResult,
    PluginUpdateResponse,
    PluginUpdateAllResponse,
)
from ..utils.path_utils import (
    get_claude_user_plugins_dir,
    get_project_plugins_dir,
    get_claude_user_settings_file,
    get_known_marketplaces_file,
    get_marketplaces_dir,
    ensure_directory_exists,
)
from ..utils.file_utils import read_json_file, write_json_file
from .cli_executor import CLIExecutor
from .plugin_descriptions import get_plugin_info


class PluginService:
    """Service for managing Claude Code plugins."""

    def __init__(self, db: Optional[AsyncSession] = None):
        """Initialize plugin service."""
        self.db = db
        self.cli_executor = CLIExecutor()
        self._marketplace_cache: Dict[str, List[MarketplacePlugin]] = {}

    def list_installed_plugins(
        self, project_path: Optional[str] = None
    ) -> PluginListResponse:
        """
        List all installed plugins from user and project scopes.

        Includes:
        - Locally installed plugins (directories with .claude-plugin/plugin.json)
        - Enabled plugins from settings.json (enabledPlugins configuration)

        Args:
            project_path: Optional project directory path

        Returns:
            PluginListResponse with list of installed plugins
        """
        plugins = []

        # First, get enabled plugins from settings.json
        plugins.extend(self._get_enabled_plugins_from_settings())

        # User-level local plugins
        user_plugins_dir = get_claude_user_plugins_dir()
        if user_plugins_dir.exists():
            local_plugins = self._scan_plugins_directory(user_plugins_dir, scope="user")
            # Mark local plugins and avoid duplicates
            for plugin in local_plugins:
                plugin.source = "local"
                if not any(p.name == plugin.name for p in plugins):
                    plugins.append(plugin)

        # Project-level local plugins
        if project_path:
            project_plugins_dir = get_project_plugins_dir(project_path)
            if project_plugins_dir.exists():
                local_plugins = self._scan_plugins_directory(project_plugins_dir, scope="project")
                for plugin in local_plugins:
                    plugin.source = "local-project"
                    if not any(p.name == plugin.name for p in plugins):
                        plugins.append(plugin)

        return PluginListResponse(plugins=plugins)

    def _get_enabled_plugins_from_settings(self) -> List[Plugin]:
        """
        Read enabled plugins from ~/.claude/settings.json.

        The enabledPlugins setting has the format:
        {
            "enabledPlugins": {
                "plugin-name@source": true/false,
                ...
            }
        }

        Returns:
            List of Plugin objects for enabled plugins
        """
        plugins = []

        settings_file = get_claude_user_settings_file()
        if not settings_file.exists():
            return plugins

        settings_data = read_json_file(settings_file)
        if not settings_data:
            return plugins

        enabled_plugins = settings_data.get("enabledPlugins", {})
        if not isinstance(enabled_plugins, dict):
            return plugins

        for plugin_key, is_enabled in enabled_plugins.items():
            # Parse plugin key format: "name@source" or just "name"
            if "@" in plugin_key:
                name, source = plugin_key.rsplit("@", 1)
            else:
                name = plugin_key
                source = "unknown"

            # Look up detailed info from hardcoded descriptions
            plugin_info = get_plugin_info(name)

            if plugin_info:
                plugins.append(
                    Plugin(
                        name=name,
                        source=source,
                        enabled=bool(is_enabled),
                        description=plugin_info.get("description", f"Plugin from {source}"),
                        usage=plugin_info.get("usage"),
                        examples=plugin_info.get("examples"),
                    )
                )
            else:
                plugins.append(
                    Plugin(
                        name=name,
                        source=source,
                        enabled=bool(is_enabled),
                        description=f"Plugin from {source}",
                    )
                )

        return plugins

    def _scan_plugins_directory(self, plugins_dir: Path, scope: str = "user") -> List[Plugin]:
        """
        Scan a plugins directory for installed plugins.

        Looks for directories containing .claude-plugin/plugin.json.

        Args:
            plugins_dir: Path to plugins directory
            scope: Installation scope ("user", "project", "local")

        Returns:
            List of Plugin objects
        """
        plugins = []

        if not plugins_dir.exists():
            return plugins

        # Iterate through subdirectories
        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            # Check for .claude-plugin/plugin.json
            plugin_json_path = plugin_dir / ".claude-plugin" / "plugin.json"
            if plugin_json_path.exists():
                try:
                    with open(plugin_json_path, "r", encoding="utf-8") as f:
                        plugin_data = json.load(f)

                    # Parse components with better aggregation
                    components = []
                    skill_count = 0
                    agent_count = 0
                    hook_count = 0
                    mcp_count = 0
                    lsp_count = 0

                    if "components" in plugin_data:
                        for comp in plugin_data["components"]:
                            comp_type = comp.get("type", "")
                            components.append(
                                PluginComponent(
                                    type=comp_type,
                                    name=comp.get("name", ""),
                                    description=comp.get("description"),
                                )
                            )
                            # Count by type
                            if comp_type == "skill" or comp_type == "command":
                                skill_count += 1
                            elif comp_type == "agent":
                                agent_count += 1
                            elif comp_type == "hook":
                                hook_count += 1
                            elif comp_type == "mcp":
                                mcp_count += 1
                            elif comp_type == "lsp":
                                lsp_count += 1

                    # Scan for additional components in directories
                    skill_count += self._count_directory_items(plugin_dir / "skills")
                    agent_count += self._count_directory_items(plugin_dir / "agents")
                    mcp_count += self._count_directory_items(plugin_dir / "mcp-servers")

                    # Parse hooks from hooks/hooks.json
                    hooks = self._parse_plugin_hooks(plugin_dir)
                    if hooks:
                        hook_count = len(hooks)

                    # Parse LSP configs from .lsp.json
                    lsp_configs = self._parse_lsp_config(plugin_dir)
                    if lsp_configs:
                        lsp_count = len(lsp_configs)

                    # Read README.md if it exists
                    readme_content = self._read_plugin_readme(plugin_dir)

                    plugin = Plugin(
                        name=plugin_data.get("name", plugin_dir.name),
                        version=plugin_data.get("version"),
                        description=plugin_data.get("description"),
                        author=plugin_data.get("author"),
                        category=plugin_data.get("category"),
                        scope=scope,
                        components=components,
                        skill_count=skill_count,
                        agent_count=agent_count,
                        hook_count=hook_count,
                        mcp_count=mcp_count,
                        lsp_count=lsp_count,
                        usage=plugin_data.get("usage"),
                        examples=plugin_data.get("examples"),
                        readme=readme_content,
                        hooks=hooks,
                        lsp_configs=lsp_configs,
                    )
                    plugins.append(plugin)
                except Exception as e:
                    # Skip plugins with invalid plugin.json
                    print(f"Warning: Failed to parse {plugin_json_path}: {e}")
                    continue

        return plugins

    def _count_directory_items(self, directory: Path) -> int:
        """Count items in a directory (for component counting)."""
        if not directory.exists():
            return 0
        return len([d for d in directory.iterdir() if d.is_dir() or d.suffix == ".md"])

    def _parse_plugin_hooks(self, plugin_dir: Path) -> Optional[List[PluginHook]]:
        """
        Parse hooks from a plugin's hooks/hooks.json file.

        Args:
            plugin_dir: Path to plugin directory

        Returns:
            List of PluginHook objects or None
        """
        hooks_json_path = plugin_dir / "hooks" / "hooks.json"
        if not hooks_json_path.exists():
            return None

        try:
            with open(hooks_json_path, "r", encoding="utf-8") as f:
                hooks_data = json.load(f)

            hooks = []
            # hooks.json can be a dict with event names as keys or a list
            if isinstance(hooks_data, dict):
                for event, hook_list in hooks_data.items():
                    if isinstance(hook_list, list):
                        for hook in hook_list:
                            hooks.append(
                                PluginHook(
                                    event=event,
                                    type=hook.get("type", "command"),
                                    matcher=hook.get("matcher"),
                                    command=hook.get("command"),
                                    prompt=hook.get("prompt"),
                                )
                            )
            elif isinstance(hooks_data, list):
                for hook in hooks_data:
                    hooks.append(
                        PluginHook(
                            event=hook.get("event", ""),
                            type=hook.get("type", "command"),
                            matcher=hook.get("matcher"),
                            command=hook.get("command"),
                            prompt=hook.get("prompt"),
                        )
                    )
            return hooks if hooks else None
        except Exception as e:
            print(f"Warning: Failed to parse hooks.json: {e}")
            return None

    def _parse_lsp_config(self, plugin_dir: Path) -> Optional[List[PluginLSPConfig]]:
        """
        Parse LSP configuration from plugin's .lsp.json file.

        Args:
            plugin_dir: Path to plugin directory

        Returns:
            List of PluginLSPConfig objects or None
        """
        lsp_json_path = plugin_dir / ".lsp.json"
        if not lsp_json_path.exists():
            # Also check in .claude-plugin directory
            lsp_json_path = plugin_dir / ".claude-plugin" / ".lsp.json"
            if not lsp_json_path.exists():
                return None

        try:
            with open(lsp_json_path, "r", encoding="utf-8") as f:
                lsp_data = json.load(f)

            configs = []
            # Can be a single config or list of configs
            if isinstance(lsp_data, dict):
                if "servers" in lsp_data:
                    # Multiple servers format
                    for server in lsp_data["servers"]:
                        configs.append(
                            PluginLSPConfig(
                                name=server.get("name", ""),
                                language=server.get("language", ""),
                                command=server.get("command", ""),
                                args=server.get("args"),
                                env=server.get("env"),
                            )
                        )
                else:
                    # Single server format
                    configs.append(
                        PluginLSPConfig(
                            name=lsp_data.get("name", ""),
                            language=lsp_data.get("language", ""),
                            command=lsp_data.get("command", ""),
                            args=lsp_data.get("args"),
                            env=lsp_data.get("env"),
                        )
                    )
            elif isinstance(lsp_data, list):
                for server in lsp_data:
                    configs.append(
                        PluginLSPConfig(
                            name=server.get("name", ""),
                            language=server.get("language", ""),
                            command=server.get("command", ""),
                            args=server.get("args"),
                            env=server.get("env"),
                        )
                    )
            return configs if configs else None
        except Exception as e:
            print(f"Warning: Failed to parse .lsp.json: {e}")
            return None

    def _read_plugin_readme(self, plugin_dir: Path) -> Optional[str]:
        """
        Read README.md from a plugin directory.

        Looks for README.md in the plugin directory or .claude-plugin subdirectory.

        Args:
            plugin_dir: Path to plugin directory

        Returns:
            README content as string, or None if not found
        """
        # Check common README locations
        readme_paths = [
            plugin_dir / "README.md",
            plugin_dir / "readme.md",
            plugin_dir / ".claude-plugin" / "README.md",
            plugin_dir / ".claude-plugin" / "readme.md",
        ]

        for readme_path in readme_paths:
            if readme_path.exists():
                try:
                    with open(readme_path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    continue

        return None

    def get_plugin_details(
        self, name: str, project_path: Optional[str] = None
    ) -> Optional[Plugin]:
        """
        Get detailed information about a specific plugin.

        Args:
            name: Plugin name
            project_path: Optional project directory path

        Returns:
            Plugin object or None if not found
        """
        # Check user plugins
        user_plugins_dir = get_claude_user_plugins_dir()
        plugin_path = user_plugins_dir / name / ".claude-plugin" / "plugin.json"

        if not plugin_path.exists() and project_path:
            # Check project plugins
            project_plugins_dir = get_project_plugins_dir(project_path)
            plugin_path = project_plugins_dir / name / ".claude-plugin" / "plugin.json"

        if not plugin_path.exists():
            return None

        try:
            with open(plugin_path, "r", encoding="utf-8") as f:
                plugin_data = json.load(f)

            # Parse components
            components = []
            if "components" in plugin_data:
                for comp in plugin_data["components"]:
                    components.append(
                        PluginComponent(
                            type=comp.get("type", ""),
                            name=comp.get("name", ""),
                        )
                    )

            return Plugin(
                name=plugin_data.get("name", name),
                version=plugin_data.get("version"),
                description=plugin_data.get("description"),
                author=plugin_data.get("author"),
                category=plugin_data.get("category"),
                components=components,
            )
        except Exception as e:
            print(f"Error reading plugin details: {e}")
            return None

    def _enhance_git_error_message(self, stderr: str, stdout: str) -> str:
        """
        Detect common git/SSH errors and provide helpful suggestions.

        Args:
            stderr: Standard error output from CLI
            stdout: Standard output from CLI

        Returns:
            Enhanced error message with suggestions
        """
        combined_output = f"{stderr}\n{stdout}".lower()

        # Detect SSH authentication failure
        if "permission denied" in combined_output and "publickey" in combined_output:
            return (
                "Failed to clone repository: SSH authentication failed.\n\n"
                "This usually means the plugin repository is private or requires authentication.\n\n"
                "For private repositories:\n"
                "• Set up SSH keys: Add your SSH public key to GitHub\n"
                "• Or use GitHub CLI: Run 'gh auth login' to authenticate\n\n"
                "For public repositories:\n"
                "• This should not happen - please report this issue\n\n"
                f"Original error:\n{stderr}"
            )

        # Detect other common git errors
        if "could not read from remote repository" in combined_output:
            return (
                "Failed to access remote repository. Please verify:\n"
                "• The repository exists and is accessible\n"
                "• You have the correct access permissions\n"
                "• Your network connection is working\n\n"
                f"Original error:\n{stderr}"
            )

        # Return original error if no enhancement needed
        return stderr

    def install_plugin(
        self, request: PluginInstallRequest
    ) -> PluginInstallResponse:
        """
        Install a plugin using the Claude CLI.

        Args:
            request: Plugin installation request

        Returns:
            PluginInstallResponse with installation result
        """
        # For now, we'll use a simple install command
        # In the future, this could use marketplace-specific install commands
        try:
            # Configure git to use HTTPS instead of SSH for GitHub
            # This allows cloning public repos without SSH keys
            import os
            env = os.environ.copy()
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "url.https://github.com/.insteadOf"
            env["GIT_CONFIG_VALUE_0"] = "git@github.com:"

            result = self.cli_executor.execute(
                "plugin", ["install", request.name], timeout=120, env=env
            )

            success = result.exit_code == 0

            if success:
                message = f"Successfully installed plugin '{request.name}'"
                enhanced_stderr = result.stderr
            else:
                # Enhance error message if it's a known issue
                enhanced_stderr = self._enhance_git_error_message(
                    result.stderr, result.stdout
                )
                message = f"Failed to install plugin '{request.name}'"

            return PluginInstallResponse(
                success=success,
                message=message,
                stdout=result.stdout,
                stderr=enhanced_stderr,
            )
        except Exception as e:
            return PluginInstallResponse(
                success=False,
                message=f"Error installing plugin: {str(e)}",
                stdout="",
                stderr=str(e),
            )

    def uninstall_plugin(
        self, name: str, project_path: Optional[str] = None
    ) -> bool:
        """
        Uninstall a plugin by removing its directory and updating config files.

        Args:
            name: Plugin name (can be 'plugin-name' or 'plugin-name@marketplace')
            project_path: Optional project directory path

        Returns:
            True if uninstalled successfully, False otherwise
        """
        removed_any = False
        matching_key = None

        # Try to remove from installed_plugins.json
        installed_plugins_file = get_claude_user_plugins_dir() / "installed_plugins.json"
        if installed_plugins_file.exists():
            try:
                with open(installed_plugins_file, "r") as f:
                    data = json.load(f)

                plugins = data.get("plugins", {})

                # Find matching plugin key
                for key in plugins.keys():
                    if key == name or key.startswith(f"{name}@"):
                        matching_key = key
                        break

                if matching_key:
                    # Remove installation directories
                    plugin_entries = plugins.get(matching_key, [])
                    for entry in plugin_entries:
                        install_path = entry.get("installPath")
                        if install_path:
                            plugin_dir = Path(install_path)
                            if plugin_dir.exists():
                                try:
                                    shutil.rmtree(plugin_dir)
                                    removed_any = True
                                except Exception as e:
                                    print(f"Error removing plugin directory {plugin_dir}: {e}")

                    # Remove from installed_plugins.json
                    del plugins[matching_key]
                    with open(installed_plugins_file, "w") as f:
                        json.dump(data, f, indent=2)
                    removed_any = True
            except Exception as e:
                print(f"Error processing installed_plugins.json: {e}")

        # ALWAYS try to remove from settings.json (enabledPlugins)
        settings_file = get_claude_user_settings_file()
        if settings_file.exists():
            try:
                settings_data = read_json_file(settings_file) or {}
                enabled_plugins = settings_data.get("enabledPlugins", {})

                # Remove matching entries from enabledPlugins
                keys_to_remove = [
                    k for k in enabled_plugins.keys()
                    if k == name or k == matching_key or k.startswith(f"{name}@")
                ]
                for key in keys_to_remove:
                    del enabled_plugins[key]

                if keys_to_remove:
                    write_json_file(settings_file, settings_data)
                    removed_any = True
            except Exception as e:
                print(f"Error updating settings.json: {e}")

        return removed_any

    async def toggle_plugin(
        self, name: str, enabled: bool, source: Optional[str] = None
    ) -> PluginToggleResponse:
        """
        Toggle a plugin's enabled state in settings.json.

        Args:
            name: Plugin name
            enabled: Whether to enable or disable the plugin
            source: Plugin source (e.g., 'anthropic-agent-skills')

        Returns:
            PluginToggleResponse with success status and updated plugin
        """
        settings_file = get_claude_user_settings_file()

        # Read current settings
        settings_data = read_json_file(settings_file) or {}

        # Ensure enabledPlugins exists
        if "enabledPlugins" not in settings_data:
            settings_data["enabledPlugins"] = {}

        # Build plugin key
        if source:
            plugin_key = f"{name}@{source}"
        else:
            # Try to find existing key with this name
            existing_key = None
            for key in settings_data["enabledPlugins"].keys():
                if key == name or key.startswith(f"{name}@"):
                    existing_key = key
                    break
            plugin_key = existing_key or name

        # Update enabled state
        settings_data["enabledPlugins"][plugin_key] = enabled

        # Write back to settings file
        success = await write_json_file(settings_file, settings_data)

        if not success:
            return PluginToggleResponse(
                success=False,
                message=f"Failed to write settings file",
                plugin=None,
            )

        # Get updated plugin info
        plugin_info = get_plugin_info(name)
        plugin = Plugin(
            name=name,
            source=source or "unknown",
            enabled=enabled,
            description=plugin_info.get("description") if plugin_info else None,
            usage=plugin_info.get("usage") if plugin_info else None,
            examples=plugin_info.get("examples") if plugin_info else None,
        )

        return PluginToggleResponse(
            success=True,
            message=f"Plugin '{name}' {'enabled' if enabled else 'disabled'} successfully",
            plugin=plugin,
        )

    # Marketplace Management

    async def list_marketplaces(self) -> MarketplaceListResponse:
        """
        List all configured marketplaces from database.

        Returns:
            MarketplaceListResponse with list of marketplaces
        """
        if not self.db:
            return MarketplaceListResponse(marketplaces=[])

        result = await self.db.execute(select(Marketplace))
        marketplaces = result.scalars().all()

        marketplace_responses = [
            MarketplaceResponse(
                id=m.id,
                name=m.name,
                url=m.url,
                last_synced=m.last_synced.isoformat() if m.last_synced else None,
                created_at=m.created_at.isoformat(),
            )
            for m in marketplaces
        ]

        return MarketplaceListResponse(marketplaces=marketplace_responses)

    def _resolve_marketplace_input(self, input_str: str) -> tuple:
        """
        Resolve marketplace input to (name, url).

        Supports two formats:
        1. Full URL: https://example.com/plugins.json
        2. GitHub shorthand: owner/repo

        Args:
            input_str: Either "owner/repo" or full URL

        Returns:
            Tuple of (name, url)
        """
        input_str = input_str.strip()

        # Check if it's a URL
        if input_str.startswith(("http://", "https://")):
            # Extract name from URL path
            name = input_str.rstrip("/").split("/")[-1].replace(".json", "")
            return (name, input_str)

        # Assume owner/repo format
        if "/" in input_str:
            parts = input_str.split("/", 1)
            owner = parts[0]
            repo = parts[1]
            name = repo
            # Use raw GitHub URL for plugins.json in main branch
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/plugins.json"
            return (name, url)

        raise ValueError(
            f"Invalid marketplace input: '{input_str}'. "
            "Expected 'owner/repo' or full URL."
        )

    async def add_marketplace(
        self, marketplace: MarketplaceCreate
    ) -> MarketplaceResponse:
        """
        Add a new marketplace to the database.

        Supports smart input resolution for owner/repo format.

        Args:
            marketplace: Marketplace configuration

        Returns:
            MarketplaceResponse with created marketplace
        """
        if not self.db:
            raise ValueError("Database session required")

        # Smart resolution from input field
        if marketplace.input:
            resolved_name, resolved_url = self._resolve_marketplace_input(
                marketplace.input
            )
            # Use resolved values if not explicitly provided
            if not marketplace.name:
                marketplace.name = resolved_name
            if not marketplace.url:
                marketplace.url = resolved_url

        # Validate we have required fields
        if not marketplace.name or not marketplace.url:
            raise ValueError(
                "Marketplace name and URL are required. "
                "Provide them directly or use the 'input' field with 'owner/repo' format."
            )

        # Check if marketplace already exists
        result = await self.db.execute(
            select(Marketplace).where(Marketplace.name == marketplace.name)
        )
        existing = result.scalar_one_or_none()

        if existing:
            raise ValueError(f"Marketplace '{marketplace.name}' already exists")

        # Create new marketplace
        new_marketplace = Marketplace(
            name=marketplace.name,
            url=marketplace.url,
            last_synced=None,
            created_at=datetime.utcnow(),
        )

        self.db.add(new_marketplace)
        await self.db.commit()
        await self.db.refresh(new_marketplace)

        return MarketplaceResponse(
            id=new_marketplace.id,
            name=new_marketplace.name,
            url=new_marketplace.url,
            last_synced=None,
            created_at=new_marketplace.created_at.isoformat(),
        )

    async def remove_marketplace(self, name: str) -> bool:
        """
        Remove a marketplace from the database.

        Args:
            name: Marketplace name

        Returns:
            True if removed successfully, False otherwise
        """
        if not self.db:
            return False

        result = await self.db.execute(
            select(Marketplace).where(Marketplace.name == name)
        )
        marketplace = result.scalar_one_or_none()

        if not marketplace:
            return False

        await self.db.delete(marketplace)
        await self.db.commit()

        # Clear cache for this marketplace
        if name in self._marketplace_cache:
            del self._marketplace_cache[name]

        return True

    async def sync_marketplace(self, name: str) -> bool:
        """
        Sync marketplace catalog from remote URL.

        Fetches the marketplace catalog and caches it locally.

        Args:
            name: Marketplace name

        Returns:
            True if synced successfully, False otherwise
        """
        if not self.db:
            return False

        # Get marketplace from database
        result = await self.db.execute(
            select(Marketplace).where(Marketplace.name == name)
        )
        marketplace = result.scalar_one_or_none()

        if not marketplace:
            return False

        try:
            # Fetch marketplace catalog
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(marketplace.url)
                response.raise_for_status()
                catalog_data = response.json()

            # Parse catalog
            plugins = []
            if isinstance(catalog_data, dict) and "plugins" in catalog_data:
                for plugin_data in catalog_data["plugins"]:
                    plugins.append(
                        MarketplacePlugin(
                            name=plugin_data.get("name", ""),
                            description=plugin_data.get("description"),
                            version=plugin_data.get("version"),
                            install_command=plugin_data.get(
                                "install_command", f"plugin install {plugin_data.get('name', '')}"
                            ),
                        )
                    )

            # Cache the catalog
            self._marketplace_cache[name] = plugins

            # Update last_synced timestamp
            marketplace.last_synced = datetime.utcnow()
            await self.db.commit()

            return True
        except Exception as e:
            print(f"Error syncing marketplace: {e}")
            return False

    def browse_marketplace(self, name: str) -> MarketplacePluginListResponse:
        """
        Browse cached marketplace catalog.

        Args:
            name: Marketplace name

        Returns:
            MarketplacePluginListResponse with list of available plugins
        """
        plugins = self._marketplace_cache.get(name, [])
        return MarketplacePluginListResponse(plugins=plugins)

    # =========================================================================
    # CLI Passthrough Methods - Use Claude CLI for marketplace management
    # =========================================================================

    def add_marketplace_via_cli(self, marketplace_input: str) -> dict:
        """
        Add a marketplace using Claude CLI.

        This delegates to `claude plugin marketplace add` which handles:
        - Cloning the repository
        - Discovering plugins
        - Updating known_marketplaces.json

        Args:
            marketplace_input: GitHub repo (owner/repo) or full URL

        Returns:
            Dict with success status and message
        """
        result = self.cli_executor.execute(
            "plugin", ["marketplace", "add", marketplace_input], timeout=120
        )

        success = result.exit_code == 0
        return {
            "success": success,
            "message": result.stdout if success else result.stderr,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def remove_marketplace_via_cli(self, name: str) -> dict:
        """
        Remove a marketplace using Claude CLI.

        Args:
            name: Marketplace name

        Returns:
            Dict with success status and message
        """
        result = self.cli_executor.execute(
            "plugin", ["marketplace", "remove", name], timeout=60
        )
        return {
            "success": result.exit_code == 0,
            "message": result.stdout if result.exit_code == 0 else result.stderr,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def update_marketplace_via_cli(self, name: str) -> dict:
        """
        Update a marketplace using Claude CLI.

        Args:
            name: Marketplace name

        Returns:
            Dict with success status and message
        """
        result = self.cli_executor.execute(
            "plugin", ["marketplace", "update", name], timeout=120
        )
        return {
            "success": result.exit_code == 0,
            "message": result.stdout if result.exit_code == 0 else result.stderr,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # =========================================================================
    # File-based Methods - Read marketplace data from Claude's config files
    # =========================================================================

    def list_marketplaces_from_files(self) -> List[dict]:
        """
        List marketplaces from Claude's known_marketplaces.json.

        Returns:
            List of marketplace info dicts
        """
        known_file = get_known_marketplaces_file()
        known_data = read_json_file(known_file) or {}

        # Load auto-update settings
        auto_update_settings = self._load_marketplace_auto_update_settings()

        marketplaces = []
        for name, info in known_data.items():
            # Get plugin count from marketplace.json
            marketplace_json = (
                get_marketplaces_dir() / name / ".claude-plugin" / "marketplace.json"
            )
            marketplace_data = read_json_file(marketplace_json) or {}
            plugin_count = len(marketplace_data.get("plugins", []))

            marketplaces.append({
                "name": name,
                "repo": info.get("source", {}).get("repo", ""),
                "install_location": info.get("installLocation", ""),
                "last_updated": info.get("lastUpdated"),
                "plugin_count": plugin_count,
                "auto_update": auto_update_settings.get(name, False),
            })

        return marketplaces

    def _load_marketplace_auto_update_settings(self) -> Dict[str, bool]:
        """Load per-marketplace auto-update settings."""
        settings_file = get_claude_user_plugins_dir() / "marketplace_settings.json"
        if not settings_file.exists():
            return {}
        data = read_json_file(settings_file) or {}
        return data.get("auto_update", {})

    def set_marketplace_auto_update(self, name: str, enabled: bool) -> bool:
        """
        Set auto-update preference for a marketplace.

        Args:
            name: Marketplace name
            enabled: Whether auto-update is enabled

        Returns:
            True if saved successfully
        """
        settings_file = get_claude_user_plugins_dir() / "marketplace_settings.json"
        ensure_directory_exists(settings_file.parent)

        data = read_json_file(settings_file) or {}
        if "auto_update" not in data:
            data["auto_update"] = {}
        data["auto_update"][name] = enabled

        return write_json_file(settings_file, data)

    def browse_marketplace_from_files(self, name: str) -> List[dict]:
        """
        Browse plugins from a marketplace's local clone.

        Args:
            name: Marketplace name

        Returns:
            List of plugin info dicts
        """
        marketplace_json = (
            get_marketplaces_dir() / name / ".claude-plugin" / "marketplace.json"
        )
        marketplace_data = read_json_file(marketplace_json) or {}
        return marketplace_data.get("plugins", [])

    # =========================================================================
    # Plugin Update Methods
    # =========================================================================

    def check_for_updates(self) -> PluginUpdatesResponse:
        """
        Compare installed plugins with marketplace versions.

        Uses `claude plugin list --available --json` to get latest versions
        and compares with installed plugins.

        Returns:
            PluginUpdatesResponse with list of plugins that have updates
        """
        update_info_list = []

        # Get installed plugins
        installed_response = self.list_installed_plugins()
        installed_plugins = {p.name: p for p in installed_response.plugins}

        # Get all available plugins from marketplaces
        available_plugins = self.get_all_available_plugins()
        available_by_name = {p.name: p for p in available_plugins}

        # Compare versions
        for name, installed in installed_plugins.items():
            available = available_by_name.get(name)
            if available and available.version and installed.version:
                has_update = self._version_compare(installed.version, available.version) < 0
                if has_update:
                    update_info_list.append(
                        PluginUpdateInfo(
                            name=name,
                            installed_version=installed.version,
                            latest_version=available.version,
                            has_update=True,
                            source=installed.source,
                        )
                    )

        return PluginUpdatesResponse(
            plugins=update_info_list,
            outdated_count=len(update_info_list),
        )

    def _version_compare(self, v1: str, v2: str) -> int:
        """
        Compare two version strings.

        Returns:
            -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
        """
        def normalize(v):
            # Remove 'v' prefix if present
            v = v.lstrip('v')
            # Split by dots and convert to integers where possible
            parts = []
            for part in v.split('.'):
                try:
                    parts.append(int(part))
                except ValueError:
                    parts.append(part)
            return parts

        parts1 = normalize(v1)
        parts2 = normalize(v2)

        # Compare part by part
        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0

            if isinstance(p1, int) and isinstance(p2, int):
                if p1 < p2:
                    return -1
                elif p1 > p2:
                    return 1
            else:
                # String comparison for non-numeric parts
                if str(p1) < str(p2):
                    return -1
                elif str(p1) > str(p2):
                    return 1

        return 0

    def update_plugin(self, name: str) -> PluginUpdateResponse:
        """
        Update a plugin via CLI: claude plugin update <name>

        Args:
            name: Plugin name to update

        Returns:
            PluginUpdateResponse with update result
        """
        try:
            result = self.cli_executor.execute(
                "plugin", ["update", name], timeout=120
            )

            success = result.exit_code == 0
            return PluginUpdateResponse(
                success=success,
                message=f"Plugin '{name}' {'updated successfully' if success else 'update failed'}",
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except Exception as e:
            return PluginUpdateResponse(
                success=False,
                message=f"Error updating plugin: {str(e)}",
                stdout="",
                stderr=str(e),
            )

    def update_all_plugins(self) -> PluginUpdateAllResponse:
        """
        Update all outdated plugins.

        Returns:
            PluginUpdateAllResponse with results
        """
        updates = self.check_for_updates()
        results = []
        updated_count = 0
        failed_count = 0

        for plugin_info in updates.plugins:
            result = self.update_plugin(plugin_info.name)
            results.append(result)
            if result.success:
                updated_count += 1
            else:
                failed_count += 1

        return PluginUpdateAllResponse(
            success=failed_count == 0,
            message=f"Updated {updated_count} plugins, {failed_count} failed",
            updated_count=updated_count,
            failed_count=failed_count,
            results=results,
        )

    def get_all_available_plugins(self) -> List[MarketplacePlugin]:
        """
        Get all plugins from all marketplaces.

        Returns:
            List of MarketplacePlugin from all configured marketplaces
        """
        all_plugins = []
        seen_names = set()

        # Get all marketplaces
        marketplaces = self.list_marketplaces_from_files()

        for marketplace in marketplaces:
            plugins = self.browse_marketplace_from_files(marketplace["name"])
            for plugin_data in plugins:
                name = plugin_data.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    all_plugins.append(
                        MarketplacePlugin(
                            name=name,
                            description=plugin_data.get("description"),
                            version=plugin_data.get("version"),
                            install_command=plugin_data.get(
                                "install_command",
                                f"claude plugin install {name}"
                            ),
                        )
                    )

        return all_plugins

    def validate_plugin(self, path: str) -> PluginValidationResult:
        """
        Validate a plugin via CLI: claude plugin validate <path>

        Args:
            path: Path to plugin directory

        Returns:
            PluginValidationResult with validation status
        """
        errors = []
        warnings = []

        # Check if path exists
        plugin_path = Path(path)
        if not plugin_path.exists():
            return PluginValidationResult(
                valid=False,
                errors=[f"Path does not exist: {path}"],
                warnings=[],
            )

        # Check for plugin.json
        plugin_json_path = plugin_path / ".claude-plugin" / "plugin.json"
        if not plugin_json_path.exists():
            errors.append("Missing .claude-plugin/plugin.json")
        else:
            # Validate plugin.json structure
            try:
                with open(plugin_json_path, "r", encoding="utf-8") as f:
                    plugin_data = json.load(f)

                # Check required fields
                if not plugin_data.get("name"):
                    errors.append("Missing 'name' field in plugin.json")

                # Check optional but recommended fields
                if not plugin_data.get("description"):
                    warnings.append("Missing 'description' field in plugin.json")
                if not plugin_data.get("version"):
                    warnings.append("Missing 'version' field in plugin.json")

            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON in plugin.json: {str(e)}")

        # Check for README
        readme_paths = [
            plugin_path / "README.md",
            plugin_path / "readme.md",
        ]
        if not any(p.exists() for p in readme_paths):
            warnings.append("Missing README.md")

        return PluginValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
