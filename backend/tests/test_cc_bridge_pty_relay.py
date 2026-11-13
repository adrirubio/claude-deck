"""Tests for CC Bridge pty relay."""
import asyncio
import fcntl
import json
import logging
import os
import pty
import struct
import subprocess
import sys
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
# What the browser is told when sudo could not allocate its own pty (use_pty without CAP_CHOWN).
PTY_HINT_ERROR = "Could not attach to the terminal: sudo needs `!use_pty` for the agent tmux command. See the setup docs and the backend log."

# A failure that has nothing to do with the pty: the generic message must stay.
FAILS_FOR_ANOTHER_REASON = """
echo "tmux: no server running on the private socket" >&2
exit 1
"""

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
async def test_a_pty_allocation_failure_sends_one_fixed_hint_that_names_use_pty_and_no_raw_text(monkeypatch, tmp_path, caplog):
    stand_in_tmux(monkeypatch, tmp_path, FAILS_WITH_A_CONTROLLING_TERMINAL)
    websocket = FrameWebSocket()
    relay = pty_relay.PtyRelay("test:attach-fails", read_only=False)
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(relay.run(websocket), timeout=10)

    # One frame of the usual shape, the usual close code; only the fixed text names the setup rule.
    assert websocket.frames == [{"type": "error", "message": PTY_HINT_ERROR}]
    assert websocket.close_code == 4000
    assert b"sudo" not in websocket.sent and b"allocate" not in websocket.sent
    assert "Operation not permitted" not in websocket.frames[0]["message"]
    logged = [r.getMessage() for r in caplog.records if "unable to allocate pty" in r.getMessage()]
    assert len(logged) == 1 and "test:attach-fails" in logged[0]


@pytest.mark.asyncio
async def test_an_unrelated_attach_failure_keeps_the_generic_message(monkeypatch, tmp_path, caplog):
    stand_in_tmux(monkeypatch, tmp_path, FAILS_FOR_ANOTHER_REASON)
    websocket = FrameWebSocket()
    relay = pty_relay.PtyRelay("test:attach-fails-otherwise", read_only=False)
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(relay.run(websocket), timeout=10)

    assert websocket.frames == [{"type": "error", "message": FIXED_ATTACH_ERROR}]
    assert websocket.close_code == 4000
    assert b"no server running" not in websocket.sent
    assert "!use_pty" not in websocket.frames[0]["message"]
    logged = [r.getMessage() for r in caplog.records if "no server running" in r.getMessage()]
    assert len(logged) == 1 and "test:attach-fails-otherwise" in logged[0]


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
