from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.services.providers import get_provider
from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions
from app.services.providers.launch_options import build_provider_launch_options
from app.services.providers.pi_cli import pi_session_directory


@pytest.fixture
def options(tmp_path):
    return SpawnCommandOptions(directory=str(tmp_path), platform="openrouter")


def test_pi_default_launch_and_descriptor(options):
    provider = get_provider("pi-cli")
    assert provider.build_spawn_command(options) == ["pi", "--provider", "openrouter", "--model", "moonshotai/kimi-k3", "--session-dir", str(pi_session_directory(options.directory).resolve())]
    descriptor = build_provider_launch_options(provider)
    assert descriptor["platform_options"] == ["openrouter"]
    assert descriptor["bedrock_supported"] is False
    assert not provider.get_capabilities()["permissions"]
    assert provider.get_allowed_cli_commands() == []


@pytest.mark.parametrize("prompt", ["--flag", "spaces and 'quotes'", '"quoted"', "two\nlines"])
def test_pi_literal_prompts(options, prompt):
    assert get_provider("pi-cli").build_spawn_command(replace(options, prompt=prompt))[-2:] == ["--", prompt]


@pytest.mark.parametrize("prompt", ["@/nonexistent", "@relative-file"])
def test_pi_attachment_like_prompt_refuses(options, prompt):
    with pytest.raises(ProviderLaunchError) as error:
        get_provider("pi-cli").build_spawn_command(replace(options, prompt=prompt))
    assert error.value.block_code == "pi_literal_prompt_required"


@pytest.mark.parametrize("level", ["off", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_pi_thinking(options, level):
    assert get_provider("pi-cli").build_spawn_command(replace(options, reasoning_effort=level))[-2:] == ["--thinking", level]


@pytest.mark.parametrize("field,value", [
    ("platform", "anthropic"), ("platform", "bedrock"), ("mode", "fork"),
    ("skip_permissions", True), ("sandbox", "workspace-write"), ("aws_profile", "test"),
    ("profile", "test"), ("remote", True), ("agent", "test"), ("plan", True),
    ("reasoning_effort", "invalid"),
])
def test_pi_unsupported_options(options, field, value):
    with pytest.raises(ProviderLaunchError):
        get_provider("pi-cli").build_spawn_command(replace(options, **{field: value}))


def test_pi_exact_resume_and_project_encoding(options, monkeypatch, tmp_path):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    directory = pi_session_directory(options.directory)
    directory.mkdir(parents=True)
    session_id = "e8e7f1be-b0e2-41e1-8e57-fca115081fc0"
    session = directory / f"2026-09-26_{session_id}.jsonl"
    session.write_text(json.dumps({"type": "session", "id": session_id, "cwd": options.directory}) + "\n")
    provider = get_provider("pi-cli")
    assert provider.build_spawn_command(replace(options, mode="resume", session_id=session_id))[-2:] == ["--session", str(session)]
    assert provider.build_spawn_command(replace(options, mode="resume", session_id=str(session)))[-1] == str(session)
    assert provider.build_spawn_command(replace(options, mode="resume", use_last=True))[-1] == "--continue"
    for bad in [session_id[:8], str(tmp_path / "foreign.jsonl")]:
        with pytest.raises(ProviderLaunchError):
            provider.build_spawn_command(replace(options, mode="resume", session_id=bad))
    with pytest.raises(ProviderLaunchError):
        provider.build_spawn_command(replace(options, mode="resume", session_id=session_id, use_last=True))


@pytest.mark.parametrize("source", ["environment", "global", "project"])
def test_pi_custom_session_directories_keep_exact_project_ownership(options, monkeypatch, tmp_path, source):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.delenv("PI_CODING_AGENT_SESSION_DIR", raising=False)
    shared = tmp_path / "shared"
    shared.mkdir()
    if source == "environment":
        monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(shared))
    else:
        settings = tmp_path / ("agent/settings.json" if source == "global" else ".pi/settings.json")
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"sessionDir": str(shared)}))
    session_id = "e8e7f1be-b0e2-41e1-8e57-fca115081fc0"
    session = shared / f"2026-09-26_{session_id}.jsonl"
    session.write_text(json.dumps({"type": "session", "id": session_id, "cwd": options.directory}) + "\n")
    provider = get_provider("pi-cli")
    for selector in [session_id, str(session)]:
        command = provider.build_spawn_command(replace(options, mode="resume", session_id=selector))
        assert command[command.index("--session-dir") + 1] == str(shared)
        assert command[-1] == str(session)
    session.write_text(json.dumps({"type": "session", "id": session_id, "cwd": str(tmp_path / "foreign")}) + "\n")
    for selector in [session_id, str(session)]:
        with pytest.raises(ProviderLaunchError):
            provider.build_spawn_command(replace(options, mode="resume", session_id=selector))


def test_pi_bundle_discovery_rejects_node_impostor(monkeypatch):
    import app.services.providers.pi_cli as pi

    monkeypatch.setattr(pi, "_pi_descendant", lambda *_: False)
    provider = get_provider("pi-cli")
    assert provider.is_process_match("node /tmp/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js", "42")
    assert not provider.is_process_match("node /tmp/pi-script.js", "42")
    assert not provider.is_process_match("python /tmp/pi-mcp.py", "42")


def test_bridge_platform_presence(monkeypatch, tmp_path):
    import app.api.v1.agent_bridge.router as bridge

    monkeypatch.setattr(bridge, "spawn_session", lambda provider, options: {"platform": options.platform})
    for extra in [{}, {"platform": ""}, {"platform": "   "}, {"platform": "openrouter"}]:
        response = bridge.spawn_session_endpoint(bridge.SpawnRequest(provider="pi-cli", directory=str(tmp_path), **extra))
        assert response["platform"] == "openrouter"
    response = bridge.spawn_session_endpoint(bridge.SpawnRequest(provider="pi-cli", directory=str(tmp_path), platform="anthropic"))
    assert response["platform"] == "anthropic"


def test_pi_spawn_readiness_and_explicit_extension(monkeypatch, options):
    from types import SimpleNamespace
    from app.services.agent_bridge.spawn import spawn_session
    import app.services.agent_bridge.spawn as spawn
    import app.services.pi_mail_readiness as readiness

    captured = []
    monkeypatch.setattr(readiness, "pi_mail_readiness", lambda: (True, None))
    monkeypatch.setattr(spawn.subprocess, "run", lambda argv, **kwargs: captured.append(argv) or SimpleNamespace(returncode=0, stdout="123", stderr=""))
    spawn_session("pi-cli", options)
    assert "--extension" in captured[0][-1]
    assert "CLAUDE_DECK_MAIL_OPT_IN=1" in captured[0]
    assert "CLAUDE_DECK_PROVIDER=pi-cli" in captured[0]
    monkeypatch.setattr(readiness, "pi_mail_readiness", lambda: (False, "missing"))
    with pytest.raises(ValueError, match="agent_mail_not_configured"):
        spawn_session("pi-cli", options)
    assert len(captured) == 1
