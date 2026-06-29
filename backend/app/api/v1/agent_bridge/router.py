"""Agent Bridge endpoints: mixed provider session discovery and terminal access."""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.database import AgentTeamPreset, AgentTeamSlot
from app.services.agent_bridge.discovery import capture_pane_preview, discover_agent_sessions
from app.services.agent_bridge.pty_relay import PtyRelay
from app.services.agent_bridge.spawn import kill_session, spawn_session
from app.services.providers import get_provider
from app.services.providers.base import SpawnCommandOptions

logger = logging.getLogger(__name__)

router = APIRouter()

_tokens: dict[str, float] = {}
_TOKEN_TTL = 30


class SpawnRequest(BaseModel):
    provider: str = "claude-code"
    directory: str
    mode: Literal["plain", "worktree", "resume", "fork"] = "plain"
    worktree_name: str | None = None
    session_id: str | None = None
    project_folder: str | None = None
    skip_permissions: bool = False
    prompt: str | None = None
    model: str | None = None
    profile: str | None = None
    profile_v2: str | None = None
    sandbox: str | None = None
    approval_policy: str | None = None
    search: bool | None = None
    no_alt_screen: bool = False
    dangerously_bypass_approvals_and_sandbox: bool = False
    use_last: bool = False
    platform: str = "anthropic"
    aws_region: str | None = None
    aws_profile: str | None = None
    bedrock_model: str | None = None
    agent: str | None = None
    context_tier: str | None = None
    reasoning_effort: str | None = None
    plan: bool = False
    remote: bool | None = None
    allow_all: bool = False
    no_ask_user: bool = False


async def _enrich_team_sessions(
    sessions: list[dict[str, Any]],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    slot_ids = {
        int(session["team_slot_id"])
        for session in sessions
        if isinstance(session.get("team_slot_id"), int)
    }
    if not slot_ids:
        return sessions

    slots = {
        slot.id: slot
        for slot in (
            await db.execute(select(AgentTeamSlot).where(AgentTeamSlot.id.in_(slot_ids)))
        ).scalars().all()
    }
    preset_ids = {slot.preset_id for slot in slots.values()}
    presets = {
        preset.id: preset
        for preset in (
            await db.execute(select(AgentTeamPreset).where(AgentTeamPreset.id.in_(preset_ids)))
        ).scalars().all()
    } if preset_ids else {}

    enriched: list[dict[str, Any]] = []
    for session in sessions:
        updated = dict(session)
        slot_id = updated.get("team_slot_id")
        slot = slots.get(slot_id) if isinstance(slot_id, int) else None
        if slot is not None:
            preset = presets.get(slot.preset_id)
            updated.update(
                team_preset_id=slot.preset_id,
                team_preset_name=preset.name if preset is not None else updated.get("team_preset_name"),
                team_slot_name=slot.display_name,
                team_slot_role=slot.role,
                team_slot_charter=slot.charter,
                team_slot_color=slot.ui_color,
            )
        enriched.append(updated)
    return enriched


@router.get("/sessions")
async def list_sessions(
    provider: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        sessions = discover_agent_sessions(provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    sessions = await _enrich_team_sessions(sessions, db)
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{target:path}/preview")
def get_session_preview(target: str):
    content = capture_pane_preview(target)
    if not content:
        raise HTTPException(status_code=404, detail="Could not capture pane")
    return {"target": target, "content": content}


@router.get("/token")
async def get_terminal_token():
    now = time.time()
    expired = [token for token, issued_at in _tokens.items() if now - issued_at > _TOKEN_TTL]
    for token in expired:
        _tokens.pop(token, None)

    token = secrets.token_urlsafe(32)
    _tokens[token] = now
    return {"token": token}


def _is_same_origin(origin: str, websocket: WebSocket) -> bool:
    try:
        origin_host = urlparse(origin).netloc.lower()
    except ValueError:
        return False
    if not origin_host:
        return False

    request_host = (websocket.headers.get("host") or "").lower()
    if request_host and origin_host == request_host:
        return True
    return origin_host.split(":")[0] in {"localhost", "127.0.0.1", "[::1]"}


def _validate_token(token: str) -> bool:
    issued_at = _tokens.pop(token, None)
    return issued_at is not None and (time.time() - issued_at) <= _TOKEN_TTL


@router.websocket("/sessions/{target:path}/terminal")
async def session_terminal(
    websocket: WebSocket,
    target: str,
    token: str = "",
    mode: str = "readonly",
):
    origin = websocket.headers.get("origin", "")
    if origin and not _is_same_origin(origin, websocket):
        await websocket.close(code=4403, reason="Invalid origin")
        return

    if not _validate_token(token):
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    relay = PtyRelay(target=target, read_only=mode != "interactive")
    await relay.run(websocket)


@router.post("/sessions")
def spawn_session_endpoint(request: SpawnRequest):
    try:
        get_provider(request.provider)
        options = SpawnCommandOptions(
            directory=request.directory,
            mode=request.mode,
            worktree_name=request.worktree_name,
            session_id=request.session_id,
            project_folder=request.project_folder,
            skip_permissions=request.skip_permissions,
            prompt=request.prompt,
            model=request.model,
            profile=request.profile,
            profile_v2=request.profile_v2,
            sandbox=request.sandbox,
            approval_policy=request.approval_policy,
            search=request.search,
            no_alt_screen=request.no_alt_screen,
            dangerously_bypass_approvals_and_sandbox=request.dangerously_bypass_approvals_and_sandbox,
            use_last=request.use_last,
            platform=request.platform,
            aws_region=request.aws_region,
            aws_profile=request.aws_profile,
            bedrock_model=request.bedrock_model,
            agent=request.agent,
            context_tier=request.context_tier,
            reasoning_effort=request.reasoning_effort,
            plan=request.plan,
            remote=request.remote,
            allow_all=request.allow_all,
            no_ask_user=request.no_ask_user,
        )
        return spawn_session(request.provider, options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/sessions/{target}")
def kill_session_endpoint(target: str, cleanup_worktree: bool = False):
    return kill_session(session_name=target, cleanup_worktree=cleanup_worktree)
