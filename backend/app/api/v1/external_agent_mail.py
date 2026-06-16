"""External local Agent Mail orchestration endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.database import MailExternalActor
from app.models.schemas import (
    ExternalAgentMailContextRequest,
    ExternalAgentMailHandoffRequest,
    ExternalAgentMailMessageRequest,
    ExternalAgentMailRequestStatus,
    ExternalAgentMailSendResponse,
    MailExternalActorCreate,
    MailExternalActorCreateResponse,
    MailExternalActorResponse,
    MailThreadResponse,
    TeamListResponse,
)
from app.services.external_agent_mail_service import (
    ExternalAgentMailAuthError,
    ExternalAgentMailRateLimitError,
    external_agent_mail_service,
)

router = APIRouter()


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    return token or None


def _is_loopback_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "test", "testclient"}


async def external_actor(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> MailExternalActor:
    try:
        return await external_agent_mail_service.authenticate_actor(
            db,
            _bearer_token(authorization),
        )
    except ExternalAgentMailAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _rate_limit_response(exc: ExternalAgentMailRateLimitError) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "external_agent_mail_rate_limited",
            "message": str(exc),
            "retry_after_seconds": exc.retry_after_seconds,
        },
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


@router.post("/actors", response_model=MailExternalActorCreateResponse)
async def create_external_actor(
    request: Request,
    actor_request: MailExternalActorCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create or rotate a local external actor token."""
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="External actor tokens can only be created locally")
    try:
        return await external_agent_mail_service.create_actor(db, actor_request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/actors/me", response_model=MailExternalActorResponse)
async def get_external_actor_me(actor: MailExternalActor = Depends(external_actor)):
    return external_agent_mail_service.actor_response(actor)


@router.get("/members", response_model=TeamListResponse)
async def list_external_agent_mail_members(
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    _ = actor
    return await external_agent_mail_service.list_members(db)


@router.post("/messages", response_model=ExternalAgentMailSendResponse)
async def send_external_agent_mail_message(
    request: ExternalAgentMailMessageRequest,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.send_direct_message(db, actor, request)
    except ExternalAgentMailRateLimitError as exc:
        raise _rate_limit_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/broadcasts", response_model=ExternalAgentMailSendResponse)
async def send_external_agent_mail_broadcast(
    request: ExternalAgentMailMessageRequest,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.send_broadcast(db, actor, request)
    except ExternalAgentMailRateLimitError as exc:
        raise _rate_limit_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/context-requests", response_model=ExternalAgentMailSendResponse)
async def send_external_agent_mail_context_request(
    request: ExternalAgentMailContextRequest,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.send_context_request(db, actor, request)
    except ExternalAgentMailRateLimitError as exc:
        raise _rate_limit_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/handoffs", response_model=ExternalAgentMailSendResponse)
async def send_external_agent_mail_handoff(
    request: ExternalAgentMailHandoffRequest,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.send_handoff(db, actor, request)
    except ExternalAgentMailRateLimitError as exc:
        raise _rate_limit_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/threads/{message_id}/replies", response_model=ExternalAgentMailSendResponse)
async def reply_external_agent_mail_thread(
    message_id: int,
    request: ExternalAgentMailMessageRequest,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.reply_in_thread(db, actor, message_id, request)
    except ExternalAgentMailRateLimitError as exc:
        raise _rate_limit_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/threads/{message_id}", response_model=MailThreadResponse)
async def get_external_agent_mail_thread(
    message_id: int,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.thread(db, actor, message_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/requests/{message_id}/status", response_model=ExternalAgentMailRequestStatus)
async def get_external_agent_mail_request_status(
    message_id: int,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.request_status(db, actor, message_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/requests/{message_id}/wait", response_model=ExternalAgentMailRequestStatus)
async def wait_external_agent_mail_request_status(
    message_id: int,
    timeout_seconds: int = 30,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await external_agent_mail_service.wait_for_request_status(
            db,
            actor,
            message_id,
            timeout_seconds,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/requests/{message_id}/ack", response_model=ExternalAgentMailRequestStatus)
async def ack_external_agent_mail_request(
    message_id: int,
    response: Response,
    actor: MailExternalActor = Depends(external_actor),
    db: AsyncSession = Depends(get_db),
):
    try:
        response.status_code = 200
        return await external_agent_mail_service.acknowledge_external_request(db, actor, message_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
