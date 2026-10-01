"""CC Bridge endpoints — session discovery, preview, and terminal WebSocket."""
import logging
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query, Response, WebSocket
from pydantic import BaseModel

from app.services.cc_bridge.discovery import discover_cc_sessions, capture_pane_preview
from app.services.cc_bridge.pty_relay import PtyRelay
from app.api.v1.deps import require_operator
from app.services.bridge_terminal_tokens import (
    TERMINAL_PROTOCOL_PREFIX,
    TerminalTokenStore,
    token_from_protocol_header,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_terminal_tokens = TerminalTokenStore()


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
async def get_terminal_token(
    response: Response,
    target: str = Query(min_length=1),
    purpose: Literal["readonly", "interactive"] = "readonly",
    x_deck_operator_token: str | None = Header(default=None),
):
    if purpose == "interactive":
        await require_operator(x_deck_operator_token)
    response.headers["Cache-Control"] = "no-store"
    return {"token": _terminal_tokens.issue(target, purpose)}


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


@router.websocket("/sessions/{target:path}/terminal")
async def session_terminal(
    websocket: WebSocket,
    target: str,
    mode: str = "readonly",
):
    """Attach to a CC tmux session via WebSocket terminal relay."""
    origin = websocket.headers.get("origin", "")
    if origin and not _is_same_origin(origin, websocket):
        await websocket.close(code=4403, reason="Invalid origin")
        return

    token = token_from_protocol_header(websocket.headers.get("sec-websocket-protocol", ""))
    if mode not in ("readonly", "interactive") or not _terminal_tokens.consume(token, target, mode):
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    read_only = mode != "interactive"
    relay = PtyRelay(target=target, read_only=read_only)
    await relay.run(websocket, subprotocol=f"{TERMINAL_PROTOCOL_PREFIX}{token}")


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
