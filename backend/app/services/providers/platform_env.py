"""Map an Agent Bridge platform selection to process environment variables.

Single source of truth for platform -> env mapping. Credentials are never
handled here: only non-secret configuration (region, profile name, model id)
is set, and the AWS SDK credential chain on the host resolves actual creds.
"""
from __future__ import annotations

PLATFORM_ANTHROPIC = "anthropic"
PLATFORM_BEDROCK = "bedrock"


def _clean(value: str | None) -> str | None:
    """Trim a value and reject control characters that break env injection."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if "\n" in stripped or "\r" in stripped or "\x00" in stripped:
        raise ValueError("Environment value must not contain newlines or null bytes")
    return stripped


def build_platform_env(
    platform: str | None,
    region: str | None = None,
    aws_profile: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Return the env vars for a platform selection (empty for Anthropic)."""
    if platform != PLATFORM_BEDROCK:
        return {}

    env: dict[str, str] = {"CLAUDE_CODE_USE_BEDROCK": "1"}
    cleaned_region = _clean(region)
    if cleaned_region:
        env["AWS_REGION"] = cleaned_region
    cleaned_profile = _clean(aws_profile)
    if cleaned_profile:
        env["AWS_PROFILE"] = cleaned_profile
    cleaned_model = _clean(model)
    if cleaned_model:
        env["ANTHROPIC_MODEL"] = cleaned_model
    return env
