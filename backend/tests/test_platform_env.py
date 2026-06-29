"""Tests for platform -> environment-variable mapping."""
import pytest


def test_anthropic_returns_empty_env():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_ANTHROPIC

    assert build_platform_env(PLATFORM_ANTHROPIC) == {}


def test_unknown_platform_returns_empty_env():
    from app.services.providers.platform_env import build_platform_env

    assert build_platform_env("vertex") == {}


def test_bedrock_minimal_sets_use_bedrock_flag():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    assert build_platform_env(PLATFORM_BEDROCK) == {"CLAUDE_CODE_USE_BEDROCK": "1"}


def test_bedrock_with_all_fields():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(
        PLATFORM_BEDROCK,
        region="us-east-1",
        aws_profile="bedrock-prod",
        model="arn:aws:bedrock:us-east-1:123:inference-profile/x",
    )
    assert env == {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_REGION": "us-east-1",
        "AWS_PROFILE": "bedrock-prod",
        "ANTHROPIC_MODEL": "arn:aws:bedrock:us-east-1:123:inference-profile/x",
    }


def test_bedrock_skips_blank_and_whitespace_values():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(PLATFORM_BEDROCK, region="  ", aws_profile="", model=None)
    assert env == {"CLAUDE_CODE_USE_BEDROCK": "1"}


def test_bedrock_strips_surrounding_whitespace():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(PLATFORM_BEDROCK, region="  us-west-2  ")
    assert env["AWS_REGION"] == "us-west-2"


def test_bedrock_rejects_newline_in_value():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    with pytest.raises(ValueError):
        build_platform_env(PLATFORM_BEDROCK, region="us-east-1\nFOO=bar")


def test_bedrock_rejects_null_byte_in_value():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    with pytest.raises(ValueError):
        build_platform_env(PLATFORM_BEDROCK, model="bad\x00value")


def test_codex_bedrock_only_sets_shared_aws_env():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(
        PLATFORM_BEDROCK,
        region="us-east-2",
        aws_profile="codex-bedrock",
        model="openai.gpt-5.5",
        provider_id="codex-cli",
    )

    assert env == {
        "AWS_REGION": "us-east-2",
        "AWS_PROFILE": "codex-bedrock",
    }


def test_codex_bedrock_without_region_or_profile_has_no_env():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    assert build_platform_env(PLATFORM_BEDROCK, provider_id="codex-cli") == {}


def test_opencode_bedrock_only_sets_shared_aws_env():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(
        PLATFORM_BEDROCK,
        region="us-west-2",
        aws_profile="opencode-bedrock",
        model="anthropic/claude-opus-4.8",
        provider_id="opencode-cli",
    )

    assert env == {
        "AWS_REGION": "us-west-2",
        "AWS_PROFILE": "opencode-bedrock",
    }
    assert "CLAUDE_CODE_USE_BEDROCK" not in env
    assert "ANTHROPIC_MODEL" not in env


def test_copilot_bedrock_does_not_receive_claude_code_env():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(
        PLATFORM_BEDROCK,
        region="us-west-2",
        aws_profile="copilot-bedrock",
        model="gpt-5.5",
        provider_id="copilot-cli",
    )

    assert env == {
        "AWS_REGION": "us-west-2",
        "AWS_PROFILE": "copilot-bedrock",
    }
    assert "CLAUDE_CODE_USE_BEDROCK" not in env
    assert "ANTHROPIC_MODEL" not in env
