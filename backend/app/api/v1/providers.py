"""Provider registry API."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.models.schemas import CLIExecuteRequest, CLIResult
from app.services.cli_executor import ProviderCLIExecutor
from app.services.providers import get_provider, get_providers

router = APIRouter()


@router.get("/providers")
def list_providers():
    providers = [provider.get_status() for provider in get_providers()]
    return {"providers": providers, "count": len(providers)}


@router.get("/providers/{provider_id}/status")
def get_provider_status(provider_id: str):
    try:
        return get_provider(provider_id).get_status()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/providers/{provider_id}/cli", response_model=CLIResult)
def execute_provider_cli(provider_id: str, request: CLIExecuteRequest):
    try:
        executor = ProviderCLIExecutor(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not executor.validate_command(request.command):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Command '{request.command}' is not allowed. "
                f"Allowed commands: {', '.join(executor.ALLOWED_COMMANDS)}"
            ),
        )

    if not executor.binary_path:
        raise HTTPException(
            status_code=500,
            detail=f"{executor.provider.display_name} binary not found in PATH.",
        )

    return executor.execute(request.command, request.args)


@router.get("/providers/{provider_id}/doctor")
def get_provider_doctor(provider_id: str):
    try:
        provider = get_provider(provider_id)
        executor = ProviderCLIExecutor(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not provider.get_capabilities().get("doctor"):
        raise HTTPException(
            status_code=400,
            detail=f"{provider.display_name} does not expose doctor diagnostics",
        )
    if not executor.binary_path:
        raise HTTPException(
            status_code=500,
            detail=f"{provider.display_name} binary not found in PATH.",
        )

    result = executor.execute("doctor", ["--json"], timeout=30)
    report = None
    parse_error = None
    if result.stdout.strip():
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "exit_code": result.exit_code,
        "report": report,
        "parse_error": parse_error,
        "stderr": result.stderr,
    }
