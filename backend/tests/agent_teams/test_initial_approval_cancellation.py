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


from app.services.github_initial_approval_recovery import cancel_stranded_initial_approval


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



async def cancel(f, request_id, reason="safe recovery"):
    async with f.maker() as db:
        return await cancel_stranded_initial_approval(db, work_item_id=f.item_id, request_id=request_id, dispatch_nonce=f.nonce, reason=reason)



@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["missing", "linked", "orphan"])
async def test_cancel_preserves_history_and_supersedes_mail(review_db, delivery):
    f = review_db
    request_id = await stranded(f, delivery)
    first = await cancel(f, request_id)
    second = await cancel(f, request_id)
    assert first.status == second.status == "superseded"
    assert first.superseded_at == second.superseded_at
    assert first.reason == "Operator cancelled initial approval: safe recovery"
    with pytest.raises(GithubApprovalError):
        await cancel(f, request_id, reason="different reason")
    async with f.maker() as db:
        item = await db.get(GithubWorkItem, f.item_id)
        assert item.dispatch_status == "escalated" and item.dispatch_nonce == f.nonce and item.approval_round_count == 1
        messages = (await db.scalars(select(MailMessage))).all()
        assert all(m.request_status == "superseded" for m in messages)
        assert len(messages) == (0 if delivery == "missing" else 1)



@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["nonce", "round", "status", "pr", "active", "ack", "lease", "orphan_lease", "decision", "mail_conflict"])
async def test_cancel_refuses_changed_authority(review_db, guard):
    f = review_db
    request_id = await stranded(f, "linked")
    async with f.maker() as db:
        item = await db.get(GithubWorkItem, f.item_id)
        approval = await db.get(GithubApprovalRequest, request_id)
        if guard == "nonce": item.dispatch_nonce = "other"
        elif guard == "round": item.approval_round_count = 2
        elif guard == "status": item.dispatch_status = "dispatched"
        elif guard == "pr": item.pr_number = 12
        elif guard == "active": item.active_scope_revision = 1
        elif guard == "ack": item.ack_received_at = datetime.utcnow()
        elif guard == "decision": approval.status = "approved"
        elif guard == "mail_conflict":
            root = await db.get(MailMessage, approval.request_message_id)
            root.body_markdown = "different"
            root.payload = {**root.payload, "summary": "different"}
        else:
            db.add(GithubWorkspace(scope_id=f.scope_id, path="/tmp/review-workspace", kind="worktree", lease_token="held", leased_item_id=f.item_id if guard == "lease" else None))
        await db.commit()
    with pytest.raises(GithubApprovalError):
        await cancel(f, request_id)
    async with f.maker() as db:
        assert (await db.get(GithubApprovalRequest, request_id)).status == ("approved" if guard == "decision" else "pending")
        assert (await db.scalar(select(MailMessage))).request_status == "pending"


@pytest.mark.asyncio
async def test_cancellation_requires_operator_and_explicit_confirmation(review_db):
    f = review_db
    request_id = await stranded(f)
    async def override():
        async with f.maker() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://review") as client:
            path = f"/api/v1/agent-teams/github-work-items/{f.item_id}/approval-requests/{request_id}/cancel"
            operator = {"X-Deck-Operator-Token": "review-operator"}
            body = {"cancel": True, "dispatch_nonce": f.nonce, "reason": "safe recovery"}
            assert (await client.post(path, json=body)).status_code == 401
            assert (await client.post(path, headers={"X-Deck-Session-Token": f.tokens[1]}, json=body)).status_code == 401
            assert (await client.post(path, headers=operator, json={**body, "cancel": False})).status_code == 422
            assert (await client.post(path, headers=operator, json={**body, "reason": "  "})).status_code == 400
            response = await client.post(path, headers=operator, json=body)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "superseded"
    finally:
        app.dependency_overrides.clear()



@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["decision", "lease", "nonce"])
async def test_cancel_cas_refuses_changes_after_preflight(review_db, monkeypatch, race):
    f = review_db
    request_id = await stranded(f, "linked")
    async with f.maker() as db:
        execute = db.execute
        injected = False
        async def inject(statement, *args, **kwargs):
            nonlocal injected
            if not injected and getattr(statement, "is_update", False) and statement.table.name == "github_work_items":
                injected = True
                async with f.maker() as other:
                    if race == "decision":
                        await other.execute(update(GithubApprovalRequest).where(GithubApprovalRequest.id == request_id).values(status="approved", decided_at=datetime.utcnow()))
                    elif race == "lease":
                        other.add(GithubWorkspace(scope_id=f.scope_id, path="/tmp/raced-workspace", kind="worktree", leased_item_id=f.item_id, lease_token="held"))
                    else:
                        await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == f.item_id).values(dispatch_nonce="changed"))
                    await other.commit()
            return await execute(statement, *args, **kwargs)
        monkeypatch.setattr(db, "execute", inject)
        with pytest.raises(GithubApprovalError):
            await cancel_stranded_initial_approval(db, work_item_id=f.item_id, request_id=request_id, dispatch_nonce=f.nonce, reason="safe recovery")
        await db.rollback()
    async with f.maker() as db:
        assert (await db.get(GithubApprovalRequest, request_id)).status == ("approved" if race == "decision" else "pending")
        assert (await db.scalar(select(MailMessage))).request_status == "pending"
