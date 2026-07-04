"""GitHub client + watcher service tests."""
import httpx
import pytest

from app.services.github_client import GithubClient


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return self.handler(request)


@pytest.mark.asyncio
async def test_list_issues_with_label_builds_request():
    def handler(request):
        return httpx.Response(
            200,
            json=[
                {
                    "number": 42,
                    "title": "bug",
                    "html_url": "u",
                    "updated_at": "2026-07-04T00:00:00Z",
                    "labels": [{"name": "claude-deck-ready"}],
                }
            ],
        )

    transport = _RecordingTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http, token="tok")
        issues = await client.list_issues_with_label("o", "r", "claude-deck-ready")

    req = transport.requests[0]
    assert req.url.path == "/repos/o/r/issues"
    assert req.url.params["labels"] == "claude-deck-ready"
    assert req.url.params["state"] == "open"
    assert req.headers["Authorization"] == "Bearer tok"
    assert issues[0]["number"] == 42
