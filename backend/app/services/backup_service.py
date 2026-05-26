"""Service for managing configuration backups."""
import json
import os
import platform
import re
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Backup
from app.models.schemas import (
    BackupManifest,
    BackupManifestContents,
    BackupMCPServerInfo,
    BackupPluginInfo,
    BackupSkillDependency,
    BackupSkillInfo,
    DependencyInstallRequest,
    DependencyInstallResult,
    DependencyInstallStatus,
    RestoreOptions,
    RestorePlan,
    RestorePlanDependency,
    RestorePlanWarning,
    RestoreResult,
)
from app.utils.path_utils import (
    get_user_home,
    get_claude_user_config_dir,
    get_claude_user_config_file,
    get_claude_user_settings_file,
    get_claude_user_settings_local_file,
    get_claude_user_commands_dir,
    get_claude_user_agents_dir,
    get_claude_user_skills_dir,
    get_claude_user_plugins_dir,
    get_project_claude_dir,
    get_project_mcp_config_file,
    get_project_claude_md_file,
)
from app.services.cli_executor import ProviderCLIExecutor
from app.services.providers.codex_cli import get_codex_home


SENSITIVE_KEY_PATTERN = re.compile(r"(token|secret|password|credential|api[_-]?key|auth|cookie|session)", re.I)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key>[A-Za-z0-9_.-]*(?:token|secret|password|credential|api[_-]?key|auth|cookie|session)[A-Za-z0-9_.-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>[^\s,;]+)",
    re.I,
)
SENSITIVE_TOML_ASSIGNMENT_PATTERN = re.compile(
    r"(?im)^"
    r"(?P<prefix>\s*[A-Za-z0-9_.-]*(?:token|secret|password|credential|api[_-]?key|auth|cookie|session)"
    r"[A-Za-z0-9_.-]*\s*=\s*)"
    r"(?P<value>.+?)"
    r"(?P<suffix>\s*(?:#.*)?)$"
)


def get_backup_storage_dir() -> Path:
    """Get the backup storage directory."""
    backup_dir = get_user_home() / ".claude-registry" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _get_current_platform() -> str:
    """Get current platform identifier."""
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    elif system == "windows":
        return "win32"
    return "linux"


def _get_claude_code_version() -> Optional[str]:
    """Try to get Claude Code version."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


class BackupService:
    """Service for managing configuration backups."""

    def __init__(self, db: AsyncSession, codex_home: Optional[Path] = None):
        self.db = db
        self.codex_home = codex_home or get_codex_home()

    def _get_user_config_paths(self) -> List[Path]:
        """Get all user-level configuration paths."""
        paths = []

        # Main config files
        for path_fn in [
            get_claude_user_config_file,
            get_claude_user_settings_file,
            get_claude_user_settings_local_file,
        ]:
            path = path_fn()
            if path.exists():
                paths.append(path)

        # Directories
        for dir_fn in [
            get_claude_user_commands_dir,
            get_claude_user_agents_dir,
            get_claude_user_skills_dir,
            get_claude_user_plugins_dir,
        ]:
            dir_path = dir_fn()
            if dir_path.exists():
                for file_path in dir_path.rglob("*"):
                    if file_path.is_file():
                        paths.append(file_path)

        return paths

    def _get_project_config_paths(self, project_path: str) -> List[Path]:
        """Get all project-level configuration paths."""
        paths = []

        # .claude directory
        claude_dir = get_project_claude_dir(project_path)
        if claude_dir.exists():
            for file_path in claude_dir.rglob("*"):
                if file_path.is_file():
                    paths.append(file_path)

        # .mcp.json
        mcp_file = get_project_mcp_config_file(project_path)
        if mcp_file.exists():
            paths.append(mcp_file)

        # CLAUDE.md
        claude_md = get_project_claude_md_file(project_path)
        if claude_md.exists():
            paths.append(claude_md)

        return paths

    def _get_codex_config_paths(self) -> List[Path]:
        """Get safe Codex configuration files for export-only backups."""
        paths: List[Path] = []
        config_file = self.codex_home / "config.toml"
        if config_file.exists() and config_file.is_file():
            paths.append(config_file)

        if self.codex_home.exists():
            for profile in sorted(self.codex_home.glob("*.config.toml")):
                if profile.is_file():
                    paths.append(profile)

            rules_dir = self.codex_home / "rules"
            if rules_dir.exists():
                for rule in sorted(rules_dir.glob("*.rules")):
                    if rule.is_file():
                        paths.append(rule)

        return paths

    def _redact_value(self, value: Any, parent_key: str = "") -> Any:
        """Redact sensitive values from generated backup metadata."""
        if value is None:
            return None
        if isinstance(value, dict):
            return {
                key: "[redacted]" if SENSITIVE_KEY_PATTERN.search(key) or SENSITIVE_KEY_PATTERN.search(parent_key)
                else self._redact_value(child, key)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item, parent_key) for item in value]
        if SENSITIVE_KEY_PATTERN.search(parent_key):
            return "[redacted]"
        if isinstance(value, str):
            return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\g<key>\g<sep>[redacted]", value)
        return value

    def _redact_text_content(self, content: str) -> str:
        """Redact obvious secret assignments in text files before exporting."""
        redacted = SENSITIVE_TOML_ASSIGNMENT_PATTERN.sub(
            lambda match: f'{match.group("prefix")}"[redacted]"{match.group("suffix")}',
            content,
        )
        return SENSITIVE_ASSIGNMENT_PATTERN.sub(r'\g<key>\g<sep>"[redacted]"', redacted)

    def _read_redacted_file(self, path: Path) -> str:
        try:
            return self._redact_text_content(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            return self._redact_text_content(path.read_text(errors="replace"))

    def _get_codex_provider_inventory(self, paths: List[Path]) -> Dict[str, Any]:
        """Collect safe provider metadata for Codex export manifests."""
        inventory: Dict[str, Any] = {
            "provider": "codex-cli",
            "codex_home": str(self.codex_home),
            "files": [
                {
                    "path": str(path),
                    "scope": (
                        "user" if path.name == "config.toml"
                        else "rules" if path.suffix == ".rules"
                        else "profile"
                    ),
                }
                for path in paths
            ],
        }

        try:
            executor = ProviderCLIExecutor("codex-cli")
            if not executor.binary_path:
                inventory["cli"] = {"installed": False}
                return inventory
        except Exception as exc:
            inventory["cli"] = {"installed": False, "error": str(exc)}
            return inventory

        inventory["cli"] = {"installed": True, "binary_path": executor.binary_path}

        mcp_result = executor.execute("mcp", ["list", "--json"], timeout=30)
        mcp_inventory: Dict[str, Any] = {
            "exit_code": mcp_result.exit_code,
            "stderr": self._redact_value(mcp_result.stderr),
        }
        if mcp_result.stdout.strip():
            try:
                mcp_inventory["servers"] = self._redact_value(json.loads(mcp_result.stdout))
            except json.JSONDecodeError as exc:
                mcp_inventory["parse_error"] = str(exc)
                mcp_inventory["raw_stdout"] = self._redact_value(mcp_result.stdout)
        inventory["mcp"] = mcp_inventory

        plugin_result = executor.execute("plugin", ["list"], timeout=30)
        inventory["plugins"] = {
            "exit_code": plugin_result.exit_code,
            "stderr": self._redact_value(plugin_result.stderr),
            "raw_stdout": self._redact_value(plugin_result.stdout),
        }

        return self._redact_value(inventory)

    def _detect_skill_dependencies(self, skill_path: Path) -> BackupSkillInfo:
        """Detect dependencies in a skill directory."""
        skill_name = skill_path.name
        info = BackupSkillInfo(
            name=skill_name,
            path=str(skill_path),
        )

        # Check for package.json
        package_json = skill_path / "package.json"
        if package_json.exists():
            info.has_package_json = True
            try:
                with open(package_json) as f:
                    pkg = json.load(f)
                    deps = pkg.get("dependencies", {})
                    dev_deps = pkg.get("devDependencies", {})
                    for name, version in {**deps, **dev_deps}.items():
                        info.dependencies.append(
                            BackupSkillDependency(kind="npm", name=name, version=version)
                        )
            except Exception:
                pass

        # Check for requirements.txt
        requirements_txt = skill_path / "requirements.txt"
        if requirements_txt.exists():
            info.has_requirements_txt = True
            try:
                with open(requirements_txt) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # Parse package==version or package>=version
                            for sep in ["==", ">=", "<=", "~=", "!="]:
                                if sep in line:
                                    name, version = line.split(sep, 1)
                                    info.dependencies.append(
                                        BackupSkillDependency(
                                            kind="pip", name=name.strip(), version=version.strip()
                                        )
                                    )
                                    break
                            else:
                                info.dependencies.append(
                                    BackupSkillDependency(kind="pip", name=line)
                                )
            except Exception:
                pass

        # Check for install.sh
        install_sh = skill_path / "install.sh"
        if install_sh.exists():
            info.has_install_script = True

        return info

    def _get_plugin_install_info(self, plugin_name: str, plugin_path: Path) -> BackupPluginInfo:
        """Get plugin install information from plugin metadata."""
        info = BackupPluginInfo(name=plugin_name)

        # Try to read plugin manifest
        manifest_path = plugin_path / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
                    info.version = manifest.get("version")
                    info.source = manifest.get("source")
            except Exception:
                pass

        # Check for .source file that claude creates
        source_file = plugin_path / ".source"
        if source_file.exists():
            try:
                with open(source_file) as f:
                    source_data = json.load(f)
                    info.marketplace = source_data.get("marketplace")
                    info.install_command = source_data.get("install_command")
            except Exception:
                pass

        return info

    def _detect_mcp_server_info(
        self, name: str, config: Dict[str, Any], scope: str
    ) -> BackupMCPServerInfo:
        """Extract MCP server info from config."""
        server_type = "stdio"
        if "url" in config:
            server_type = "sse" if "sse" in config.get("url", "").lower() else "http"

        info = BackupMCPServerInfo(
            name=name,
            type=server_type,
            scope=scope,
            command=config.get("command"),
            args=config.get("args"),
            url=config.get("url"),
        )

        # Check if it's an npx command that might need npm install
        if info.command and info.command.startswith("npx"):
            info.requires_npm_install = True

        return info

    def _generate_manifest(
        self,
        paths: List[Path],
        scope: str,
        extra_files: Optional[Dict[str, str]] = None,
        provider_inventory: Optional[Dict[str, Any]] = None,
    ) -> BackupManifest:
        """Generate a backup manifest with all dependency information."""
        contents = BackupManifestContents()

        # Track files
        home = get_user_home()
        for path in paths:
            try:
                rel_path = str(path.relative_to(home))
            except ValueError:
                rel_path = str(path)
            contents.files.append(rel_path)
        if extra_files:
            contents.files.extend(extra_files.keys())
        if provider_inventory:
            contents.provider_inventory = provider_inventory

        # Detect skills
        if scope != "codex":
            skills_dir = get_claude_user_skills_dir()
            if skills_dir.exists():
                for skill_path in skills_dir.iterdir():
                    if skill_path.is_dir():
                        skill_info = self._detect_skill_dependencies(skill_path)
                        contents.skills.append(skill_info)

            # Detect plugins
            plugins_dir = get_claude_user_plugins_dir()
            if plugins_dir.exists():
                for plugin_path in plugins_dir.iterdir():
                    if plugin_path.is_dir():
                        plugin_info = self._get_plugin_install_info(plugin_path.name, plugin_path)
                        contents.plugins.append(plugin_info)

            # Detect MCP servers from user config
            config_file = get_claude_user_config_file()
            if config_file.exists():
                try:
                    with open(config_file) as f:
                        config = json.load(f)
                        mcp_servers = config.get("mcpServers", {})
                        for name, srv_config in mcp_servers.items():
                            mcp_info = self._detect_mcp_server_info(name, srv_config, "user")
                            contents.mcp_servers.append(mcp_info)
                except Exception:
                    pass

            # Detect agents
            agents_dir = get_claude_user_agents_dir()
            if agents_dir.exists():
                for agent_file in agents_dir.glob("*.md"):
                    contents.agents.append(agent_file.stem)

            # Detect commands
            commands_dir = get_claude_user_commands_dir()
            if commands_dir.exists():
                for cmd_file in commands_dir.rglob("*.md"):
                    try:
                        rel = cmd_file.relative_to(commands_dir)
                        contents.commands.append(str(rel).replace(".md", ""))
                    except ValueError:
                        contents.commands.append(cmd_file.stem)

        manifest = BackupManifest(
            created_at=datetime.utcnow().isoformat(),
            claude_code_version=None if scope == "codex" else _get_claude_code_version(),
            platform=_get_current_platform(),
            scope=scope,
            contents=contents,
        )

        return manifest

    def _create_archive(
        self,
        name: str,
        paths: List[Path],
        scope: str,
        base_path: Optional[Path] = None,
        extra_files: Optional[Dict[str, str]] = None,
        file_overrides: Optional[Dict[Path, str]] = None,
        provider_inventory: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Path, int, BackupManifest]:
        """
        Create a zip archive from the given paths.

        Args:
            name: Backup name
            paths: List of file paths to include
            scope: Backup scope
            base_path: Base path for relative paths in archive

        Returns:
            Tuple of (archive_path, size_bytes, manifest)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{name}_{timestamp}.zip"
        archive_path = get_backup_storage_dir() / archive_name

        # Generate manifest
        manifest = self._generate_manifest(paths, scope, extra_files, provider_inventory)

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add manifest.json first
            zf.writestr("manifest.json", manifest.model_dump_json(indent=2))
            for arcname, content in (extra_files or {}).items():
                zf.writestr(arcname, content)

            for file_path in paths:
                if base_path:
                    try:
                        arcname = str(file_path.relative_to(base_path))
                    except ValueError:
                        arcname = str(file_path)
                else:
                    # Use path relative to home for user configs
                    try:
                        arcname = str(file_path.relative_to(get_user_home()))
                    except ValueError:
                        arcname = str(file_path)

                if file_overrides and file_path in file_overrides:
                    zf.writestr(arcname, file_overrides[file_path])
                else:
                    zf.write(file_path, arcname)

        size_bytes = archive_path.stat().st_size
        return archive_path, size_bytes, manifest

    async def create_backup(
        self,
        name: str,
        scope: str,
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        project_id: Optional[int] = None,
    ) -> Tuple[Backup, BackupManifest]:
        """
        Create a new backup.

        Args:
            name: Backup name
            scope: Scope ("full", "user", "project")
            project_path: Project path for project/full scope
            description: Optional description
            project_id: Optional project ID reference

        Returns:
            Tuple of (Backup record, BackupManifest)
        """
        paths = []
        extra_files: Dict[str, str] = {}
        file_overrides: Dict[Path, str] = {}
        provider_inventory: Optional[Dict[str, Any]] = None

        if scope in ["full", "user"]:
            paths.extend(self._get_user_config_paths())

        if scope in ["full", "project"] and project_path:
            paths.extend(self._get_project_config_paths(project_path))

        if scope == "codex":
            paths.extend(self._get_codex_config_paths())
            provider_inventory = self._get_codex_provider_inventory(paths)
            inventory_arcname = str(
                (self.codex_home / "provider-inventory.json").relative_to(self.codex_home.parent)
            )
            extra_files[inventory_arcname] = json.dumps(
                provider_inventory,
                indent=2,
                sort_keys=True,
            )
            file_overrides = {
                path: self._read_redacted_file(path)
                for path in paths
            }

        if not paths:
            raise ValueError("No configuration files found to backup")

        # Determine base path for relative paths
        base_path = None
        if scope == "project" and project_path:
            base_path = Path(project_path)
        elif scope == "codex":
            base_path = self.codex_home.parent

        archive_path, size_bytes, manifest = self._create_archive(
            name,
            paths,
            scope,
            base_path,
            extra_files=extra_files,
            file_overrides=file_overrides,
            provider_inventory=provider_inventory,
        )

        backup = Backup(
            name=name,
            description=description,
            file_path=str(archive_path),
            scope=scope,
            project_id=project_id,
            size_bytes=size_bytes,
        )

        self.db.add(backup)
        await self.db.commit()
        await self.db.refresh(backup)

        return backup, manifest

    async def list_backups(self) -> List[Backup]:
        """List all backups."""
        result = await self.db.execute(
            select(Backup).order_by(Backup.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_backup(self, backup_id: int) -> Optional[Backup]:
        """Get a backup by ID."""
        result = await self.db.execute(select(Backup).where(Backup.id == backup_id))
        return result.scalar_one_or_none()

    async def delete_backup(self, backup_id: int) -> bool:
        """
        Delete a backup.

        Args:
            backup_id: Backup ID

        Returns:
            True if deleted, False if not found
        """
        backup = await self.get_backup(backup_id)
        if not backup:
            return False

        # Delete the archive file
        archive_path = Path(backup.file_path)
        if archive_path.exists():
            archive_path.unlink()

        # Delete the database record
        await self.db.delete(backup)
        await self.db.commit()

        return True

    def get_manifest_from_backup(self, file_path: str) -> Optional[BackupManifest]:
        """Extract manifest from a backup zip file."""
        archive_path = Path(file_path)
        if not archive_path.exists():
            return None

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if "manifest.json" in zf.namelist():
                    manifest_data = zf.read("manifest.json")
                    return BackupManifest.model_validate_json(manifest_data)
        except Exception:
            pass

        return None

    async def get_restore_plan(
        self, backup_id: int, project_path: Optional[str] = None
    ) -> Optional[RestorePlan]:
        """
        Analyze a backup and generate a restore plan.

        Args:
            backup_id: Backup ID
            project_path: Target project path

        Returns:
            RestorePlan or None if backup not found
        """
        backup = await self.get_backup(backup_id)
        if not backup:
            return None

        archive_path = Path(backup.file_path)
        if not archive_path.exists():
            return None

        current_platform = _get_current_platform()
        manifest = self.get_manifest_from_backup(backup.file_path)

        plan = RestorePlan(
            backup_id=backup.id,
            backup_name=backup.name,
            created_at=backup.created_at.isoformat(),
            scope=backup.scope,
            platform_current=current_platform,
            platform_backup=manifest.platform if manifest else "unknown",
            platform_compatible=True,
        )
        if backup.scope == "codex":
            plan.warnings.append(
                RestorePlanWarning(
                    type="version",
                    message="Codex backups are export-only in this version. Download the archive and restore files manually.",
                    severity="warning",
                )
            )
            plan.manual_steps.append("Review the redacted Codex export before manually copying files into CODEX_HOME.")

        # Check platform compatibility
        if manifest and manifest.platform != current_platform:
            plan.platform_compatible = False
            plan.warnings.append(
                RestorePlanWarning(
                    type="platform",
                    message=f"Backup was created on {manifest.platform}, current platform is {current_platform}. Some paths or scripts may not work correctly.",
                    severity="warning",
                )
            )

        # Get files list
        with zipfile.ZipFile(archive_path, "r") as zf:
            plan.files_to_restore = [
                f for f in zf.namelist() if f != "manifest.json"
            ]

        if manifest:
            plan.skills_to_restore = manifest.contents.skills
            plan.plugins_to_restore = manifest.contents.plugins
            plan.mcp_servers_to_restore = manifest.contents.mcp_servers

            # Collect dependencies
            for skill in manifest.contents.skills:
                for dep in skill.dependencies:
                    plan.dependencies.append(
                        RestorePlanDependency(
                            kind=dep.kind,
                            name=dep.name,
                            version=dep.version,
                            source=f"skill:{skill.name}",
                        )
                    )
                if skill.has_install_script:
                    plan.manual_steps.append(
                        f"Run install.sh for skill '{skill.name}'"
                    )

            for plugin in manifest.contents.plugins:
                if plugin.install_command:
                    plan.dependencies.append(
                        RestorePlanDependency(
                            kind="plugin",
                            name=plugin.name,
                            source=plugin.marketplace,
                            install_command=plugin.install_command,
                        )
                    )
                elif plugin.source:
                    plan.manual_steps.append(
                        f"Reinstall plugin '{plugin.name}' from {plugin.source or 'marketplace'}"
                    )

            for mcp in manifest.contents.mcp_servers:
                if mcp.requires_npm_install:
                    # Extract package name from npx command
                    if mcp.args:
                        pkg_name = mcp.args[0] if mcp.args else mcp.name
                    else:
                        pkg_name = mcp.name
                    plan.dependencies.append(
                        RestorePlanDependency(
                            kind="mcp_npm",
                            name=pkg_name,
                            source=f"mcp:{mcp.name}",
                        )
                    )

            plan.has_dependencies = len(plan.dependencies) > 0

        return plan

    async def validate_backup(self, backup_id: int) -> Tuple[bool, List[str]]:
        """
        Validate a backup before restore.

        Args:
            backup_id: Backup ID

        Returns:
            Tuple of (is_valid, list of issues)
        """
        backup = await self.get_backup(backup_id)
        issues = []

        if not backup:
            return False, ["Backup not found"]

        archive_path = Path(backup.file_path)
        if not archive_path.exists():
            return False, ["Backup file not found on disk"]

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                # Test archive integrity
                bad_file = zf.testzip()
                if bad_file:
                    issues.append(f"Corrupted file in archive: {bad_file}")

                # Check for manifest
                if "manifest.json" not in zf.namelist():
                    issues.append("Backup is missing manifest.json (older format)")
        except zipfile.BadZipFile:
            return False, ["Backup file is corrupted"]

        return len(issues) == 0, issues

    def _install_skill_dependencies(self, skill_path: Path) -> Tuple[bool, str]:
        """
        Install dependencies for a skill.

        Args:
            skill_path: Path to skill directory

        Returns:
            Tuple of (success, log output)
        """
        logs = []
        success = True

        # npm install
        if (skill_path / "package.json").exists():
            try:
                result = subprocess.run(
                    ["npm", "install"],
                    cwd=str(skill_path),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                logs.append(f"npm install in {skill_path.name}:")
                logs.append(result.stdout)
                if result.returncode != 0:
                    logs.append(f"Error: {result.stderr}")
                    success = False
            except Exception as e:
                logs.append(f"npm install failed: {e}")
                success = False

        # pip install
        if (skill_path / "requirements.txt").exists():
            try:
                result = subprocess.run(
                    ["pip", "install", "-r", "requirements.txt"],
                    cwd=str(skill_path),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                logs.append(f"pip install in {skill_path.name}:")
                logs.append(result.stdout)
                if result.returncode != 0:
                    logs.append(f"Error: {result.stderr}")
                    success = False
            except Exception as e:
                logs.append(f"pip install failed: {e}")
                success = False

        return success, "\n".join(logs)

    def _reinstall_plugin(self, plugin_info: BackupPluginInfo) -> Tuple[bool, str]:
        """
        Reinstall a plugin using its install command.

        Args:
            plugin_info: Plugin information

        Returns:
            Tuple of (success, log output)
        """
        if not plugin_info.install_command:
            return False, f"No install command for plugin {plugin_info.name}"

        try:
            result = subprocess.run(
                plugin_info.install_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            logs = f"Installing {plugin_info.name}:\n{result.stdout}"
            if result.returncode != 0:
                logs += f"\nError: {result.stderr}"
                return False, logs
            return True, logs
        except Exception as e:
            return False, f"Failed to install {plugin_info.name}: {e}"

    async def restore_backup(
        self,
        backup_id: int,
        project_path: Optional[str] = None,
        options: Optional[RestoreOptions] = None,
    ) -> RestoreResult:
        """
        Restore from a backup.

        Args:
            backup_id: Backup ID
            project_path: Target project path for project-scoped backups
            options: Restore options

        Returns:
            RestoreResult with details
        """
        if options is None:
            options = RestoreOptions()

        backup = await self.get_backup(backup_id)
        if not backup:
            return RestoreResult(success=False, message="Backup not found")

        if backup.scope == "codex":
            return RestoreResult(
                success=False,
                message="Codex backups are export-only; automatic restore is not supported",
            )

        archive_path = Path(backup.file_path)
        if not archive_path.exists():
            return RestoreResult(
                success=False, message=f"Backup file not found: {archive_path}"
            )

        # Determine restore target
        if backup.scope == "project" and project_path:
            target_path = Path(project_path)
        else:
            target_path = get_user_home()

        result = RestoreResult(success=True, message="", dry_run=options.dry_run)
        manifest = self.get_manifest_from_backup(backup.file_path)

        # Extract the archive
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.namelist():
                # Skip manifest
                if member == "manifest.json":
                    continue

                # Check selective restore
                if options.selective_restore:
                    if member not in options.selective_restore:
                        result.files_skipped += 1
                        continue

                # Skip skills if requested
                if options.skip_skills and ".claude/skills/" in member:
                    result.files_skipped += 1
                    continue

                # Skip plugins if requested
                if options.skip_plugins and ".claude/plugins/" in member:
                    result.files_skipped += 1
                    continue

                # Determine the full target path
                member_target = target_path / member

                if options.dry_run:
                    result.files_restored += 1
                    continue

                # Ensure parent directory exists
                member_target.parent.mkdir(parents=True, exist_ok=True)

                # Extract the file
                with zf.open(member) as source:
                    with open(member_target, "wb") as dest:
                        dest.write(source.read())

                result.files_restored += 1

        # Handle dependency installation if requested
        if options.install_dependencies and not options.dry_run and manifest:
            dep_result = await self.install_dependencies(
                backup_id,
                DependencyInstallRequest(
                    install_npm=True,
                    install_pip=True,
                    install_plugins=True,
                ),
            )
            result.dependency_results = dep_result.installed + dep_result.failed

        # Add manual steps from manifest
        if manifest:
            for skill in manifest.contents.skills:
                if skill.has_install_script:
                    result.manual_steps.append(
                        f"Run: cd ~/.claude/skills/{skill.name} && ./install.sh"
                    )

        result.message = (
            f"{'Would restore' if options.dry_run else 'Restored'} "
            f"{result.files_restored} files"
            + (f", skipped {result.files_skipped}" if result.files_skipped else "")
        )

        return result

    async def install_dependencies(
        self, backup_id: int, request: DependencyInstallRequest
    ) -> DependencyInstallResult:
        """
        Install dependencies from a backup.

        Args:
            backup_id: Backup ID
            request: What to install

        Returns:
            DependencyInstallResult
        """
        backup = await self.get_backup(backup_id)
        if not backup:
            return DependencyInstallResult(
                success=False, message="Backup not found"
            )

        manifest = self.get_manifest_from_backup(backup.file_path)
        if not manifest:
            return DependencyInstallResult(
                success=False, message="No manifest in backup"
            )

        result = DependencyInstallResult(success=True, message="")
        logs = []

        # Install skill dependencies
        if request.install_npm or request.install_pip:
            skills_dir = get_claude_user_skills_dir()
            for skill_info in manifest.contents.skills:
                # Filter by name if specified
                if request.skill_names and skill_info.name not in request.skill_names:
                    continue

                skill_path = skills_dir / skill_info.name
                if not skill_path.exists():
                    result.failed.append(
                        DependencyInstallStatus(
                            name=skill_info.name,
                            kind="skill",
                            success=False,
                            message=f"Skill directory not found: {skill_path}",
                        )
                    )
                    continue

                success, log = self._install_skill_dependencies(skill_path)
                logs.append(log)

                status = DependencyInstallStatus(
                    name=skill_info.name,
                    kind="skill",
                    success=success,
                    message="Dependencies installed" if success else "Installation failed",
                )

                if success:
                    result.installed.append(status)
                else:
                    result.failed.append(status)

        # Reinstall plugins
        if request.install_plugins:
            for plugin_info in manifest.contents.plugins:
                # Filter by name if specified
                if request.plugin_names and plugin_info.name not in request.plugin_names:
                    continue

                if plugin_info.install_command:
                    success, log = self._reinstall_plugin(plugin_info)
                    logs.append(log)

                    status = DependencyInstallStatus(
                        name=plugin_info.name,
                        kind="plugin",
                        success=success,
                        message="Plugin reinstalled" if success else "Reinstall failed",
                    )

                    if success:
                        result.installed.append(status)
                    else:
                        result.failed.append(status)

        result.logs = "\n".join(logs)
        result.message = (
            f"Installed {len(result.installed)} dependencies, "
            f"{len(result.failed)} failed"
        )

        if result.failed:
            result.success = False

        return result

    def get_backup_contents(self, backup_id: int, file_path: str) -> List[str]:
        """
        Get the list of files in a backup.

        Args:
            backup_id: Backup ID (not used, file_path is used directly)
            file_path: Path to the backup file

        Returns:
            List of file names in the archive
        """
        archive_path = Path(file_path)
        if not archive_path.exists():
            return []

        with zipfile.ZipFile(archive_path, "r") as zf:
            return [f for f in zf.namelist() if f != "manifest.json"]

    async def export_config(
        self, paths: List[str], name: str = "export"
    ) -> Tuple[Path, int]:
        """
        Export specific configuration files.

        Args:
            paths: List of absolute paths to export
            name: Export name

        Returns:
            Tuple of (archive_path, size_bytes)
        """
        valid_paths = [Path(p) for p in paths if Path(p).exists()]
        if not valid_paths:
            raise ValueError("No valid paths to export")

        archive_path, size_bytes, _ = self._create_archive(name, valid_paths, "export")
        return archive_path, size_bytes
