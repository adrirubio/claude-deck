"""Claude Code model and reasoning-effort launch options (#869).

Deterministic: argv lists and option validation only. No executable is run.
"""
import pytest

from app.services.providers import get_provider
from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions
from app.services.providers.launch_contract import MODEL_EXAMPLES, option_keys_for, reasoning_efforts_for
from app.services.providers.launch_options import build_provider_launch_options
from app.services.providers.platform_env import build_platform_env

SID = "01a13be9-b3fa-79f3-941d-e49637f03184"
OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
ARN = "arn:aws:bedrock:us-east-1:123456789012:inference-profile/profile-1"
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def build(**kwargs):
    return get_provider("claude-code").build_spawn_command(SpawnCommandOptions(directory="/w", **kwargs))


def test_option_keys_keep_every_existing_key_and_add_model_and_effort():
    keys = set(option_keys_for("claude-code"))
    assert {"skip_permissions", "platform", "aws_region", "aws_profile", "bedrock_model",
            "prompt", "session_id", "project_folder", "worktree_name"} <= keys
    assert {"model", "reasoning_effort"} <= keys


def test_reasoning_efforts_are_the_levels_of_the_claude_cli():
    assert reasoning_efforts_for("claude-code") == EFFORTS


def test_descriptor_offers_effort_and_concrete_model_examples():
    descriptor = build_provider_launch_options(get_provider("claude-code"))
    assert descriptor["reasoning_effort_supported"] is True
    assert [option["value"] for option in descriptor["reasoning_effort_options"]] == list(EFFORTS)
    values = [option["value"] for option in descriptor["model_options"]]
    assert OPUS in values and SONNET in values
    assert "model" in descriptor["supported_launch_options"]
    assert "reasoning_effort" in descriptor["supported_launch_options"]
    assert descriptor["bedrock_supported"] is True


def test_the_bedrock_arn_example_is_kept():
    values = [example["value"] for example in MODEL_EXAMPLES["claude-code"]]
    assert "arn:aws:bedrock:REGION:ACCOUNT:inference-profile/PROFILE_ID" in values


def test_a_plain_launch_without_the_new_options_is_unchanged():
    assert build() == ["claude"]
    assert build(skip_permissions=True, prompt="Hello") == ["claude", "--dangerously-skip-permissions", "Hello"]
    assert build(mode="resume", session_id=SID) == ["claude", "--resume", SID]
    assert build(mode="worktree", worktree_name="w1") == ["claude", "--worktree", "w1"]


def test_model_becomes_the_model_flag():
    assert build(model=OPUS) == ["claude", "--model", OPUS]


@pytest.mark.parametrize("level", EFFORTS)
def test_every_effort_level_becomes_the_effort_flag(level):
    assert build(reasoning_effort=level) == ["claude", "--effort", level]


def test_model_effort_permissions_and_prompt_keep_a_fixed_order():
    assert build(model=SONNET, reasoning_effort="high", skip_permissions=True, prompt="Hello") == [
        "claude", "--model", SONNET, "--effort", "high", "--dangerously-skip-permissions", "Hello"]


def test_model_and_effort_follow_the_mode_flags():
    assert build(mode="resume", session_id=SID, model=OPUS, reasoning_effort="low") == [
        "claude", "--resume", SID, "--model", OPUS, "--effort", "low"]
    assert build(mode="worktree", worktree_name="w1", session_id=SID, model=OPUS) == [
        "claude", "--worktree", "w1", "--session-id", SID, "--model", OPUS]


@pytest.mark.parametrize("model", ["", "   ", "opus", "sonnet", "claude opus", "--dangerously-skip-permissions",
                                   "-m", "claude-opus-5-5\n--effort", "claude\x00opus", "Claude Opus 5.5"])
def test_an_invalid_or_display_name_model_is_refused(model):
    with pytest.raises(ProviderLaunchError) as raised:
        build(model=model)
    assert raised.value.block_code == "invalid_model"


@pytest.mark.parametrize("effort", ["extreme", "HIGH", "High", "none", "off", "ultra", "minimal"])
def test_an_unsupported_effort_is_refused(effort):
    with pytest.raises(ProviderLaunchError) as raised:
        build(reasoning_effort=effort)
    assert raised.value.block_code == "invalid_reasoning_effort"


def test_a_model_on_the_bedrock_platform_is_passed_as_the_model_flag():
    assert build(platform="bedrock", model=OPUS) == ["claude", "--model", OPUS]


def test_a_bedrock_slot_with_only_bedrock_model_is_unchanged():
    assert build(platform="bedrock", bedrock_model=ARN) == ["claude"]
    assert build_platform_env("bedrock", "us-east-1", "prod", ARN, provider_id="claude-code") == {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_REGION": "us-east-1",
        "AWS_PROFILE": "prod",
        "ANTHROPIC_MODEL": ARN,
    }


def test_setting_model_and_bedrock_model_together_on_bedrock_is_refused():
    with pytest.raises(ProviderLaunchError) as raised:
        build(platform="bedrock", model=OPUS, bedrock_model=ARN)
    assert raised.value.block_code == "bedrock_model_conflict"
    assert "model" in str(raised.value) and "bedrock_model" in str(raised.value)


def test_a_stale_bedrock_model_on_the_default_platform_is_ignored():
    assert build(platform="anthropic", model=OPUS, bedrock_model=ARN) == ["claude", "--model", OPUS]
    assert build(platform="anthropic", bedrock_model=ARN) == ["claude"]
