"""Agent Bridge image attachment API tests."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import BridgeSessionAttachment
from app.services.agent_bridge.attachments import agent_bridge_attachment_service

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


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


@pytest.fixture(autouse=True)
def attachment_boundaries(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "bridge_attachment_dir", str(tmp_path / "attachments"))
    monkeypatch.setattr(settings, "bridge_attachment_agent_root", None)
    monkeypatch.setattr(settings, "bridge_attachment_max_bytes", 1024)
    monkeypatch.setattr(settings, "bridge_attachment_retention_days", 7)
    monkeypatch.setattr(settings, "bridge_attachment_max_per_session_per_day", 100)
    monkeypatch.setattr(
        "app.services.agent_bridge.attachments.discover_agent_sessions",
        lambda: [
            {
                "tmux_target": "snazzyemail:0.0",
                "session_name": "snazzyemail",
                "provider": "claude-code",
            }
        ],
    )


async def _token(client) -> str:
    response = await client.get("/api/v1/agent-bridge/token")
    assert response.status_code == 200
    return response.json()["token"]


@pytest.mark.asyncio
async def test_upload_image_attachment_persists_metadata_and_file(client, db):
    response = await client.post(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
        files={"file": ("../../screen.png", PNG_BYTES, "image/png")},
        data={"prompt": "Please inspect\n{path}", "created_by": "test"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target"] == "snazzyemail:0.0"
    assert body["provider"] == "claude-code"
    assert body["mime_type"] == "image/png"
    assert body["original_filename"] == "../../screen.png"
    assert "\n" not in body["prompt_text"]
    assert body["agent_path"].endswith(".png")

    attachment = await db.get(BridgeSessionAttachment, body["id"])
    assert attachment is not None
    assert attachment.created_by == "test"
    assert attachment.storage_path.endswith(".png")


@pytest.mark.asyncio
async def test_attachment_token_is_required_and_single_use(client):
    token = await _token(client)
    first = await client.get(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={"X-Claude-Deck-Terminal-Token": token},
    )
    second = await client.get(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={"X-Claude-Deck-Terminal-Token": token},
    )
    missing = await client.get("/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments")

    assert first.status_code == 200
    assert second.status_code == 401
    assert missing.status_code == 401


@pytest.mark.asyncio
async def test_attachment_endpoint_rejects_cross_origin(client):
    response = await client.get(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={
            "X-Claude-Deck-Terminal-Token": await _token(client),
            "Origin": "https://evil.example",
            "Host": "test",
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_file(client):
    response = await client.post(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported image type"


@pytest.mark.asyncio
async def test_paste_attachment_sends_literal_text_then_delayed_enter(client, monkeypatch):
    upload = await client.post(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
        files={"file": ("screen.png", PNG_BYTES, "image/png")},
    )
    attachment_id = upload.json()["id"]
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.agent_bridge.attachments.subprocess.run", fake_run)
    monkeypatch.setattr(
        "app.services.agent_bridge.attachments.time.sleep",
        lambda seconds: calls.append(["sleep", seconds]),
    )

    response = await client.post(
        f"/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments/{attachment_id}/paste",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
        json={"submit": True, "prefix": "Look: ", "suffix": "\nthanks"},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] is True
    assert calls[0][:5] == ["tmux", "send-keys", "-t", "snazzyemail:0.0", "-l"]
    assert "\n" not in calls[0][5]
    assert calls[1][0] == "sleep"
    assert calls[2] == ["tmux", "send-keys", "-t", "snazzyemail:0.0", "Enter"]


@pytest.mark.asyncio
async def test_paste_attachment_can_require_interactive_relay(client, monkeypatch):
    upload = await client.post(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
        files={"file": ("screen.png", PNG_BYTES, "image/png")},
    )
    attachment_id = upload.json()["id"]
    calls = []

    monkeypatch.setattr(
        "app.api.v1.agent_bridge.router.is_target_interactive",
        lambda _target: False,
    )
    monkeypatch.setattr(
        "app.services.agent_bridge.attachments.subprocess.run",
        lambda args, **_kwargs: calls.append(args),
    )

    response = await client.post(
        f"/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments/{attachment_id}/paste",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
        json={"submit": False, "require_interactive_relay": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Terminal relay is read-only or not attached"
    assert calls == []


@pytest.mark.asyncio
async def test_delete_attachment_removes_file_and_row(client, db):
    upload = await client.post(
        "/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
        files={"file": ("screen.png", PNG_BYTES, "image/png")},
    )
    attachment_id = upload.json()["id"]
    attachment = await db.get(BridgeSessionAttachment, attachment_id)
    assert attachment is not None
    storage_path = attachment.storage_path

    response = await client.delete(
        f"/api/v1/agent-bridge/sessions/snazzyemail:0.0/attachments/{attachment_id}",
        headers={"X-Claude-Deck-Terminal-Token": await _token(client)},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert not Path(storage_path).exists()
    assert await db.get(BridgeSessionAttachment, attachment_id) is None


@pytest.mark.asyncio
async def test_cleanup_expired_removes_file_and_row(db, tmp_path):
    storage_path = tmp_path / "attachments" / "expired.png"
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(PNG_BYTES)
    now = datetime.now(UTC).replace(tzinfo=None)
    attachment = BridgeSessionAttachment(
        target="snazzyemail:0.0",
        mime_type="image/png",
        size_bytes=len(PNG_BYTES),
        sha256="abc123",
        storage_path=str(storage_path),
        agent_path=str(storage_path),
        prompt_text=f"Please inspect this image: {storage_path}",
        created_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=1),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    removed = await agent_bridge_attachment_service.cleanup_expired(db, now=now)

    assert removed == 1
    assert not storage_path.exists()
    assert await db.get(BridgeSessionAttachment, attachment.id) is None
