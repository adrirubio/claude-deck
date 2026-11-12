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
LIVE_SOCKET = "/home/deckproduct/.local/state/albiex-synth-city-product/tmux.sock"
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


@pytest.mark.parametrize("argv", [
    # -S wins over -L whenever a path is supplied, in either order.
    ["-S", LIVE_SOCKET, "-L", "private-name", "kill-server"],
    ["-L", "private-name", "-S", LIVE_SOCKET, "kill-server"],
    ["-S" + LIVE_SOCKET, "-Lprivate-name", "kill-server"],
    ["-Lprivate-name", "-S" + LIVE_SOCKET, "kill-server"],
    # A repeated -S: the last path is the effective socket.
    ["-S", "/tmp/private.sock", "-S", LIVE_SOCKET, "kill-server"],
])
def test_mixed_socket_options_path_wins_and_live_kill_is_refused(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 1
    assert calls == []


@pytest.mark.parametrize("argv", [
    ["-S", "/tmp/private.sock", "-L", "private-name", "kill-server"],
    ["-L", "private-name", "-S", "/tmp/private.sock", "kill-server"],
    ["-S", LIVE_SOCKET, "-S", "/tmp/private.sock", "kill-server"],
])
def test_mixed_socket_options_private_path_keeps_caller_call(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 0
    assert calls == [("/usr/bin/tmux", ["tmux", *argv], CALLER_ENV)]


@pytest.mark.parametrize("argv", [
    ["-S", LIVE_SOCKET, "list-sessions"],
    ["-S" + LIVE_SOCKET, "-Lprivate-name", "list-sessions"],
    ["-S", LIVE_SOCKET.replace("albiex-synth-city-product/tmux.sock", "albiex-synth-city-product//tmux.sock"), "list-sessions"],
])
def test_explicit_live_socket_keeps_argv_but_uses_sanitized_environment(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 0
    assert calls == [("/usr/bin/tmux", ["tmux", *argv], {"SANITIZED": "yes"})]


@pytest.mark.parametrize("socket_path", [
    LIVE_SOCKET.replace("albiex-synth-city-product/tmux.sock", "albiex-synth-city-product//tmux.sock"),
    LIVE_SOCKET.replace("albiex-synth-city-product/tmux.sock", "albiex-synth-city-product/./tmux.sock"),
])
def test_kill_server_via_live_socket_spelling_is_refused(monkeypatch, socket_path):
    _module, calls, code = _run(monkeypatch, ["-S", socket_path, "kill-server"])
    assert code == 1
    assert calls == []


def test_kill_server_via_symlink_to_live_socket_is_refused(monkeypatch, tmp_path):
    link = tmp_path / "live-link.sock"
    link.symlink_to(LIVE_SOCKET)
    _module, calls, code = _run(monkeypatch, ["-S", str(link), "kill-server"])
    assert code == 1
    assert calls == []


@pytest.mark.parametrize("argv", [
    ["-vf", "/dev/null", "kill-server"],
    ["-vT", "RGB", "kill-server"],
    ["-vf/dev/null", "kill-server"],
    ["--", "kill-server"],
    ["-vS", LIVE_SOCKET, "kill-server"],
])
def test_grouped_global_options_still_refuse_live_kill_server(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 1
    assert calls == []


@pytest.mark.parametrize("argv", [
    ["-vL", "private-name", "kill-server"],
    ["-vS/tmp/private.sock", "kill-server"],
    ["-vc", "kill-server", "list-sessions"],
])
def test_grouped_global_options_consume_their_values(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 0
    expected_env = CALLER_ENV if argv[0] in ("-vL", "-vS/tmp/private.sock") else {"SANITIZED": "yes"}
    expected_argv = ["tmux", *argv] if expected_env is CALLER_ENV else ["tmux", "-S", LIVE_SOCKET, *argv]
    assert calls == [("/usr/bin/tmux", expected_argv, expected_env)]


@pytest.mark.parametrize("argv", [
    ["list-sessions;", "kill-server"],
    ["kill-server;"],
    ["list-sessions;", "kill-server;"],
])
def test_trailing_semicolon_is_a_command_boundary(monkeypatch, argv):
    _module, calls, code = _run(monkeypatch, argv)
    assert code == 1
    assert calls == []


def test_sanitized_environment_is_unchanged(monkeypatch):
    module, _calls = _load(monkeypatch)
    fake = type("Pw", (), {"pw_dir": "/home/deckproduct", "pw_name": "deckproduct"})()
    monkeypatch.setattr(module.pwd, "getpwnam", lambda _name: fake)
    monkeypatch.setenv("TERM", "screen-test")
    assert module.sanitized_env() == {
        "HOME": "/home/deckproduct",
        "USER": "deckproduct",
        "LOGNAME": "deckproduct",
        "PATH": "/opt/albiex-synth-city-product/agent-bin:/opt/albiex-synth-city-product/tools:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TERM": "screen-test",
        "SYNTH_CITY_URL": "http://127.0.0.1:8011",
        "SYNTH_CITY_PROVIDER": "codex-cli",
    }


@pytest.mark.parametrize("target", [
    "/home/deckproduct/.local/state/claude-deck-product/tmux.sock",
    "/home/deckproduct/.local/state/albiex-synth-city-product/tmux.sock",
])
def test_both_factory_socket_generations_refuse_kill_server(monkeypatch, tmp_path, target):
    for value in (target, target.replace("/tmux.sock", "/./tmux.sock")):
        _module, calls, code = _run(monkeypatch, ["-S", value, "-L", "private-name", "kill-server"])
        assert code == 1 and calls == []
    link = tmp_path / "factory-link.sock"
    link.symlink_to(target)
    _module, calls, code = _run(monkeypatch, ["-S", str(link), "kill-server"])
    assert code == 1 and calls == []


def test_new_default_is_used_and_the_old_socket_is_only_a_deny_guard(monkeypatch):
    renamed = "/home/deckproduct/.local/state/albiex-synth-city-product/tmux.sock"
    module, calls, code = _run(monkeypatch, ["list-sessions"])
    assert code == 0 and module.LIVE_SOCKET == renamed
    assert calls[0][1] == ["tmux", "-S", renamed, "list-sessions"]
    old = "/home/deckproduct/.local/state/claude-deck-product/tmux.sock"
    _module, calls, code = _run(monkeypatch, ["-S", old, "list-sessions"])
    assert code == 0 and calls == [("/usr/bin/tmux", ["tmux", "-S", old, "list-sessions"], CALLER_ENV)]
