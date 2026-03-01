"""CC Bridge endpoints — session discovery, preview, and terminal WebSocket."""
import logging
import secrets
import time

from fastapi import APIRouter, WebSocket, HTTPException

from app.services.cc_bridge.discovery import discover_cc_sessions, capture_pane_preview
from app.services.cc_bridge.pty_relay import PtyRelay

logger = logging.getLogger(__name__)

router = APIRouter()

_tokens: dict[str, float] = {}
_TOKEN_TTL = 30


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
    """Attach to a CC tmux session via WebSocket terminal relay."""
    origin = websocket.headers.get("origin", "")
    allowed_origins = {"http://localhost:5173", "http://127.0.0.1:5173"}
    if origin and origin not in allowed_origins:
        await websocket.close(code=4403, reason="Invalid origin")
        return

    if not _validate_token(token):
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    read_only = mode != "interactive"
    relay = PtyRelay(target=target, read_only=read_only)
    await relay.run(websocket)
