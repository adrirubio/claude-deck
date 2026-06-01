"""Provider-aware CLI executor service."""

import subprocess
import shutil
import re
from typing import List, Optional, Dict
from ..models.schemas import CLIResult
from .providers import get_provider
from .providers.base import AgentProvider


class ProviderCLIExecutor:
    """Execute whitelisted provider CLI commands with security constraints."""

    DEFAULT_PROVIDER = "claude-code"
    SAFE_ARG_PATTERN = re.compile(r"^[A-Za-z0-9_./@:+,=%?#&-]{0,4096}$")

    def __init__(self, provider_id: str = DEFAULT_PROVIDER):
        self.provider = get_provider(provider_id)
        self.provider_id = self.provider.id
        self.binary_path = self._find_binary(self.provider)
        self.ALLOWED_COMMANDS = self.provider.get_allowed_cli_commands()
        # Compatibility for existing callers that check claude_binary directly.
        self.claude_binary = self.binary_path if self.provider_id == "claude-code" else None

    def _find_binary(self, provider: AgentProvider) -> Optional[str]:
        return shutil.which(provider.binary_name)

    def validate_command(self, command: str) -> bool:
        """
        Validate that the command is in the whitelist

        Args:
            command: The Claude CLI subcommand to validate

        Returns:
            True if command is allowed, False otherwise
        """
        return command in self.provider.get_allowed_cli_commands()

    def _validate_args(self, args: List[str]) -> List[str]:
        safe_args = []
        for arg in args:
            if not isinstance(arg, str):
                raise ValueError("CLI arguments must be strings")
            if "\x00" in arg or any(ord(char) < 32 for char in arg):
                raise ValueError("CLI arguments cannot contain control characters")
            if not self.SAFE_ARG_PATTERN.fullmatch(arg):
                raise ValueError("CLI argument contains unsupported characters")
            safe_args.append(arg)
        return safe_args

    def execute(
        self,
        command: str,
        args: List[str],
        timeout: int = 30,
        env: Optional[Dict[str, str]] = None
    ) -> CLIResult:
        """
        Execute a provider CLI command

        Args:
            command: The provider CLI subcommand (must be whitelisted)
            args: List of arguments to pass to the command
            timeout: Maximum execution time in seconds (default: 30)
            env: Optional environment variables to pass to the command

        Returns:
            CLIResult containing stdout, stderr, and exit code

        Raises:
            ValueError: If command is not whitelisted or provider binary not found
            subprocess.TimeoutExpired: If command execution exceeds timeout
        """
        if not self.validate_command(command):
            raise ValueError(
                f"Command '{command}' is not allowed. "
                f"Allowed commands for {self.provider.display_name}: "
                f"{', '.join(self.provider.get_allowed_cli_commands())}"
            )

        if not self.binary_path:
            raise ValueError(
                f"{self.provider.display_name} binary not found in PATH. "
                f"Please ensure {self.provider.display_name} is installed and accessible."
            )

        safe_args = self._validate_args(args)
        full_command = [self.binary_path, command] + safe_args

        try:
            # Provider commands use a resolved fixed binary, a provider-owned subcommand
            # whitelist, shell=False, and validation for user-controlled arguments.
            # lgtm[py/command-line-injection]
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )

            return CLIResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode
            )
        except subprocess.TimeoutExpired as e:
            return CLIResult(
                stdout=e.stdout.decode() if e.stdout else "",
                stderr=f"Command timed out after {timeout} seconds",
                exit_code=-1
            )
        except Exception as e:
            return CLIResult(
                stdout="",
                stderr=f"Failed to execute command: {str(e)}",
                exit_code=-1
            )


class CLIExecutor(ProviderCLIExecutor):
    """Backward-compatible Claude Code executor."""

    def __init__(self):
        super().__init__("claude-code")
