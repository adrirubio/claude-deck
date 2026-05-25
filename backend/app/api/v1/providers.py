"""Provider registry API."""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException

from app.models.schemas import CLIExecuteRequest, CLIResult
from app.services.cli_executor import ProviderCLIExecutor
from app.services.providers import get_provider, get_providers

router = APIRouter()

SENSITIVE_KEY_PATTERN = re.compile(r"(token|secret|password|credential|api[_-]?key|auth|cookie|session)", re.I)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key>[A-Za-z0-9_.-]*(?:token|secret|password|credential|api[_-]?key|auth|cookie|session)[A-Za-z0-9_.-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>[^\s,;]+)",
    re.I,
)


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


def _require_codex_provider(provider_id: str):
    try:
        provider = get_provider(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if provider.id != "codex-cli":
        raise HTTPException(status_code=400, detail="Inventory endpoints are currently Codex-only")
    return provider


def _redact_value(value: Any, parent_key: str = "") -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {
            key: "[redacted]" if SENSITIVE_KEY_PATTERN.search(key) or SENSITIVE_KEY_PATTERN.search(parent_key)
            else _redact_value(child, key)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, parent_key) for item in value]
    if SENSITIVE_KEY_PATTERN.search(parent_key):
        return "[redacted]"
    if isinstance(value, str):
        return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\g<key>\g<sep>[redacted]", value)
    return value


def _parse_plugin_rows(stdout: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    in_plugin_table = False
    column_starts: tuple[int, int, int, int] | None = None

    def append_row(name: str, status: str, version: str = "", path: str = "") -> None:
        name = name.strip()
        status = status.strip()
        if not name or not status:
            return
        row = {
            "name": name,
            "status": status,
        }
        version = version.strip()
        path = path.strip()
        if version:
            row["version"] = version
        if path:
            row["path"] = path
        rows.append(row)

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or set(line) <= {"-", " "}:
            continue
        lower = line.lower()
        if not in_plugin_table and (lower.startswith("marketplace ") or line.endswith(".json") or line.startswith("/")):
            continue

        upper_line = raw_line.upper()
        header_starts = (
            upper_line.find("PLUGIN"),
            upper_line.find("STATUS"),
            upper_line.find("VERSION"),
            upper_line.find("PATH"),
        )
        if all(start >= 0 for start in header_starts) and list(header_starts) == sorted(header_starts):
            column_starts = header_starts
            in_plugin_table = True
            continue
        if lower.startswith(("name ", "plugin ")):
            continue

        if in_plugin_table and column_starts:
            plugin_start, status_start, version_start, path_start = column_starts
            append_row(
                raw_line[plugin_start:status_start],
                raw_line[status_start:version_start],
                raw_line[version_start:path_start],
                raw_line[path_start:],
            )
            continue

        columns = re.split(r"\s{2,}|\t+", line)
        if in_plugin_table and len(columns) >= 2:
            append_row(
                columns[0],
                columns[1],
                columns[2] if len(columns) >= 3 else "",
                "  ".join(columns[3:]) if len(columns) >= 4 else "",
            )
    return rows


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


@router.get("/providers/{provider_id}/mcp")
def get_provider_mcp_inventory(provider_id: str):
    provider = _require_codex_provider(provider_id)
    executor = ProviderCLIExecutor(provider.id)
    if not executor.binary_path:
        raise HTTPException(status_code=500, detail=f"{provider.display_name} binary not found in PATH.")

    result = executor.execute("mcp", ["list", "--json"], timeout=30)
    servers = None
    parse_error = None
    if result.stdout.strip():
        try:
            servers = _redact_value(json.loads(result.stdout))
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "exit_code": result.exit_code,
        "servers": servers,
        "parse_error": parse_error,
        "stderr": _redact_value(result.stderr),
        "raw_stdout": _redact_value(result.stdout),
    }


@router.get("/providers/{provider_id}/plugins")
def get_provider_plugin_inventory(provider_id: str):
    provider = _require_codex_provider(provider_id)
    executor = ProviderCLIExecutor(provider.id)
    if not executor.binary_path:
        raise HTTPException(status_code=500, detail=f"{provider.display_name} binary not found in PATH.")

    result = executor.execute("plugin", ["list"], timeout=30)
    safe_stdout = _redact_value(result.stdout)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "exit_code": result.exit_code,
        "plugins": _redact_value(_parse_plugin_rows(result.stdout)),
        "stderr": _redact_value(result.stderr),
        "raw_stdout": safe_stdout,
    }
