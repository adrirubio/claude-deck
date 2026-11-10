"""The agent-tmux wrapper: caller sockets win, kill-server on the live server is refused.

The wrapper is loaded with os.execve captured, so no real tmux binary is
executed and no tmux server is started.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "product-factory" / "agent-tmux"
LIVE_SOCKET = "/home/deckproduct/.local/state/claude-deck-product/tmux.sock"
CALLER_ENV = {"PATH": "/caller/bin", "HOME": "/caller-home", "MARKER": "caller"}


def _load(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "execve", lambda path, args, env: calls.append((path, list(args), dict(env))))
    loader = importlib.machinery.SourceFileLoader("agent_tmux", str(SCRIPT))
    spec = importlib.util.spec_from_loader("agent_tmux", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module, calls


def _run(monkeypatch, argv):
    module, calls = _load(monkeypatch)
    monkeypatch.setattr(module, "sanitized_env", lambda: {"SANITIZED": "yes"})
    monkeypatch.setattr(os, "environ", dict(CALLER_ENV))
    return module, calls, module.main(list(argv))


@pytest.mark.parametrize("argv", [
    ["-L", "private-name", "list-sessions"],
    ["-S", "/tmp/private.sock", "list-sessions"],
    ["-Lprivate-name", "list-sessions"],
    ["-S/tmp/private.sock", "list-sessions"],
])
def test_caller_socket_is_honoured_and_keeps_caller_environment(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 0
    assert calls == [("/usr/bin/tmux", ["tmux", *argv], CALLER_ENV)]


def test_default_uses_live_socket_and_sanitized_environment(monkeypatch):
    _module, calls, code = _run(monkeypatch, ["list-sessions"])
    assert code == 0
    assert calls == [("/usr/bin/tmux", ["tmux", "-S", LIVE_SOCKET, "list-sessions"], {"SANITIZED": "yes"})]


@pytest.mark.parametrize("argv", [
    ["kill-server"],
    ["-f", "/dev/null", "kill-server"],
    ["-S", LIVE_SOCKET, "kill-server"],
    ["new-session", "-d", ";", "kill-server"],
    ["list-sessions", "\\;", "kill-server"],
])
def test_kill_server_against_live_socket_is_refused(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 1
    assert calls == []


@pytest.mark.parametrize("argv", [
    ["-L", "private-name", "kill-server"],
    ["-S", "/tmp/private.sock", "kill-server"],
    ["-Lprivate-name", "kill-server"],
])
def test_kill_server_on_caller_socket_is_allowed(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 0
    assert calls == [("/usr/bin/tmux", ["tmux", *argv], CALLER_ENV)]


def test_send_keys_text_containing_kill_server_is_allowed(monkeypatch):
    argv = ["send-keys", "-t", "fixture:0.0", "-l", "kill-server"]
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 0
    assert calls == [("/usr/bin/tmux", ["tmux", "-S", LIVE_SOCKET, *argv], {"SANITIZED": "yes"})]


@pytest.mark.parametrize("option", ["-c", "-f", "-T"])
def test_argument_taking_global_option_consumes_kill_server_value(monkeypatch, option):
    argv = [option, "kill-server", "list-sessions"]
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 0
    assert calls == [("/usr/bin/tmux", ["tmux", "-S", LIVE_SOCKET, *argv], {"SANITIZED": "yes"})]


def test_sanitized_environment_is_unchanged(monkeypatch):
    module, _calls = _load(monkeypatch)
    fake = type("Pw", (), {"pw_dir": "/home/deckproduct", "pw_name": "deckproduct"})()
    monkeypatch.setattr(module.pwd, "getpwnam", lambda _name: fake)
    monkeypatch.setenv("TERM", "screen-test")
    assert module.sanitized_env() == {
        "HOME": "/home/deckproduct",
        "USER": "deckproduct",
        "LOGNAME": "deckproduct",
        "PATH": "/opt/claude-deck-product/agent-bin:/opt/claude-deck-product/tools:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TERM": "screen-test",
        "SYNTH_CITY_URL": "http://127.0.0.1:8011",
        "SYNTH_CITY_PROVIDER": "codex-cli",
    }
