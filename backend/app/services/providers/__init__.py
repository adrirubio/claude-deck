"""Provider registry."""
from __future__ import annotations

from app.services.providers.base import AgentProvider
from app.services.providers.claude_code import ClaudeCodeProvider
from app.services.providers.copilot_cli import CopilotCliProvider
from app.services.providers.codex_cli import CodexCliProvider
from app.services.providers.opencode_cli import OpenCodeCliProvider
from app.services.providers.pi_cli import PiCliProvider


_PROVIDERS: dict[str, AgentProvider] = {
    "claude-code": ClaudeCodeProvider(),
    "codex-cli": CodexCliProvider(),
    "copilot-cli": CopilotCliProvider(),
    "opencode-cli": OpenCodeCliProvider(),
    "pi-cli": PiCliProvider(),
}


def get_providers() -> list[AgentProvider]:
    return list(_PROVIDERS.values())


def get_provider(provider_id: str) -> AgentProvider:
    try:
        return _PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {provider_id}") from exc
