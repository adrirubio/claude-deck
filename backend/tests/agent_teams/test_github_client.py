import httpx
import pytest

from app.services.github_client import GithubClient


def test_explicit_authorization_does_not_mutate_ambient_token():
    client = GithubClient(token="ambient-token")

    assert client._headers()["Authorization"] == "Bearer ambient-token"
    assert client._headers("app-token")["Authorization"] == "Bearer app-token"
    assert client._headers()["Authorization"] == "Bearer ambient-token"


@pytest.mark.asyncio
async def test_existing_watcher_call_keeps_ambient_authorization():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, request=request, json=[])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http, token="ambient-token")
        assert await client.list_issues_with_label("owner", "repo", "ready") == []

    assert seen[0].headers["Authorization"] == "Bearer ambient-token"
