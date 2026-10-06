"""Synthetic response fixtures for the observation-only setup preflight."""

import subprocess

import httpx
import pytest
import pytest_asyncio

from app.config import settings
from app.main import app


OPERATOR = "synthetic-setup-preflight-operator"
PRIVATE = "synthetic-private-credential"


def _github_status_error(status, *, headers=None, message="synthetic provider detail"):
    request = httpx.Request("GET", "https://api.github.com/repos/example/synthetic-repo")
    response = httpx.Response(status, headers=headers or {}, json={"message": message}, request=request)
    return httpx.HTTPStatusError("synthetic provider detail", request=request, response=response)


def _init_checkout(path, remote="https://github.com/example/synthetic-repo.git"):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=Fixture", "-c",
         "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture"],
        check=True,
    )
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path


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
    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "private": True, "default_branch": "main"}

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
        "checkout_identity", "polling_credential", "operator_credential", "repository_read", "labels",
        "dispatch_label", "design_label", "base_branch", "dispatch_auth"
    }
    assert body["observed_at"] == body["checked_at"]
    assert all(item["remedy"] for item in body["checks"].values())


@pytest.mark.asyncio
async def test_preflight_presence_map_and_host_guidance_are_safe(client, monkeypatch, tmp_path):
    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_app_private_key_path", "/synthetic/private/key/path")

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "default_branch": "main"}

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    response = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
    })
    body = response.json()
    presence = body["configuration_presence"]
    assert set(presence) == {"github_token", "operator_token", "github_app_id",
                             "github_app_private_key_path", "github_app_bot_login"}
    assert all(isinstance(value, bool) for value in presence.values())
    assert presence == {"github_token": False, "operator_token": True, "github_app_id": False,
                        "github_app_private_key_path": True, "github_app_bot_login": False}
    assert body["checks"]["operator_credential"] == {
        "status": "ready", "code": "operator_token_configured", "remedy": "No action is required for this check.",
    }
    guidance = " ".join(body["host_guidance"])
    assert "restart" in guidance
    assert "harness" in guidance and "Agent Mail" in guidance
    assert "/synthetic/private/key/path" not in response.text
    assert PRIVATE not in response.text
    assert OPERATOR not in response.text


@pytest.mark.asyncio
async def test_preflight_pagination_bound_is_incomplete_unknown(client, monkeypatch, tmp_path):
    from app.services.github_client import GithubClientResponseError

    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "default_branch": "main"}

    async def bounded(*_args, **_kwargs):
        raise GithubClientResponseError("GitHub label pagination bound exceeded")

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", bounded)
    response = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
    })
    body = response.json()
    assert body["status"] == "unknown"
    assert body["checks"]["labels"]["status"] == "unknown"
    assert body["checks"]["labels"]["code"] == "label_check_incomplete"
    assert body["checks"]["labels"]["remedy"]


@pytest.mark.asyncio
async def test_preflight_missing_labels_blocks_and_timeout_is_unknown(client, monkeypatch, tmp_path):
    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "default_branch": "main"}

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
    assert blocked.json()["checks"]["dispatch_label"]["status"] == "ready"
    assert blocked.json()["checks"]["design_label"]["status"] == "blocked"
    assert "Create" in blocked.json()["checks"]["design_label"]["remedy"]

    async def timeout(*_args, **_kwargs):
        raise TimeoutError()

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", timeout)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", timeout)
    unknown = await client.post("/api/v1/factory/setup-preflight", json=body)
    assert unknown.json()["status"] == "unknown"
    assert unknown.json()["checks"]["repository_read"]["status"] == "unknown"
    assert unknown.json()["checks"]["labels"]["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", ["repository", "labels"])
async def test_preflight_rate_limit_403_is_unknown_with_safe_retry_remedy(client, monkeypatch, tmp_path, probe):
    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        if probe == "repository":
            raise _github_status_error(403, headers={"x-ratelimit-remaining": "0"})
        return {"name": "synthetic-repo", "default_branch": "main"}

    async def labels(*_args, **_kwargs):
        if probe == "labels":
            raise _github_status_error(403, headers={"retry-after": "30"})
        return ["dispatch", "design"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    response = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
    })

    body = response.json()
    # The per-probe check carries the rate-limit code; the label aggregate stays incomplete.
    expected_name = "repository_read" if probe == "repository" else "dispatch_label"
    check = body["checks"][expected_name]
    assert response.status_code == 200
    assert body["status"] == "unknown"
    if probe == "labels":
        assert body["checks"]["labels"]["status"] == "unknown"
        assert body["checks"]["design_label"]["code"] == "github_rate_limited"
    assert body["observed_at"]
    assert check["status"] == "unknown"
    assert check["code"] == "github_rate_limited"
    assert "rate limit" in check["remedy"].lower()
    assert PRIVATE not in response.text
    assert "synthetic provider detail" not in response.text
    assert "retry-after" not in response.text
    assert "x-ratelimit" not in response.text
    assert "30" not in check["remedy"]


@pytest.mark.asyncio
async def test_preflight_permission_denied_403_remains_blocked(client, monkeypatch, tmp_path):
    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        raise _github_status_error(403, message="Resource access denied")

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    response = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
    })
    assert response.json()["status"] == "blocked"
    assert response.json()["checks"]["repository_read"]["status"] == "blocked"
    assert response.json()["checks"]["repository_read"]["code"] == "repository_not_readable"


@pytest.mark.asyncio
async def test_preflight_requires_primary_checkout_and_exact_remote_identity(client, monkeypatch, tmp_path):
    checkout = _init_checkout(
        tmp_path / "renamed-directory",
        "git@github.com:Example/Synthetic-Repo.git",
    )
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "Synthetic-Repo", "default_branch": "main"}

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    body = {
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
    }
    ready = await client.post("/api/v1/factory/setup-preflight", json=body)
    assert ready.json()["checks"]["checkout_identity"]["status"] == "ready"
    assert ready.json()["checks"]["checkout_identity"]["code"] == "checkout_identity_matches"

    wrong_owner = {**body, "repo_owner": "other"}
    blocked = await client.post("/api/v1/factory/setup-preflight", json=wrong_owner)
    assert blocked.json()["checks"]["checkout_identity"]["code"] == "checkout_identity_mismatch"
    assert str(checkout) not in blocked.text

    worktree = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "-C", str(checkout), "worktree", "add", "-q", "--detach", str(worktree)],
        check=True,
    )
    linked = await client.post("/api/v1/factory/setup-preflight", json={**body, "repo_path": str(worktree)})
    assert linked.json()["checks"]["checkout_identity"]["code"] == "checkout_identity_mismatch"


@pytest.mark.asyncio
async def test_preflight_github_app_requires_bot_login(client, monkeypatch, tmp_path):
    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)
    monkeypatch.setattr(settings, "github_app_id", "synthetic-app")
    monkeypatch.setattr(settings, "github_app_bot_login", "")
    key = tmp_path / "key.pem"
    key.write_text("synthetic key fixture")
    monkeypatch.setattr(settings, "github_app_private_key_path", str(key))

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "default_branch": "main"}

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    response = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "github_app",
    })
    assert response.json()["checks"]["dispatch_auth"]["status"] == "blocked"
    assert response.json()["checks"]["dispatch_auth"]["code"] == "github_app_configuration_missing"
    assert "synthetic key fixture" not in response.text
    assert str(key) not in response.text

    monkeypatch.setattr(settings, "github_app_bot_login", "synthetic-bot[bot]")
    monkeypatch.setattr(
        "app.api.v1.factory.github_app_auth_service.require_configuration",
        lambda **_kwargs: None,
    )

    async def no_installation(_owner, _repo):
        return None

    monkeypatch.setattr(
        "app.api.v1.factory.github_app_auth_service.resolve_installation",
        no_installation,
    )
    missing = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "github_app",
    })
    assert missing.json()["checks"]["dispatch_auth"]["status"] == "blocked"
    assert missing.json()["checks"]["dispatch_auth"]["code"] == "github_app_installation_missing"

    async def installed(_owner, _repo):
        return 55

    monkeypatch.setattr(
        "app.api.v1.factory.github_app_auth_service.resolve_installation",
        installed,
    )
    ready = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "github_app",
    })
    assert ready.json()["checks"]["dispatch_auth"]["status"] == "ready"
    assert ready.json()["checks"]["dispatch_auth"]["code"] == "github_app_installation_available"


@pytest.mark.asyncio
async def test_preflight_checks_explicit_base_branch_and_rejects_invalid_value(client, monkeypatch, tmp_path):
    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "default_branch": "main"}

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    async def get_ref(_owner, _repo, ref, **_kwargs):
        return {"ref": f"refs/heads/{ref}"} if ref == "release/2" else None

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    monkeypatch.setattr("app.api.v1.factory.github_client.get_ref", get_ref)
    body = {
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
        "base_ref": "origin/release/2",
    }
    valid = await client.post("/api/v1/factory/setup-preflight", json=body)
    assert valid.json()["checks"]["base_branch"]["status"] == "ready"
    assert valid.json()["checks"]["base_branch"]["code"] == "base_branch_exists"

    invalid = await client.post("/api/v1/factory/setup-preflight", json={**body, "base_ref": "origin/bad branch"})
    assert invalid.json()["checks"]["base_branch"]["status"] == "blocked"
    assert invalid.json()["checks"]["base_branch"]["code"] == "base_branch_invalid"


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


@pytest.mark.asyncio
async def test_v13_preflight_logs_and_response_expose_no_secret_values(client, monkeypatch, tmp_path, caplog):
    import logging

    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)
    monkeypatch.setattr(settings, "github_app_private_key_path", "/synthetic/private/key")

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "default_branch": "main"}

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    with caplog.at_level(logging.DEBUG):
        response = await client.post("/api/v1/factory/setup-preflight", json={
            "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
            "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
        })
    assert response.status_code == 200
    # Presence booleans are allowed. Values, key paths, and credentials are not.
    assert response.json()["configuration_presence"]["github_app_private_key_path"] is True
    for secret in (PRIVATE, OPERATOR, "/synthetic/private/key"):
        assert secret not in response.text
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_r3_checkout_subprocess_timeout_is_safe_unknown(client, monkeypatch, tmp_path):
    """R3: a bounded Git subprocess timeout returns unknown, not a 500."""
    import subprocess as subprocess_module

    checkout = _init_checkout(tmp_path / "synthetic-repo")
    monkeypatch.setattr(settings, "github_token", PRIVATE)

    async def repository(*_args, **_kwargs):
        return {"name": "synthetic-repo", "default_branch": "main"}

    async def labels(*_args, **_kwargs):
        return ["dispatch", "design"]

    def slow_git(*_args, **_kwargs):
        raise subprocess_module.TimeoutExpired(cmd=["git"], timeout=2)

    monkeypatch.setattr("app.api.v1.factory.github_client.get_repository", repository)
    monkeypatch.setattr("app.api.v1.factory.github_client.list_repo_labels", labels)
    monkeypatch.setattr("app.utils.repo_utils.subprocess.run", slow_git)
    response = await client.post("/api/v1/factory/setup-preflight", json={
        "repo_owner": "example", "repo_name": "synthetic-repo", "repo_path": str(checkout),
        "dispatch_label": "dispatch", "design_label": "design", "dispatch_auth_mode": "token",
    })
    body = response.json()
    assert response.status_code == 200
    assert body["checks"]["checkout_identity"]["status"] == "unknown"
    assert body["checks"]["checkout_identity"]["code"] == "checkout_check_timeout"
    assert body["checks"]["checkout_identity"]["remedy"]
    # Independent observations keep their own results.
    assert body["checks"]["repository_read"]["status"] == "ready"
    assert body["checks"]["labels"]["status"] == "ready"
