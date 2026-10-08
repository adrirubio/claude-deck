"""Shared bounded configuration decisions; never credential or session proof."""
from typing import Any

from app.models.provider_operations_schemas import Check, Configuration


def agent_mail_ready_reason(provider: str, install_status: Any) -> str | None:
    if provider == "pi-cli":
        return None if getattr(install_status, "pi_mail_ready", False) else (
            getattr(install_status, "pi_mail_reason", None) or "Pi Agent Mail extension is not ready"
        )
    if provider == "claude-code":
        if not install_status.claude_code_mcp_installed:
            return "Claude Code Agent Mail MCP is not installed"
        if install_status.claude_code_hooks_missing:
            return "Claude Code Agent Mail hooks are missing"
        return None
    if provider == "codex-cli":
        if not install_status.codex_cli_available:
            return "Codex CLI is not available on this machine"
        if not install_status.codex_mcp_installed:
            return "Codex Agent Mail MCP is not installed"
        if install_status.codex_hooks_missing:
            return "Codex Agent Mail hooks are missing"
        return None
    if provider == "copilot-cli":
        if not getattr(install_status, "copilot_cli_available", False):
            return "GitHub Copilot CLI is not available on this machine"
        if not getattr(install_status, "copilot_mcp_installed", False):
            return "GitHub Copilot CLI Agent Mail MCP is not installed"
        if getattr(install_status, "copilot_hooks_missing", []):
            return "GitHub Copilot CLI Agent Mail hooks are missing"
        return None
    if provider == "opencode-cli":
        if not getattr(install_status, "opencode_cli_available", False):
            return "OpenCode CLI is not available on this machine"
        if not getattr(install_status, "opencode_mcp_installed", False):
            return "OpenCode Agent Mail MCP is not installed"
        if getattr(install_status, "opencode_plugin_events_missing", []):
            return "OpenCode Agent Mail plugin is missing or incomplete"
        return None
    return None


def configuration_readiness(provider_id: str, display_name: str, installed: bool | None, install_status: Any) -> Configuration:
    if installed is not None and type(installed) is not bool:
        installed = None
    binary = Check(state="unknown" if installed is None else "ready" if installed else "blocked", code="binary_unknown" if installed is None else "binary_installed" if installed else "provider_unavailable", reason="Binary availability was not observed." if installed is None else "Provider binary is installed." if installed else f"{display_name} is not available on this machine", source="providers/base.py:get_status")
    fields = {
        "claude-code": {"claude_code_mcp_installed": bool, "claude_code_hooks_missing": list},
        "codex-cli": {"codex_cli_available": bool, "codex_mcp_installed": bool, "codex_hooks_missing": list},
        "copilot-cli": {"copilot_cli_available": bool, "copilot_mcp_installed": bool, "copilot_hooks_missing": list},
        "opencode-cli": {"opencode_cli_available": bool, "opencode_mcp_installed": bool, "opencode_plugin_events_missing": list},
        "pi-cli": {"pi_mail_ready": bool},
    }
    expected = fields.get(provider_id)
    if expected is None or (install_status is not None and any(type(getattr(install_status, name, None)) is not kind for name, kind in expected.items())):
        install_status = None
    if install_status is None:
        mail = Check(state="unknown", code="mail_check_unavailable", reason="Agent Mail configuration could not be observed.", source="agent_mail_install_service.py:get_install_status")
    else:
        reason = agent_mail_ready_reason(provider_id, install_status)
        # Pi diagnostics are reduced to a reviewed safe summary in this public projection.
        if reason and provider_id == "pi-cli":
            reason = "Pi Agent Mail extension runtime prerequisites are not ready."
        mail = Check(state="unknown" if reason else "ready", code="agent_mail_not_configured" if reason else "agent_mail_configured", reason=(reason + ". Positive launch evidence is missing; legacy flags do not distinguish absence from a failed probe.") if reason else "Agent Mail launch prerequisites are configured.", source="agent_team_service.py:_agent_mail_ready_reason")
    checks = [binary, mail]
    # A completed legacy check without positive Mail evidence blocks launch,
    # while its underlying observation remains unknown (not verified absence).
    state = "blocked" if binary.state == "blocked" or (install_status is not None and mail.code == "agent_mail_not_configured") else "unknown" if any(c.state == "unknown" for c in checks) else "ready"
    return Configuration(state=state, checks=checks)
