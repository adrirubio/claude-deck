"""
CLI execution API endpoints.
"""

from fastapi import APIRouter, HTTPException
from ...models.schemas import CLIExecuteRequest, CLIResult
from ...services.cli_executor import CLIExecutor, ProviderCLIExecutor

router = APIRouter(prefix="/cli", tags=["CLI"])

# Initialize default Claude executor for compatibility checks.
cli_executor = CLIExecutor()


@router.post("/execute", response_model=CLIResult)
async def execute_cli_command(request: CLIExecuteRequest) -> CLIResult:
    """
    Execute a whitelisted provider CLI command.

    Args:
        request: CLI execution request with command and args

    Returns:
        CLIResult containing stdout, stderr, and exit code

    Raises:
        HTTPException: If command is not whitelisted or execution fails
    """
    try:
        executor = ProviderCLIExecutor(request.provider)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not executor.validate_command(request.command):
        raise HTTPException(
            status_code=400,
            detail=f"Command '{request.command}' is not allowed. "
                   f"Allowed commands: {', '.join(executor.ALLOWED_COMMANDS)}"
        )

    if not executor.binary_path:
        raise HTTPException(
            status_code=500,
            detail=f"{executor.provider.display_name} binary not found in PATH. "
                   f"Please ensure {executor.provider.display_name} is installed."
        )

    try:
        result = executor.execute(
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
