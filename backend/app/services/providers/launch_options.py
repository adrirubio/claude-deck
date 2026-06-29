"""Provider launch option capabilities shared by API, validation, and UI."""
from __future__ import annotations

from typing import Any

from app.services.codex_config_service import CodexConfigService
from app.services.providers.launch_contract import (
    COPILOT_CONTEXT_TIERS,
    MODEL_EXAMPLES,
    PROVIDER_CODEX_CLI,
    PROVIDER_COPILOT_CLI,
    PLATFORM_ANTHROPIC,
    PLATFORM_BEDROCK,
    launch_modes_for,
    option_keys_for,
    reasoning_efforts_for,
    supports_bedrock,
)


def build_provider_launch_options(provider: Any) -> dict[str, Any]:
    """Build the provider launch-options descriptor consumed by UI and agents."""
    descriptor: dict[str, Any] = {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "supported_launch_modes": list(launch_modes_for(provider.id)),
        "supported_launch_options": list(option_keys_for(provider.id)),
        "platform_options": [PLATFORM_ANTHROPIC, PLATFORM_BEDROCK]
        if supports_bedrock(provider.id)
        else [PLATFORM_ANTHROPIC],
        "default_platform": PLATFORM_ANTHROPIC,
        "bedrock_supported": supports_bedrock(provider.id),
        "reasoning_effort_supported": bool(reasoning_efforts_for(provider.id)),
        "reasoning_effort_options": [
            {"value": value, "label": _labelize_effort(value)}
            for value in reasoning_efforts_for(provider.id)
        ],
        "context_tier_options": [
            {"value": value, "label": _labelize_context(value)}
            for value in (COPILOT_CONTEXT_TIERS if provider.id == PROVIDER_COPILOT_CLI else ())
        ],
        "model_options": list(MODEL_EXAMPLES.get(provider.id, ())),
        "profile_options": [],
        "model_examples": list(MODEL_EXAMPLES.get(provider.id, ())),
        "warnings": [],
    }

    if provider.id == PROVIDER_CODEX_CLI:
        codex_options = CodexConfigService().get_launch_options()
        descriptor.update(codex_options)
        existing_values = {
            option.get("value")
            for option in descriptor.get("model_options", [])
            if isinstance(option, dict)
        }
        examples = [
            option
            for option in MODEL_EXAMPLES[PROVIDER_CODEX_CLI]
            if option["value"] not in existing_values
        ]
        descriptor["model_options"] = list(descriptor.get("model_options", [])) + examples
        descriptor["model_examples"] = list(MODEL_EXAMPLES[PROVIDER_CODEX_CLI])

    return descriptor


def _labelize_effort(value: str) -> str:
    if value == "xhigh":
        return "Extra High"
    return value.replace("_", " ").title()


def _labelize_context(value: str) -> str:
    if value == "long_context":
        return "Long context"
    return value.replace("_", " ").title()
