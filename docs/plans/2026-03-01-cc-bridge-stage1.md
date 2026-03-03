# CC Bridge Stage 1 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Discover running Claude Code sessions in tmux and view them live in the browser via xterm.js.

**Architecture:** FastAPI backend discovers CC sessions via `libtmux`, exposes a REST API for listing and a WebSocket endpoint that bridges a tmux pane to the browser via pty relay. React frontend renders the terminal using `@xterm/xterm` with fit/webgl addons.

**Tech Stack:** Python (libtmux, pty stdlib, asyncio), FastAPI WebSocket, React, @xterm/xterm 6.x, TypeScript

**Design doc:** `docs/plans/cc-bridge-design.md`

---

## Task 0: Remove old ACP scaffolding

**Files:**
- Delete: `backend/app/services/acp/` (entire directory)
- Delete: `backend/app/api/v1/acp/` (entire directory)
- Modify: `backend/app/api/v1/router.py:20,54`

**Step 1: Remove the ACP import and route registration from router.py**

In `backend/app/api/v1/router.py`, remove line 20:
```python
from .acp.router import router as acp_router
```

And remove line 54:
```python
router.include_router(acp_router, prefix="/acp", tags=["ACP"])
```

**Step 2: Delete the old ACP directories**

```bash
rm -rf backend/app/services/acp/
rm -rf backend/app/api/v1/acp/
```

**Step 3: Verify the app still starts**

```bash
cd backend && source venv/bin/activate && python -c "from app.main import app; print('OK')"
```

Expected: `OK` with no import errors.

**Step 4: Commit**

```bash
git add -u
git commit -m "chore: remove old ACP scaffolding (replaced by CC Bridge)"
```

---

## Task 1: Add libtmux dependency

**Files:**
- Modify: `backend/pyproject.toml:6-14`

**Step 1: Add libtmux to dependencies**

In `backend/pyproject.toml`, add `"libtmux>=0.37.0"` to the dependencies list:

```toml
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.25",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.1.0",
    "python-dotenv>=1.0.0",
    "aiosqlite>=0.19.0",
    "libtmux>=0.37.0",
]
```

**Step 2: Install the dependency**

```bash
cd backend && source venv/bin/activate && pip install libtmux
```

**Step 3: Verify it works**

```bash
cd backend && source venv/bin/activate && python -c "import libtmux; s = libtmux.Server(); print(f'tmux sessions: {len(s.sessions)}')"
```

Expected: prints the number of active tmux sessions (should be >= 1 if you're running in tmux).

**Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "feat(cc-bridge): add libtmux dependency"
```

---

## Task 2: Backend — Session discovery service

**Files:**
- Create: `backend/app/services/cc_bridge/__init__.py`
- Create: `backend/app/services/cc_bridge/discovery.py`
- Create: `backend/tests/test_cc_bridge_discovery.py`

**Step 1: Create the package init**

Create `backend/app/services/cc_bridge/__init__.py` — empty file.

**Step 2: Write the failing test**

Create `backend/tests/test_cc_bridge_discovery.py`:

```python
"""Tests for CC Bridge session discovery."""
import pytest
from unittest.mock import MagicMock, patch


def test_is_claude_code_matches_claude_command():
    from app.services.cc_bridge.discovery import _is_claude_code
    assert _is_claude_code("claude") is True


def test_is_claude_code_rejects_other_commands():
    from app.services.cc_bridge.discovery import _is_claude_code
    assert _is_claude_code("vim") is False
    assert _is_claude_code("bash") is False
    assert _is_claude_code("node") is False  # too generic on its own


def test_is_claude_code_matches_claude_variants():
    from app.services.cc_bridge.discovery import _is_claude_code
    assert _is_claude_code("claude") is True


def test_discover_returns_list():
    from app.services.cc_bridge.discovery import discover_cc_sessions
    # Should not raise even if no tmux server is running
    result = discover_cc_sessions()
    assert isinstance(result, list)


def test_discover_session_dict_shape():
    """When a CC session is found, it should have the expected keys."""
    from app.services.cc_bridge.discovery import _build_session_info

    mock_pane = MagicMock()
    mock_pane.pane_current_command = "claude"
    mock_pane.pane_current_path = "/home/user/project"
    mock_pane.pane_pid = "12345"
    mock_pane.pane_id = "%0"
    mock_pane.pane_index = "0"

    mock_window = MagicMock()
    mock_window.window_index = "0"
    mock_window.window_name = "main"

    mock_session = MagicMock()
    mock_session.session_name = "cc-proj"

    result = _build_session_info(mock_pane, mock_window, mock_session)
    assert result["tmux_target"] == "cc-proj:0.0"
    assert result["session_name"] == "cc-proj"
    assert result["cwd"] == "/home/user/project"
    assert result["pid"] == "12345"
    assert result["pane_id"] == "%0"


def test_capture_pane_preview_returns_string():
    """capture_pane_preview should return a string even on failure."""
    from app.services.cc_bridge.discovery import capture_pane_preview
    # Using a non-existent target — should return empty string, not raise
    result = capture_pane_preview("nonexistent-session:0.0")
    assert isinstance(result, str)
```

**Step 3: Run test to verify it fails**

```bash
cd backend && source venv/bin/activate && pytest tests/test_cc_bridge_discovery.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.cc_bridge'`

**Step 4: Write the implementation**

Create `backend/app/services/cc_bridge/discovery.py`:

```python
"""Discover Claude Code sessions running in tmux."""
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _is_claude_code(command: str) -> bool:
    """Check if a tmux pane command looks like Claude Code."""
    return command.strip().lower() == "claude"


def _build_session_info(pane: Any, window: Any, session: Any) -> dict:
    """Build a session info dict from libtmux objects."""
    return {
        "tmux_target": f"{session.session_name}:{window.window_index}.{pane.pane_index}",
        "session_name": session.session_name,
        "window_name": window.window_name,
        "pane_id": pane.pane_id,
        "cwd": pane.pane_current_path,
        "pid": pane.pane_pid,
        "status": "active",
    }


def discover_cc_sessions() -> list[dict]:
    """Find all tmux panes running Claude Code.

    Returns an empty list if tmux is not running or no CC sessions are found.
    """
    try:
        import libtmux
        server = libtmux.Server()
    except Exception:
        logger.debug("Could not connect to tmux server")
        return []

    results = []
    try:
        for session in server.sessions:
            for window in session.windows:
                for pane in window.panes:
                    cmd = pane.pane_current_command or ""
                    if _is_claude_code(cmd):
                        results.append(_build_session_info(pane, window, session))
    except Exception as e:
        logger.warning(f"Error discovering tmux sessions: {e}")

    return results


def capture_pane_preview(target: str) -> str:
    """Capture the current visible content of a tmux pane.

    Args:
        target: tmux target string (e.g., "session:window.pane")

    Returns:
        The pane content as a string, or empty string on failure.
    """
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-e"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""
```

**Step 5: Run tests to verify they pass**

```bash
cd backend && source venv/bin/activate && pytest tests/test_cc_bridge_discovery.py -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add backend/app/services/cc_bridge/ backend/tests/test_cc_bridge_discovery.py
git commit -m "feat(cc-bridge): add tmux session discovery service"
```

---

## Task 3: Backend — Pty relay service

**Files:**
- Create: `backend/app/services/cc_bridge/pty_relay.py`
- Create: `backend/tests/test_cc_bridge_pty_relay.py`

**Step 1: Write the failing test**

Create `backend/tests/test_cc_bridge_pty_relay.py`:

```python
"""Tests for CC Bridge pty relay."""
import json
import pytest


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
    # Should not raise, just log warning
    resize_pty(-1, 24, 80)
```

**Step 2: Run test to verify it fails**

```bash
cd backend && source venv/bin/activate && pytest tests/test_cc_bridge_pty_relay.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

Create `backend/app/services/cc_bridge/pty_relay.py`:

```python
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

# Track active relays for cleanup
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
    except OSError as e:
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

        # Close slave in parent — child owns it now
        os.close(slave_fd)

        # Set master to non-blocking
        flag = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

        _active_relays[self.target] = self
        loop = asyncio.get_event_loop()

        # Event-driven pty reader using add_reader
        output_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def on_pty_readable():
            try:
                data = os.read(master_fd, 65536)
                if data:
                    output_queue.put_nowait(data)
                else:
                    output_queue.put_nowait(b"")  # EOF signal
            except OSError:
                output_queue.put_nowait(b"")  # EOF signal

        loop.add_reader(master_fd, on_pty_readable)

        async def relay_output():
            """Read from pty and send to WebSocket."""
            try:
                while True:
                    data = await output_queue.get()
                    if not data:
                        break  # EOF
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_bytes(data)
            except Exception as e:
                logger.debug(f"Output relay ended: {e}")

        async def relay_input():
            """Read from WebSocket and write to pty."""
            try:
                while True:
                    message = await websocket.receive()
                    msg_type = message.get("type", "")

                    if msg_type == "websocket.disconnect":
                        break

                    # Binary frames — raw terminal input
                    if "bytes" in message and message["bytes"]:
                        if not self.read_only:
                            os.write(master_fd, message["bytes"])
                        continue

                    # Text frames — either control messages or terminal input
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
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && source venv/bin/activate && pytest tests/test_cc_bridge_pty_relay.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add backend/app/services/cc_bridge/pty_relay.py backend/tests/test_cc_bridge_pty_relay.py
git commit -m "feat(cc-bridge): add pty relay service for tmux-to-WebSocket bridging"
```

---

## Task 4: Backend — API endpoints

**Files:**
- Create: `backend/app/api/v1/cc_bridge/__init__.py`
- Create: `backend/app/api/v1/cc_bridge/router.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/main.py:14-19`

**Step 1: Create the API route module**

Create `backend/app/api/v1/cc_bridge/__init__.py` — empty file.

Create `backend/app/api/v1/cc_bridge/router.py`:

```python
"""CC Bridge endpoints — session discovery, preview, and terminal WebSocket."""
import logging
import secrets
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, HTTPException, Query

from app.services.cc_bridge.discovery import discover_cc_sessions, capture_pane_preview
from app.services.cc_bridge.pty_relay import PtyRelay

logger = logging.getLogger(__name__)

router = APIRouter()

# One-time token store: token -> (issued_at, used)
_tokens: dict[str, float] = {}
_TOKEN_TTL = 30  # seconds


@router.get("/sessions")
async def list_sessions():
    """List all discovered Claude Code sessions in tmux."""
    sessions = discover_cc_sessions()
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{target:path}/preview")
async def get_session_preview(target: str):
    """Get a capture-pane text snapshot of a tmux session."""
    content = capture_pane_preview(target)
    if not content:
        raise HTTPException(status_code=404, detail="Could not capture pane")
    return {"target": target, "content": content}


@router.get("/token")
async def get_terminal_token():
    """Generate a one-time token for WebSocket authentication."""
    # Clean expired tokens
    now = time.time()
    expired = [t for t, ts in _tokens.items() if now - ts > _TOKEN_TTL]
    for t in expired:
        _tokens.pop(t, None)

    token = secrets.token_urlsafe(32)
    _tokens[token] = now
    return {"token": token}


def _validate_token(token: str) -> bool:
    """Validate and consume a one-time token."""
    issued_at = _tokens.pop(token, None)
    if issued_at is None:
        return False
    return (time.time() - issued_at) <= _TOKEN_TTL


@router.websocket("/sessions/{target:path}/terminal")
async def session_terminal(
    websocket: WebSocket,
    target: str,
    token: str = "",
    mode: str = "readonly",
):
    """Attach to a CC tmux session via WebSocket terminal relay.

    Query params:
        token: One-time auth token from GET /token
        mode: "readonly" (default) or "interactive"
    """
    # Validate origin
    origin = websocket.headers.get("origin", "")
    allowed_origins = {"http://localhost:5173", "http://127.0.0.1:5173"}
    if origin and origin not in allowed_origins:
        await websocket.close(code=4403, reason="Invalid origin")
        return

    # Validate token
    if not _validate_token(token):
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    read_only = mode != "interactive"
    relay = PtyRelay(target=target, read_only=read_only)
    await relay.run(websocket)
```

**Step 2: Register the route in the main router**

In `backend/app/api/v1/router.py`, add the import (replacing the old ACP import) and include the router:

Add import:
```python
from .cc_bridge.router import router as cc_bridge_router
```

Add registration:
```python
router.include_router(cc_bridge_router, prefix="/cc-bridge", tags=["CC Bridge"])
```

**Step 3: Wire shutdown cleanup into lifespan**

In `backend/app/main.py`, update the lifespan function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup: Initialize database
    await init_db()
    yield
    # Shutdown: Cleanup
    from app.services.cc_bridge.pty_relay import close_all_relays
    await close_all_relays()
```

**Step 4: Verify the app starts and the endpoints work**

```bash
cd backend && source venv/bin/activate && python -c "from app.main import app; print('OK')"
```

Expected: `OK`

Start the server and test the discovery endpoint (in another terminal):

```bash
curl -s http://localhost:8000/api/v1/cc-bridge/sessions | python -m json.tool
```

Expected: JSON with `sessions` array (may be empty if no CC is running in tmux) and `count`.

**Step 5: Commit**

```bash
git add backend/app/api/v1/cc_bridge/ backend/app/api/v1/router.py backend/app/main.py
git commit -m "feat(cc-bridge): add REST and WebSocket API endpoints"
```

---

## Task 5: Frontend — Install xterm.js dependencies

**Files:**
- Modify: `frontend/package.json`

**Step 1: Install the packages**

```bash
cd frontend && npm install @xterm/xterm @xterm/addon-fit @xterm/addon-webgl @xterm/addon-web-links
```

**Step 2: Verify installation**

```bash
cd frontend && node -e "require('@xterm/xterm'); console.log('xterm OK')"
```

Expected: `xterm OK`

**Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(cc-bridge): add xterm.js dependencies"
```

---

## Task 6: Frontend — Types and API client

**Files:**
- Create: `frontend/src/features/cc-bridge/types.ts`
- Create: `frontend/src/features/cc-bridge/api.ts`

**Step 1: Create the types file**

Create `frontend/src/features/cc-bridge/types.ts`:

```typescript
export interface CCSession {
  tmux_target: string
  session_name: string
  window_name: string
  pane_id: string
  cwd: string
  pid: string
  status: string
}

export interface CCSessionsResponse {
  sessions: CCSession[]
  count: number
}

export interface CCPreviewResponse {
  target: string
  content: string
}

export interface CCTokenResponse {
  token: string
}
```

**Step 2: Create the API client**

Create `frontend/src/features/cc-bridge/api.ts`:

```typescript
import { apiClient } from '@/lib/api'
import type { CCSessionsResponse, CCPreviewResponse, CCTokenResponse } from './types'

const BASE = 'cc-bridge'

export async function fetchCCSessions(): Promise<CCSessionsResponse> {
  return apiClient<CCSessionsResponse>(BASE + '/sessions')
}

export async function fetchSessionPreview(target: string): Promise<CCPreviewResponse> {
  return apiClient<CCPreviewResponse>(`${BASE}/sessions/${encodeURIComponent(target)}/preview`)
}

export async function fetchTerminalToken(): Promise<CCTokenResponse> {
  return apiClient<CCTokenResponse>(BASE + '/token')
}

export function buildTerminalWsUrl(target: string, token: string, mode: string = 'readonly'): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}/api/v1/${BASE}/sessions/${encodeURIComponent(target)}/terminal?token=${token}&mode=${mode}`
}
```

**Step 3: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20
```

Expected: No errors related to cc-bridge files.

**Step 4: Commit**

```bash
git add frontend/src/features/cc-bridge/
git commit -m "feat(cc-bridge): add frontend types and API client"
```

---

## Task 7: Frontend — useCCSessions hook

**Files:**
- Create: `frontend/src/features/cc-bridge/useCCSessions.ts`

**Step 1: Create the hook**

Create `frontend/src/features/cc-bridge/useCCSessions.ts`:

```typescript
import { useState, useEffect, useCallback, useRef } from 'react'
import type { CCSession } from './types'
import { fetchCCSessions } from './api'

const POLL_INTERVAL = 5000

export function useCCSessions() {
  const [sessions, setSessions] = useState<CCSession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await fetchCCSessions()
      setSessions(data.sessions)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch sessions')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    intervalRef.current = setInterval(refresh, POLL_INTERVAL)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [refresh])

  return { sessions, loading, error, refresh }
}
```

**Step 2: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep cc-bridge
```

Expected: No errors.

**Step 3: Commit**

```bash
git add frontend/src/features/cc-bridge/useCCSessions.ts
git commit -m "feat(cc-bridge): add useCCSessions polling hook"
```

---

## Task 8: Frontend — useTerminal hook

**Files:**
- Create: `frontend/src/features/cc-bridge/useTerminal.ts`

**Step 1: Create the hook**

Create `frontend/src/features/cc-bridge/useTerminal.ts`:

```typescript
import { useRef, useCallback, useState, useEffect } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebglAddon } from '@xterm/addon-webgl'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'
import { fetchTerminalToken } from './api'
import { buildTerminalWsUrl } from './api'

export function useTerminal(containerRef: React.RefObject<HTMLDivElement | null>) {
  const termRef = useRef<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [readOnly, setReadOnly] = useState(true)
  const readOnlyRef = useRef(true)

  // Keep ref in sync with state
  useEffect(() => {
    readOnlyRef.current = readOnly
  }, [readOnly])

  const initTerminal = useCallback(() => {
    if (termRef.current || !containerRef.current) return

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
      theme: {
        background: '#1e1e2e',
        foreground: '#cdd6f4',
        cursor: '#f5e0dc',
      },
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(new WebLinksAddon())

    term.open(containerRef.current)

    // Try WebGL, fall back to canvas
    try {
      term.loadAddon(new WebglAddon())
    } catch {
      // WebGL not available, canvas fallback is fine
    }

    fitAddon.fit()
    termRef.current = term
    fitAddonRef.current = fitAddon
  }, [containerRef])

  const attach = useCallback(async (target: string) => {
    // Clean up previous connection
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    initTerminal()
    const term = termRef.current
    if (!term) return

    term.clear()

    // Get auth token
    const { token } = await fetchTerminalToken()
    const mode = readOnlyRef.current ? 'readonly' : 'interactive'
    const url = buildTerminalWsUrl(target, token, mode)

    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      // Send initial resize
      const dims = fitAddonRef.current?.proposeDimensions()
      if (dims) {
        ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
      }
    }

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(event.data))
      } else {
        // Text frame — could be error JSON
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'error') {
            term.writeln(`\r\n\x1b[31mError: ${msg.message}\x1b[0m`)
          }
        } catch {
          term.write(event.data)
        }
      }
    }

    ws.onclose = () => {
      setConnected(false)
    }

    ws.onerror = () => {
      setConnected(false)
    }

    // Forward user input
    const onDataDisposable = term.onData((data) => {
      if (!readOnlyRef.current && ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    // Handle resize
    const onResizeDisposable = term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols, rows }))
      }
    })

    // Store disposables for cleanup
    ws.addEventListener('close', () => {
      onDataDisposable.dispose()
      onResizeDisposable.dispose()
    }, { once: true })
  }, [initTerminal])

  const detach = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setConnected(false)
    termRef.current?.clear()
    termRef.current?.writeln('\x1b[90mDetached.\x1b[0m')
  }, [])

  // Fit on container resize
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const observer = new ResizeObserver(() => {
      fitAddonRef.current?.fit()
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [containerRef])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close()
      termRef.current?.dispose()
    }
  }, [])

  return { connected, readOnly, setReadOnly, attach, detach }
}
```

**Step 2: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep cc-bridge
```

Expected: No errors.

**Step 3: Commit**

```bash
git add frontend/src/features/cc-bridge/useTerminal.ts
git commit -m "feat(cc-bridge): add useTerminal hook with xterm.js + WebSocket"
```

---

## Task 9: Frontend — SessionCard and SessionList components

**Files:**
- Create: `frontend/src/features/cc-bridge/SessionCard.tsx`
- Create: `frontend/src/features/cc-bridge/SessionList.tsx`

**Step 1: Create SessionCard**

Create `frontend/src/features/cc-bridge/SessionCard.tsx`:

```tsx
import { Card, CardContent } from '@/components/ui/card'
import { CLICKABLE_CARD } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type { CCSession } from './types'

interface SessionCardProps {
  session: CCSession
  isSelected: boolean
  onClick: () => void
}

export function SessionCard({ session, isSelected, onClick }: SessionCardProps) {
  // Extract project name from cwd (last path segment)
  const projectName = session.cwd.split('/').pop() || session.cwd

  return (
    <Card
      className={cn(
        CLICKABLE_CARD,
        isSelected && 'border-primary bg-primary/5'
      )}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      tabIndex={0}
      role="button"
    >
      <CardContent className="p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium truncate">{session.session_name}</span>
          <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
        </div>
        <p className="text-xs text-muted-foreground truncate mt-1" title={session.cwd}>
          {projectName}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {session.tmux_target}
        </p>
      </CardContent>
    </Card>
  )
}
```

**Step 2: Create SessionList**

Create `frontend/src/features/cc-bridge/SessionList.tsx`:

```tsx
import { Loader2, RefreshCw, MonitorX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SessionCard } from './SessionCard'
import type { CCSession } from './types'

interface SessionListProps {
  sessions: CCSession[]
  loading: boolean
  error: string | null
  selectedTarget: string | null
  onSelect: (target: string) => void
  onRefresh: () => void
}

export function SessionList({
  sessions,
  loading,
  error,
  selectedTarget,
  onSelect,
  onRefresh,
}: SessionListProps) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-3 border-b">
        <span className="text-sm font-medium">
          Sessions ({sessions.length})
        </span>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRefresh}>
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {loading && sessions.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && (
          <p className="text-sm text-destructive p-2">{error}</p>
        )}

        {!loading && !error && sessions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
            <MonitorX className="h-8 w-8 mb-2" />
            <p className="text-sm">No CC sessions found</p>
            <p className="text-xs mt-1">Start Claude Code in a tmux session</p>
          </div>
        )}

        {sessions.map((session) => (
          <SessionCard
            key={session.pane_id}
            session={session}
            isSelected={selectedTarget === session.tmux_target}
            onClick={() => onSelect(session.tmux_target)}
          />
        ))}
      </div>
    </div>
  )
}
```

Note: `SessionList.tsx` uses `cn` — add the import:

```tsx
import { cn } from '@/lib/utils'
```

to the imports at the top (after lucide-react import).

**Step 3: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i error | head -10
```

Expected: No errors in cc-bridge files.

**Step 4: Commit**

```bash
git add frontend/src/features/cc-bridge/SessionCard.tsx frontend/src/features/cc-bridge/SessionList.tsx
git commit -m "feat(cc-bridge): add SessionCard and SessionList components"
```

---

## Task 10: Frontend — TerminalView component

**Files:**
- Create: `frontend/src/features/cc-bridge/TerminalView.tsx`

**Step 1: Create the component**

Create `frontend/src/features/cc-bridge/TerminalView.tsx`:

```tsx
import { useRef } from 'react'
import { Monitor } from 'lucide-react'
import { useTerminal } from './useTerminal'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface TerminalViewProps {
  target: string | null
}

export function TerminalView({ target }: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { connected, readOnly, setReadOnly, attach, detach } = useTerminal(containerRef)

  // Attach when target changes
  const prevTargetRef = useRef<string | null>(null)
  if (target !== prevTargetRef.current) {
    prevTargetRef.current = target
    if (target) {
      attach(target)
    } else {
      detach()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Terminal area */}
      <div className="flex-1 relative">
        {!target && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground bg-background">
            <Monitor className="h-12 w-12 mb-3" />
            <p className="text-sm">Select a session to attach</p>
          </div>
        )}
        <div
          ref={containerRef}
          className={cn(
            'h-full w-full',
            !target && 'invisible'
          )}
        />
      </div>

      {/* Bottom toolbar */}
      {target && (
        <div className="flex items-center justify-between px-3 py-2 border-t bg-background">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-sm">
              <button
                className={cn(
                  'px-2 py-0.5 rounded text-xs font-medium transition-colors',
                  readOnly
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => setReadOnly(true)}
              >
                Read-only
              </button>
              <button
                className={cn(
                  'px-2 py-0.5 rounded text-xs font-medium transition-colors',
                  !readOnly
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => setReadOnly(false)}
              >
                Interactive
              </button>
            </div>
            <span className={cn(
              'text-xs',
              connected ? 'text-green-500' : 'text-muted-foreground'
            )}>
              {connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={detach}>
            Detach
          </Button>
        </div>
      )}
    </div>
  )
}
```

**Step 2: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i error | head -10
```

Expected: No errors.

**Step 3: Commit**

```bash
git add frontend/src/features/cc-bridge/TerminalView.tsx
git commit -m "feat(cc-bridge): add TerminalView component with xterm.js rendering"
```

---

## Task 11: Frontend — CCBridgePage and route integration

**Files:**
- Create: `frontend/src/features/cc-bridge/CCBridgePage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`

**Step 1: Create the page**

Create `frontend/src/features/cc-bridge/CCBridgePage.tsx`:

```tsx
import { useState } from 'react'
import { MonitorPlay } from 'lucide-react'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'

export function CCBridgePage() {
  const { sessions, loading, error, refresh } = useCCSessions()
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null)

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* Header */}
      <div className="flex items-center gap-2 px-6 py-4 border-b shrink-0">
        <MonitorPlay className="h-5 w-5" />
        <div>
          <h1 className="text-lg font-semibold">CC Bridge</h1>
          <p className="text-sm text-muted-foreground">
            Live Claude Code sessions
          </p>
        </div>
      </div>

      {/* Main content: sidebar + terminal */}
      <div className="flex flex-1 min-h-0">
        {/* Session sidebar */}
        <div className="w-56 border-r shrink-0">
          <SessionList
            sessions={sessions}
            loading={loading}
            error={error}
            selectedTarget={selectedTarget}
            onSelect={setSelectedTarget}
            onRefresh={refresh}
          />
        </div>

        {/* Terminal */}
        <div className="flex-1 min-w-0">
          <TerminalView target={selectedTarget} />
        </div>
      </div>
    </div>
  )
}
```

**Step 2: Add the route to App.tsx**

In `frontend/src/App.tsx`, add import:

```typescript
import { CCBridgePage } from './features/cc-bridge/CCBridgePage'
```

Add route (after the `sessions` route):

```tsx
<Route path="cc-bridge" element={<CCBridgePage />} />
```

**Step 3: Add sidebar navigation**

In `frontend/src/components/layout/Sidebar.tsx`, add `MonitorPlay` to the lucide-react import:

```typescript
import {
  // ... existing imports ...
  MonitorPlay,
} from 'lucide-react'
```

Add navigation entry in the "Tier 4: Monitoring & Tools" section, after the Sessions entry:

```typescript
{ name: 'CC Bridge', href: '/cc-bridge', icon: MonitorPlay },
```

**Step 4: Verify it compiles and lint passes**

```bash
cd frontend && npx tsc --noEmit --pretty && npm run lint
```

Expected: No errors.

**Step 5: Commit**

```bash
git add frontend/src/features/cc-bridge/CCBridgePage.tsx frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(cc-bridge): add CCBridgePage and wire up routing + navigation"
```

---

## Task 12: Integration test — end-to-end verification

**Step 1: Start a test CC session in tmux**

```bash
tmux new-session -d -s test-cc-bridge 'claude'
```

**Step 2: Start the Deck dev servers**

```bash
./scripts/dev.sh
```

**Step 3: Verify backend discovery**

```bash
curl -s http://localhost:8000/api/v1/cc-bridge/sessions | python -m json.tool
```

Expected: JSON with at least one session showing `session_name: "test-cc-bridge"`.

**Step 4: Verify preview endpoint**

```bash
curl -s http://localhost:8000/api/v1/cc-bridge/sessions/test-cc-bridge:0.0/preview | python -m json.tool
```

Expected: JSON with `content` field showing the terminal content.

**Step 5: Verify token endpoint**

```bash
curl -s http://localhost:8000/api/v1/cc-bridge/token | python -m json.tool
```

Expected: JSON with `token` field.

**Step 6: Open the frontend**

Navigate to `http://localhost:5173/cc-bridge`. Verify:
- The page loads with "CC Bridge" header
- The session list shows the test-cc-bridge session
- Clicking the session opens a live terminal view
- The terminal shows Claude Code's TUI
- Read-only/Interactive toggle works
- Detach button works

**Step 7: Clean up**

```bash
tmux kill-session -t test-cc-bridge
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 0 | Remove old ACP scaffolding | router.py, delete acp/ dirs |
| 1 | Add libtmux dependency | pyproject.toml |
| 2 | Session discovery service | discovery.py + tests |
| 3 | Pty relay service | pty_relay.py + tests |
| 4 | Backend API endpoints + lifespan | cc_bridge/router.py, router.py, main.py |
| 5 | Install xterm.js | package.json |
| 6 | Frontend types + API client | types.ts, api.ts |
| 7 | useCCSessions hook | useCCSessions.ts |
| 8 | useTerminal hook | useTerminal.ts |
| 9 | SessionCard + SessionList | SessionCard.tsx, SessionList.tsx |
| 10 | TerminalView | TerminalView.tsx |
| 11 | CCBridgePage + routing + nav | CCBridgePage.tsx, App.tsx, Sidebar.tsx |
| 12 | End-to-end verification | Manual testing |
