"""Codex app-server control for Agent Mail wakeups."""
from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

APP_SERVER_REQUEST_TIMEOUT_SECONDS = 15
APP_SERVER_START_TIMEOUT_SECONDS = 20


@dataclass
class CodexAppServerStatus:
    codex_cli_available: bool
    app_server_available: bool
    app_server_running: bool
    remote_control_running: bool
    remote_control_error: str | None = None
    app_server_error: str | None = None


@dataclass
class CodexWakeResult:
    ok: bool
    method: str = "codex_app_server"
    thread_id: str | None = None
    turn_id: str | None = None
    created_thread: bool = False
    resumed_thread: bool = False
    error: str | None = None


class CodexAppServerError(RuntimeError):
    """Raised when the Codex app-server control path cannot complete."""


class CodexAppServerService:
    """Own a local Codex app-server process for Agent Mail wakeup turns."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._request_id = 0
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._last_error: str | None = None

    def _codex_binary(self) -> str | None:
        return shutil.which("codex")

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def status(self) -> CodexAppServerStatus:
        codex_binary = self._codex_binary()
        remote_running, remote_error = self._remote_control_status(codex_binary)
        return CodexAppServerStatus(
            codex_cli_available=codex_binary is not None,
            app_server_available=codex_binary is not None,
            app_server_running=self.is_running(),
            remote_control_running=remote_running,
            remote_control_error=remote_error,
            app_server_error=self._last_error,
        )

    def start(self) -> CodexAppServerStatus:
        """Start the Deck-managed app-server process if needed."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self.status()
            self._stop_locked()
            self._last_error = None
            codex_binary = self._codex_binary()
            if codex_binary is None:
                self._last_error = "Codex CLI is not available on this machine"
                return self.status()
            try:
                self._proc = subprocess.Popen(
                    [codex_binary, "app-server", "--stdio"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                self._reader_thread = threading.Thread(
                    target=self._reader_loop,
                    name="codex-app-server-reader",
                    daemon=True,
                )
                self._stderr_thread = threading.Thread(
                    target=self._stderr_loop,
                    name="codex-app-server-stderr",
                    daemon=True,
                )
                self._reader_thread.start()
                self._stderr_thread.start()
                self._initialize()
            except Exception as exc:
                logger.info("failed to start Codex app-server: %s", exc)
                self._last_error = str(exc)
                self._stop_locked()
            return self.status()

    def stop(self) -> CodexAppServerStatus:
        with self._lock:
            self._stop_locked()
            self._last_error = None
            return self.status()

    def wake_repo(self, repo_path: str, prompt: str) -> CodexWakeResult:
        """Send a fixed wake prompt to a Codex thread for a repo."""
        with self._lock:
            if not self.is_running():
                return CodexWakeResult(
                    ok=False,
                    error="Codex app-server wakeups are not running",
                )
            try:
                thread, created, resumed = self._get_or_create_thread(repo_path)
                thread_id = thread.get("id")
                if not thread_id:
                    raise CodexAppServerError("Codex app-server returned a thread without an id")
                turn_result = self._request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "cwd": repo_path,
                        "input": [{"type": "text", "text": prompt}],
                    },
                    timeout=APP_SERVER_REQUEST_TIMEOUT_SECONDS,
                )
                turn_id = (turn_result.get("turn") or {}).get("id")
                return CodexWakeResult(
                    ok=True,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    created_thread=created,
                    resumed_thread=resumed,
                )
            except Exception as exc:
                logger.info("Codex app-server wake failed for %s: %s", repo_path, exc)
                self._last_error = str(exc)
                return CodexWakeResult(ok=False, error=str(exc))

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "claude_deck",
                    "title": "Claude Deck",
                    "version": settings.app_version,
                },
                "capabilities": {
                    "experimentalApi": True,
                    "optOutNotificationMethods": ["item/agentMessage/delta"],
                },
            },
            timeout=APP_SERVER_START_TIMEOUT_SECONDS,
        )
        self._notify("initialized", {})

    def _get_or_create_thread(self, repo_path: str) -> tuple[dict[str, Any], bool, bool]:
        threads_result = self._request(
            "thread/list",
            {"cwd": repo_path, "limit": 10, "archived": False},
            timeout=APP_SERVER_REQUEST_TIMEOUT_SECONDS,
        )
        thread = self._choose_thread(threads_result.get("data") or [])
        if thread is None:
            created = self._request(
                "thread/start",
                {"cwd": repo_path},
                timeout=APP_SERVER_REQUEST_TIMEOUT_SECONDS,
            )
            return created["thread"], True, False
        status = (thread.get("status") or {}).get("type")
        if status == "idle":
            return thread, False, False
        resumed = self._request(
            "thread/resume",
            {"threadId": thread["id"], "cwd": repo_path},
            timeout=APP_SERVER_REQUEST_TIMEOUT_SECONDS,
        )
        return resumed["thread"], False, True

    def _choose_thread(self, threads: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = []
        for thread in threads:
            status = (thread.get("status") or {}).get("type")
            if status in {"active", "systemError"}:
                continue
            priority = 0 if status == "idle" else 1 if status == "notLoaded" else 2
            candidates.append((priority, -(thread.get("updatedAt") or 0), thread))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    def _request(self, method: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
        with self._pending_lock:
            self._request_id += 1
            request_id = self._request_id
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._write({"id": request_id, "method": method, "params": params})
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise CodexAppServerError(f"Codex app-server request timed out: {method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                raise CodexAppServerError(error.get("message") or str(error))
            raise CodexAppServerError(str(error))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"method": method, "params": params})

    def _write(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise CodexAppServerError("Codex app-server is not running")
        with self._write_lock:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

    def _reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            response_id = message.get("id")
            if response_id is None:
                continue
            with self._pending_lock:
                response_queue = self._pending.get(response_id)
            if response_queue is not None:
                try:
                    response_queue.put_nowait(message)
                except queue.Full:
                    logger.debug("ignored duplicate Codex app-server response id %s", response_id)

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr_tail.append(line.rstrip())

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        with self._pending_lock:
            self._pending.clear()

    def _remote_control_status(self, codex_binary: str | None) -> tuple[bool, str | None]:
        if codex_binary is None:
            return False, "Codex CLI is not available on this machine"
        try:
            result = subprocess.run(
                [codex_binary, "app-server", "daemon", "version"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if result.returncode == 0:
            return True, None
        error = (result.stderr or result.stdout or "").strip()
        return False, error[:300] or "Codex remote control is not running"


codex_app_server_service = CodexAppServerService()
