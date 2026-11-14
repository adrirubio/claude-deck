"""#922: a SQLite lock after a continuation request commits never turns the saved request into a 500."""
from __future__ import annotations

import asyncio
import logging
import sqlite3

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, configure_sqlite_connection, get_db
from app.main import app
from app.models.database import FactoryAuditEvent, GithubApprovalRequest, GithubAttemptScopeRevision, MailMessage
from app.services.github_approval_service import github_approval_service
from app.services.sqlite_busy_retry import SqliteBusyExhausted, is_sqlite_busy, retry_when_busy
from tests.agent_mail.test_api import (  # noqa: F401  (the route's fixtures and helpers, and its autouse session binding)
    _continuation_approval_fixture, _continuation_request_body, _stub_continuation_github, live_slot_session_bindings,
)

REAL_ENSURE = github_approval_service.ensure_continuation_request_message  # before any test patches it
BUSY_MS = 150  # short, so a held lock turns into a real 'database is locked' quickly
URL = "/api/v1/agent-teams/github-work-items/{}/continuation-requests"


def _busy(code=5, name="SQLITE_BUSY"):
    """A SQLAlchemy OperationalError that carries what SQLite itself puts on a busy or locked error."""
    original = sqlite3.OperationalError("database is locked")
    original.sqlite_errorcode, original.sqlite_errorname = code, name
    return OperationalError("INSERT INTO mail_messages", {}, original)


@pytest_asyncio.fixture
async def maker(tmp_path):
    """A file-backed database with the app's own pragma function, so locks between connections are real."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/lock.db")

    @event.listens_for(engine.sync_engine, "connect")
    def pragma(dbapi_conn, _):
        configure_sqlite_connection(dbapi_conn, busy_timeout_ms=BUSY_MS)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(maker):
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "test-director-key")

    async def override():
        yield db

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


class HoldTheWriter:
    """Wraps the notice step: for the first ``times`` calls another connection holds the write lock."""

    def __init__(self, maker, times):
        self.maker, self.times, self.calls = maker, times, 0
        self.real = REAL_ENSURE

    async def __call__(self, db, item, approval, revision):
        self.calls += 1
        if self.calls > self.times:
            return await self.real(db, item, approval, revision)
        async with self.maker() as other:
            await other.execute(text("BEGIN IMMEDIATE"))
            try:
                return await self.real(db, item, approval, revision)  # its INSERT waits BUSY_MS, then really fails
            finally:
                await other.rollback()


async def _setup(db, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _scope, members, tokens, _workspace = await _continuation_approval_fixture(db)
    _stub_continuation_github(monkeypatch)
    return item, tokens[1]


async def _post(client, item, token):
    return await client.post(URL.format(item.id), headers={"X-Synth-City-Session-Token": token},
                             json=_continuation_request_body(item))


async def _count(db, model, *conditions):
    return await db.scalar(select(func.count()).select_from(model).where(*conditions))


async def _notice_events(db):
    rows = (await db.execute(select(FactoryAuditEvent).where(
        FactoryAuditEvent.event_kind == "continuation_request_notification"))).scalars().all()
    return sorted(row.action_outcome for row in rows)


@pytest.mark.asyncio
async def test_a_busy_notice_is_retried_and_the_saved_request_stands(client, db, maker, monkeypatch):
    item, token = await _setup(db, monkeypatch)
    hold = HoldTheWriter(maker, times=1)
    monkeypatch.setattr(github_approval_service, "ensure_continuation_request_message", hold)
    response = await _post(client, item, token)
    assert response.status_code == 200 and hold.calls == 2
    approval_id = response.json()["approval"]["id"]
    approval = await db.get(GithubApprovalRequest, approval_id, populate_existing=True)
    assert approval.request_message_id is not None
    assert await _count(db, GithubApprovalRequest) == 1
    assert await _count(db, MailMessage, MailMessage.delivery_key == f"github-approval:{approval_id}:request") == 1
    assert await _notice_events(db) == ["applied"]


@pytest.mark.asyncio
async def test_a_notice_still_busy_after_every_attempt_is_a_503_with_the_request_saved(client, db, maker, monkeypatch):
    item, token = await _setup(db, monkeypatch)
    hold = HoldTheWriter(maker, times=99)
    monkeypatch.setattr(github_approval_service, "ensure_continuation_request_message", hold)
    response = await _post(client, item, token)
    assert response.status_code == 503 and response.json()["detail"] == "database_busy_request_saved"
    assert int(response.headers["retry-after"]) >= 1
    assert hold.calls == 3  # the attempts, no more
    assert await _count(db, GithubApprovalRequest) == 1 and await _count(db, GithubAttemptScopeRevision) == 1
    approval = (await db.execute(select(GithubApprovalRequest))).scalars().one()
    assert approval.status == "pending" and approval.request_message_id is None  # saved, notice not settled
    assert await _count(db, MailMessage, MailMessage.delivery_key == f"github-approval:{approval.id}:request") == 0
    assert await _notice_events(db) == ["uncertain"]


@pytest.mark.asyncio
async def test_the_same_request_after_a_busy_failure_returns_the_saved_request_without_duplicates(client, db, maker, monkeypatch):
    item, token = await _setup(db, monkeypatch)
    monkeypatch.setattr(github_approval_service, "ensure_continuation_request_message", HoldTheWriter(maker, times=99))
    failed = await _post(client, item, token)
    assert failed.status_code == 503
    monkeypatch.setattr(github_approval_service, "ensure_continuation_request_message", HoldTheWriter(maker, times=0))
    retried = await _post(client, item, token)
    assert retried.status_code == 200
    saved = (await db.execute(select(GithubApprovalRequest))).scalars().one()  # one request, still
    assert retried.json()["approval"]["id"] == saved.id
    assert await _count(db, GithubAttemptScopeRevision) == 1
    await db.refresh(saved)
    assert saved.request_message_id is not None
    assert await _count(db, MailMessage, MailMessage.delivery_key == f"github-approval:{saved.id}:request") == 1
    assert await _notice_events(db) == ["applied", "uncertain"]  # the earlier uncertain fact is kept


@pytest.mark.asyncio
async def test_a_failure_that_is_not_a_lock_is_not_retried_and_still_raises(client, db, monkeypatch):
    item, token = await _setup(db, monkeypatch)
    calls = []

    async def broken(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError("the notice failed for another reason")

    monkeypatch.setattr(github_approval_service, "ensure_continuation_request_message", broken)
    with pytest.raises(RuntimeError):
        await _post(client, item, token)
    assert calls == [1]
    assert await _notice_events(db) == ["uncertain"]
    assert await _count(db, GithubApprovalRequest) == 1


@pytest.mark.asyncio
async def test_a_lock_error_before_the_request_commits_is_not_swallowed(client, db, monkeypatch):
    item, token = await _setup(db, monkeypatch)

    async def locked_before_the_commit(*_args, **_kwargs):
        raise _busy()

    monkeypatch.setattr(github_approval_service, "create_continuation_request", locked_before_the_commit)
    with pytest.raises(OperationalError):
        await _post(client, item, token)  # no 503: nothing was saved, so there is nothing to say was saved
    assert await _count(db, GithubApprovalRequest) == 0


@pytest.mark.asyncio
async def test_a_busy_nudge_after_the_notice_is_saved_is_logged_and_not_retried(client, db, monkeypatch, caplog):
    item, token = await _setup(db, monkeypatch)
    nudges = []

    async def busy_nudge(*_args, **_kwargs):
        nudges.append(1)
        raise _busy()

    monkeypatch.setattr(github_approval_service, "nudge_pending_continuation_leader", busy_nudge)
    with caplog.at_level(logging.WARNING):
        response = await _post(client, item, token)
    assert response.status_code == 200 and nudges == [1]  # the request and its notice are saved; the nudge is advisory
    assert any("continuation-requests" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    saved = (await db.execute(select(GithubApprovalRequest))).scalars().one()
    assert saved.request_message_id is not None


# --- the helper --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code", [5, 6, 261, 517, 262])  # BUSY, LOCKED, BUSY_RECOVERY, BUSY_SNAPSHOT, LOCKED_SHAREDCACHE
def test_every_busy_or_locked_code_is_recognized(code):
    assert is_sqlite_busy(_busy(code))


def test_other_errors_are_not_busy():
    other = sqlite3.OperationalError("no such table")
    other.sqlite_errorcode = 1
    assert not is_sqlite_busy(OperationalError("SELECT", {}, other))
    assert not is_sqlite_busy(RuntimeError("database is locked"))  # not a database error at all


class _Session:
    def __init__(self):
        self.rollbacks, self.refreshed = 0, []

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, row):
        self.refreshed.append(row)


@pytest.mark.asyncio
async def test_the_helper_retries_a_busy_step_rolls_back_and_reloads_each_time():
    session, outcomes = _Session(), [_busy(), _busy(), "done"]

    async def step():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert await retry_when_busy(session, step, route="/r", delay=0, reload=("item", "request")) == "done"
    assert session.rollbacks == 2 and session.refreshed == ["item", "request"] * 2


@pytest.mark.asyncio
async def test_the_helper_gives_up_after_its_attempts_and_leaves_the_session_usable():
    session, calls = _Session(), []

    async def always_busy():
        calls.append(1)
        raise _busy()

    with pytest.raises(SqliteBusyExhausted):
        await retry_when_busy(session, always_busy, route="/r", attempts=3, delay=0, reload=("row",))
    assert len(calls) == 3 and session.rollbacks == 3 and session.refreshed == ["row"] * 3


def _not_busy_database_error():
    other = sqlite3.OperationalError("no such table: mail_messages")
    other.sqlite_errorcode = 1
    return OperationalError("INSERT INTO mail_messages", {}, other)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("not a lock"), _not_busy_database_error()])
async def test_the_helper_does_not_retry_an_error_that_is_not_busy(error):
    session, calls = _Session(), []

    async def failing():
        calls.append(1)
        raise error

    with pytest.raises(type(error)):
        await retry_when_busy(session, failing, route="/r", delay=0)
    assert calls == [1] and session.rollbacks == 0


# --- the pragma: a second writer waits instead of failing ----------------------------------------------------------

async def _two_writers(tmp_path, busy_ms):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/writers.db")

    @event.listens_for(engine.sync_engine, "connect")
    def pragma(dbapi_conn, _):
        configure_sqlite_connection(dbapi_conn, busy_timeout_ms=busy_ms)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (n INTEGER)"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    first_has_the_lock = asyncio.Event()

    async def first():
        async with maker() as session:
            await session.execute(text("INSERT INTO t VALUES (1)"))
            first_has_the_lock.set()
            await asyncio.sleep(0.4)
            await session.commit()

    async def second():
        await first_has_the_lock.wait()
        async with maker() as session:
            await session.execute(text("INSERT INTO t VALUES (2)"))
            await session.commit()

    try:
        await asyncio.gather(first(), second())
        async with maker() as session:
            return sorted((await session.execute(text("SELECT n FROM t"))).scalars().all())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_second_concurrent_writer_waits_for_the_first_and_succeeds(tmp_path):
    assert await _two_writers(tmp_path, busy_ms=3000) == [1, 2]


@pytest.mark.asyncio
async def test_without_the_wait_the_second_writer_fails_with_database_is_locked(tmp_path):
    with pytest.raises(OperationalError, match="database is locked"):
        await _two_writers(tmp_path, busy_ms=0)


# --- the log names the route; direct callers and FastAPI injection both work --------------------------------------

@pytest.mark.asyncio
async def test_get_db_names_the_route_when_fastapi_injects_the_request(caplog):
    small = FastAPI()

    @small.post("/lock-me")
    async def lock_me(db: AsyncSession = Depends(get_db)):
        raise _busy()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=small, raise_app_exceptions=False),
                                 base_url="http://test") as http:
        with caplog.at_level(logging.WARNING):
            response = await http.post("/lock-me")
    assert response.status_code == 500
    warning = [r.getMessage() for r in caplog.records if "database_operation_failed" in r.getMessage()]
    assert warning and "route=/lock-me" in warning[0] and "sqlite_code=5" in warning[0]


@pytest.mark.asyncio
async def test_get_db_still_works_when_called_directly_without_a_request(caplog):
    generator = get_db()
    session = await generator.__anext__()
    assert isinstance(session, AsyncSession)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(OperationalError):
            await generator.athrow(_busy())
    warning = [r.getMessage() for r in caplog.records if "database_operation_failed" in r.getMessage()]
    assert warning and "route=unknown" in warning[0]
