"""Pure provider launch capability constants."""
from __future__ import annotations

from app.services.providers.platform_env import (
    PLATFORM_ANTHROPIC,
    PLATFORM_BEDROCK,
    PROVIDER_CLAUDE_CODE,
    PROVIDER_CODEX_CLI,
)

PROVIDER_COPILOT_CLI = "copilot-cli"
PROVIDER_OPENCODE_CLI = "opencode-cli"

CODEX_REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
COPILOT_REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
COPILOT_CONTEXT_TIERS = ("default", "long_context")

PROVIDER_LAUNCH_MODES: dict[str, tuple[str, ...]] = {
    PROVIDER_CLAUDE_CODE: ("plain", "worktree", "resume"),
    PROVIDER_CODEX_CLI: ("plain", "resume", "fork"),
    PROVIDER_COPILOT_CLI: ("plain", "resume"),
    PROVIDER_OPENCODE_CLI: ("plain", "resume"),
}

PROVIDER_REASONING_EFFORTS: dict[str, tuple[str, ...]] = {
    PROVIDER_CODEX_CLI: CODEX_REASONING_EFFORTS,
    PROVIDER_COPILOT_CLI: COPILOT_REASONING_EFFORTS,
}

PROVIDER_BEDROCK_SUPPORT: dict[str, bool] = {
    PROVIDER_CLAUDE_CODE: True,
    PROVIDER_CODEX_CLI: True,
    PROVIDER_COPILOT_CLI: False,
    PROVIDER_OPENCODE_CLI: True,
}

PROVIDER_OPTION_KEYS: dict[str, tuple[str, ...]] = {
    PROVIDER_CLAUDE_CODE: (
        "skip_permissions",
        "platform",
        "aws_region",
        "aws_profile",
        "bedrock_model",
        "prompt",
        "session_id",
        "project_folder",
        "worktree_name",
    ),
    PROVIDER_CODEX_CLI: (
        "model",
        "profile",
        "profile_v2",
        "sandbox",
        "approval_policy",
        "search",
        "no_alt_screen",
        "dangerously_bypass_approvals_and_sandbox",
        "use_last",
        "session_id",
        "platform",
        "aws_region",
        "aws_profile",
        "bedrock_model",
        "reasoning_effort",
        "prompt",
    ),
    PROVIDER_COPILOT_CLI: (
        "model",
        "agent",
        "context_tier",
        "reasoning_effort",
        "plan",
        "remote",
        "allow_all",
        "no_ask_user",
        "skip_permissions",
        "dangerously_bypass_approvals_and_sandbox",
        "use_last",
        "session_id",
        "prompt",
    ),
    PROVIDER_OPENCODE_CLI: (
        "model",
        "agent",
        "use_last",
        "session_id",
        "platform",
        "aws_region",
        "aws_profile",
        "reasoning_effort",
        "prompt",
    ),
}

MODEL_EXAMPLES: dict[str, tuple[dict[str, str], ...]] = {
    PROVIDER_CLAUDE_CODE: (
        {
            "value": "arn:aws:bedrock:REGION:ACCOUNT:inference-profile/PROFILE_ID",
            "label": "Amazon Bedrock inference profile ARN",
            "source": "example",
        },
    ),
    PROVIDER_CODEX_CLI: (
        {
            "value": "openai.gpt-5.5",
            "label": "OpenAI GPT-5.5 via Bedrock gateway",
            "source": "example",
        },
        {
            "value": "gpt-5.5",
            "label": "GPT-5.5 through Codex default provider",
            "source": "example",
        },
    ),
    PROVIDER_COPILOT_CLI: (
        {
            "value": "gpt-5.4",
            "label": "GPT-5.4",
            "source": "example",
        },
        {
            "value": "claude-sonnet-4.6",
            "label": "Claude Sonnet 4.6",
            "source": "example",
        },
    ),
    PROVIDER_OPENCODE_CLI: (
        {
            "value": "anthropic/claude-sonnet-4.6",
            "label": "Anthropic Claude Sonnet 4.6",
            "source": "example",
        },
    ),
}


def reasoning_efforts_for(provider_id: str) -> tuple[str, ...]:
    """Return accepted reasoning effort values for a provider."""
    return PROVIDER_REASONING_EFFORTS.get(provider_id, ())


def launch_modes_for(provider_id: str) -> tuple[str, ...]:
    """Return supported launch modes for a provider."""
    return PROVIDER_LAUNCH_MODES.get(provider_id, ("plain",))


def option_keys_for(provider_id: str) -> tuple[str, ...]:
    """Return supported launch option keys for a provider."""
    return PROVIDER_OPTION_KEYS.get(provider_id, ())


def supports_bedrock(provider_id: str) -> bool:
    """Return whether a provider exposes a Deck Bedrock launch path."""
    return PROVIDER_BEDROCK_SUPPORT.get(provider_id, False)
