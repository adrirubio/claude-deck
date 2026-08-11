"""Agent Mail endpoints: team roster, messages, agent registration, hooks, install."""
import logging
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.database import MailTeamMember
from app.models.schemas import (
    AgentMailInstallStatus,
    AgentMailSnippets,
    MailAgentRegisterRequest,
    MailAgentRegisterResponse,
    MailInboxResponse,
    MailMemberResponse,
    MailMemberUpdate,
    MailMessageCreate,
    MailMessageResponse,
    MailThreadResponse,
    TeamListResponse,
)
from app.services import agent_mail_install_service
from app.services.agent_mail_service import agent_mail_service
from app.utils import peer_process

logger = logging.getLogger(__name__)

router = APIRouter()


def resolve_request_pane(http_request: Request) -> Optional[peer_process.PeerPane]:
    """Resolve the calling pane from the live connection."""
    client = http_request.client
    if client is None:
        return None
    local_port = http_request.scope.get("server", (None, None))[1]
    return peer_process.resolve_peer_pane(client.host, client.port, local_port=local_port)


@router.get("/team", response_model=TeamListResponse)
async def get_team(sync: bool = True, db: AsyncSession = Depends(get_db)):
    """Team roster with sessions and inbox counts."""
    if sync:
        await agent_mail_service.sync_observed_sessions(db)
    return TeamListResponse(members=await agent_mail_service.list_team(db))


@router.patch("/members/{member_id}", response_model=MailMemberResponse)
async def update_member(
    member_id: int,
    update: MailMemberUpdate,
    db: AsyncSession = Depends(get_db),
):
    member = await db.get(MailTeamMember, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if update.display_name is not None:
        member.display_name = update.display_name.strip() or member.display_name
    if update.role is not None:
        member.role = update.role.strip() or None
    if update.charter is not None:
        member.charter = update.charter.strip() or None
    member.updated_at = datetime.utcnow()
    await db.commit()
    members = await agent_mail_service.list_team(db)
    found = next((candidate for candidate in members if candidate.id == member_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return found


@router.post("/messages", response_model=MailMessageResponse)
async def send_message(request: MailMessageCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_mail_service.send_message(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/messages", response_model=list[MailMessageResponse])
async def list_messages(db: AsyncSession = Depends(get_db)):
    return await agent_mail_service.list_root_messages(db)


@router.get("/messages/{message_id}/thread", response_model=MailThreadResponse)
async def get_thread(
    message_id: int,
    member_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_mail_service.get_thread(db, message_id, for_member_id=member_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/messages/{message_id}/read")
async def mark_read(
    message_id: int,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    await agent_mail_service.mark_read(db, message_id, int(body["member_id"]))
    return {"ok": True}


@router.post("/messages/{message_id}/ack")
async def ack_message(
    message_id: int,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    await agent_mail_service.ack_message(db, message_id, int(body["member_id"]))
    return {"ok": True}


@router.post("/members/{member_id}/queue-inbox-check")
async def queue_inbox_check(member_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await agent_mail_service.queue_inbox_check(db, member_id)
        return {"ok": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent/register", response_model=MailAgentRegisterResponse)
async def register_agent(
    http_request: Request,
    request: MailAgentRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    existing = await agent_mail_service.peek_session_by_key(db, request.session_key)
    hashless_rebind = existing is not None and existing.capability_token_hash is None
    if hashless_rebind and settings.mail_capability_tokens_required:
        raise HTTPException(status_code=409, detail="token_required_for_rebind")

    claims_team_context = request.team_preset_id is not None or request.team_slot_id is not None
    pane = resolve_request_pane(http_request)

    binding = None
    if pane is None:
        if claims_team_context and settings.mail_capability_tokens_required:
            raise HTTPException(status_code=409, detail="bind_unverifiable")
    else:
        binding = await agent_mail_service.resolve_pane_binding(db, pane)
        if binding is None and claims_team_context:
            raise HTTPException(status_code=409, detail="bind_pending")

    derived_slot_id = binding.slot_id if binding is not None else None
    if (
        request.team_slot_id is not None
        and derived_slot_id is not None
        and request.team_slot_id != derived_slot_id
    ):
        raise HTTPException(status_code=403, detail="slot_claim_mismatch")

    request = request.model_copy(
        update={
            "team_slot_id": derived_slot_id,
            "team_preset_id": binding.preset_id if binding is not None else None,
        }
    )
    member, session = await agent_mail_service.register_session(db, request)
    if pane is not None:
        session.bound_pane_pid = pane.pane_pid
        session.bound_pane_proc_start = pane.pane_proc_start
        await db.commit()
    capability_token = (
        None if hashless_rebind else await agent_mail_service.ensure_capability_token(db, session)
    )
    members = await agent_mail_service.list_team(db)
    member_resp = next(candidate for candidate in members if candidate.id == member.id)
    session_resp = next(
        candidate for candidate in member_resp.sessions if candidate.session_key == session.session_key
    )
    return MailAgentRegisterResponse(
        member=member_resp,
        session=session_resp,
        capability_token=capability_token,
    )


@router.get("/agent/inbox", response_model=MailInboxResponse)
async def agent_inbox(
    member_id: int,
    unread_only: bool = False,
    mark_read: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    return await agent_mail_service.get_inbox(
        db,
        member_id,
        unread_only=unread_only,
        mark_read=mark_read,
        limit=limit,
        refresh_mcp_session=True,
    )


def _hook_provider(payload: dict) -> str:
    provider = str(payload.get("provider") or "claude-code")
    return provider if provider in {"claude-code", "codex-cli", "copilot-cli", "opencode-cli"} else "unknown"


def _hook_session_key(payload: dict) -> Optional[str]:
    session_id = payload.get("session_id")
    if not session_id:
        return None
    provider = _hook_provider(payload)
    prefix_by_provider = {
        "claude-code": "cc",
        "codex-cli": "codex",
        "copilot-cli": "copilot",
        "opencode-cli": "opencode",
    }
    prefix = prefix_by_provider.get(provider, "unknown")
    team_slot_id = _payload_int(payload, "team_slot_id")
    if team_slot_id is not None:
        return f"{prefix}:{session_id}:team-slot:{team_slot_id}"
    return f"{prefix}:{session_id}"


def _payload_int(payload: dict, key: str) -> Optional[int]:
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _register_from_hook(db: AsyncSession, payload: dict):
    session_key = _hook_session_key(payload)
    cwd = payload.get("cwd")
    if not session_key or not cwd:
        return None, None
    return await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="hook",
            provider=_hook_provider(payload),
            cwd=cwd,
            session_key=session_key,
            pid=payload.get("pid"),
            team_preset_id=_payload_int(payload, "team_preset_id"),
            team_slot_id=_payload_int(payload, "team_slot_id"),
        ),
    )


@router.post("/hooks/session-start")
async def hook_session_start(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        member, session = await _register_from_hook(db, payload)
        if member is None:
            return {}
        context = await agent_mail_service.build_session_start_context(
            db,
            member.id,
            session.session_key if session is not None else None,
        )
        if not context:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
    except Exception as exc:
        logger.warning("session-start hook failed: %s", exc)
        return {}


@router.post("/hooks/user-prompt-submit")
async def hook_user_prompt_submit(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        session_key = _hook_session_key(payload)
        if session_key is None:
            return {}
        session = await agent_mail_service.heartbeat_session(db, session_key)
        if session is None:
            _, session = await _register_from_hook(db, payload)
            if session is None:
                return {}
        context = await agent_mail_service.build_prompt_submit_context(db, session.member_id)
        if context is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
    except Exception as exc:
        logger.warning("user-prompt-submit hook failed: %s", exc)
        return {}


@router.post("/hooks/session-end")
async def hook_session_end(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        session_key = _hook_session_key(payload)
        if session_key is not None:
            await agent_mail_service.mark_session_offline(db, session_key)
    except Exception as exc:
        logger.warning("session-end hook failed: %s", exc)
    return {}


@router.post("/hooks/post-tool-use")
async def hook_post_tool_use(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        session_key = _hook_session_key(payload)
        if session_key is None:
            return {}
        activity = None
        tool_input = payload.get("tool_input") or {}
        file_path = tool_input.get("file_path")
        if file_path:
            activity = f"edited {os.path.basename(str(file_path))}"
        session = await agent_mail_service.heartbeat_session(db, session_key, activity=activity)
        if session is None:
            await _register_from_hook(db, payload)
            if activity:
                await agent_mail_service.heartbeat_session(db, session_key, activity=activity)
    except Exception as exc:
        logger.warning("post-tool-use hook failed: %s", exc)
    return {}


def _require_confirmed(body: dict[str, Any] | None) -> None:
    if not body or not body.get("confirmed"):
        raise HTTPException(status_code=400, detail='Pass {"confirmed": true} to mutate config')


@router.get("/install/status", response_model=AgentMailInstallStatus)
async def install_status():
    return await agent_mail_install_service.get_install_status()


@router.post("/install/claude-code/apply", response_model=AgentMailInstallStatus)
async def install_claude_code(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    return await agent_mail_install_service.apply_claude_code_install(db)


@router.post("/install/claude-code/uninstall", response_model=AgentMailInstallStatus)
async def uninstall_claude_code(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    return await agent_mail_install_service.uninstall_claude_code(db)


@router.post("/install/codex/apply", response_model=AgentMailInstallStatus)
async def install_codex(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    try:
        return await agent_mail_install_service.apply_codex_install(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/install/codex/uninstall", response_model=AgentMailInstallStatus)
async def uninstall_codex(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    return await agent_mail_install_service.uninstall_codex(db)


@router.post("/install/copilot/apply", response_model=AgentMailInstallStatus)
async def install_copilot(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    try:
        return await agent_mail_install_service.apply_copilot_install(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/install/copilot/uninstall", response_model=AgentMailInstallStatus)
async def uninstall_copilot(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    return await agent_mail_install_service.uninstall_copilot(db)


@router.post("/install/opencode/apply", response_model=AgentMailInstallStatus)
async def install_opencode(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    try:
        return await agent_mail_install_service.apply_opencode_install(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/install/opencode/uninstall", response_model=AgentMailInstallStatus)
async def uninstall_opencode(
    body: dict[str, Any] | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_confirmed(body)
    return await agent_mail_install_service.uninstall_opencode(db)


@router.get("/install/snippets", response_model=AgentMailSnippets)
async def install_snippets():
    return agent_mail_install_service.get_snippets()
