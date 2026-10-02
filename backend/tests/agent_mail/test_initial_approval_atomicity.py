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
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("boundary", ["before_mail", "after_mail", "commit"])
async def test_file_transaction_failure_leaves_no_partial_delivery(review_db, monkeypatch, legacy, boundary):
    f = review_db
    if legacy:
        async with f.maker() as db:
            item = await db.get(GithubWorkItem, f.item_id)
            await github_approval_service.create_initial_request(db, item, authenticated_owner_member_id=f.owner_id, summary="bounded")
    original = agent_mail_service.send_message
    async def fail(db, request, **kwargs):
        if boundary == "after_mail":
            await original(db, request, **kwargs)
        raise RuntimeError("injected delivery failure")
    async with f.maker() as db:
        if boundary == "commit":
            async def fail_commit():
                raise RuntimeError("injected commit failure")
            monkeypatch.setattr(db, "commit", fail_commit)
        else:
            monkeypatch.setattr(agent_mail_service, "send_message", fail)
        with pytest.raises(RuntimeError):
            await submit(f, db=db)
    assert await counts(f) == (int(legacy), 0, 0)
    if legacy:
        async with f.maker() as db:
            assert (await db.scalar(select(GithubApprovalRequest))).request_message_id is None



@pytest.mark.asyncio
@pytest.mark.parametrize("summaries", [("bounded", "bounded"), ("bounded", "different")])
async def test_file_concurrent_replays_converge(review_db, summaries):
    outcomes = await asyncio.gather(*(submit(review_db, s) for s in summaries), return_exceptions=True)
    successes = [o for o in outcomes if not isinstance(o, Exception)]
    assert len(successes) == (2 if summaries[0] == summaries[1] else 1), outcomes
    if len(successes) == 2:
        assert successes[0].id == successes[1].id
    else:
        failures = [o for o in outcomes if isinstance(o, Exception)]
        assert isinstance(failures[0], HTTPException) and failures[0].status_code == 409
    assert await counts(review_db) == (1, 1, 1)



@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["busy_once", "busy_twice", "not_busy", "wake"])
async def test_retry_and_wake_boundaries(review_db, monkeypatch, failure):
    calls = 0
    original = agent_mail_service.send_message
    async def send(db, request, **kwargs):
        nonlocal calls
        calls += 1
        await original(db, request, **kwargs)
        if failure == "busy_twice" or failure == "busy_once" and calls == 1:
            raise busy()
        if failure == "not_busy":
            raise busy(sqlite3.SQLITE_LOCKED)
        return await original(db, request, **kwargs)
    monkeypatch.setattr(agent_mail_service, "send_message", send)
    if failure == "wake":
        async def failed_wake(*_args, **_kwargs):
            raise busy()
        monkeypatch.setattr(agent_mail_service, "auto_nudge_members", failed_wake)
    if failure in {"busy_once", "wake"}:
        assert (await submit(review_db)).request_message_id is not None
        assert await counts(review_db) == (1, 1, 1)
    elif failure == "busy_twice":
        with pytest.raises(HTTPException) as error:
            await submit(review_db)
        assert error.value.status_code == 503
        assert error.value.headers == {"Retry-After": "1"}
        assert await counts(review_db) == (0, 0, 0)
    else:
        with pytest.raises(OperationalError):
            await submit(review_db)
        assert await counts(review_db) == (0, 0, 0)
    assert calls == (2 if failure.startswith("busy") else 1)



@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["closed_session", "nonce", "owner"])
async def test_busy_retry_rechecks_authority(review_db, monkeypatch, drift):
    f = review_db
    calls = 0
    async def failed_send(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise busy(sqlite3.SQLITE_BUSY_SNAPSHOT)
    async def change_during_backoff(_delay):
        async with f.maker() as other:
            if drift == "closed_session":
                await other.execute(update(MailAgentSession).where(MailAgentSession.id == f.session_id).values(closed_at=datetime.utcnow()))
            else:
                values = {"dispatch_nonce": "new-nonce"} if drift == "nonce" else {"owner_slot_id": None}
                await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == f.item_id).values(**values))
            await other.commit()
    monkeypatch.setattr(agent_mail_service, "send_message", failed_send)
    monkeypatch.setattr(agent_mail.asyncio, "sleep", change_during_backoff)
    with pytest.raises(HTTPException) as error:
        await submit(f)
    assert error.value.status_code in {401, 403, 409}
    assert calls == 1
    assert await counts(f) == (0, 0, 0)



@pytest.mark.asyncio
async def test_real_sqlite_writer_lock_retries_after_rollback(review_db, monkeypatch):
    f = review_db
    async with f.maker() as locker:
        await locker.execute(update(GithubWorkItem).where(GithubWorkItem.id == f.item_id).values(updated_at=datetime.utcnow()))
        backoffs = []
        async def release_lock(_delay):
            backoffs.append(True)
            await locker.rollback()
        monkeypatch.setattr(agent_mail.asyncio, "sleep", release_lock)
        response = await submit(f)
    assert backoffs == [True]
    assert response.request_message_id is not None
    assert await counts(f) == (1, 1, 1)
