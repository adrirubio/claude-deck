import pytest

from app.services.providers import get_provider
from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions
from app.services.providers.capabilities import capability_flags
from app.services.providers.launch_contract import launch_modes_for, option_keys_for, reasoning_efforts_for

SID = "01a13be9-b3fa-79f3-941d-e49637f03184"


def build(**kwargs):
    return get_provider("muse-cli").build_spawn_command(SpawnCommandOptions(directory="/w", **kwargs))


def test_registry_and_contract():
    provider = get_provider("muse-cli")
    assert (provider.display_name, provider.binary_name) == ("Muse Code", "muse")
    assert launch_modes_for("muse-cli") == ("plain", "resume")
    assert "ultra" in reasoning_efforts_for("muse-cli")
    assert set(option_keys_for("muse-cli")) == {"model", "reasoning_effort", "skip_permissions", "prompt", "session_id"}
    flags = capability_flags("muse-cli")
    assert flags["spawn"] and flags["resume"] and flags["mcp"] and flags["hooks"]


def test_plain_launch():
    assert build(model="muse-wonder-1.0", reasoning_effort="high", skip_permissions=True, prompt="Hello") == [
        "muse", "--trust-workspace", "--model", "muse-wonder-1.0", "--reasoning-effort", "high", "--yolo", "Hello"]


def test_resume_launch():
    assert build(mode="resume", session_id=SID, model="muse-wonder-1.0") == [
        "muse", "--trust-workspace", "--model", "muse-wonder-1.0", "resume", SID]


@pytest.mark.parametrize("kwargs,code", [
    ({"mode": "resume", "session_id": "last"}, "muse_session_invalid"),
    ({"mode": "resume"}, "muse_session_invalid"),
    ({"session_id": SID}, "muse_session_invalid"),
    ({"mode": "worktree"}, "unsupported_launch_mode"),
    ({"reasoning_effort": "extreme"}, "invalid_reasoning_effort"),
    ({"model": "bad\nmodel"}, "invalid_model"),
    ({"platform": "bedrock"}, "muse_platform_unsupported"),
    ({"bedrock_model": "x"}, "muse_option_unsupported"),
    ({"no_ask_user": True}, "muse_option_unsupported"),
    ({"prompt": "-rf"}, "muse_literal_prompt_required"),
])
def test_refusals(kwargs, code):
    with pytest.raises(ProviderLaunchError) as error:
        build(**kwargs)
    assert error.value.block_code == code


@pytest.mark.parametrize("command,match", [
    ("muse --trust-workspace", True),
    ("/home/u/.local/bin/muse-bin-1.4.8-R6256.1 --trust-workspace", True),
    ("musescore", False),
    ("python3 muse.py", False),
])
def test_process_match(command, match):
    assert get_provider("muse-cli").is_process_match(command, "1") is match
