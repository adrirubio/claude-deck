"""CC Bridge endpoints — session discovery, preview, and terminal WebSocket."""
import logging
import secrets
import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, HTTPException
from pydantic import BaseModel

from app.services.cc_bridge.discovery import discover_cc_sessions, capture_pane_preview
from app.services.cc_bridge.pty_relay import PtyRelay

logger = logging.getLogger(__name__)

router = APIRouter()

_tokens: dict[str, float] = {}
_TOKEN_TTL = 30


class SpawnRequest(BaseModel):
    directory: str
    mode: str  # "plain", "worktree", "resume"
    worktree_name: Optional[str] = None
    session_id: Optional[str] = None
    project_folder: Optional[str] = None
    skip_permissions: bool = False


@router.get("/sessions")
def list_sessions():
    """List all discovered Claude Code sessions in tmux."""
    sessions = discover_cc_sessions()
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{target:path}/preview")
def get_session_preview(target: str):
    """Get a capture-pane text snapshot of a tmux session."""
    content = capture_pane_preview(target)
    if not content:
        raise HTTPException(status_code=404, detail="Could not capture pane")
    return {"target": target, "content": content}


@router.get("/token")
async def get_terminal_token():
    """Generate a one-time token for WebSocket authentication."""
    now = time.time()
    expired = [t for t, ts in _tokens.items() if now - ts > _TOKEN_TTL]
    for t in expired:
        _tokens.pop(t, None)

    token = secrets.token_urlsafe(32)
    _tokens[token] = now
    return {"token": token}


def _is_same_origin(origin: str, websocket: WebSocket) -> bool:
    """Accept the WebSocket if the Origin host matches the request Host header.

    This lets the UI attach over any reachable address (localhost, LAN, tailnet)
    without requiring explicit allowlist config, while still blocking cross-site
    WebSocket hijacking from unrelated domains.
    """
    try:
        origin_host = urlparse(origin).netloc.lower()
    except ValueError:
        return False
    if not origin_host:
        return False

    request_host = (websocket.headers.get("host") or "").lower()
    if request_host and origin_host == request_host:
        return True

    # Dev-mode fallback: Vite proxies WS to uvicorn, so when the browser
    # connects to <host>:5173 the WS Host header is still <host>:5173 —
    # which matches above. This branch only fires if a reverse proxy strips
    # the port; accept any loopback origin in that case.
    if origin_host.split(":")[0] in {"localhost", "127.0.0.1", "[::1]"}:
        return True

    return False


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
    """Attach to a CC tmux session via WebSocket terminal relay."""
    origin = websocket.headers.get("origin", "")
    if origin and not _is_same_origin(origin, websocket):
        await websocket.close(code=4403, reason="Invalid origin")
        return

    if not _validate_token(token):
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    read_only = mode != "interactive"
    relay = PtyRelay(target=target, read_only=read_only)
    await relay.run(websocket)


@router.post("/sessions")
def spawn_session_endpoint(request: SpawnRequest):
    """Spawn a new Claude Code session in tmux."""
    from app.services.cc_bridge.spawn import spawn_session as do_spawn
    try:
        result = do_spawn(
            directory=request.directory,
            mode=request.mode,
            worktree_name=request.worktree_name,
            session_id=request.session_id,
            project_folder=request.project_folder,
            skip_permissions=request.skip_permissions,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/sessions/{target}")
def kill_session_endpoint(target: str, cleanup_worktree: bool = False):
    """Kill a tmux session and optionally clean up its worktree."""
    from app.services.cc_bridge.spawn import kill_session
    return kill_session(session_name=target, cleanup_worktree=cleanup_worktree)
