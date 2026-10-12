"""GitHub HTTP clients that respect the test-instance setting.

A test instance (``settings.test_instance``) must never contact GitHub. Its
clients use a transport that fails every request as a connection error, so
callers take their existing "GitHub unreachable" paths and no socket opens.
"""
from __future__ import annotations

import httpx

from app.config import Settings

OFFLINE_MESSAGE = "GitHub access is disabled on a test instance"


class OfflineGithubTransport(httpx.AsyncBaseTransport):
    """Refuse every request without network access."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(OFFLINE_MESSAGE, request=request)


def github_http_client(base_url: str, config: Settings) -> httpx.AsyncClient:
    """Return the HTTP client for GitHub calls under ``config``."""
    if config.test_instance:
        return httpx.AsyncClient(
            base_url=base_url, timeout=30.0, transport=OfflineGithubTransport()
        )
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)
