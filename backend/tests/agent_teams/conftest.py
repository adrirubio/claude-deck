"""Local fixtures for agent team tests."""
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base


@pytest.fixture(autouse=True)
def allow_tmp_agent_team_repos(monkeypatch, tmp_path_factory):
    monkeypatch.setenv(
        "CLAUDE_DECK_ALLOWED_REPO_ROOTS",
        os.pathsep.join([str(tmp_path_factory.getbasetemp())]),
    )


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()
