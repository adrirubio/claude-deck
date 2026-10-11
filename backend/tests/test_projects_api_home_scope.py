"""Project add and discover accept only paths in the home tree, like browse."""
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "repo").mkdir(parents=True)
    (tmp_path / "outside" / "repo").mkdir(parents=True)
    (home / "link-out").symlink_to(tmp_path / "outside")
    (tmp_path / "home-sibling").mkdir()
    monkeypatch.setenv("HOME", str(home))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, home, tmp_path / "outside"
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_discover_refuses_paths_outside_home(client):
    c, home, outside = client
    sibling = str(home) + "-sibling"  # shares the home prefix but is outside it
    for base_path in (str(outside), "/", sibling, str(home / "link-out"), str(home / ".." / "outside")):
        response = await c.post("/api/v1/projects/discover", json={"base_path": base_path})
        assert response.status_code == 403, base_path


@pytest.mark.asyncio
async def test_discover_accepts_the_home_tree(client):
    c, home, _ = client
    for base_path in ("~", str(home)):
        response = await c.post("/api/v1/projects/discover", json={"base_path": base_path})
        assert response.status_code == 200, base_path
        assert str(home / "repo") in {p["path"] for p in response.json()["discovered"]}


@pytest.mark.asyncio
async def test_add_refuses_paths_outside_home(client):
    c, home, outside = client
    for path in (str(outside / "repo"), "/etc", str(home / "link-out" / "repo")):
        response = await c.post("/api/v1/projects", json={"name": "x", "path": path})
        assert response.status_code == 403, path

    listed = await c.get("/api/v1/projects")
    assert listed.json()["projects"] == []


@pytest.mark.asyncio
async def test_add_accepts_a_path_in_home(client):
    c, home, _ = client
    response = await c.post("/api/v1/projects", json={"name": "repo", "path": str(home / "repo")})
    assert response.status_code == 200
    assert response.json()["path"] == str(home / "repo")
