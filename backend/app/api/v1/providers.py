"""Provider registry API."""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.models.schemas import CLIExecuteRequest, CLIResult
from app.services.cli_executor import ProviderCLIExecutor
from app.services.codex_history_service import CodexHistoryService
from app.services.codex_usage_context_service import CodexUsageContextService
from app.services.providers import get_provider, get_providers

router = APIRouter()

SENSITIVE_KEY_PATTERN = re.compile(r"(token|secret|password|credential|api[_-]?key|auth|cookie|session)", re.I)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key>[A-Za-z0-9_.-]*(?:token|secret|password|credential|api[_-]?key|auth|cookie|session)[A-Za-z0-9_.-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>[^\s,;]+)",
    re.I,
)
MCP_SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_MCP_ARGS = 64
MAX_MCP_ENV_VARS = 64
MAX_MCP_STRING_LENGTH = 4096
PLUGIN_SELECTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?:@[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?$")


CODEX_PLUGIN_MUTATION_CAPABILITIES = {
    "install": {
        "state": "supported",
        "command": "codex plugin add",
        "reason": "Supported by the installed Codex CLI plugin command surface.",
    },
    "remove": {
        "state": "supported",
        "command": "codex plugin remove",
        "reason": "Supported by the installed Codex CLI plugin command surface.",
    },
    "enable": {
        "state": "unsupported",
        "reason": "The installed Codex CLI does not expose plugin enable commands.",
    },
    "disable": {
        "state": "unsupported",
        "reason": "The installed Codex CLI does not expose plugin disable commands.",
    },
}


def _provider_error(
    status_code: int,
    code: str,
    message: str,
    *,
    provider_id: str | None = None,
    operation: str | None = None,
    capability: str | None = None,
    supported_providers: list[str] | None = None,
) -> HTTPException:
    detail: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if provider_id:
        detail["provider"] = provider_id
    if operation:
        detail["operation"] = operation
    if capability:
        detail["capability"] = capability
    if supported_providers is not None:
        detail["supported_providers"] = supported_providers
    return HTTPException(status_code=status_code, detail=detail)


class CodexMcpAddRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    command: str | None = Field(default=None, max_length=MAX_MCP_STRING_LENGTH)
    args: list[str] = Field(default_factory=list, max_length=MAX_MCP_ARGS)
    env: dict[str, str] = Field(default_factory=dict, max_length=MAX_MCP_ENV_VARS)
    url: str | None = Field(default=None, max_length=MAX_MCP_STRING_LENGTH)
    bearer_token_env_var: str | None = Field(default=None, max_length=256)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_mcp_server_name(value)

    @field_validator("command", "url", "bearer_token_env_var")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_cli_string(value)

    @field_validator("args")
    @classmethod
    def validate_args(cls, value: list[str]) -> list[str]:
        return [_validate_cli_string(arg) for arg in value]

    @field_validator("env")
    @classmethod
    def validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        safe_env: dict[str, str] = {}
        for key, env_value in value.items():
            if not ENV_KEY_PATTERN.fullmatch(key):
                raise ValueError(f"Invalid environment variable name: {key}")
            safe_env[key] = _validate_cli_string(env_value)
        return safe_env


class CodexPluginMutationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    marketplace: str | None = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_plugin_selector(value)

    @field_validator("marketplace")
    @classmethod
    def validate_marketplace(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_plugin_marketplace(value)


@router.get("/providers")
def list_providers():
    providers = [provider.get_status() for provider in get_providers()]
    return {"providers": providers, "count": len(providers)}


@router.get("/providers/{provider_id}/status")
def get_provider_status(provider_id: str):
    return _get_provider_or_404(provider_id).get_status()


@router.get("/providers/{provider_id}/capabilities")
def get_provider_capabilities(provider_id: str):
    provider = _get_provider_or_404(provider_id)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "capabilities": provider.get_capabilities(),
        "capability_matrix": provider.get_capability_matrix(),
    }


def _get_provider_or_404(provider_id: str):
    try:
        return get_provider(provider_id)
    except ValueError as exc:
        raise _provider_error(
            404,
            "unknown_provider",
            str(exc),
            provider_id=provider_id,
        )


def _require_capability(provider, capability: str, operation: str) -> None:
    if provider.get_capabilities().get(capability):
        return
    raise _provider_error(
        400,
        "unsupported_operation",
        f"{provider.display_name} does not support {operation}",
        provider_id=provider.id,
        operation=operation,
        capability=capability,
    )


def _require_provider_binary(executor: ProviderCLIExecutor, operation: str) -> None:
    if executor.binary_path:
        return
    raise _provider_error(
        500,
        "provider_binary_missing",
        f"{executor.provider.display_name} binary not found in PATH.",
        provider_id=executor.provider_id,
        operation=operation,
    )


def _require_codex_provider(provider_id: str, operation: str):
    provider = _get_provider_or_404(provider_id)
    if provider.id != "codex-cli":
        raise _provider_error(
            400,
            "unsupported_provider_operation",
            f"{operation} is currently supported only for Codex CLI",
            provider_id=provider.id,
            operation=operation,
            supported_providers=["codex-cli"],
        )
    return provider


def _validate_mcp_server_name(name: str) -> str:
    name = name.strip()
    if not MCP_SERVER_NAME_PATTERN.fullmatch(name):
        raise ValueError("MCP server name must use letters, numbers, '.', '_', '@', or '-'")
    return name


def _validate_cli_string(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Value must be a string")
    if not value:
        raise ValueError("Value cannot be empty")
    if "\x00" in value or any(ord(char) < 32 and char not in {"\t"} for char in value):
        raise ValueError("Value contains control characters")
    if len(value) > MAX_MCP_STRING_LENGTH:
        raise ValueError(f"Value cannot exceed {MAX_MCP_STRING_LENGTH} characters")
    return value


def _validate_plugin_selector(value: str) -> str:
    value = value.strip()
    if not PLUGIN_SELECTOR_PATTERN.fullmatch(value):
        raise ValueError("Plugin selector must be PLUGIN or PLUGIN@MARKETPLACE using letters, numbers, '.', '_', or '-'")
    return value


def _validate_plugin_marketplace(value: str) -> str:
    value = value.strip()
    if not value or "@" in value or not PLUGIN_SELECTOR_PATTERN.fullmatch(value):
        raise ValueError("Marketplace must use letters, numbers, '.', '_', or '-'")
    return value


def _redact_cli_result(result: CLIResult) -> dict[str, Any]:
    return {
        "stdout": _redact_value(result.stdout),
        "stderr": _redact_value(result.stderr),
        "exit_code": result.exit_code,
    }


def _build_codex_mcp_add_args(request: CodexMcpAddRequest) -> list[str]:
    has_url = bool(request.url)
    has_command = bool(request.command)
    if has_url == has_command:
        raise HTTPException(status_code=400, detail="Provide exactly one of url or command")

    if request.url:
        if not request.url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="MCP server URL must start with http:// or https://")
        if request.args:
            raise HTTPException(status_code=400, detail="args are only valid with command-based MCP servers")
        if request.env:
            raise HTTPException(status_code=400, detail="env is only valid with command-based MCP servers")
        args = ["add", "--url", request.url]
        if request.bearer_token_env_var:
            if not ENV_KEY_PATTERN.fullmatch(request.bearer_token_env_var):
                raise HTTPException(status_code=400, detail="Invalid bearer token environment variable name")
            args.extend(["--bearer-token-env-var", request.bearer_token_env_var])
        args.append(request.name)
        return args

    if request.bearer_token_env_var:
        raise HTTPException(
            status_code=400,
            detail="bearer_token_env_var is only valid with URL-based MCP servers",
        )
    args = ["add"]
    for key, value in request.env.items():
        args.extend(["--env", f"{key}={value}"])
    args.extend([request.name, "--", request.command or ""])
    args.extend(request.args)
    return args


def _build_codex_plugin_args(action: str, name: str, marketplace: str | None = None) -> list[str]:
    if action not in {"add", "remove"}:
        raise HTTPException(status_code=400, detail="Codex plugin action is not supported")
    try:
        safe_name = _validate_plugin_selector(name)
        safe_marketplace = _validate_plugin_marketplace(marketplace) if marketplace else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if marketplace:
        if "@" in safe_name:
            raise HTTPException(
                status_code=400,
                detail="Provide marketplace either in the plugin selector or marketplace field, not both",
            )
        return [action, safe_name, "--marketplace", safe_marketplace]
    return [action, safe_name]


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
    provider = _get_provider_or_404(provider_id)
    executor = ProviderCLIExecutor(provider.id)

    if not executor.validate_command(request.command):
        raise _provider_error(
            400,
            "command_not_allowed",
            (
                f"Command '{request.command}' is not allowed. "
                f"Allowed commands: {', '.join(executor.ALLOWED_COMMANDS)}"
            ),
            provider_id=provider.id,
            operation=f"cli:{request.command}",
        )

    _require_provider_binary(executor, f"cli:{request.command}")

    result = executor.execute(request.command, request.args)
    return CLIResult(**_redact_cli_result(result))


@router.get("/providers/{provider_id}/doctor")
def get_provider_doctor(provider_id: str):
    provider = _get_provider_or_404(provider_id)
    executor = ProviderCLIExecutor(provider.id)
    _require_capability(provider, "doctor", "doctor diagnostics")
    _require_provider_binary(executor, "doctor diagnostics")

    result = executor.execute("doctor", ["--json"], timeout=30)
    report = None
    parse_error = None
    if result.stdout.strip():
        try:
            report = _redact_value(json.loads(result.stdout))
        except json.JSONDecodeError:
            parse_error = "Provider doctor output was not valid JSON"

    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "exit_code": result.exit_code,
        "report": report,
        "parse_error": parse_error,
        "stderr": _redact_value(result.stderr),
    }


@router.get("/providers/{provider_id}/mcp")
def get_provider_mcp_inventory(provider_id: str):
    provider = _require_codex_provider(provider_id, "MCP inventory")
    executor = ProviderCLIExecutor(provider.id)
    _require_provider_binary(executor, "MCP inventory")

    result = executor.execute("mcp", ["list", "--json"], timeout=30)
    servers = None
    parse_error = None
    raw_stdout = _redact_value(result.stdout)
    if result.stdout.strip():
        try:
            servers = _redact_value(json.loads(result.stdout))
            raw_stdout = json.dumps(servers)
        except json.JSONDecodeError:
            parse_error = "Provider MCP inventory output was not valid JSON"

    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "exit_code": result.exit_code,
        "servers": servers,
        "parse_error": parse_error,
        "stderr": _redact_value(result.stderr),
        "raw_stdout": raw_stdout,
    }


@router.post("/providers/{provider_id}/mcp")
def add_provider_mcp_server(provider_id: str, request: CodexMcpAddRequest):
    mcp_args = _build_codex_mcp_add_args(request)
    provider = _require_codex_provider(provider_id, "MCP server mutation")
    executor = ProviderCLIExecutor(provider.id)
    _require_provider_binary(executor, "MCP server mutation")

    result = executor.execute("mcp", mcp_args, timeout=30)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "name": request.name,
        **_redact_cli_result(result),
    }


@router.delete("/providers/{provider_id}/mcp/{server_name}")
def remove_provider_mcp_server(provider_id: str, server_name: str):
    try:
        safe_name = _validate_mcp_server_name(server_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    provider = _require_codex_provider(provider_id, "MCP server mutation")
    executor = ProviderCLIExecutor(provider.id)
    _require_provider_binary(executor, "MCP server mutation")

    result = executor.execute("mcp", ["remove", safe_name], timeout=30)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "name": safe_name,
        **_redact_cli_result(result),
    }


@router.get("/providers/{provider_id}/plugins")
def get_provider_plugin_inventory(provider_id: str):
    provider = _require_codex_provider(provider_id, "plugin inventory")
    executor = ProviderCLIExecutor(provider.id)
    _require_provider_binary(executor, "plugin inventory")

    result = executor.execute("plugin", ["list"], timeout=30)
    safe_stdout = _redact_value(result.stdout)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "exit_code": result.exit_code,
        "plugins": _redact_value(_parse_plugin_rows(result.stdout)),
        "mutation_capabilities": CODEX_PLUGIN_MUTATION_CAPABILITIES,
        "stderr": _redact_value(result.stderr),
        "raw_stdout": safe_stdout,
    }


@router.post("/providers/{provider_id}/plugins")
def install_provider_plugin(provider_id: str, request: CodexPluginMutationRequest):
    plugin_args = _build_codex_plugin_args("add", request.name, request.marketplace)
    provider = _require_codex_provider(provider_id, "plugin mutation")
    executor = ProviderCLIExecutor(provider.id)
    _require_provider_binary(executor, "plugin mutation")

    result = executor.execute("plugin", plugin_args, timeout=60)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "name": request.name,
        "action": "install",
        **_redact_cli_result(result),
    }


@router.delete("/providers/{provider_id}/plugins/{plugin_name}")
def remove_provider_plugin(provider_id: str, plugin_name: str, marketplace: str | None = None):
    plugin_args = _build_codex_plugin_args("remove", plugin_name, marketplace)
    provider = _require_codex_provider(provider_id, "plugin mutation")
    executor = ProviderCLIExecutor(provider.id)
    _require_provider_binary(executor, "plugin mutation")

    result = executor.execute("plugin", plugin_args, timeout=60)
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "name": plugin_name,
        "action": "remove",
        **_redact_cli_result(result),
    }


@router.post("/providers/{provider_id}/plugins/{plugin_name}/enable")
def enable_provider_plugin(provider_id: str, plugin_name: str):
    _require_codex_provider(provider_id, "plugin mutation")
    try:
        _validate_plugin_selector(plugin_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(
        status_code=400,
        detail=CODEX_PLUGIN_MUTATION_CAPABILITIES["enable"]["reason"],
    )


@router.post("/providers/{provider_id}/plugins/{plugin_name}/disable")
def disable_provider_plugin(provider_id: str, plugin_name: str):
    _require_codex_provider(provider_id, "plugin mutation")
    try:
        _validate_plugin_selector(plugin_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(
        status_code=400,
        detail=CODEX_PLUGIN_MUTATION_CAPABILITIES["disable"]["reason"],
    )


@router.get("/providers/{provider_id}/history-diagnostics")
def get_provider_history_diagnostics(provider_id: str):
    provider = _require_codex_provider(provider_id, "history diagnostics")
    diagnostics = CodexHistoryService().get_diagnostics()
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        **diagnostics,
    }


@router.get("/providers/{provider_id}/usage-context-diagnostics")
def get_provider_usage_context_diagnostics(provider_id: str):
    provider = _require_codex_provider(provider_id, "usage context diagnostics")
    diagnostics = CodexUsageContextService().get_diagnostics()
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        **diagnostics,
    }
