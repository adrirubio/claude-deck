"""Legacy Presence API behavior."""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import PresenceEvent, PresenceSession


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


@pytest.mark.asyncio
async def test_presence_events_noop_when_disabled_by_default(client, db, monkeypatch):
    monkeypatch.setattr(settings, "enable_presence", False)

    resp = await client.post(
        "/api/v1/presence/events",
        json={
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "cwd": "/tmp/repo",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {}
    assert await _count(db, PresenceEvent) == 0
    assert await _count(db, PresenceSession) == 0


@pytest.mark.asyncio
async def test_presence_config_snippet_hidden_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "enable_presence", False)

    resp = await client.get("/api/v1/presence/config-snippet")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_presence_events_process_when_explicitly_enabled(client, db, monkeypatch):
    monkeypatch.setattr(settings, "enable_presence", True)

    resp = await client.post(
        "/api/v1/presence/events",
        json={
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "cwd": "/tmp/repo",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {}
    assert await _count(db, PresenceEvent) == 1
    assert await _count(db, PresenceSession) == 1
