"""Synthetic response fixtures for the observation-only setup preflight."""

import httpx
import pytest
import pytest_asyncio

from app.config import settings
from app.main import app


OPERATOR = "synthetic-setup-preflight-operator"
PRIVATE = "synthetic-private-credential"


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(settings, "operator_token", OPERATOR)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Deck-Operator-Token": OPERATOR},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_preflight_returns_allowlisted_ready_checks(client, monkeypatch, tmp_path):
    checkout = tmp_path / "synthetic-repo"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "private": True}

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    response = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example",
        "repo_name": "synthetic-repo",
        "repo_path": str(checkout),
        "dispatch_label": "dispatch",
        "design_label": "design",
        "dispatch_auth_mode": "token",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {entry["status"] for entry in body["checks"].values()} == {"ready"}
    assert PRIVATE not in response.text
    assert str(checkout) not in response.text
    assert set(body["checks"]) == {
        "checkout_identity", "polling_credential", "repository_read", "labels", "dispatch_auth"
    }


@pytest.mark.asyncio
async def test_preflight_missing_labels_blocks_and_timeout_is_unknown(client, monkeypatch, tmp_path):
    checkout = tmp_path / "synthetic-repo"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo"}

    async def labels(*_args, **_kwargs):
        return ["dispatch"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    body = {
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
    }
    blocked = await client.post("/api/v1/factory/setup-preflight", json=body)
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["checks"]["labels"]["code"] == "selected_labels_missing"

    async def timeout(*_args, **_kwargs):
        raise TimeoutError()

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", timeout)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", timeout)
    unknown = await client.post("/api/v1/factory/setup-preflight", json=body)
    assert unknown.json()["status"] == "unknown"
    assert unknown.json()["checks"]["repository_read"]["status"] == "unknown"
    assert unknown.json()["checks"]["labels"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_preflight_requires_operator_and_uses_safe_validation(client):
    denied = await client.post(
        "/api/v1/factory/setup-preflight",
        headers={"X-Deck-Operator-Token": ""},
        json={},
    )
    assert denied.status_code == 401
    invalid = await client.post(
        "/api/v1/factory/setup-preflight",
        json={"repo_owner": "example"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_filter"
