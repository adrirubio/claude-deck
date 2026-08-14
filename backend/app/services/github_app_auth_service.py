"""GitHub App authentication and repository-scoped installation tokens."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

import httpx
import jwt

from app.config import Settings, settings

_GITHUB_API = "https://api.github.com"

GithubTokenPurpose = Literal["push", "pull_request"]
_TOKEN_PERMISSIONS: dict[GithubTokenPurpose, dict[str, str]] = {
    "push": {"contents": "write"},
    "pull_request": {"contents": "read", "pull_requests": "write"},
}


class GithubAppAuthError(RuntimeError):
    """A stable, secret-free GitHub App authentication failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class GithubAppUnconfigured(GithubAppAuthError):
    def __init__(self, message: str = "GitHub App authentication is not configured"):
        super().__init__("app_auth_unconfigured", message)


class GithubAppLookupError(GithubAppAuthError):
    def __init__(self, message: str):
        super().__init__("app_installation_lookup_failed", message)


class GithubAppNotInstalled(GithubAppAuthError):
    def __init__(self, owner: str, repo: str, installation_id: int):
        super().__init__(
            "app_not_installed",
            f"GitHub App installation {installation_id} cannot mint for {owner}/{repo}",
        )


class GithubAppMintError(GithubAppAuthError):
    def __init__(self, owner: str, repo: str, message: str = "token mint failed"):
        super().__init__(
            "app_token_mint_failed",
            f"GitHub App {message} for {owner}/{repo}",
        )


class GithubAppMintRejected(GithubAppMintError):
    """GitHub definitively refused a mint request without issuing a token."""


class GithubAppRevokeError(GithubAppAuthError):
    def __init__(self, owner: str, repo: str):
        super().__init__(
            "app_token_revoke_failed",
            f"GitHub App token revocation failed for {owner}/{repo}",
        )


@dataclass(frozen=True)
class _CachedToken:
    token: str
    expires_at: datetime


class GithubAppAuthService:
    """Sign App JWTs, resolve installations, and cache scoped tokens."""

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        *,
        config: Settings | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._http = http
        self._config = config or settings
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._tokens: dict[tuple[int, str, GithubTokenPurpose, str], _CachedToken] = {}
        self._retired_tokens: dict[
            tuple[int, str, GithubTokenPurpose, str], list[_CachedToken]
        ] = {}
        self._locks: dict[
            tuple[int, str, GithubTokenPurpose, str], asyncio.Lock
        ] = {}

    def configured(self, *, require_bot_login: bool = False) -> bool:
        if not self._config.github_app_id or not self._config.github_app_private_key_path:
            return False
        if require_bot_login and not self._config.github_app_bot_login:
            return False
        return True

    def require_configuration(self, *, require_bot_login: bool = False) -> None:
        if not self.configured(require_bot_login=require_bot_login):
            raise GithubAppUnconfigured()
        self._jwt()

    def _private_key(self) -> str:
        path = self._config.github_app_private_key_path
        if not path:
            raise GithubAppUnconfigured()
        try:
            return Path(path).expanduser().read_text()
        except OSError as exc:
            raise GithubAppUnconfigured("GitHub App private key is unavailable") from exc

    def _jwt(self) -> str:
        if not self._config.github_app_id:
            raise GithubAppUnconfigured()
        now = self._now()
        payload = {
            "iat": int((now - timedelta(seconds=30)).timestamp()),
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": self._config.github_app_id,
        }
        try:
            return jwt.encode(payload, self._private_key(), algorithm="RS256")
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise GithubAppUnconfigured("GitHub App private key is invalid") from exc

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        return httpx.AsyncClient(base_url=_GITHUB_API, timeout=30.0)

    async def _revoke_token(
        self,
        client: httpx.AsyncClient,
        token: str,
        owner: str,
        repo: str,
    ) -> None:
        try:
            response = await client.delete(
                "/installation/token",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                },
            )
        except httpx.HTTPError as exc:
            raise GithubAppRevokeError(owner, repo) from exc
        if response.status_code in {204, 401, 404}:
            return
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GithubAppRevokeError(owner, repo) from exc

    async def resolve_installation(self, owner: str, repo: str) -> int | None:
        """Return the repository installation id, or None for lookup 404."""
        token = self._jwt()
        client = self._client()
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/installation",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                },
            )
            if response.status_code == 404:
                return None
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise GithubAppLookupError(
                    f"GitHub App installation lookup failed for {owner}/{repo}"
                ) from exc
            try:
                installation_id = response.json().get("id")
            except (ValueError, TypeError) as exc:
                raise GithubAppLookupError(
                    f"GitHub App installation lookup returned invalid data for {owner}/{repo}"
                ) from exc
            if not isinstance(installation_id, int):
                raise GithubAppLookupError(
                    f"GitHub App installation lookup returned no id for {owner}/{repo}"
                )
            return installation_id
        except GithubAppAuthError:
            raise
        except httpx.HTTPError as exc:
            raise GithubAppLookupError(
                f"GitHub App installation lookup failed for {owner}/{repo}"
            ) from exc
        finally:
            if self._http is None:
                await client.aclose()

    async def mint_repository_token(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        *,
        purpose: GithubTokenPurpose = "pull_request",
        cache_subject: str = "backend",
    ) -> str:
        """Return a cached or freshly minted token narrowed to one repository."""
        permissions = _TOKEN_PERMISSIONS[purpose]
        key = (installation_id, f"{owner}/{repo}", purpose, cache_subject)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = self._now()
            cached = self._tokens.get(key)
            margin = timedelta(
                seconds=self._config.github_app_token_refresh_margin_seconds
            )
            if cached is not None and cached.expires_at - now > margin:
                return cached.token

            app_jwt = self._jwt()
            client = self._client()
            try:
                if cached is not None:
                    if purpose == "push":
                        self._retired_tokens.setdefault(key, []).append(cached)
                    self._tokens.pop(key, None)
                response = await client.post(
                    f"/app/installations/{installation_id}/access_tokens",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {app_jwt}",
                    },
                    json={
                        "repositories": [repo],
                        "permissions": permissions,
                    },
                )
                if response.status_code == 404:
                    raise GithubAppNotInstalled(owner, repo, installation_id)
                if 400 <= response.status_code < 500:
                    raise GithubAppMintRejected(owner, repo)
                try:
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise GithubAppMintError(owner, repo) from exc
                try:
                    body = response.json()
                    token = body.get("token")
                    expires_at = body.get("expires_at")
                    expiry = (
                        datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                        if isinstance(expires_at, str)
                        else None
                    )
                except (ValueError, TypeError) as exc:
                    raise GithubAppMintError(owner, repo, "token response was invalid") from exc
                if not isinstance(token, str) or expiry is None:
                    raise GithubAppMintError(owner, repo, "token response was incomplete")
                self._tokens[key] = _CachedToken(token, expiry)
                return token
            except GithubAppAuthError:
                raise
            except httpx.HTTPError as exc:
                raise GithubAppMintError(owner, repo) from exc
            finally:
                if self._http is None:
                    await client.aclose()

    async def revoke_cached_repository_token(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        *,
        purpose: GithubTokenPurpose,
        cache_subject: str,
    ) -> bool:
        """Revoke one cached token without affecting another lease or purpose."""
        key = (installation_id, f"{owner}/{repo}", purpose, cache_subject)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._tokens.get(key)
            retired = self._retired_tokens.get(key, [])
            if cached is None and not retired:
                return False
            entries = [*retired, *([cached] if cached is not None else [])]
            self._tokens.pop(key, None)
            self._retired_tokens.pop(key, None)
            client = self._client()
            try:
                for entry in entries:
                    await self._revoke_token(
                        client,
                        entry.token,
                        owner,
                        repo,
                    )
                return True
            except GithubAppAuthError:
                raise
            except httpx.HTTPError as exc:
                raise GithubAppRevokeError(owner, repo) from exc
            finally:
                if self._http is None:
                    await client.aclose()

    def cached_repository_token_expiry(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        *,
        purpose: GithubTokenPurpose,
        cache_subject: str,
    ) -> datetime | None:
        key = (installation_id, f"{owner}/{repo}", purpose, cache_subject)
        entries = [
            *self._retired_tokens.get(key, []),
            *([self._tokens[key]] if key in self._tokens else []),
        ]
        return max((entry.expires_at for entry in entries), default=None)


github_app_auth_service = GithubAppAuthService()
