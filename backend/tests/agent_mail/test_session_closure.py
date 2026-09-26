import hashlib
import asyncio
import io
import os
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db, _run_sqlite_compat_migrations
from app.main import app
from app.models.database import MailAgentSession, MailPaneLifecycle, MailTeamMember
from app.models.schemas import MailAgentRegisterRequest
from app.services.agent_mail_service import MailAuthorityError, agent_mail_service
from app.utils import peer_process


@pytest_asyncio.fixture
async def client(db):
    async def override():
        yield db
    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http_client:
            yield http_client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def registered(db, tmp_path):
    request = MailAgentRegisterRequest(source="mcp", provider="pi-cli", cwd=str(tmp_path), session_key="mcp:pi-close", pid=os.getpid())
    member, session = await agent_mail_service.register_session(db, request)
    token = await agent_mail_service.ensure_capability_token(db, session)
    return request, member, session, token


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("presented", [None, "wrong", "correct"])
@pytest.mark.asyncio
async def test_closed_key_never_registers_or_rebinds(client, db, registered, monkeypatch, enforce, presented):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", enforce)
    request, member, session, token = registered
    close = await client.post("/api/v1/agent-mail/agent/close", headers={"X-Deck-Session-Token": token})
    assert close.status_code == 200 and close.json()["closed"]
    headers = {} if presented is None else {"X-Deck-Session-Token": token if presented == "correct" else presented}
    response = await client.post("/api/v1/agent-mail/agent/register", json=request.model_dump(), headers=headers)
    assert response.status_code == 409
    await db.refresh(session)
    assert session.member_id == member.id and session.mailbox_status == "offline"
    assert session.closed_at is not None
    inbox = await client.get("/api/v1/agent-mail/agent/inbox", headers={"X-Deck-Session-Token": token})
    assert inbox.status_code == 401 and inbox.json()["detail"] == "session_token_closed"


@pytest.mark.asyncio
async def test_self_close_replay_is_private_and_heartbeats_cannot_reopen(client, db, registered):
    request, _, session, token = registered
    headers = {"X-Deck-Session-Token": token}
    assert (await client.post("/api/v1/agent-mail/agent/close", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/agent-mail/agent/close", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/agent-mail/agent/close")).status_code == 401
    await agent_mail_service.heartbeat_session(db, request.session_key)
    await agent_mail_service.heartbeat_member_mcp_session(db, session.member_id)
    await db.refresh(session)
    assert session.mailbox_status == "offline"
    assert agent_mail_service._effective_status(session, datetime.utcnow()) == "offline"
    with pytest.raises(MailAuthorityError):
        await agent_mail_service.register_session(db, request)


@pytest.mark.parametrize("liveness", [True, None, False])
@pytest.mark.asyncio
async def test_operator_retirement_exact_identity_and_admission_barrier(client, db, registered, monkeypatch, liveness):
    request, _, session, _ = registered
    session.bound_pane_pid = 54321
    session.bound_pane_proc_start = "111"
    await db.commit()
    monkeypatch.setattr(settings, "operator_token", "fixture-operator")
    monkeypatch.setattr(peer_process, "pane_is_alive_strict", lambda *_: liveness)
    payload = {"pane_pid": 54321, "pane_proc_start": "111"}
    assert (await client.post("/api/v1/agent-mail/sessions/retire-dead-pane", json=payload)).status_code == 401
    response = await client.post("/api/v1/agent-mail/sessions/retire-dead-pane", json=payload, headers={"X-Deck-Operator-Token": "fixture-operator"})
    await db.refresh(session)
    if liveness is not False:
        assert response.status_code == 409 and session.closed_at is None
        return
    assert response.status_code == 200 and response.json()["retired_count"] == 1
    assert session.closed_at is not None
    with pytest.raises(MailAuthorityError, match="pane_retired"):
        await agent_mail_service.register_session(db, request.model_copy(update={"session_key": "mcp:new"}), pane=peer_process.PeerPane(54321, "111", None, 99))
    new = await agent_mail_service.register_session(db, request.model_copy(update={"session_key": "mcp:replacement"}), pane=peer_process.PeerPane(54321, "112", None, 99))
    assert new[1].closed_at is None and new[1].bound_pane_proc_start == "112"


@pytest.mark.asyncio
async def test_register_row_appearing_after_initial_miss_is_guarded(db, tmp_path, monkeypatch):
    request = MailAgentRegisterRequest(source="mcp", provider="pi-cli", cwd=str(tmp_path), session_key="mcp:race")
    inserted = False
    async def interleave(database, payload):
        nonlocal inserted
        if not inserted:
            inserted = True
            member = MailTeamMember(identity_key="race", repo_id="race", repo_path=str(tmp_path), repo_name="race", display_name="race")
            database.add(member)
            await database.flush()
            database.add(MailAgentSession(member_id=member.id, source="mcp", provider="pi-cli", session_key=payload.session_key, mailbox_status="offline", closed_at=datetime.utcnow()))
            await database.commit()
        return None, None
    monkeypatch.setattr(agent_mail_service, "_infer_team_context_from_process", interleave)
    with pytest.raises(MailAuthorityError, match="session_token_closed"):
        await agent_mail_service.register_session(db, request)
    row = await db.scalar(select(MailAgentSession).where(MailAgentSession.session_key == request.session_key))
    assert row.mailbox_status == "offline" and row.pid is None


@pytest.mark.parametrize("error", [PermissionError(), OSError(), ValueError()])
def test_strict_liveness_refuses_unobservable_process(monkeypatch, error):
    import builtins
    def unavailable(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(builtins, "open", unavailable)
    assert peer_process.pane_is_alive_strict(42, "1") is None


def test_strict_liveness_distinguishes_missing_reused_and_malformed(monkeypatch):
    import builtins
    current = peer_process.read_proc_stat(os.getpid())
    assert peer_process.pane_is_alive_strict(os.getpid(), current[1]) is True
    assert peer_process.pane_is_alive_strict(os.getpid(), "0") is False
    assert peer_process.pane_is_alive_strict(2147483647, "0") is False
    monkeypatch.setattr(builtins, "open", lambda *_: io.StringIO("malformed"))
    assert peer_process.pane_is_alive_strict(42, "1") is None


@pytest.mark.asyncio
async def test_mint_close_race_is_a_structured_conflict(client, db, tmp_path, monkeypatch):
    original = agent_mail_service.ensure_capability_token
    async def close_before_mint(database, session):
        await database.execute(update(MailAgentSession).where(MailAgentSession.id == session.id).values(closed_at=datetime.utcnow(), mailbox_status="offline"))
        await database.commit()
        return await original(database, session)
    monkeypatch.setattr(agent_mail_service, "ensure_capability_token", close_before_mint)
    response = await client.post("/api/v1/agent-mail/agent/register", json={
        "source": "mcp", "provider": "pi-cli", "cwd": str(tmp_path), "session_key": "mcp:mint-race",
    })
    assert response.status_code == 409 and response.json()["detail"] == "session_token_closed"
    assert "capability_token" not in response.json()


@pytest.mark.asyncio
async def test_compat_closed_column_migration_is_repeatable_and_keeps_rows(db, registered):
    _, _, session, _ = registered
    session_id = session.id
    connection = await db.connection()
    await connection.execute(text("ALTER TABLE mail_agent_sessions DROP COLUMN closed_at"))
    await _run_sqlite_compat_migrations(connection)
    await _run_sqlite_compat_migrations(connection)
    row = (await connection.execute(text("SELECT id, closed_at FROM mail_agent_sessions WHERE id=:id"), {"id": session_id})).one()
    assert row == (session_id, None)


@pytest.mark.asyncio
async def test_closed_key_created_on_a_second_connection_cannot_be_resurrected(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    entered = asyncio.Event()
    resume = asyncio.Event()
    async def suspend(_db, _request):
        entered.set()
        await resume.wait()
        return None, None
    monkeypatch.setattr(agent_mail_service, "_infer_team_context_from_process", suspend)
    try:
        async with maker() as caller, maker() as competitor:
            request = MailAgentRegisterRequest(source="mcp", provider="pi-cli", cwd=str(tmp_path), session_key="mcp:second-connection")
            task = asyncio.create_task(agent_mail_service.register_session(caller, request))
            await asyncio.wait_for(entered.wait(), 2)
            member = MailTeamMember(identity_key="second", repo_id="second", repo_path=str(tmp_path), repo_name="second", display_name="second")
            competitor.add(member)
            await competitor.flush()
            closed = MailAgentSession(member_id=member.id, source="mcp", provider="pi-cli", session_key=request.session_key, mailbox_status="offline", closed_at=datetime.utcnow())
            competitor.add(closed)
            await competitor.commit()
            closed_id, member_id = closed.id, member.id
            resume.set()
            with pytest.raises(MailAuthorityError, match="session_token_closed"):
                await task
            await competitor.refresh(closed)
            assert closed.id == closed_id and closed.member_id == member_id
            assert closed.mailbox_status == "offline" and closed.pid is None
    finally:
        resume.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_retirement_serializes_with_inflight_pane_admission(tmp_path, monkeypatch):
    from app.api.v1.agent_mail import DeadPaneRetirement, retire_dead_pane

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pane-race.sqlite'}")
    async with engine.begin() as connection:
        await connection.execute(text("PRAGMA journal_mode=WAL"))
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    entered = asyncio.Event()
    resume = asyncio.Event()
    async def suspend(_db, _request):
        entered.set()
        await resume.wait()
        return None, None
    monkeypatch.setattr(agent_mail_service, "_infer_team_context_from_process", suspend)
    monkeypatch.setattr(peer_process, "pane_is_alive_strict", lambda *_: False)
    pane = peer_process.PeerPane(30001, "101", None, 1)
    payload = MailAgentRegisterRequest(source="mcp", provider="pi-cli", cwd=str(tmp_path), session_key="mcp:admission-race")
    try:
        async with maker() as caller, maker() as competitor:
            admission = asyncio.create_task(agent_mail_service.register_session(caller, payload, pane=pane))
            await asyncio.wait_for(entered.wait(), 2)
            retirement = asyncio.create_task(retire_dead_pane(DeadPaneRetirement(pane_pid=pane.pane_pid, pane_proc_start=pane.pane_proc_start), _operator=None, db=competitor))
            await asyncio.sleep(0.05)
            assert not retirement.done()
            resume.set()
            await asyncio.wait_for(admission, 3)
            assert (await asyncio.wait_for(retirement, 3))["retired_count"] == 1
            rows = (await competitor.execute(select(MailAgentSession))).scalars().all()
            assert len(rows) == 1 and rows[0].closed_at is not None
            with pytest.raises(MailAuthorityError, match="pane_retired"):
                await agent_mail_service.register_session(caller, payload.model_copy(update={"session_key": "mcp:after-retirement"}), pane=pane)
            assert len((await competitor.execute(select(MailAgentSession))).scalars().all()) == 1
    finally:
        resume.set()
        await engine.dispose()
