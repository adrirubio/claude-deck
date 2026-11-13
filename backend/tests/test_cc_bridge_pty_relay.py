"""Tests for CC Bridge pty relay."""
import asyncio
import fcntl
import getpass
import json
import logging
import os
import pty
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

import pytest
from starlette.websockets import WebSocketState

from app.services.cc_bridge import pty_relay


class FakeProcess:
    def __init__(self, slave_fd=None):
        self.slave_fd = os.dup(slave_fd) if slave_fd is not None else None
        self.terminate_calls = 0
        self.wait_thread_id = None

    def terminate(self):
        self.terminate_calls += 1
        if self.slave_fd is not None:
            os.close(self.slave_fd)
            self.slave_fd = None

    def wait(self, timeout=None):
        self.wait_thread_id = threading.get_ident()
        return 0


class FakeWebSocket:
    def __init__(self, *, disconnect_first=True, on_receive=None, fail_send=False):
        self.client_state = WebSocketState.CONNECTED
        self.disconnect_first = disconnect_first
        self.on_receive = on_receive
        self.fail_send = fail_send
        self.receive_started = asyncio.Event()
        self.closed = False

    async def accept(self, *, subprotocol=None):
        pass

    async def receive(self):
        self.receive_started.set()
        if self.on_receive is not None:
            self.on_receive()
        if self.disconnect_first:
            self.client_state = WebSocketState.DISCONNECTED
            return {"type": "websocket.disconnect"}
        await asyncio.Future()

    async def send_bytes(self, data):
        if self.fail_send:
            raise RuntimeError("send failed")

    async def close(self):
        self.closed = True
        self.client_state = WebSocketState.DISCONNECTED


def fake_relay_io(monkeypatch):
    loop = asyncio.get_running_loop()
    callbacks = {}
    removed_fds = []
    processes = []

    def popen(*args, **kwargs):
        process = FakeProcess(kwargs["stdin"])
        processes.append(process)
        return process

    monkeypatch.setattr(pty_relay.pty, "openpty", os.pipe)
    monkeypatch.setattr(pty_relay.subprocess, "Popen", popen)
    monkeypatch.setattr(
        loop, "add_reader", lambda fd, callback: callbacks.update({fd: callback})
    )
    monkeypatch.setattr(loop, "remove_reader", lambda fd: removed_fds.append(fd))
    return callbacks, removed_fds, processes


def test_parse_control_message_resize():
    from app.services.cc_bridge.pty_relay import parse_control_message
    msg = json.dumps({"type": "resize", "cols": 120, "rows": 40})
    result = parse_control_message(msg)
    assert result is not None
    assert result["type"] == "resize"
    assert result["cols"] == 120
    assert result["rows"] == 40


def test_parse_control_message_returns_none_for_plain_text():
    from app.services.cc_bridge.pty_relay import parse_control_message
    assert parse_control_message("ls -la") is None
    assert parse_control_message("hello world") is None


def test_parse_control_message_returns_none_for_invalid_json():
    from app.services.cc_bridge.pty_relay import parse_control_message
    assert parse_control_message("{invalid") is None


def test_parse_control_message_returns_none_for_json_without_type():
    from app.services.cc_bridge.pty_relay import parse_control_message
    assert parse_control_message('{"cols": 80}') is None


def test_resize_pty_does_not_raise_on_invalid_fd():
    from app.services.cc_bridge.pty_relay import resize_pty
    resize_pty(-1, 24, 80)


@pytest.mark.asyncio
async def test_client_disconnect_closes_idle_relay_without_blocking_loop(monkeypatch):
    _, removed_fds, processes = fake_relay_io(monkeypatch)
    websocket = FakeWebSocket()
    relay = pty_relay.PtyRelay("test:disconnect", read_only=False)

    await asyncio.wait_for(relay.run(websocket), timeout=1)

    assert processes[0].terminate_calls == 1
    assert removed_fds == [relay.master_fd]
    assert "test:disconnect" not in pty_relay._active_relays
    assert processes[0].wait_thread_id != threading.get_ident()


@pytest.mark.asyncio
async def test_pty_eof_closes_socket_with_idle_client(monkeypatch):
    callbacks, removed_fds, processes = fake_relay_io(monkeypatch)
    websocket = FakeWebSocket(disconnect_first=False)
    relay = pty_relay.PtyRelay("test:eof")
    relay_task = asyncio.create_task(relay.run(websocket))

    await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
    processes[0].terminate()
    callbacks[relay.master_fd]()
    await asyncio.wait_for(relay_task, timeout=1)

    assert websocket.closed
    assert removed_fds == [relay.master_fd]
    assert "test:eof" not in pty_relay._active_relays


@pytest.mark.asyncio
async def test_output_error_closes_idle_client_and_relay(monkeypatch):
    callbacks, removed_fds, processes = fake_relay_io(monkeypatch)
    websocket = FakeWebSocket(disconnect_first=False, fail_send=True)
    relay = pty_relay.PtyRelay("test:send-error")
    relay_task = asyncio.create_task(relay.run(websocket))

    await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
    os.write(processes[0].slave_fd, b"output")
    callbacks[relay.master_fd]()
    await asyncio.wait_for(relay_task, timeout=1)

    assert websocket.closed
    assert processes[0].terminate_calls == 1
    assert removed_fds == [relay.master_fd]
    assert "test:send-error" not in pty_relay._active_relays


@pytest.mark.asyncio
async def test_old_relay_does_not_deregister_replacement(monkeypatch):
    fake_relay_io(monkeypatch)
    target = "test:replacement"
    replacement = pty_relay.PtyRelay(target, read_only=False)
    websocket = FakeWebSocket(
        on_receive=lambda: pty_relay._active_relays.update({target: replacement})
    )
    relay = pty_relay.PtyRelay(target)

    try:
        await asyncio.wait_for(relay.run(websocket), timeout=1)
        assert pty_relay._active_relays[target] is replacement
    finally:
        pty_relay._active_relays.pop(target, None)


@pytest.mark.asyncio
async def test_close_all_relays_waits_off_event_loop():
    relay = pty_relay.PtyRelay("test:shutdown")
    process = FakeProcess()
    relay.process = process
    pty_relay._active_relays[relay.target] = relay

    await pty_relay.close_all_relays()

    assert process.terminate_calls == 1
    assert process.wait_thread_id != threading.get_ident()
    assert relay.target not in pty_relay._active_relays


# --- #749: resize and attach errors when the attach process cannot be signalled -------------
#
# In production the attach process is `sudo`, which runs tmux as another user. The
# controller cannot signal it, and sudo's own errors used to be written into the lane.
# These tests use real ptys and real child processes. Nothing here runs sudo or tmux, and
# nothing here is a trial on a real cross-user setup. That trial is a separate acceptance gate.

# Prints the pty size each time the shell receives SIGWINCH.
WINCH_SHELL = 'trap \'echo "WINCH:$(stty size)"\' WINCH; echo ready; while :; do sleep 0.05; done'

# Emulates `sudo` with `use_pty`: it puts the command in a second pty and copies its own
# terminal size to that pty when it gets SIGWINCH. It is not sudo and does not change user.
SUDO_LIKE = r"""
import fcntl, os, pty, signal, sys, termios
pid, inner = pty.fork()
if pid == 0:
    os.execvp("sh", ["sh", "-c", sys.argv[1]])
def sync(*_):
    fcntl.ioctl(inner, termios.TIOCSWINSZ, fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8))
signal.signal(signal.SIGWINCH, sync)
sync()
while True:
    try:
        data = os.read(inner, 4096)
    except InterruptedError:
        continue
    except OSError:
        break
    if not data:
        break
    os.write(1, data)
"""


def set_winsize(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def get_winsize(fd):
    rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    return rows, cols


def start_attach_like(argv):
    """Start argv the way the relay starts `tmux attach-session`, on a fresh pty."""
    master, slave = pty.openpty()
    set_winsize(master, 24, 80)
    process = subprocess.Popen(
        argv, stdin=slave, stdout=slave, stderr=subprocess.PIPE, preexec_fn=pty_relay._child_preexec
    )
    os.close(slave)
    os.set_blocking(master, False)
    return master, process


def read_until(fd, needle: bytes, timeout=5.0) -> bytes:
    seen = b""
    deadline = time.monotonic() + timeout
    while needle not in seen:
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {needle!r}; saw {seen!r}")
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.02)
            continue
        except OSError:
            break
        seen += chunk
    return seen


def stop(process, master):
    process.kill()
    process.wait(timeout=5)
    if process.stderr:
        process.stderr.close()
    os.close(master)


def never_signal(monkeypatch):
    def refuse(pid, sig):
        raise AssertionError(f"the relay signalled pid {pid} with {sig}")
    monkeypatch.setattr(os, "kill", refuse)


def test_resize_pty_only_sets_the_pty_size(monkeypatch):
    master, slave = pty.openpty()
    try:
        never_signal(monkeypatch)
        assert pty_relay.resize_pty(master, 40, 120) is None
        assert get_winsize(slave) == (40, 120)
    finally:
        os.close(master)
        os.close(slave)


def test_resize_pty_reports_failure_without_raising():
    assert isinstance(pty_relay.resize_pty(-1, 24, 80), Exception)
    master, slave = pty.openpty()
    try:
        assert isinstance(pty_relay.resize_pty(master, 70000, 80), Exception)
        assert isinstance(pty_relay.resize_pty(master, "tall", 80), Exception)
    finally:
        os.close(master)
        os.close(slave)


def test_relay_resize_never_signals_the_attach_process(monkeypatch):
    master, slave = pty.openpty()

    class AttachProcess:
        pid = 1  # a pid the controller must not signal, as in a sudo boundary

        def poll(self):
            return None

    relay = pty_relay.PtyRelay("test:no-signal", read_only=False)
    relay.master_fd = master
    relay.process = AttachProcess()
    try:
        never_signal(monkeypatch)
        relay.resize(33, 101)
        assert get_winsize(slave) == (33, 101)
    finally:
        os.close(master)
        os.close(slave)


def test_attach_child_gets_the_kernel_resize_signal_and_back(monkeypatch):
    """Same user: the child sees every size change, with no signal sent by the controller."""
    master, process = start_attach_like(["sh", "-c", WINCH_SHELL])
    try:
        read_until(master, b"ready")
        never_signal(monkeypatch)
        for rows, cols in ((50, 200), (24, 80)):  # full screen, then back
            pty_relay.resize_pty(master, rows, cols)
            read_until(master, f"WINCH:{rows} {cols}".encode())
    finally:
        monkeypatch.undo()
        stop(process, master)


def test_resize_reaches_a_command_behind_a_second_pty(monkeypatch):
    """Emulation of sudo with use_pty. Supporting evidence only, not a cross-user trial."""
    master, process = start_attach_like([sys.executable, "-c", SUDO_LIKE, WINCH_SHELL])
    try:
        read_until(master, b"ready")
        never_signal(monkeypatch)
        for rows, cols in ((45, 160), (24, 80)):
            pty_relay.resize_pty(master, rows, cols)
            read_until(master, f"WINCH:{rows} {cols}".encode())
    finally:
        monkeypatch.undo()
        stop(process, master)


class RecordingWebSocket(FakeWebSocket):
    def __init__(self):
        super().__init__(disconnect_first=False)
        self.sent = b""

    async def send_bytes(self, data):
        self.sent += data


def stand_in_tmux(monkeypatch, tmp_path, body):
    """Replace the attach program with a script that ignores its arguments."""
    script = tmp_path / "fake-tmux"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(0o755)
    monkeypatch.setattr(pty_relay, "TMUX_BINARY", str(script))


@pytest.mark.asyncio
async def test_attach_stderr_goes_to_the_log_and_not_the_terminal(monkeypatch, tmp_path, caplog):
    stand_in_tmux(monkeypatch, tmp_path, "echo sudo: kill failed >&2; echo visible-output; sleep 0.2")
    websocket = RecordingWebSocket()
    relay = pty_relay.PtyRelay("test:stderr", read_only=False)
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(relay.run(websocket), timeout=5)

    assert b"visible-output" in websocket.sent
    assert b"sudo" not in websocket.sent
    logged = [r.getMessage() for r in caplog.records if "sudo: kill failed" in r.getMessage()]
    assert len(logged) == 1
    assert "test:stderr" in logged[0]


@pytest.mark.asyncio
async def test_attach_stderr_log_is_bounded(monkeypatch, tmp_path, caplog):
    stand_in_tmux(
        monkeypatch, tmp_path,
        "i=0; while [ $i -lt 400 ]; do echo error-line-$i >&2; i=$((i+1)); done; sleep 0.1",
    )
    relay = pty_relay.PtyRelay("test:stderr-flood", read_only=False)
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(relay.run(RecordingWebSocket()), timeout=5)

    lines = [r for r in caplog.records if r.name == pty_relay.logger.name]
    assert 0 < len(lines) < 400
    assert any("suppressed" in r.getMessage() for r in lines)


def test_a_failed_resize_is_logged_once_per_relay(caplog):
    relay = pty_relay.PtyRelay("test:log-once", read_only=False)
    relay.master_fd = -1
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        relay.resize(24, 80)
        relay.resize(30, 100)
        relay.resize(40, 120)
    failures = [r for r in caplog.records if "resize" in r.getMessage().lower()]
    assert len(failures) == 1
    assert "test:log-once" in failures[0].getMessage()


def test_closing_the_relay_stops_reading_attach_stderr():
    """After close() nothing reads the old stderr fd, which the process may reuse."""
    read_end, write_end = os.pipe()
    relay = pty_relay.PtyRelay("test:stderr-closed", read_only=False)
    relay._stderr_fd = read_end
    os.write(write_end, b"before close\n")
    os.set_blocking(read_end, False)

    class Attach:
        stderr = os.fdopen(read_end, "rb", buffering=0)

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    relay.process = Attach()
    relay.close()
    assert relay._stderr_fd is None
    assert relay._read_attach_stderr() is False
    os.close(write_end)


def pipe_with_room(megabytes=1):
    """A non-blocking pipe big enough to hold many reads of queued data."""
    read_end, write_end = os.pipe()
    try:
        fcntl.fcntl(write_end, 1031, megabytes * 1024 * 1024)  # F_SETPIPE_SZ
    except OSError:
        pytest.skip("cannot enlarge the pipe on this host")
    os.set_blocking(read_end, False)
    return read_end, write_end


def queued_bytes(fd):
    return struct.unpack("i", fcntl.ioctl(fd, termios.FIONREAD, b"\0\0\0\0"))[0]


def test_one_stderr_callback_reads_a_bounded_amount_and_yields():
    """A producer that never stops must not keep one callback running: it returns, the loop runs."""
    read_end, write_end = pipe_with_room()
    relay = pty_relay.PtyRelay("test:stderr-budget", read_only=False)
    relay._stderr_fd = read_end
    queued = 256 * 1024
    os.write(write_end, b"x" * queued)
    try:
        more = relay._read_attach_stderr()
        assert more is True  # not at the end of the stream: the loop will call again
        read = queued - queued_bytes(read_end)
        assert 0 < read <= pty_relay._STDERR_READ_BUDGET
        assert queued_bytes(read_end) > 0  # the rest waits for the next loop turn
    finally:
        os.close(read_end)
        os.close(write_end)


@pytest.mark.asyncio
async def test_event_loop_runs_between_stderr_callbacks():
    """Draining a flood takes several callbacks, and other tasks run between them."""
    read_end, write_end = pipe_with_room()
    relay = pty_relay.PtyRelay("test:stderr-fair", read_only=False)
    relay._stderr_fd = read_end
    os.write(write_end, b"x" * (512 * 1024))
    loop = asyncio.get_running_loop()
    heartbeats = 0
    seen_at_callback = []
    stop = asyncio.Event()

    async def heartbeat():
        nonlocal heartbeats
        while not stop.is_set():
            heartbeats += 1
            await asyncio.sleep(0)

    def on_readable():
        seen_at_callback.append(heartbeats)
        relay._read_attach_stderr()

    task = asyncio.create_task(heartbeat())
    loop.add_reader(read_end, on_readable)
    try:
        for _ in range(500):
            if queued_bytes(read_end) == 0:
                break
            await asyncio.sleep(0.005)
    finally:
        stop.set()
        loop.remove_reader(read_end)
        await task
        os.close(read_end)
        os.close(write_end)
    assert draining_took_several_turns(seen_at_callback)


def draining_took_several_turns(seen_at_callback):
    # An unbounded drain empties the pipe in one callback. A bounded one needs several,
    # and the heartbeat task ran between them.
    return len(seen_at_callback) >= 2 and seen_at_callback[-1] > seen_at_callback[0]


def test_stderr_log_allowance_is_never_exceeded(caplog):
    relay = pty_relay.PtyRelay("test:stderr-allowance", read_only=False)
    limit = pty_relay._ATTACH_STDERR_LOG_LIMIT
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        relay._log_attach_stderr(b"a" * (limit - 1))
        relay._log_attach_stderr(b"b" * limit)  # a chunk larger than what is left
        relay._log_attach_stderr(b"c" * 100)  # and more after the limit
    payloads = [
        r.getMessage().split(": ", 1)[1] for r in caplog.records if r.getMessage().startswith("tmux attach for")
    ]
    assert sum(len(p) for p in payloads) <= limit
    assert len(payloads) == 2 and len(payloads[1]) == 1  # only the one character that was left
    notices = [r for r in caplog.records if "suppressed" in r.getMessage()]
    assert len(notices) == 1


# --- #749: a failed attach shows one fixed, bounded error, never raw sudo text ---------------

FIXED_ATTACH_ERROR = "Could not attach to the terminal. See the backend log."

# Fails exactly when it has a controlling terminal, as `sudo` with use_pty does when it
# cannot allocate its own pty (trial run H2, no CAP_CHOWN).
FAILS_WITH_A_CONTROLLING_TERMINAL = """
if ( : </dev/tty ) 2>/dev/null; then
  echo "sudo: unable to allocate pty: Operation not permitted" >&2
  exit 1
fi
echo visible-output
sleep 0.3
"""


class FrameWebSocket:
    """Records terminal bytes, JSON frames and the close code. The test ends it with finish()."""

    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.sent = b""
        self.frames = []
        self.close_code = None
        self._incoming = asyncio.Queue()

    async def accept(self, *, subprotocol=None):
        pass

    async def receive(self):
        return await self._incoming.get()

    def finish(self):
        self._incoming.put_nowait({"type": "websocket.disconnect"})

    async def send_bytes(self, data):
        self.sent += data

    async def send_json(self, frame):
        self.frames.append(frame)

    async def close(self, code=1000):
        self.close_code = code
        self.client_state = WebSocketState.DISCONNECTED


@pytest.mark.asyncio
async def test_a_failed_attach_sends_one_fixed_error_frame_and_no_raw_text(monkeypatch, tmp_path, caplog):
    stand_in_tmux(monkeypatch, tmp_path, FAILS_WITH_A_CONTROLLING_TERMINAL)
    websocket = FrameWebSocket()
    relay = pty_relay.PtyRelay("test:attach-fails", read_only=False)
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(relay.run(websocket), timeout=10)

    assert websocket.frames == [{"type": "error", "message": FIXED_ATTACH_ERROR}]
    assert websocket.close_code == 4000
    assert b"sudo" not in websocket.sent and b"allocate" not in websocket.sent
    logged = [r.getMessage() for r in caplog.records if "unable to allocate pty" in r.getMessage()]
    assert len(logged) == 1 and "test:attach-fails" in logged[0]


@pytest.mark.asyncio
async def test_an_attach_that_ends_after_output_sends_no_error_frame(monkeypatch, tmp_path):
    stand_in_tmux(monkeypatch, tmp_path, "echo visible-output; exit 1")
    websocket = FrameWebSocket()
    await asyncio.wait_for(pty_relay.PtyRelay("test:ends-after-output", read_only=False).run(websocket), timeout=10)

    assert b"visible-output" in websocket.sent
    assert websocket.frames == []


@pytest.mark.asyncio
async def test_an_attach_that_exits_cleanly_without_output_sends_no_error_frame(monkeypatch, tmp_path):
    stand_in_tmux(monkeypatch, tmp_path, "exit 0")
    websocket = FrameWebSocket()
    await asyncio.wait_for(pty_relay.PtyRelay("test:clean-exit", read_only=False).run(websocket), timeout=10)

    assert websocket.frames == []


@pytest.mark.asyncio
async def test_an_attach_that_cannot_start_sends_the_fixed_frame_and_logs_the_reason(monkeypatch, caplog):
    monkeypatch.setattr(pty_relay, "TMUX_BINARY", "/nonexistent-dir/tmux")
    websocket = FrameWebSocket()
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(pty_relay.PtyRelay("test:cannot-start", read_only=False).run(websocket), timeout=10)

    assert websocket.frames == [{"type": "error", "message": FIXED_ATTACH_ERROR}]
    assert websocket.close_code == 4000
    assert any("nonexistent-dir" in r.getMessage() for r in caplog.records)


# --- #749: real sudo, a disposable agent user and the production capability limits -----------
#
# The production service runs with a limited capability set: no CAP_KILL and no CAP_CHOWN. With
# `use_pty`, sudo then cannot allocate the pty it needs ("unable to allocate pty"). With a
# command-scoped `!use_pty` the attach works and the kernel delivers the resize.
#
# This test uses real `sudo`. It creates a disposable OS user and a new file in /etc/sudoers.d,
# and it runs `sudo setpriv`. That is only acceptable on an ephemeral machine. It runs ONLY on
# GitHub-hosted Linux runners. There is no other way to turn it on. Where it runs, a missing
# prerequisite FAILS the test: it never skips. Everything it creates has a unique random name,
# is removed even when the test fails, and its removal is checked. It never edits /etc/sudoers,
# a pre-existing sudoers file, a pre-existing user or a pre-existing rule.
#
# A nonzero exit of the attach is not accepted as the negative result. Before either phase the
# test attests the setup: the controller and agent identities, the exact reduced bounding set,
# and the sudo rule. The negative phase must show the specific refusal to allocate a pty, and no
# sign of a wrong setup. The positive phase uses the same user, program, launcher, bounding set
# and session, and changes only the command-scoped use_pty line. It checks the sizes that the
# attached program itself reports.

PRODUCTION_BOUNDING_SET = "-all,+dac_override,+dac_read_search,+setgid,+setuid,+sys_ptrace"
CAP_CHOWN, CAP_DAC_OVERRIDE, CAP_DAC_READ_SEARCH, CAP_KILL = 0, 1, 2, 5
CAP_SETGID, CAP_SETUID, CAP_SYS_PTRACE = 6, 7, 19
EXPECTED_CAPBND = sum(
    1 << bit for bit in (CAP_DAC_OVERRIDE, CAP_DAC_READ_SEARCH, CAP_SETGID, CAP_SETUID, CAP_SYS_PTRACE)
)

# Prints the pty size each time it receives SIGWINCH, as the tmux client does.
CAPABILITY_ATTACH_PROGRAM = (
    "#!/bin/sh\n"
    "trap 'echo \"WINCH:$(stty size)\"' WINCH\n"
    "echo ready\n"
    "while :; do sleep 0.05; done\n"
)

# Prints who it runs as and its bounding set. It runs under !use_pty, so it works under the limits.
CAPABILITY_PROBE_PROGRAM = (
    "#!/bin/sh\n"
    'echo "ID:$(id -u):$(id -un)"\n'
    "grep '^CapBnd:' /proc/self/status\n"
)

# What sudo prints when a setup is wrong. None of these may be in the negative result.
WRONG_SETUP_MARKERS = (
    "a password is required", "is not in the sudoers", "may not run sudo", "not allowed to",
    "command not found", "No such file or directory", "no tty present", "a terminal is required",
    "unknown user", "sudoers",
)


def is_ephemeral_hosted_runner(environ) -> bool:
    """True only on a GitHub-hosted Linux runner, which is a fresh virtual machine for every job."""
    return (
        environ.get("GITHUB_ACTIONS") == "true"
        and environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and environ.get("RUNNER_OS") == "Linux"
    )


hosted_runner_only = pytest.mark.skipif(
    not is_ephemeral_hosted_runner(os.environ),
    reason="creates a disposable OS user and a sudoers.d file, so it runs only on ephemeral GitHub-hosted runners",
)


def test_the_privileged_regression_has_no_other_way_to_switch_on():
    hosted_linux = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux"}
    assert is_ephemeral_hosted_runner(hosted_linux)
    assert not is_ephemeral_hosted_runner({**hosted_linux, "RUNNER_OS": "Windows"})
    assert not is_ephemeral_hosted_runner({k: v for k, v in hosted_linux.items() if k != "RUNNER_OS"})
    assert not is_ephemeral_hosted_runner({"CI": "true"})
    assert not is_ephemeral_hosted_runner({})
    assert not is_ephemeral_hosted_runner({"GITHUB_ACTIONS": "true"})
    assert not is_ephemeral_hosted_runner({**hosted_linux, "RUNNER_ENVIRONMENT": "self-hosted"})
    assert not is_ephemeral_hosted_runner({"RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux"})
    assert not is_ephemeral_hosted_runner({"SYNTH_CITY_PRIVILEGED_TESTS": "1"})


def test_the_expected_bounding_set_has_no_chown_and_no_kill():
    assert EXPECTED_CAPBND == 0x800C6
    assert not EXPECTED_CAPBND & (1 << CAP_CHOWN)
    assert not EXPECTED_CAPBND & (1 << CAP_KILL)


def run_sudo(*args, check=True, timeout=60):
    result = subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=timeout)
    if check:
        assert result.returncode == 0, f"sudo -n {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
    return result


def parse_capbnd(text: str) -> int:
    lines = [line for line in text.splitlines() if line.startswith("CapBnd:")]
    assert len(lines) == 1, f"expected one CapBnd line, saw {text!r}"
    return int(lines[0].split(":", 1)[1].strip(), 16)


class ProcessObservationError(OSError):
    """The processes of the created user could not be observed reliably."""


class DisposableAgent:
    """A new OS user, a new sudoers.d file and root-owned programs, all with unique names."""

    def __init__(self):
        self.suffix = secrets.token_hex(4)
        self.user = f"sctrial{self.suffix}"
        self.dropin = f"/etc/sudoers.d/zz-sctrial-{self.suffix}"
        self.root_dir = f"/tmp/sctrial-{self.suffix}"
        self.program = f"{self.root_dir}/attach.sh"
        self.probe = f"{self.root_dir}/probe.sh"
        self.work_dir = tempfile.mkdtemp(prefix=f"sctrial-{self.suffix}-")
        self.launcher = f"{self.work_dir}/launcher.sh"
        self.probe_launcher = f"{self.work_dir}/probe-launcher.sh"
        self.outer_probe = f"{self.work_dir}/outer-probe.sh"
        self.setpriv = None
        self.me = getpass.getuser()
        # A resource is "owned" only after this test created it successfully. Cleanup touches
        # nothing else, whatever name was generated. "attempted" is what we tried to create.
        self.owned = {"user": False, "root_dir": False, "dropin": False}
        self.attempted = set()
        self.agent_uid = None
        self.process_wait_seconds = 5.0

    def _stage(self, name, content, mode=0o644):
        path = f"{self.work_dir}/{name}"
        with open(path, "w") as handle:
            handle.write(content)
        os.chmod(path, mode)
        return path

    def rules(self, use_pty: bool) -> str:
        """The only text that differs between the two phases is the last line."""
        return (
            f"# disposable rules for the #749 regression test {self.suffix}\n"
            f"{self.me} ALL=(root) NOPASSWD: {self.setpriv}\n"
            f"Defaults!{self.setpriv} !use_pty\n"
            f"{self.me} ALL=({self.user}) NOPASSWD: {self.program}, {self.probe}\n"
            f"Defaults!{self.probe} !use_pty\n"
            f"Defaults!{self.program} {'use_pty' if use_pty else '!use_pty'}\n"
        )

    def _user_exists(self) -> bool:
        return subprocess.run(["getent", "passwd", self.user], capture_output=True).returncode == 0

    def _path_exists(self, path) -> bool:
        return os.path.exists(path)

    def _proc_pids(self) -> list:
        return [entry for entry in os.listdir("/proc") if entry.isdigit()]

    def _read_proc_status(self, pid) -> str:
        with open(f"/proc/{pid}/status") as handle:
            return handle.read()

    def _processes_of_uid(self, uid) -> list:
        """Pids whose real uid is uid, read from /proc. It does not depend on the user name.

        Only a process that is confirmed gone (it ended while we looked) is ignored. Anything that
        cannot be read or understood raises, so the caller treats the observation as unknown.
        """
        pids = []
        for pid in self._proc_pids():
            try:
                status = self._read_proc_status(pid)
            except (FileNotFoundError, ProcessLookupError):
                continue  # confirmed gone
            except OSError as error:
                raise ProcessObservationError(f"cannot read the status of process {pid}: {error}") from error
            line = next((line for line in status.splitlines() if line.startswith("Uid:")), None)
            try:
                real_uid = int(line.split()[1])
            except (AttributeError, IndexError, ValueError):
                raise ProcessObservationError(f"the status of process {pid} has no readable Uid line") from None
            if real_uid == uid:
                pids.append(int(pid))
        return pids

    def _wait_for_no_processes(self, uid) -> list:
        deadline = time.monotonic() + self.process_wait_seconds
        remaining = self._processes_of_uid(uid)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.1)
            remaining = self._processes_of_uid(uid)
        return remaining

    def check_prerequisites(self):
        assert shutil.which("sudo"), "the privileged regression needs sudo on this hosted runner"
        run_sudo("true")
        for tool in ("setpriv", "visudo", "useradd", "userdel", "install", "mkdir", "rm", "pkill", "cat", "sh"):
            found = run_sudo("sh", "-c", f"command -v {tool}", check=False)
            assert found.returncode == 0, f"the privileged regression needs {tool} on this hosted runner"
        assert os.getuid() != 0, "the controller identity must not be root"
        assert not self._user_exists(), f"the generated user {self.user} already exists"
        assert not self._path_exists(self.dropin), f"{self.dropin} already exists"
        assert not self._path_exists(self.root_dir), f"{self.root_dir} already exists"

    def create(self):
        self.check_prerequisites()
        self.setpriv = run_sudo("sh", "-c", "command -v setpriv").stdout.strip()
        uid, gid = os.getuid(), os.getgid()
        self.attempted.add("user")
        run_sudo("useradd", "--no-create-home", "--shell", "/bin/sh", self.user)  # fails if the user exists
        self.owned["user"] = True
        self.agent_uid = int(run_sudo("id", "-u", self.user).stdout.strip() or 0) or None
        self.attempted.add("root_dir")
        run_sudo("mkdir", "-m", "0755", self.root_dir)  # fails if the directory exists
        self.owned["root_dir"] = True
        for name, content, target in (
            ("attach.sh", CAPABILITY_ATTACH_PROGRAM, self.program),
            ("probe.sh", CAPABILITY_PROBE_PROGRAM, self.probe),
        ):
            staged = self._stage(name, content, 0o755)
            run_sudo("install", "-m", "0755", "-o", "root", "-g", "root", staged, target)
        reduced = (
            f"sudo -n {self.setpriv} --bounding-set={PRODUCTION_BOUNDING_SET} "
            f"--reuid={uid} --regid={gid} --init-groups"
        )
        self._stage("launcher.sh", f"#!/bin/sh\nexec {reduced} sudo -n -u {self.user} {self.program}\n", 0o755)
        self._stage("probe-launcher.sh", f"#!/bin/sh\nexec {reduced} sudo -n -u {self.user} {self.probe}\n", 0o755)
        self._stage(
            "outer-probe.sh",
            f"#!/bin/sh\nexec {reduced} sh -c 'echo \"ID:$(id -u)\"; grep \"^CapBnd:\" /proc/self/status'\n",
            0o755,
        )

    def install_rules(self, use_pty: bool):
        """Install the rules, replacing only this object's own file. A bad file is never installed."""
        rules = self.rules(use_pty)
        staged = self._stage("rules", rules)
        run_sudo("visudo", "-cf", staged)
        if not self.owned["dropin"]:
            # Step 1: reserve the name with an empty file, exclusively (noclobber). If this succeeds,
            # this test created the file, and from then on it is owned and cleaned up. An existing
            # file is never overwritten. An empty sudoers file is valid.
            self.attempted.add("dropin")
            run_sudo("sh", "-c", 'set -C; : > "$1"', "sh", self.dropin)
            self.owned["dropin"] = True
        # Step 2: write the content and the mode. Only the owned file is replaced. If this fails,
        # the file is still owned, so cleanup removes it.
        run_sudo("install", "-m", "0440", "-o", "root", "-g", "root", staged, self.dropin)
        run_sudo("true")  # sudo still works with the new file
        installed = run_sudo("cat", self.dropin).stdout
        assert installed == rules, f"the installed rules are not the intended rules: {installed!r}"

    def attest(self):
        """Attest the setup before a phase. Wrong setup errors fail here and not later."""
        controller = os.getuid()
        outer = subprocess.run([self.outer_probe], capture_output=True, text=True, timeout=60)
        assert outer.returncode == 0, f"the controller probe failed: {outer.stderr.strip()}"
        assert f"ID:{controller}" in outer.stdout.splitlines()
        outer_capbnd = parse_capbnd(outer.stdout)
        inner = subprocess.run([self.probe_launcher], capture_output=True, text=True, timeout=60)
        assert inner.returncode == 0, f"the agent probe through sudo failed: {inner.stderr.strip()}"
        identity = next((l for l in inner.stdout.splitlines() if l.startswith("ID:")), "")
        _, agent_uid, agent_user = identity.split(":", 2)
        assert agent_user == self.user, f"the probe ran as {agent_user!r}, not {self.user!r}"
        assert int(agent_uid) not in (0, controller), "the agent must be a distinct non-root identity"
        inner_capbnd = parse_capbnd(inner.stdout)
        for capbnd in (outer_capbnd, inner_capbnd):
            assert capbnd == EXPECTED_CAPBND, f"CapBnd {capbnd:#x} is not the production set {EXPECTED_CAPBND:#x}"
            assert not capbnd & (1 << CAP_CHOWN) and not capbnd & (1 << CAP_KILL)

    def remove(self):
        """Remove only what this test created, and check that it is gone.

        Every step is tried even if an earlier one fails, and all failures are reported together.
        A resource that was only attempted, or that already existed, is never deleted or signalled.
        The user is deleted only after its processes are confirmed gone, so no process can survive
        under a deleted numeric uid.
        """
        errors = []

        def step(label, action):
            try:
                action()
            except (subprocess.TimeoutExpired, OSError, AssertionError) as error:
                errors.append(f"{label}: {error}")

        survivors = []
        if self.owned["user"]:
            if self.agent_uid is None:
                errors.append("the uid of the created user is unknown, so its processes cannot be checked")
                survivors = ["unknown"]
            else:
                step("pkill", lambda: run_sudo("pkill", "-KILL", "-u", str(self.agent_uid), check=False))
                try:
                    survivors = self._wait_for_no_processes(self.agent_uid)
                except OSError as error:
                    errors.append(f"checking the processes: {error}")
                    survivors = ["unknown"]
                if survivors:
                    errors.append(f"processes of uid {self.agent_uid} are still running: {survivors}; the user was not deleted")
        if self.owned["dropin"]:
            step("remove the rules", lambda: run_sudo("rm", "-f", self.dropin, check=False))
        if self.owned["user"] and not survivors:
            step("userdel", lambda: run_sudo("userdel", "-f", self.user, check=False))
        if self.owned["root_dir"]:
            step("remove the program directory", lambda: run_sudo("rm", "-rf", self.root_dir, check=False))
        step("remove the work directory", lambda: shutil.rmtree(self.work_dir, ignore_errors=True))

        if self.owned["user"] and not survivors and self._user_exists():
            errors.append(f"user {self.user} is still there")
        if self.owned["dropin"] and self._path_exists(self.dropin):
            errors.append(f"{self.dropin} is still there")
        if self.owned["root_dir"] and self._path_exists(self.root_dir):
            errors.append(f"{self.root_dir} is still there")
        if self._path_exists(self.work_dir):
            errors.append(f"{self.work_dir} is still there")
        paths = {"dropin": self.dropin, "root_dir": self.root_dir}
        for name in sorted(self.attempted - {k for k, v in self.owned.items() if v}):
            if name in paths and self._path_exists(paths[name]):
                errors.append(f"{paths[name]} exists but this test did not confirm creating it, so it was left in place")
        assert not errors, "the privileged regression cleanup failed: " + "; ".join(errors)


@pytest.fixture
def disposable_agent():
    made = []

    def make() -> DisposableAgent:
        agent = DisposableAgent()
        made.append(agent)  # registered first, so a failed setup is still cleaned up
        agent.create()
        return agent

    yield make
    failures = []
    for agent in made:
        try:
            agent.remove()
        except AssertionError as error:
            failures.append(str(error))
    assert not failures, "; ".join(failures)


async def wait_for_terminal_bytes(websocket, needle: bytes, timeout=30.0):
    deadline = time.monotonic() + timeout
    while needle not in websocket.sent:
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {needle!r}; the terminal showed {websocket.sent!r}")
        await asyncio.sleep(0.05)


@hosted_runner_only
@pytest.mark.asyncio
async def test_real_sudo_under_production_capabilities_needs_use_pty_off_for_the_attach_command(
    monkeypatch, disposable_agent, caplog
):
    agent = disposable_agent()
    monkeypatch.setattr(pty_relay, "TMUX_BINARY", agent.launcher)

    # Phase 1, the defect the real trial found (run H2): with use_pty the attach cannot start.
    agent.install_rules(use_pty=True)
    agent.attest()
    websocket = FrameWebSocket()
    relay = pty_relay.PtyRelay("test:real-sudo-use-pty", read_only=False)
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(relay.run(websocket), timeout=60)
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name == pty_relay.logger.name)

    # The browser frame is fixed and generic, so it proves nothing about the cause. The cause is
    # proven only by the backend log, which keeps sudo's own text out of the client payload.
    assert "unable to allocate pty" in logged, f"the attach did not fail for the intended cause. Log: {logged!r}"
    for marker in WRONG_SETUP_MARKERS:
        assert marker not in logged, f"the attach failed for the wrong reason ({marker!r}). Log: {logged!r}"
    assert b"ready" not in websocket.sent, "the attach started although use_pty is on and CAP_CHOWN is missing"
    assert websocket.frames == [{"type": "error", "message": FIXED_ATTACH_ERROR}]
    assert websocket.close_code == 4000
    assert b"sudo" not in websocket.sent and b"allocate" not in websocket.sent

    # Phase 2, the supported setup. Same user, programs, launcher, bounding set and session.
    # Only the command-scoped use_pty line of the rules changes.
    agent.install_rules(use_pty=False)
    agent.attest()
    websocket = FrameWebSocket()
    relay = pty_relay.PtyRelay("test:real-sudo-no-use-pty", read_only=False)
    task = asyncio.create_task(relay.run(websocket))
    try:
        await wait_for_terminal_bytes(websocket, b"ready")
        for rows, cols in ((45, 160), (24, 80)):  # full screen, then back
            relay.resize(rows, cols)
            # The size the attached program reports, not only the resize that was sent.
            await wait_for_terminal_bytes(websocket, f"WINCH:{rows} {cols}".encode())
        assert b"sudo" not in websocket.sent
        assert websocket.frames == []
    finally:
        websocket.finish()
        await asyncio.wait_for(task, timeout=60)


# --- the lifecycle of the privileged test: fake commands, so it runs anywhere --------------------
#
# These controls drive DisposableAgent with a fake sudo. They check what the privileged test does
# on a collision, on a partial setup, when a cleanup command fails, and when a process survives.


class FakeSudo:
    """Records the commands and can raise for chosen ones. Nothing is executed."""

    def __init__(self, raise_for=()):
        self.commands = []
        self.raise_for = raise_for

    def __call__(self, *args, check=True, timeout=60):
        self.commands.append(args)
        if args[0] in self.raise_for:
            raise subprocess.TimeoutExpired(args, timeout)
        stdout = ""
        staged = next((a for a in args if isinstance(a, str) and a.endswith("/rules")), None)
        if staged and args[0] in ("sh", "install"):
            self.installed = open(staged).read()  # what the fake "installs"
        if args[0] == "cat":
            stdout = getattr(self, "installed", "")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def names(self):
        return [c[0] for c in self.commands]


@pytest.fixture
def lifecycle(monkeypatch):
    """A DisposableAgent with every outside effect replaced. Returns (agent, fake sudo)."""
    fake = FakeSudo()
    monkeypatch.setattr(sys.modules[__name__], "run_sudo", fake)
    agent = DisposableAgent()
    agent.process_wait_seconds = 0.2
    monkeypatch.setattr(agent, "_user_exists", lambda: False)
    monkeypatch.setattr(agent, "_path_exists", lambda path: False)
    monkeypatch.setattr(agent, "_processes_of_uid", lambda uid: [])
    yield agent, fake
    shutil.rmtree(agent.work_dir, ignore_errors=True)


def destructive(fake):
    return [c for c in fake.commands if c[0] in ("rm", "userdel", "pkill")]


def test_a_preflight_collision_creates_nothing_and_cleanup_touches_nothing(lifecycle, monkeypatch):
    agent, fake = lifecycle
    monkeypatch.setattr(agent, "_user_exists", lambda: True)  # the generated name is already taken
    monkeypatch.setattr(agent, "check_prerequisites", agent.check_prerequisites)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    with pytest.raises(AssertionError):
        agent.create()
    assert not any(v for v in agent.owned.values())
    agent.remove()
    assert destructive(fake) == [], "cleanup touched a resource this test did not create"
    assert "useradd" not in fake.names()


def test_a_colliding_file_is_never_overwritten(lifecycle, monkeypatch):
    agent, fake = lifecycle
    agent.owned["user"] = True  # setup got as far as the user
    agent.agent_uid = 4242
    monkeypatch.setattr(agent, "_path_exists", lambda path: path == agent.dropin)  # the file is there
    agent.attempted.add("dropin")  # we tried to create it, but never confirmed that we did
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert not any(c[0] == "rm" and agent.dropin in c for c in fake.commands), "deleted a file it did not create"
    assert "left in place" in str(error.value)


def test_the_first_creation_of_the_rules_is_exclusive_and_replacement_needs_ownership(lifecycle):
    agent, fake = lifecycle
    agent.setpriv = "/usr/bin/setpriv"
    agent.install_rules(use_pty=True)
    created = [c for c in fake.commands if c[0] == "sh" and agent.dropin in c]
    assert len(created) == 1 and "set -C" in created[0][2], "the first creation must not overwrite"
    assert agent.owned["dropin"]
    agent.install_rules(use_pty=False)  # replacing the owned file is allowed
    assert any(c[0] == "install" and agent.dropin in c for c in fake.commands)


def test_a_partial_setup_cleans_only_what_exists(lifecycle):
    agent, fake = lifecycle
    agent.owned["user"] = True
    agent.agent_uid = 4242
    agent.owned["root_dir"] = True  # the rules were never installed
    agent.remove()
    assert any(c[0] == "userdel" for c in fake.commands)
    assert any(c[0] == "rm" and agent.root_dir in c for c in fake.commands)
    assert not any(c[0] == "rm" and agent.dropin in c for c in fake.commands)


def test_cleanup_continues_after_a_command_raises_and_reports_it(lifecycle, monkeypatch):
    agent, fake = lifecycle
    fake.raise_for = ("pkill",)  # the very first cleanup command times out
    agent.owned.update(user=True, dropin=True, root_dir=True)
    agent.agent_uid = 4242
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert {"rm", "userdel"} <= set(fake.names()), "later owned cleanup did not run"
    assert "pkill" in str(error.value)


def test_a_surviving_process_stops_the_user_deletion_and_fails_the_cleanup(lifecycle, monkeypatch):
    agent, fake = lifecycle
    agent.owned.update(user=True, dropin=True, root_dir=True)
    agent.agent_uid = 4242
    monkeypatch.setattr(agent, "_processes_of_uid", lambda uid: [31337])
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert "userdel" not in fake.names(), "the user was deleted while its process still ran"
    assert "31337" in str(error.value)
    assert {"rm"} <= set(fake.names())  # the rules and the directory are still removed


# --- residual failure paths found in review: a partial rules file, and unreadable processes -----


def test_a_failure_after_the_rules_file_is_reserved_is_still_cleaned_up(lifecycle):
    """The file exists but writing its content fails. It is the test's own file, so it is removed."""
    agent, fake = lifecycle
    agent.setpriv = "/usr/bin/setpriv"
    fake.raise_for = ("install",)  # the stage that writes the content fails after the file exists
    with pytest.raises(subprocess.TimeoutExpired):
        agent.install_rules(use_pty=True)
    assert agent.owned["dropin"], "the file was created exclusively, so it must be owned"
    fake.raise_for = ()
    agent.remove()
    assert any(c[0] == "rm" and agent.dropin in c for c in fake.commands), "the partial file was not removed"


def test_a_reservation_that_is_not_proven_leaves_an_existing_file_alone(lifecycle, monkeypatch):
    agent, fake = lifecycle
    agent.setpriv = "/usr/bin/setpriv"
    fake.raise_for = ("sh",)  # the exclusive create itself raises, so nothing is proven
    with pytest.raises(subprocess.TimeoutExpired):
        agent.install_rules(use_pty=True)
    assert not agent.owned["dropin"]
    monkeypatch.setattr(agent, "_path_exists", lambda path: path == agent.dropin)
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert not any(c[0] == "rm" and agent.dropin in c for c in fake.commands)
    assert "left in place" in str(error.value)


@pytest.fixture
def observed(lifecycle, monkeypatch):
    """The real process observation, over a fake /proc, with a created user to clean up."""
    agent, fake = lifecycle
    monkeypatch.setattr(agent, "_processes_of_uid", DisposableAgent._processes_of_uid.__get__(agent))
    agent.owned.update(user=True, dropin=True, root_dir=True)
    agent.agent_uid = 4242
    return agent, fake


def other_uid_status(pid):
    return "Name:\tsh\nUid:\t1000\t1000\t1000\t1000\n"


def test_an_unreadable_process_keeps_the_user_and_fails_the_cleanup(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["10", "11"])

    def read(pid):
        if pid == "10":
            raise PermissionError(13, "Permission denied")
        return other_uid_status(pid)

    monkeypatch.setattr(agent, "_read_proc_status", read)
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert "userdel" not in fake.names(), "the user was deleted although a process could not be observed"
    assert "rm" in fake.names(), "the other owned cleanup did not continue"
    assert "processes" in str(error.value)


def test_a_process_that_disappeared_is_not_a_survivor(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["10", "11"])

    def read(pid):
        if pid == "10":
            raise FileNotFoundError(2, "No such file or directory")  # it ended while we looked
        return other_uid_status(pid)

    monkeypatch.setattr(agent, "_read_proc_status", read)
    agent.remove()
    assert "userdel" in fake.names()


def test_a_process_of_the_created_uid_keeps_the_user(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["11"])
    monkeypatch.setattr(agent, "_read_proc_status", lambda pid: "Name:\tsleep\nUid:\t4242\t4242\t4242\t4242\n")
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert "userdel" not in fake.names()
    assert "11" in str(error.value)


def test_an_invalid_process_status_is_unknown_and_keeps_the_user(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["11"])
    monkeypatch.setattr(agent, "_read_proc_status", lambda pid: "Name:\tsleep\n")  # no Uid line
    with pytest.raises(AssertionError):
        agent.remove()
    assert "userdel" not in fake.names()
