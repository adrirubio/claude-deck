"""Central provider capability matrix."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


CAPABILITY_KEYS = (
    "config",
    "sessions",
    "spawn",
    "resume",
    "fork",
    "mcp",
    "plugins",
    "permissions",
    "commands",
    "agents",
    "skills",
    "hooks",
    "memory",
    "output_styles",
    "statusline",
    "usage",
    "context",
    "doctor",
    "backup",
    "restore",
    "plans",
)
SUPPORTED_STATES = {"supported", "read_only", "write_capable"}


def capability(state: str, label: str, reason: str | None = None) -> dict[str, str]:
    result = {"state": state, "label": label}
    if reason:
        result["reason"] = reason
    return result


PROVIDER_CAPABILITY_MATRIX: dict[str, dict[str, dict[str, str]]] = {
    "claude-code": {
        "config": capability("write_capable", "Configuration", "Claude Code JSON settings can be viewed and edited."),
        "sessions": capability("read_only", "Session History", "Claude Code transcript history is available."),
        "spawn": capability("write_capable", "Spawn Sessions", "Agent Bridge can launch Claude Code sessions."),
        "resume": capability("write_capable", "Resume Sessions", "Claude Code resume is available."),
        "fork": capability("unsupported", "Fork Sessions", "Claude Code fork mode is not exposed."),
        "mcp": capability("write_capable", "MCP Servers", "Claude Code MCP servers can be managed."),
        "plugins": capability("write_capable", "Plugins", "Claude Code plugins can be managed."),
        "permissions": capability("write_capable", "Permissions", "Claude Code trust and permissions can be managed."),
        "commands": capability("write_capable", "Commands", "Claude Code slash commands can be managed."),
        "agents": capability("write_capable", "Agents", "Claude Code agents can be managed."),
        "skills": capability("write_capable", "Skills", "Claude Code skills can be managed."),
        "hooks": capability("write_capable", "Hooks", "Claude Code hooks can be managed."),
        "memory": capability("write_capable", "Memory", "Claude Code memory files can be viewed and edited."),
        "output_styles": capability("write_capable", "Output Styles", "Claude Code output styles can be managed."),
        "statusline": capability("write_capable", "Status Line", "Claude Code status line settings can be managed."),
        "usage": capability("read_only", "Usage", "Claude Code usage data is available read-only."),
        "context": capability("read_only", "Context", "Claude Code context diagnostics are available read-only."),
        "doctor": capability("unsupported", "Doctor", "Claude Code does not expose provider doctor diagnostics."),
        "backup": capability("write_capable", "Backup", "Claude Code backup and restore workflows are available."),
        "restore": capability("write_capable", "Restore", "Claude Code backup restore workflows are available."),
        "plans": capability("read_only", "Plans", "Claude Code markdown plan files are available read-only."),
    },
    "codex-cli": {
        "config": capability("write_capable", "Configuration", "Safe Codex TOML settings can be viewed and edited."),
        "sessions": capability("write_capable", "Agent Bridge Sessions", "Agent Bridge can discover and launch Codex sessions."),
        "spawn": capability("write_capable", "Spawn Sessions", "Agent Bridge can launch Codex sessions."),
        "resume": capability("write_capable", "Resume Sessions", "Codex resume is available."),
        "fork": capability("write_capable", "Fork Sessions", "Codex fork is available."),
        "mcp": capability("write_capable", "MCP Servers", "Codex MCP servers can be managed through the Codex CLI."),
        "plugins": capability("write_capable", "Plugins", "Codex plugin inventory and CLI-backed install/remove are available."),
        "permissions": capability("unsupported", "Permissions", "Codex trust and permissions use different config semantics."),
        "commands": capability("unsupported", "Commands", "Codex does not expose Claude Code slash commands."),
        "agents": capability("unsupported", "Agents", "Codex does not expose Claude Code agents."),
        "skills": capability("unsupported", "Skills", "Codex skills are not surfaced in this build."),
        "hooks": capability("unsupported", "Hooks", "Codex does not expose Claude Code hooks."),
        "memory": capability("unsupported", "Memory", "Codex memory files are not surfaced in this build."),
        "output_styles": capability("unsupported", "Output Styles", "Codex does not expose Claude Code output styles."),
        "statusline": capability("unsupported", "Status Line", "Codex does not expose Claude Code status line settings."),
        "usage": capability("unsupported", "Usage", "Codex usage data is not available with stable local semantics."),
        "context": capability("unsupported", "Context", "Codex context diagnostics are not available with stable local semantics."),
        "doctor": capability("read_only", "Doctor", "Codex doctor diagnostics are available read-only."),
        "backup": capability("read_only", "Backup", "Codex export-only backups are available."),
        "restore": capability("unsupported", "Restore", "Automatic Codex restore is refused without a stable provider-owned restore API."),
        "plans": capability("read_only", "Plan Snapshots", "Codex update_plan snapshots are available read-only."),
    },
}


def normalize_capability_matrix(provider_id: str) -> dict[str, dict[str, Any]]:
    matrix = deepcopy(PROVIDER_CAPABILITY_MATRIX.get(provider_id, {}))
    for key in CAPABILITY_KEYS:
        matrix.setdefault(
            key,
            capability("unknown", key.replace("_", " ").title(), "Capability has not been classified."),
        )
    return matrix


def capability_flags(provider_id: str) -> dict[str, bool]:
    matrix = normalize_capability_matrix(provider_id)
    return {
        key: detail.get("state") in SUPPORTED_STATES
        for key, detail in matrix.items()
    }
