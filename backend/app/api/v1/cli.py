"""
CLI execution API endpoints.
"""

from fastapi import APIRouter, HTTPException
from ...models.schemas import CLIExecuteRequest, CLIResult
from ...services.cli_executor import CLIExecutor

router = APIRouter(prefix="/cli", tags=["CLI"])

# Initialize CLI executor
cli_executor = CLIExecutor()


@router.post("/execute", response_model=CLIResult)
async def execute_cli_command(request: CLIExecuteRequest) -> CLIResult:
    """
    Execute a whitelisted Claude CLI command.

    Args:
        request: CLI execution request with command and args

    Returns:
        CLIResult containing stdout, stderr, and exit code

    Raises:
        HTTPException: If command is not whitelisted or execution fails
    """
    # Validate command against whitelist
    if not cli_executor.validate_command(request.command):
        raise HTTPException(
            status_code=400,
            detail=f"Command '{request.command}' is not allowed. "
                   f"Allowed commands: {', '.join(cli_executor.ALLOWED_COMMANDS)}"
        )

    # Check if claude binary is available
    if not cli_executor.claude_binary:
        raise HTTPException(
            status_code=500,
            detail="Claude CLI binary not found in PATH. "
                   "Please ensure Claude Code is installed."
        )

    try:
        # Execute the command
        result = cli_executor.execute(
            command=request.command,
            args=request.args
        )
        return result

    except ValueError as e:
        # Command validation error or binary not found
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # Unexpected error
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute command: {str(e)}"
        )
