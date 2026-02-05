"""Service for managing skill dependencies and installation."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from app.models.schemas import (
    SkillDependency,
    SkillDependencyStatus,
    SkillInstallResult,
    SkillSupportingFile,
)
from app.utils.path_utils import get_claude_user_skills_dir


class SkillDependencyService:
    """Service for checking and installing skill dependencies."""

    @staticmethod
    def _parse_frontmatter(content: str) -> Dict:
        """Parse YAML frontmatter from skill content."""
        import re

        pattern = r"^---\s*\n(.*?)\n---\s*\n"
        match = re.match(pattern, content, re.DOTALL)
        if match:
            try:
                return yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                return {}
        return {}

    @staticmethod
    def _resolve_skill_dir(base: Path, name: str) -> Optional[Path]:
        """
        Find a skill directory by name, checking:
        1. Direct: base/name/SKILL.md
        2. Nested: base/*/name/SKILL.md (e.g. nextjs/vercel-ai-sdk/)
        """
        # Direct subdirectory
        skill_dir = base / name
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            return skill_dir
        # Nested (one level deep)
        if base.exists():
            for parent in base.iterdir():
                if parent.is_dir():
                    nested = parent / name
                    if nested.is_dir() and (nested / "SKILL.md").exists():
                        return nested
        return None

    @staticmethod
    def _get_skill_dir(name: str, location: str, project_path: Optional[str] = None) -> Optional[Path]:
        """
        Resolve the skill directory path.

        Skills can be:
        - User: ~/.claude/skills/<name>/SKILL.md or ~/.claude/skills/<name>.md
        - Project: <project>/.claude/skills/<name>/SKILL.md
        - Plugin: <plugin_path>/skills/<name>/SKILL.md
        """
        if location == "user":
            base = get_claude_user_skills_dir()
            resolved = SkillDependencyService._resolve_skill_dir(base, name)
            if resolved:
                return resolved
            # Flat file skill (no directory, just a .md file)
            flat_file = base / f"{name}.md"
            if flat_file.exists():
                return None  # Flat files don't have a directory for deps
            return None

        elif location == "project" and project_path:
            base = Path(project_path) / ".claude" / "skills"
            resolved = SkillDependencyService._resolve_skill_dir(base, name)
            if resolved:
                return resolved
            return None

        elif location.startswith("plugin:"):
            # Plugin skills: need to find the plugin's install path
            plugin_name = location.replace("plugin:", "")
            plugins_file = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
            if not plugins_file.exists():
                return None
            try:
                data = json.loads(plugins_file.read_text(encoding="utf-8"))
                for key, installs in data.get("plugins", {}).items():
                    if key.startswith(f"{plugin_name}@") or key == plugin_name:
                        for install in installs:
                            install_path = install.get("installPath")
                            if install_path:
                                skill_dir = Path(install_path) / "skills" / name
                                if skill_dir.is_dir():
                                    return skill_dir
            except (json.JSONDecodeError, Exception):
                pass
            return None

        return None

    @staticmethod
    def _get_skill_file(name: str, location: str, project_path: Optional[str] = None) -> Optional[Path]:
        """Get the SKILL.md or flat .md file path for a skill."""
        skill_dir = SkillDependencyService._get_skill_dir(name, location, project_path)
        if skill_dir:
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                return skill_file

        # Try flat file
        if location == "user":
            flat_file = get_claude_user_skills_dir() / f"{name}.md"
            if flat_file.exists():
                return flat_file

        return None

    @staticmethod
    def _check_binary(name: str) -> Tuple[bool, Optional[str]]:
        """Check if a binary is available in PATH."""
        path = shutil.which(name)
        if not path:
            return False, None
        # Try to get version
        version = None
        for flag in ["--version", "-v", "version"]:
            try:
                result = subprocess.run(
                    [name, flag],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    # Extract version-like string
                    output = result.stdout.strip().split("\n")[0]
                    version = output
                    break
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue
        return True, version

    @staticmethod
    def _check_npm_package(name: str) -> Tuple[bool, Optional[str]]:
        """Check if an npm package is globally installed."""
        try:
            result = subprocess.run(
                ["npm", "list", "-g", name, "--json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                deps = data.get("dependencies", {})
                if name in deps:
                    return True, deps[name].get("version")
            return False, None
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            return False, None

    @staticmethod
    def _check_pip_package(name: str) -> Tuple[bool, Optional[str]]:
        """Check if a pip package is installed."""
        try:
            result = subprocess.run(
                ["pip", "show", name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("Version:"):
                        return True, line.split(":")[1].strip()
                return True, None
            return False, None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Try pip3
            try:
                result = subprocess.run(
                    ["pip3", "show", name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if line.startswith("Version:"):
                            return True, line.split(":")[1].strip()
                    return True, None
                return False, None
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return False, None

    @staticmethod
    def check_dependencies(
        name: str, location: str, project_path: Optional[str] = None
    ) -> SkillDependencyStatus:
        """
        Check dependency status for a skill.

        Parses the skill's frontmatter metadata for dependency declarations
        and checks each one against the system.

        Supported metadata formats:
        1. Agent Skills standard (openclaw/requires):
           metadata:
             openclaw:
               requires:
                 bins: ["ffmpeg", "jq"]
               install:
                 - kind: npm
                   package: "@some/tool"
                 - kind: pip
                   package: some-lib

        2. Simple requires format:
           requires:
             bins: ["ffmpeg"]
             npm: ["package-name"]
             pip: ["package-name"]

        Also checks for scripts/install.sh in the skill directory.
        """
        dependencies: List[SkillDependency] = []
        has_install_script = False
        install_script_path = None

        # Get skill file and parse metadata
        skill_file = SkillDependencyService._get_skill_file(name, location, project_path)
        if skill_file:
            content = skill_file.read_text(encoding="utf-8")
            metadata = SkillDependencyService._parse_frontmatter(content)

            # Check for Agent Skills standard format (openclaw metadata)
            openclaw_meta = {}
            if "metadata" in metadata:
                meta = metadata["metadata"]
                if isinstance(meta, dict):
                    openclaw_meta = meta.get("openclaw", {})

            requires = openclaw_meta.get("requires", {})
            install_defs = openclaw_meta.get("install", [])

            # Also check direct requires format
            if not requires and "requires" in metadata:
                requires = metadata["requires"]

            # Check binary requirements
            bins = requires.get("bins", [])
            if isinstance(bins, list):
                for bin_name in bins:
                    installed, version = SkillDependencyService._check_binary(bin_name)
                    dependencies.append(
                        SkillDependency(
                            kind="bin",
                            name=bin_name,
                            installed=installed,
                            installed_version=version,
                        )
                    )

            # Check npm requirements
            npm_deps = requires.get("npm", [])
            if isinstance(npm_deps, list):
                for pkg_name in npm_deps:
                    installed, version = SkillDependencyService._check_npm_package(pkg_name)
                    dependencies.append(
                        SkillDependency(
                            kind="npm",
                            name=pkg_name,
                            installed=installed,
                            installed_version=version,
                        )
                    )

            # Check pip requirements
            pip_deps = requires.get("pip", [])
            if isinstance(pip_deps, list):
                for pkg_name in pip_deps:
                    installed, version = SkillDependencyService._check_pip_package(pkg_name)
                    dependencies.append(
                        SkillDependency(
                            kind="pip",
                            name=pkg_name,
                            installed=installed,
                            installed_version=version,
                        )
                    )

            # Check install definitions (Agent Skills standard)
            for install_def in install_defs:
                if not isinstance(install_def, dict):
                    continue
                kind = install_def.get("kind", "")
                pkg = install_def.get("package", install_def.get("formula", ""))

                if not pkg:
                    continue

                # Skip if already checked via requires
                if any(d.name == pkg for d in dependencies):
                    continue

                if kind == "npm":
                    installed, version = SkillDependencyService._check_npm_package(pkg)
                    dependencies.append(
                        SkillDependency(kind="npm", name=pkg, installed=installed, installed_version=version)
                    )
                elif kind == "pip":
                    installed, version = SkillDependencyService._check_pip_package(pkg)
                    dependencies.append(
                        SkillDependency(kind="pip", name=pkg, installed=installed, installed_version=version)
                    )
                elif kind in ("brew", "apt"):
                    # Check the binary specified in bins
                    check_bins = install_def.get("bins", [])
                    for bin_name in check_bins:
                        if not any(d.name == bin_name for d in dependencies):
                            installed, version = SkillDependencyService._check_binary(bin_name)
                            dependencies.append(
                                SkillDependency(kind="bin", name=bin_name, installed=installed, installed_version=version)
                            )

        # Check for install script in skill directory
        skill_dir = SkillDependencyService._get_skill_dir(name, location, project_path)
        if skill_dir:
            for script_name in ["scripts/install.sh", "install.sh", "setup.sh"]:
                script_path = skill_dir / script_name
                if script_path.exists():
                    has_install_script = True
                    install_script_path = str(script_path)
                    dependencies.append(
                        SkillDependency(
                            kind="script",
                            name=script_name,
                            installed=True,  # Script exists, that's what matters
                        )
                    )
                    break

        all_satisfied = all(d.installed for d in dependencies)

        return SkillDependencyStatus(
            skill_name=name,
            all_satisfied=all_satisfied,
            dependencies=dependencies,
            has_install_script=has_install_script,
            install_script_path=install_script_path,
        )

    @staticmethod
    def list_supporting_files(
        name: str, location: str, project_path: Optional[str] = None
    ) -> List[SkillSupportingFile]:
        """List supporting files in a skill directory (excluding SKILL.md)."""
        skill_dir = SkillDependencyService._get_skill_dir(name, location, project_path)
        if not skill_dir or not skill_dir.is_dir():
            return []

        files = []
        for path in sorted(skill_dir.rglob("*")):
            if not path.is_file():
                continue
            # Skip SKILL.md itself
            if path.name == "SKILL.md" and path.parent == skill_dir:
                continue

            relative = path.relative_to(skill_dir)
            is_script = (
                path.suffix in (".sh", ".py", ".js", ".ts")
                or os.access(path, os.X_OK)
            )

            files.append(
                SkillSupportingFile(
                    name=str(relative),
                    path=str(path),
                    size_bytes=path.stat().st_size,
                    is_script=is_script,
                )
            )

        return files

    @staticmethod
    def install_dependencies(
        name: str, location: str, project_path: Optional[str] = None
    ) -> SkillInstallResult:
        """
        Install missing dependencies for a skill.

        Strategy:
        1. If an install script exists, run it first
        2. Install missing npm packages globally
        3. Install missing pip packages
        4. Report on missing binaries (can't auto-install)
        """
        status = SkillDependencyService.check_dependencies(name, location, project_path)

        if status.all_satisfied:
            return SkillInstallResult(
                success=True,
                message="All dependencies are already satisfied.",
                installed=[],
                failed=[],
                logs="",
            )

        installed = []
        failed = []
        all_logs = []
        skill_dir = SkillDependencyService._get_skill_dir(name, location, project_path)

        # Run install script if available
        if status.has_install_script and status.install_script_path:
            script_path = Path(status.install_script_path)
            try:
                # Make executable
                os.chmod(script_path, 0o755)
                result = subprocess.run(
                    ["bash", str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(skill_dir) if skill_dir else None,
                )
                all_logs.append(f"=== Install script: {script_path.name} ===")
                if result.stdout:
                    all_logs.append(result.stdout)
                if result.stderr:
                    all_logs.append(result.stderr)

                if result.returncode == 0:
                    installed.append(f"script:{script_path.name}")
                else:
                    failed.append(f"script:{script_path.name} (exit code {result.returncode})")
            except subprocess.TimeoutExpired:
                failed.append(f"script:{script_path.name} (timeout)")
                all_logs.append(f"Install script timed out after 120s")
            except Exception as e:
                failed.append(f"script:{script_path.name} ({str(e)})")
                all_logs.append(f"Error running install script: {e}")

        # Install missing npm packages
        for dep in status.dependencies:
            if dep.installed or dep.kind != "npm":
                continue
            try:
                all_logs.append(f"\n=== npm install -g {dep.name} ===")
                result = subprocess.run(
                    ["npm", "install", "-g", dep.name],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.stdout:
                    all_logs.append(result.stdout)
                if result.stderr:
                    all_logs.append(result.stderr)

                if result.returncode == 0:
                    installed.append(f"npm:{dep.name}")
                else:
                    failed.append(f"npm:{dep.name}")
            except subprocess.TimeoutExpired:
                failed.append(f"npm:{dep.name} (timeout)")
            except FileNotFoundError:
                failed.append(f"npm:{dep.name} (npm not found)")

        # Install missing pip packages
        for dep in status.dependencies:
            if dep.installed or dep.kind != "pip":
                continue
            try:
                pip_cmd = "pip3" if shutil.which("pip3") else "pip"
                all_logs.append(f"\n=== {pip_cmd} install {dep.name} ===")
                result = subprocess.run(
                    [pip_cmd, "install", dep.name],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.stdout:
                    all_logs.append(result.stdout)
                if result.stderr:
                    all_logs.append(result.stderr)

                if result.returncode == 0:
                    installed.append(f"pip:{dep.name}")
                else:
                    failed.append(f"pip:{dep.name}")
            except subprocess.TimeoutExpired:
                failed.append(f"pip:{dep.name} (timeout)")
            except FileNotFoundError:
                failed.append(f"pip:{dep.name} (pip not found)")

        # Report missing binaries (can't auto-install)
        for dep in status.dependencies:
            if dep.installed or dep.kind != "bin":
                continue
            failed.append(f"bin:{dep.name} (manual install required)")
            all_logs.append(f"\n⚠ Binary '{dep.name}' not found. Install it manually.")

        success = len(failed) == 0
        if success:
            message = f"Successfully installed {len(installed)} dependencies."
        elif installed:
            message = f"Installed {len(installed)} dependencies, {len(failed)} failed."
        else:
            message = f"Failed to install {len(failed)} dependencies."

        return SkillInstallResult(
            success=success,
            message=message,
            installed=installed,
            failed=failed,
            logs="\n".join(all_logs),
        )
