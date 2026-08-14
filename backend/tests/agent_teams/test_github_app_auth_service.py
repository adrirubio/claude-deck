import asyncio
import json
import logging
import tomllib
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.services.github_app_auth_service import (
    GithubAppAuthError,
    GithubAppAuthService,
    GithubAppLookupError,
    GithubAppMintError,
    GithubAppMintRejected,
    GithubAppNotInstalled,
    GithubAppRevokeError,
    GithubAppUnconfigured,
)


def _key_pair(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "app.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return private_path, private_key.public_key()


def _settings(private_path, **overrides):
    values = {
        "github_app_id": "12345",
        "github_app_private_key_path": str(private_path),
        "github_app_bot_login": "deck-agent[bot]",
        "github_app_token_refresh_margin_seconds": 300,
    }
    values.update(overrides)
    return Settings(**values)


def test_github_app_settings_defaults():
    assert Settings.model_fields["github_app_id"].default == ""
    assert Settings.model_fields["github_app_private_key_path"].default == ""
    assert Settings.model_fields["github_app_bot_login"].default == ""
    assert Settings.model_fields["github_app_token_refresh_margin_seconds"].default == 300


def test_github_app_dependencies_are_direct():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    requirements = (root / "requirements.txt").read_text().lower()
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    dependencies = {value.lower() for value in pyproject["project"]["dependencies"]}
    root_package = next(
        package
        for package in lock["package"]
        if package["name"] == pyproject["project"]["name"]
        and package.get("source", {}).get("editable") == "."
    )
    locked_dependencies = {
        requirement["name"]: requirement
        for requirement in root_package["metadata"]["requires-dist"]
    }
    assert "pyjwt[crypto]" in requirements
    assert "cryptography" in requirements
    assert any(value.startswith("pyjwt[crypto]") for value in dependencies)
    assert any(value.startswith("cryptography") for value in dependencies)
    assert locked_dependencies["pyjwt"]["extras"] == ["crypto"]
    assert locked_dependencies["cryptography"]["specifier"] == ">=44.0.0"


@pytest.mark.asyncio
async def test_lookup_signs_short_lived_jwt_and_distinguishes_404(tmp_path):
    private_path, public_key = _key_pair(tmp_path)
    fixed_now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(
            http, config=_settings(private_path), now=lambda: fixed_now
        )
        assert await service.resolve_installation("owner", "repo") is None

    encoded = seen[0].headers["Authorization"].removeprefix("Bearer ")
    payload = jwt.decode(
        encoded,
        public_key,
        algorithms=["RS256"],
        options={"verify_iat": False, "verify_exp": False},
    )
    assert payload["iss"] == "12345"
    assert payload["iat"] <= int(fixed_now.timestamp())
    assert payload["exp"] - payload["iat"] <= 600


@pytest.mark.asyncio
async def test_lookup_failure_is_not_ambient(tmp_path):
    private_path, _ = _key_pair(tmp_path)

    def handler(request: httpx.Request):
        return httpx.Response(503, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        with pytest.raises(GithubAppLookupError):
            await service.resolve_installation("owner", "repo")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500])
async def test_lookup_http_failures_are_explicit(tmp_path, status):
    private_path, _ = _key_pair(tmp_path)

    def handler(request: httpx.Request):
        return httpx.Response(status, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        with pytest.raises(GithubAppLookupError) as exc_info:
            await service.resolve_installation("owner", "repo")
    assert exc_info.value.code == "app_installation_lookup_failed"


@pytest.mark.asyncio
async def test_mint_http_rejection_is_distinct_from_unknown_transport_outcome(
    tmp_path,
):
    private_path, _ = _key_pair(tmp_path)

    def handler(request: httpx.Request):
        return httpx.Response(422, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        with pytest.raises(GithubAppMintRejected) as exc_info:
            await service.mint_repository_token(
                7,
                "owner",
                "repo",
                purpose="push",
                cache_subject="lease",
            )

    assert exc_info.value.code == "app_token_mint_failed"


@pytest.mark.asyncio
async def test_mint_server_failure_keeps_an_ambiguous_outcome(tmp_path):
    private_path, _ = _key_pair(tmp_path)

    def handler(request: httpx.Request):
        return httpx.Response(503, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        with pytest.raises(GithubAppMintError) as exc_info:
            await service.mint_repository_token(
                7,
                "owner",
                "repo",
                purpose="push",
                cache_subject="lease",
            )

    assert not isinstance(exc_info.value, GithubAppMintRejected)
    assert exc_info.value.code == "app_token_mint_failed"


@pytest.mark.asyncio
async def test_lookup_transport_failure_is_explicit(tmp_path):
    private_path, _ = _key_pair(tmp_path)

    def handler(request: httpx.Request):
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        with pytest.raises(GithubAppLookupError):
            await service.resolve_installation("owner", "repo")


@pytest.mark.asyncio
async def test_token_is_repository_narrowed_cached_and_refreshed(tmp_path):
    private_path, _ = _key_pair(tmp_path)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        index = len(calls)
        return httpx.Response(
            201,
            request=request,
            json={
                "token": f"token-{index}",
                "expires_at": (now + timedelta(minutes=30 + index)).isoformat(),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(
            http, config=_settings(private_path), now=lambda: now
        )
        first = await service.mint_repository_token(7, "owner", "repo")
        second = await service.mint_repository_token(7, "owner", "repo")
        other = await service.mint_repository_token(7, "owner", "other")

    assert first == second == "token-1"
    assert other == "token-2"
    assert len(calls) == 2
    assert calls[0].read() == (
        b'{"repositories":["repo"],"permissions":'
        b'{"contents":"read","pull_requests":"write"}}'
    )


@pytest.mark.asyncio
async def test_push_and_pr_tokens_have_distinct_permissions_and_cache_keys(tmp_path):
    private_path, _ = _key_pair(tmp_path)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204, request=request)
        return httpx.Response(
            201,
            request=request,
            json={
                "token": f"token-{len(requests)}",
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(
            http, config=_settings(private_path), now=lambda: now
        )
        push = await service.mint_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        )
        pull_request = await service.mint_repository_token(
            7,
            "owner",
            "repo",
            purpose="pull_request",
            cache_subject="backend",
        )
        assert push != pull_request
        assert json.loads(requests[0].content)["permissions"] == {"contents": "write"}
        assert json.loads(requests[1].content)["permissions"] == {
            "contents": "read",
            "pull_requests": "write",
        }
        assert await service.revoke_cached_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        )
        assert requests[2].method == "DELETE"
        assert requests[2].headers["Authorization"] == f"Bearer {push}"
        assert await service.mint_repository_token(
            7,
            "owner",
            "repo",
            purpose="pull_request",
            cache_subject="backend",
        ) == pull_request
        replacement_push = await service.mint_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        )
        assert replacement_push != push
        assert json.loads(requests[3].content)["permissions"] == {
            "contents": "write"
        }


@pytest.mark.asyncio
async def test_token_revocation_has_a_distinct_failure_contract(tmp_path):
    private_path, _ = _key_pair(tmp_path)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

    def handler(request: httpx.Request):
        if request.method == "DELETE":
            return httpx.Response(503, request=request)
        return httpx.Response(
            201,
            request=request,
            json={
                "token": "push-token",
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(
            http, config=_settings(private_path), now=lambda: now
        )
        await service.mint_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        )

        with pytest.raises(GithubAppRevokeError) as exc_info:
            await service.revoke_cached_repository_token(
                7,
                "owner",
                "repo",
                purpose="push",
                cache_subject="lease-a",
            )

    assert exc_info.value.code == "app_token_revoke_failed"


@pytest.mark.asyncio
async def test_cancelled_revocation_quarantines_the_unknown_token(tmp_path):
    private_path, _ = _key_pair(tmp_path)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    delete_started = asyncio.Event()
    hold_delete = asyncio.Event()
    minted = 0

    async def handler(request: httpx.Request):
        nonlocal minted
        if request.method == "DELETE":
            delete_started.set()
            await hold_delete.wait()
            return httpx.Response(204, request=request)
        minted += 1
        return httpx.Response(
            201,
            request=request,
            json={
                "token": f"push-{minted}",
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(
            http, config=_settings(private_path), now=lambda: now
        )
        assert await service.mint_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        ) == "push-1"
        revoke_task = asyncio.create_task(
            service.revoke_cached_repository_token(
                7,
                "owner",
                "repo",
                purpose="push",
                cache_subject="lease-a",
            )
        )
        await delete_started.wait()
        revoke_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await revoke_task

        assert service.cached_repository_token_expiry(
            7,
            "owner",
            "repo",
            purpose="push",
            cache_subject="lease-a",
        ) is None
        assert await service.mint_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        ) == "push-2"


@pytest.mark.asyncio
async def test_token_refreshes_inside_margin(tmp_path):
    private_path, _ = _key_pair(tmp_path)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    minted = 0
    methods = []

    def handler(request: httpx.Request):
        nonlocal minted
        methods.append(request.method)
        minted += 1
        return httpx.Response(
            201,
            request=request,
            json={
                "token": f"token-{minted}",
                "expires_at": (now + timedelta(minutes=4)).isoformat(),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(
            http, config=_settings(private_path), now=lambda: now
        )
        assert await service.mint_repository_token(7, "owner", "repo") == "token-1"
        assert await service.mint_repository_token(7, "owner", "repo") == "token-2"
        assert methods == ["POST", "POST"]


@pytest.mark.asyncio
async def test_push_refresh_revokes_every_generation_when_the_lease_ends(tmp_path):
    private_path, _ = _key_pair(tmp_path)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    minted = 0
    revoked = []

    def handler(request: httpx.Request):
        nonlocal minted
        if request.method == "DELETE":
            revoked.append(request.headers["Authorization"])
            return httpx.Response(204, request=request)
        minted += 1
        return httpx.Response(
            201,
            request=request,
            json={
                "token": f"push-{minted}",
                "expires_at": (now + timedelta(minutes=4)).isoformat(),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(
            http, config=_settings(private_path), now=lambda: now
        )
        first = await service.mint_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        )
        second = await service.mint_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        )

        assert first != second
        assert await service.revoke_cached_repository_token(
            7, "owner", "repo", purpose="push", cache_subject="lease-a"
        )

    assert revoked == ["Bearer push-1", "Bearer push-2"]


@pytest.mark.asyncio
async def test_concurrent_same_key_mints_once(tmp_path):
    private_path, _ = _key_pair(tmp_path)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(
            201,
            request=request,
            json={
                "token": "shared-token",
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        tokens = await asyncio.gather(
            service.mint_repository_token(7, "owner", "repo"),
            service.mint_repository_token(7, "owner", "repo"),
        )
    assert tokens == ["shared-token", "shared-token"]
    assert calls == 1


@pytest.mark.asyncio
async def test_mint_404_is_not_installed_and_names_no_secret(tmp_path):
    private_path, _ = _key_pair(tmp_path)

    def handler(request: httpx.Request):
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        with pytest.raises(GithubAppNotInstalled) as exc_info:
            await service.mint_repository_token(77, "owner", "repo")
    assert exc_info.value.code == "app_not_installed"
    assert "77" in str(exc_info.value)


def test_missing_or_unreadable_configuration_refuses(tmp_path):
    service = GithubAppAuthService(config=Settings())
    with pytest.raises(GithubAppUnconfigured):
        service.require_configuration(require_bot_login=True)


@pytest.mark.asyncio
async def test_secrets_do_not_enter_logs_or_errors(tmp_path, caplog):
    private_path, _ = _key_pair(tmp_path)
    private_key = private_path.read_text()
    secret_token = "installation-token-secret"

    def handler(request: httpx.Request):
        return httpx.Response(
            201,
            request=request,
            json={
                "token": secret_token,
                "expires_at": "not-a-date",
            },
        )

    caplog.set_level(logging.DEBUG)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        service = GithubAppAuthService(http, config=_settings(private_path))
        with pytest.raises(GithubAppAuthError) as exc_info:
            await service.mint_repository_token(7, "owner", "repo")
    captured = caplog.text + str(exc_info.value)
    assert private_key not in captured
    assert secret_token not in captured

    service = GithubAppAuthService(
        config=_settings(tmp_path / "missing.pem")
    )
    with pytest.raises(GithubAppUnconfigured):
        service.require_configuration(require_bot_login=True)
