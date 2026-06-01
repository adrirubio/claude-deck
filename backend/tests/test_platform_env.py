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
