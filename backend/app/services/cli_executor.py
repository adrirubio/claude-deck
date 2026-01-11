"""
CLI Executor Service for Claude Deck

Securely executes whitelisted Claude CLI commands via subprocess.
"""

import subprocess
import shutil
from typing import List, Optional, Dict
from ..models.schemas import CLIResult


class CLIExecutor:
    """Service for executing Claude CLI commands with security constraints"""

    # Whitelist of allowed Claude CLI subcommands
    ALLOWED_COMMANDS = ["mcp", "config", "plugin"]

    def __init__(self):
        """Initialize CLI executor"""
        self.claude_binary = self._find_claude_binary()

    def _find_claude_binary(self) -> Optional[str]:
        """Find the claude binary in PATH"""
        return shutil.which("claude")

    def validate_command(self, command: str) -> bool:
        """
        Validate that the command is in the whitelist

        Args:
            command: The Claude CLI subcommand to validate

        Returns:
            True if command is allowed, False otherwise
        """
        return command in self.ALLOWED_COMMANDS

    def execute(
        self,
        command: str,
        args: List[str],
        timeout: int = 30,
        env: Optional[Dict[str, str]] = None
    ) -> CLIResult:
        """
        Execute a Claude CLI command

        Args:
            command: The Claude CLI subcommand (must be whitelisted)
            args: List of arguments to pass to the command
            timeout: Maximum execution time in seconds (default: 30)
            env: Optional environment variables to pass to the command

        Returns:
            CLIResult containing stdout, stderr, and exit code

        Raises:
            ValueError: If command is not whitelisted or claude binary not found
            subprocess.TimeoutExpired: If command execution exceeds timeout
        """
        # Check if command is whitelisted
        if not self.validate_command(command):
            raise ValueError(
                f"Command '{command}' is not allowed. "
                f"Allowed commands: {', '.join(self.ALLOWED_COMMANDS)}"
            )

        # Check if claude binary exists
        if not self.claude_binary:
            raise ValueError(
                "Claude CLI binary not found in PATH. "
                "Please ensure Claude Code is installed and accessible."
            )

        # Build full command
        full_command = [self.claude_binary, command] + args

        try:
            # Execute command with timeout
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False  # Don't raise exception on non-zero exit
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
