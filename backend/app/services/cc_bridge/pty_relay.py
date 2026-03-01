"""Pty relay — bridges a tmux pane to a WebSocket via pseudo-terminal."""
import asyncio
import fcntl
import json
import logging
import os
import pty
import struct
import subprocess
import termios
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

_active_relays: dict[str, "PtyRelay"] = {}


def parse_control_message(text: str) -> Optional[dict]:
    """Parse a text frame as a control message.

    Returns the parsed dict if it's valid JSON with a 'type' field,
    otherwise returns None (meaning it's terminal input).
    """
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "type" in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def resize_pty(fd: int, rows: int, cols: int) -> None:
    """Send TIOCSWINSZ to resize the pty."""
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except (OSError, ValueError) as e:
        logger.warning(f"Failed to resize pty: {e}")


class PtyRelay:
    """Bridges a tmux session to a WebSocket via a pseudo-terminal."""

    def __init__(self, target: str, read_only: bool = True):
        self.target = target
        self.read_only = read_only
        self.master_fd: Optional[int] = None
        self.process: Optional[subprocess.Popen] = None
        self._closed = False

    async def run(self, websocket: WebSocket) -> None:
        """Main relay loop — connect tmux to the WebSocket."""
        await websocket.accept()

        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd

        try:
            self.process = subprocess.Popen(
                ["tmux", "attach-session", "-t", self.target],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
            )
        except Exception as e:
            os.close(master_fd)
            os.close(slave_fd)
            await websocket.send_json({"type": "error", "message": f"Failed to attach: {e}"})
            await websocket.close(code=4000)
            return

        os.close(slave_fd)

        flag = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

        _active_relays[self.target] = self
        loop = asyncio.get_event_loop()

        output_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def on_pty_readable():
            try:
                data = os.read(master_fd, 65536)
                if data:
                    output_queue.put_nowait(data)
                else:
                    output_queue.put_nowait(b"")
            except OSError:
                output_queue.put_nowait(b"")

        loop.add_reader(master_fd, on_pty_readable)

        async def relay_output():
            try:
                while True:
                    data = await output_queue.get()
                    if not data:
                        break
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_bytes(data)
            except Exception as e:
                logger.debug(f"Output relay ended: {e}")

        async def relay_input():
            try:
                while True:
                    message = await websocket.receive()
                    msg_type = message.get("type", "")

                    if msg_type == "websocket.disconnect":
                        break

                    if "bytes" in message and message["bytes"]:
                        if not self.read_only:
                            os.write(master_fd, message["bytes"])
                        continue

                    text = message.get("text", "")
                    if not text:
                        continue

                    ctrl = parse_control_message(text)
                    if ctrl:
                        if ctrl["type"] == "resize":
                            resize_pty(master_fd, ctrl.get("rows", 24), ctrl.get("cols", 80))
                    elif not self.read_only:
                        os.write(master_fd, text.encode())

            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.debug(f"Input relay ended: {e}")

        try:
            await asyncio.gather(relay_output(), relay_input())
        finally:
            self.close()
            loop.remove_reader(master_fd)
            _active_relays.pop(self.target, None)
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()

    def close(self) -> None:
        """Clean up pty and subprocess."""
        if self._closed:
            return
        self._closed = True

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass


async def close_all_relays() -> None:
    """Close all active pty relays. Called on app shutdown."""
    for relay in list(_active_relays.values()):
        relay.close()
    _active_relays.clear()
