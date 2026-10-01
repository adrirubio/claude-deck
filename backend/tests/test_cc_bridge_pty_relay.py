"""Tests for CC Bridge pty relay."""
import asyncio
import json
import os
import threading

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
