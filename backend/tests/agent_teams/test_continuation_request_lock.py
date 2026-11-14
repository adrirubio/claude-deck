"""#922: a SQLite lock after a continuation request commits never turns the saved request into a 500."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, configure_sqlite_connection, get_db
from app.main import app
from app.models.database import (
    FactoryAuditEvent, GithubApprovalRequest, GithubAttemptScopeRevision, GithubWorkItem, MailMessage,
)
from app.services.github_approval_service import github_approval_service
from app.services import sqlite_busy_retry
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


# --- the context can change while the step waits: nothing stale is ever noticed ------------------------------------

async def _change_context(maker, item_id, change):
    async with maker() as other:
        if change == "nonce":
            await other.execute(update(GithubWorkItem).where(GithubWorkItem.id == item_id)
                                .values(dispatch_nonce="replacement-attempt"))
        elif change == "expired":
            await other.execute(update(GithubAttemptScopeRevision)
                                .values(expires_at=datetime.utcnow() - timedelta(seconds=1)))
        elif change == "decided":  # a status the notice step itself would still accept
            await other.execute(update(GithubApprovalRequest).values(status="approved"))
        else:  # superseded and cancelled
            await other.execute(update(GithubApprovalRequest).values(status="superseded"))
            await other.execute(update(GithubAttemptScopeRevision).values(status="cancelled"))
        await other.commit()


async def _assert_refused_without_a_notice(client, db, maker, monkeypatch, item, token, nudges, status):
    response = await _post(client, item, token)
    assert response.status_code == status, response.text
    async with maker() as fresh:
        approval = (await fresh.execute(select(GithubApprovalRequest))).scalars().one()
        assert await _count(fresh, MailMessage, MailMessage.delivery_key == f"github-approval:{approval.id}:request") == 0
    assert nudges == []  # and nobody was told about it


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["nonce", "expired", "cancelled", "decided"])
async def test_a_context_change_during_the_retry_wait_is_refused_before_any_notice(client, db, maker, monkeypatch, change):
    item, token = await _setup(db, monkeypatch)
    item_id = item.id  # a plain int: the helper's rollback expires the ORM row
    monkeypatch.setattr(github_approval_service, "ensure_continuation_request_message", HoldTheWriter(maker, times=1))
    nudges = []

    async def record_nudge(*args, **kwargs):
        nudges.append(1)

    monkeypatch.setattr(github_approval_service, "nudge_pending_continuation_leader", record_nudge)

    async def wait_while_the_context_changes(delay):
        await _change_context(maker, item_id, change)

    monkeypatch.setattr(sqlite_busy_retry, "asyncio", SimpleNamespace(sleep=wait_while_the_context_changes))
    await _assert_refused_without_a_notice(client, db, maker, monkeypatch, item, token, nudges, status=409)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["nonce", "expired"])
async def test_a_context_change_while_the_lock_is_held_is_refused_before_any_notice(client, db, maker, monkeypatch, change):
    item, token = await _setup(db, monkeypatch)
    item_id = item.id
    hold = HoldTheWriter(maker, times=1)

    async def change_after_the_failed_attempt(db_, item_, approval, revision):
        try:
            return await hold(db_, item_, approval, revision)
        except OperationalError:
            await _change_context(maker, item_id, change)  # committed before the helper prepares
            raise

    monkeypatch.setattr(github_approval_service, "ensure_continuation_request_message", change_after_the_failed_attempt)
    nudges = []

    async def record_nudge(*args, **kwargs):
        nudges.append(1)

    monkeypatch.setattr(github_approval_service, "nudge_pending_continuation_leader", record_nudge)
    await _assert_refused_without_a_notice(client, db, maker, monkeypatch, item, token, nudges, status=409)


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
    def __init__(self, events):
        self.events = events

    async def rollback(self):
        self.events.append("rollback")


def _record_sleeps(monkeypatch, events):
    async def sleep(delay):
        events.append("wait")

    monkeypatch.setattr(sqlite_busy_retry, "asyncio", SimpleNamespace(sleep=sleep))


@pytest.mark.asyncio
async def test_the_helper_prepares_after_the_wait_and_before_every_retry_not_before_the_first_attempt(monkeypatch):
    events, outcomes = [], [_busy(), _busy(), "done"]
    _record_sleeps(monkeypatch, events)

    async def step():
        events.append("step")
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def prepare():
        events.append("prepare")

    assert await retry_when_busy(_Session(events), step, route="/r", prepare=prepare) == "done"
    assert events == ["step", "rollback", "wait", "prepare", "step", "rollback", "wait", "prepare", "step"]


@pytest.mark.asyncio
async def test_the_helper_gives_up_after_its_attempts_and_prepares_only_for_the_retries(monkeypatch):
    events = []
    _record_sleeps(monkeypatch, events)

    async def always_busy():
        events.append("step")
        raise _busy()

    async def prepare():
        events.append("prepare")

    with pytest.raises(SqliteBusyExhausted):
        await retry_when_busy(_Session(events), always_busy, route="/r", attempts=3, prepare=prepare)
    assert events.count("step") == 3 and events.count("prepare") == 2 and events.count("rollback") == 3
    assert events[-1] == "rollback"  # no wait and no further preparation after the last attempt


@pytest.mark.asyncio
async def test_a_refusal_raised_while_preparing_is_not_retried_and_the_step_never_runs(monkeypatch):
    events, calls = [], []
    _record_sleeps(monkeypatch, events)

    async def step():
        calls.append(1)
        raise _busy()

    async def prepare():
        raise ValueError("the request is no longer pending")

    with pytest.raises(ValueError):
        await retry_when_busy(_Session(events), step, route="/r", prepare=prepare)
    assert calls == [1]  # only the first attempt ran; the retry was refused before its step


def _not_busy_database_error():
    other = sqlite3.OperationalError("no such table: mail_messages")
    other.sqlite_errorcode = 1
    return OperationalError("INSERT INTO mail_messages", {}, other)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("not a lock"), _not_busy_database_error()])
async def test_the_helper_does_not_retry_an_error_that_is_not_busy(error):
    events, calls = [], []

    async def failing():
        calls.append(1)
        raise error

    with pytest.raises(type(error)):
        await retry_when_busy(_Session(events), failing, route="/r", delay=0)
    assert calls == [1] and events == []


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
