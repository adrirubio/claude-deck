"""Pty relay — bridges a tmux pane to a WebSocket via pseudo-terminal."""
import asyncio
import ctypes
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

_active_relays: dict[str, "PtyRelay"] = {}

# Linux PR_SET_PDEATHSIG: auto-SIGTERM the child when its parent dies.
# This prevents orphaned tmux attach-session processes on server reload/crash.
_PR_SET_PDEATHSIG = 1

# The program the relay starts to attach to a tmux target. It is a constant, not a value
# from a request. Tests replace it with a stand-in script.
TMUX_BINARY = "tmux"

# The most attach-process error text one relay writes to the log, in characters.
_ATTACH_STDERR_LOG_LIMIT = 4096

# What the browser is told when the attach fails. It is fixed: the cause is in the backend log,
# and no text from sudo, the wrapper or the exception ever goes to the client.
ATTACH_FAILED_MESSAGE = "Could not attach to the terminal. See the backend log."

# sudo prints this when it cannot allocate its own pty (use_pty without CAP_CHOWN). The relay only
# detects the phrase in the attach stderr it already reads. It never sends sudo's text to the client.
_PTY_ALLOCATION_PHRASE = "unable to allocate pty"
# What the browser is told then. Also fixed text: it names the setup rule, not the cause text.
ATTACH_PTY_MESSAGE = (
    "Could not attach to the terminal: sudo needs `!use_pty` for the agent tmux command. "
    "See the setup docs and the backend log."
)

# How long the relay waits for an attach process whose output has ended to report its status.
_ATTACH_EXIT_WAIT_SECONDS = 2

# The most stderr bytes one loop callback reads. The reader is level-triggered, so the
# rest is read on the next loop turn. A process that never stops writing cannot hold the loop.
_STDERR_READ_CHUNK = 4096
_STDERR_READ_BUDGET = 16 * _STDERR_READ_CHUNK


def is_target_interactive(target: str) -> bool:
    """Return whether a live relay for target currently accepts input."""
    relay = _active_relays.get(target)
    return relay is not None and not relay.read_only


def _child_preexec() -> None:
    """Set up the child process: new session, controlling terminal, death signal.

    The relay pty is the child's stdin. Making it the controlling terminal of the new
    session lets the kernel send SIGWINCH to the child whenever the relay changes the
    pty size, as a terminal emulator does. The relay then never has to signal the attach
    process. That matters when the attach process is `sudo` running tmux as another user,
    which the controller cannot signal.
    """
    os.setsid()
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
    except OSError:
        pass


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


def resize_pty(fd: int, rows: int, cols: int) -> Optional[Exception]:
    """Set the pty size. Return None, or the error when the size could not be set.

    The attach process learns of the new size from the kernel (see _child_preexec).
    This function never signals it. The caller decides how to report a failure.
    """
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except (OSError, ValueError, TypeError, struct.error) as e:
        return e
    return None


class PtyRelay:
    """Bridges a tmux session to a WebSocket via a pseudo-terminal."""

    def __init__(self, target: str, read_only: bool = True):
        self.target = target
        self.read_only = read_only
        self._interactive_granted = not read_only
        self.master_fd: Optional[int] = None
        self.process: Optional[subprocess.Popen] = None
        self._closed = False
        self._resize_failure_logged = False
        self._stderr_fd: Optional[int] = None
        self._stderr_logged = 0
        self._stderr_suppressed = False
        self._output_seen = False
        self._pty_allocation_failed = False

    def set_read_only(self, requested: bool) -> None:
        self.read_only = not (self._interactive_granted and requested is False)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the relay pty. A failure is logged once per relay."""
        error = resize_pty(self.master_fd if self.master_fd is not None else -1, rows, cols)
        if error is not None and not self._resize_failure_logged:
            self._resize_failure_logged = True
            logger.warning("Could not resize the terminal for %s: %s", self.target, error)

    def _read_attach_stderr(self) -> bool:
        """Read what the attach process wrote to stderr into the log.

        Reads at most _STDERR_READ_BUDGET bytes, then returns so the event loop can run.
        Return False at the end of the stream, True when more may follow.
        """
        remaining = _STDERR_READ_BUDGET
        while remaining > 0:
            fd = self._stderr_fd  # close() clears it first, so a closed fd is never read
            if fd is None:
                return False
            try:
                data = os.read(fd, min(_STDERR_READ_CHUNK, remaining))
            except BlockingIOError:
                return True
            except OSError:
                return False
            if not data:
                return False
            remaining -= len(data)
            self._log_attach_stderr(data)
        return True

    def _log_attach_stderr(self, data: bytes) -> None:
        """Write attach errors to the backend log, never to the terminal.

        The log holds at most _ATTACH_STDERR_LOG_LIMIT characters for one relay. A line that
        does not fit is cut to what is left, and one notice says the rest is suppressed.
        """
        text = data.decode("utf-8", errors="replace")
        if _PTY_ALLOCATION_PHRASE in text:
            self._pty_allocation_failed = True  # remembered even after the log limit is reached
        if self._stderr_suppressed:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            room = _ATTACH_STDERR_LOG_LIMIT - self._stderr_logged
            if room > 0:
                shown = line[:room]
                self._stderr_logged += len(shown)
                logger.warning("tmux attach for %s: %s", self.target, shown)
            if room <= 0 or len(line) > room:
                self._stderr_suppressed = True
                logger.warning("Further tmux attach output for %s suppressed", self.target)
                return

    async def run(self, websocket: WebSocket, *, subprotocol: str | None = None) -> None:
        """Main relay loop — connect tmux to the WebSocket."""
        await websocket.accept(subprotocol=subprotocol)

        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd

        try:
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            # stderr is a pipe, not the pty: sudo and wrapper errors go to the log,
            # not into the terminal the person is looking at.
            self.process = subprocess.Popen(
                [TMUX_BINARY, "attach-session", "-t", self.target],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=subprocess.PIPE,
                preexec_fn=_child_preexec,
                env=env,
            )
        except Exception as e:
            os.close(master_fd)
            os.close(slave_fd)
            logger.warning("Could not start tmux attach for %s: %s", self.target, e)
            await websocket.send_json({"type": "error", "message": ATTACH_FAILED_MESSAGE})
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
                    self._output_seen = True
                    output_queue.put_nowait(data)
                else:
                    output_queue.put_nowait(b"")
            except OSError:
                output_queue.put_nowait(b"")

        loop.add_reader(master_fd, on_pty_readable)

        stderr_stream = getattr(self.process, "stderr", None)
        if stderr_stream is not None:
            self._stderr_fd = stderr_stream.fileno()
            os.set_blocking(self._stderr_fd, False)

            def on_stderr_readable():
                if not self._read_attach_stderr() and self._stderr_fd is not None:
                    loop.remove_reader(self._stderr_fd)

            loop.add_reader(self._stderr_fd, on_stderr_readable)

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
                            self.resize(ctrl.get("rows", 24), ctrl.get("cols", 80))
                        elif ctrl["type"] == "mode":
                            self.set_read_only(ctrl.get("readOnly", True))
                    elif not self.read_only:
                        os.write(master_fd, text.encode())

            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.debug(f"Input relay ended: {e}")

        output_task = asyncio.create_task(relay_output())
        input_task = asyncio.create_task(relay_input())
        attach_failed = False
        try:
            await asyncio.wait(
                {output_task, input_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if output_task.done() and not self._output_seen:
                # The stream ended before any output. Did the attach process fail?
                attach_failed = await asyncio.to_thread(self._attach_failed)
        finally:
            for task in (output_task, input_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(output_task, input_task, return_exceptions=True)
            loop.remove_reader(master_fd)
            if self._stderr_fd is not None:
                self._read_attach_stderr()  # keep the last lines the process wrote
                loop.remove_reader(self._stderr_fd)
            if _active_relays.get(self.target) is self:
                _active_relays.pop(self.target, None)
            await asyncio.to_thread(self.close)
            if websocket.client_state == WebSocketState.CONNECTED:
                if attach_failed:
                    # The reason is in the log. The client gets one fixed message.
                    logger.warning("tmux attach for %s ended with a failure before any output", self.target)
                    message = ATTACH_PTY_MESSAGE if self._pty_allocation_failed else ATTACH_FAILED_MESSAGE
                    await websocket.send_json({"type": "error", "message": message})
                    await websocket.close(code=4000)
                else:
                    await websocket.close()

    def _attach_failed(self) -> bool:
        """True when the attach process ended with a failure status. Waits briefly for it to exit."""
        if self.process is None:
            return False
        try:
            status = self.process.wait(timeout=_ATTACH_EXIT_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            return False
        return bool(status)

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
            stderr_stream = getattr(self.process, "stderr", None)
            if stderr_stream is not None:
                self._stderr_fd = None  # before the close, so no reader uses a recycled fd
                try:
                    stderr_stream.close()
                except OSError:
                    pass


async def close_all_relays() -> None:
    """Close all active pty relays. Called on app shutdown."""
    relays = list(_active_relays.values())
    try:
        await asyncio.gather(*(asyncio.to_thread(relay.close) for relay in relays))
    finally:
        for relay in relays:
            if _active_relays.get(relay.target) is relay:
                _active_relays.pop(relay.target, None)


def cleanup_orphaned_relays() -> None:
    """Kill orphaned tmux attach-session processes from previous runs.

    Called on startup as a safety net — PR_SET_PDEATHSIG handles the normal
    case, but processes can survive if the parent was SIGKILL'd.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", "tmux attach-session"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().splitlines()
        if not pids:
            return
        for pid_str in pids:
            try:
                os.kill(int(pid_str), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        if pids:
            logger.info("Cleaned up %d orphaned tmux attach-session process(es)", len(pids))
    except Exception:
        pass
