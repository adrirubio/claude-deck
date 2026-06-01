"""Provider abstraction for local agent CLIs."""
from __future__ import annotations

import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.providers.capabilities import capability_flags, normalize_capability_matrix


_MAX_TREE_DEPTH = 4


@dataclass(frozen=True)
class SpawnCommandOptions:
    """Provider-neutral launch options used by the tmux bridge."""

    directory: str
    mode: str = "plain"
    worktree_name: str | None = None
    session_id: str | None = None
    project_folder: str | None = None
    skip_permissions: bool = False
    prompt: str | None = None
    model: str | None = None
    profile: str | None = None
    profile_v2: str | None = None
    sandbox: str | None = None
    approval_policy: str | None = None
    search: bool | None = None
    no_alt_screen: bool = False
    dangerously_bypass_approvals_and_sandbox: bool = False
    use_last: bool = False
    platform: str = "anthropic"
    aws_region: str | None = None
    aws_profile: str | None = None
    bedrock_model: str | None = None


def argv0_name(command: str) -> str:
    """Return the executable basename from a command or argv0 string."""
    if not command:
        return ""
    return Path(command.strip().split()[0]).name.lower()


def has_binary_descendant(
    pid: str,
    binary_names: set[str],
    *,
    excluded_names: set[str] | None = None,
    _depth: int = 0,
    _visited: set[str] | None = None,
) -> bool:
    """Walk a process tree looking for a descendant executable name."""
    if _depth > _MAX_TREE_DEPTH or not pid.isdigit():
        return False
    if _visited is None:
        _visited = set()
    if pid in _visited:
        return False
    _visited.add(pid)

    excluded_names = excluded_names or set()
    try:
        result = subprocess.run(
            ["pgrep", "-a", "-P", pid],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return False

    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        child_pid, cmdline = parts
        name = argv0_name(cmdline)
        if name in binary_names and name not in excluded_names:
            return True
        if has_binary_descendant(
            child_pid,
            binary_names,
            excluded_names=excluded_names,
            _depth=_depth + 1,
            _visited=_visited,
        ):
            return True
    return False


class AgentProvider(ABC):
    """Base class for provider-specific CLI behavior."""

    id: str
    display_name: str
    binary_name: str
    version_args: tuple[str, ...] = ("--version",)

    def get_capabilities(self) -> dict[str, bool]:
        """Return backward-compatible provider feature support flags."""
        return capability_flags(self.id)

    def get_capability_matrix(self) -> dict[str, dict[str, Any]]:
        """Return detailed provider capability metadata."""
        return normalize_capability_matrix(self.id)

    def get_capability_details(self) -> dict[str, dict[str, str]]:
        """Return richer capability metadata for UI/action state."""
        return self.get_capability_matrix()

    @abstractmethod
    def get_config_paths(self, project_path: str | None = None) -> dict[str, Any]:
        """Return important config paths for this provider."""

    @abstractmethod
    def is_process_match(self, command: str, pid: str) -> bool:
        """Return True when a tmux pane belongs to this provider."""

    @abstractmethod
    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        """Build the provider CLI command for a tmux session."""

    @abstractmethod
    def get_allowed_cli_commands(self) -> list[str]:
        """Return safe command names exposed by a provider CLI API."""

    def get_backup_policy(self) -> dict[str, Any] | None:
        """Return provider backup/export/restore policy metadata, if defined."""
        return None

    def get_version(self) -> str | None:
        """Read the installed CLI version, if available."""
        binary_path = shutil.which(self.binary_name)
        if not binary_path:
            return None

        try:
            result = subprocess.run(
                [binary_path, *self.version_args],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"(\d+\.\d+\.\d+(?:[-+][\w.]+)?)", output)
        return match.group(1) if match else output.strip().splitlines()[0] if output.strip() else None

    def get_status(self) -> dict[str, Any]:
        """Return install/version status suitable for the API."""
        binary_path = shutil.which(self.binary_name)
        version = self.get_version() if binary_path else None
        return {
            "id": self.id,
            "display_name": self.display_name,
            "binary_name": self.binary_name,
            "installed": binary_path is not None,
            "binary_path": binary_path,
            "version": version,
            "capabilities": self.get_capabilities(),
            "capability_matrix": self.get_capability_matrix(),
            "capability_details": self.get_capability_details(),
            "config_paths": self.get_config_paths(),
            "backup_policy": self.get_backup_policy(),
        }
