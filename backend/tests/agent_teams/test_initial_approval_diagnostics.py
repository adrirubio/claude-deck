"""Independent review regressions using disposable, file-backed SQLite."""
import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import agent_mail
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import GithubApprovalRequest, GithubWorkItem, GithubWorkspace, MailAgentSession, MailMessage, MailReceipt
from app.models.schemas import MailApprovalRequestCreate
from app.services.agent_mail_service import agent_mail_service
from app.services.github_approval_service import GithubApprovalError, github_approval_service
from app.utils import peer_process
from tests.agent_mail.test_api import _dispatch_approval_fixture




@pytest_asyncio.fixture
async def review_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'review.db'}", connect_args={"timeout": .02})
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "operator_token", "review-operator")
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda *_args: True)
    async def no_wake(*_args, **_kwargs):
        pass
    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", no_wake)
    async with maker() as db:
        item, members, tokens = await _dispatch_approval_fixture(db)
        owner_session = await db.scalar(select(MailAgentSession).where(MailAgentSession.member_id == members[1].id))
        fixture = SimpleNamespace(maker=maker, item_id=item.id, nonce=item.dispatch_nonce, owner_id=members[1].id,
                                  leader_id=members[0].id, session_id=owner_session.id, tokens=tokens, scope_id=item.scope_id)
    yield fixture
    await engine.dispose()



async def submit(f, summary="bounded", db=None):
    if db is None:
        async with f.maker() as db:
            return await submit(f, summary, db)
    session = await db.get(MailAgentSession, f.session_id)
    return await agent_mail.request_work_item_approval(MailApprovalRequestCreate(work_item_id=f.item_id, dispatch_nonce=f.nonce, summary=summary), session, db)



async def counts(f):
    async with f.maker() as db:
        return tuple([await db.scalar(select(func.count()).select_from(model)) for model in (GithubApprovalRequest, MailMessage, MailReceipt)])



def busy(code=sqlite3.SQLITE_BUSY):
    original = sqlite3.OperationalError("database is locked")
    original.sqlite_errorcode = code
    original.sqlite_errorname = "SQLITE_BUSY"
    return OperationalError("INSERT INTO mail_messages", {"secret": "private-body"}, original)



async def stranded(f, delivery="missing"):
    if delivery != "missing":
        response = await submit(f)
        request_id = response.id
    async with f.maker() as db:
        item = await db.get(GithubWorkItem, f.item_id)
        if delivery == "missing":
            approval, _ = await github_approval_service.create_initial_request(db, item, authenticated_owner_member_id=f.owner_id, summary="bounded")
            request_id = approval.id
        else:
            approval = await db.get(GithubApprovalRequest, request_id)
            if delivery == "orphan":
                approval.request_message_id = None
        item.dispatch_status = "escalated"
        item.escalation_reason = "plan_blocked"
        await db.commit()
    return request_id



@pytest.mark.asyncio
async def test_database_error_diagnostics_do_not_log_sql_or_parameters(review_db, monkeypatch, caplog):
    import app.database as database
    monkeypatch.setattr(database, "AsyncSessionLocal", review_db.maker)
    dep = database.get_db()
    await anext(dep)
    error = busy()
    with pytest.raises(OperationalError):
        await dep.athrow(error)
    assert "sqlite_code=5" in caplog.text and "operation=INSERT" in caplog.text
    assert "private-body" not in caplog.text and "mail_messages" not in caplog.text
    assert database.engine.sync_engine.hide_parameters is True


@pytest.mark.asyncio
async def test_history_is_authenticated_bounded_and_reports_delivery(review_db):
    from app.api.v1.agent_teams import _work_item_response
    from app.models.database import TeamGithubScope
    from app.models.schemas import GithubApprovalRequestResponse
    f = review_db
    request_id = await stranded(f)
    async with f.maker() as db:
        item = await db.get(GithubWorkItem, f.item_id)
        scope = await db.get(TeamGithubScope, f.scope_id)
        approval = await db.get(GithubApprovalRequest, request_id)
        projected = _work_item_response(item, scope, pending_approval=approval)
        assert projected.pending_approval_delivery_status == "delivery_pending"
        assert projected.pending_approval_request_message_id is None
        approval.request_message_id = 42
        projected = _work_item_response(item, scope, pending_approval=approval)
        assert projected.pending_approval_delivery_status == "linked"
        assert projected.pending_approval_request_message_id == 42
        await db.rollback()
    async def override():
        async with f.maker() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://review") as client:
            path = f"/api/v1/agent-teams/github-work-items/{f.item_id}/approval-requests"
            operator = {"X-Deck-Operator-Token": "review-operator"}
            member = {"X-Deck-Session-Token": f.tokens[1]}
            assert (await client.get(path)).status_code == 401
            history = await client.get(path, headers=member)
            assert history.status_code == 200, history.text
            assert history.headers["cache-control"] == "no-store"
            row = history.json()[0]
            assert row["request_delivery_status"] == "delivery_pending"
            assert (await client.get(path, headers=operator, params={"before_id": request_id})).json() == []
            for limit in [0, 201]:
                assert (await client.get(path, headers=operator, params={"limit": limit})).status_code == 422
            for status, message_id, expected in [("pending", 42, "linked"), ("approved", None, "not_pending"), ("superseded", 42, "not_pending")]:
                response = GithubApprovalRequestResponse(**{**row, "status": status, "request_message_id": message_id})
                assert response.model_dump()["request_delivery_status"] == expected
            async with f.maker() as db:
                await db.execute(update(MailAgentSession).where(MailAgentSession.id == f.session_id).values(team_preset_id=999))
                await db.commit()
            assert (await client.get(path, headers=member)).status_code == 403
    finally:
        app.dependency_overrides.clear()
