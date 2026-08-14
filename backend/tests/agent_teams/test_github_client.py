import httpx
import pytest

from app.services.github_client import GithubClient, GithubClientResponseError


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


@pytest.mark.asyncio
async def test_app_transport_uses_explicit_token_and_payloads():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/git/ref/" in request.url.path:
            return httpx.Response(200, request=request, json={"ref": "refs/heads/deck/x"})
        if request.url.path == "/repos/owner/repo" and request.method == "GET":
            return httpx.Response(200, request=request, json={"default_branch": "main"})
        if request.url.path.endswith("/pulls") and request.method == "POST":
            return httpx.Response(201, request=request, json={"number": 9})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http, token="ambient-token")
        ref = await client.get_ref(
            "owner", "repo", "deck/slot/attempt", token="app-token"
        )
        repository = await client.get_repository(
            "owner", "repo", token="app-token"
        )
        pull = await client.create_pull(
            "owner",
            "repo",
            title="Title",
            head="deck/slot/attempt",
            base="main",
            body="Body",
            draft=True,
            token="app-token",
        )

    assert ref["ref"] == "refs/heads/deck/x"
    assert repository["default_branch"] == "main"
    assert pull["number"] == 9
    assert all(request.headers["Authorization"] == "Bearer app-token" for request in seen)
    assert "heads%2Fdeck%2Fslot%2Fattempt" in str(seen[0].url)
    assert seen[2].read() == (
        b'{"title":"Title","head":"deck/slot/attempt","base":"main",'
        b'"body":"Body","draft":true}'
    )


@pytest.mark.asyncio
async def test_pull_pagination_accumulates_later_pages_and_preserves_query():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        page = request.url.params.get("page")
        if page is None:
            next_url = (
                "https://api.github.com/repos/owner/repo/pulls?"
                "head=owner%3Adeck%2Fattempt&base=main&state=all&per_page=100&page=2"
            )
            return httpx.Response(
                200,
                request=request,
                headers={"Link": f'<{next_url}>; rel="next"'},
                json=[{"number": 1, "state": "closed", "merged_at": None}],
            )
        return httpx.Response(
            200,
            request=request,
            json=[{"number": 2, "state": "open", "merged_at": None}],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        pulls = await GithubClient(http=http).list_pulls_for_head(
            "owner",
            "repo",
            head="owner:deck/attempt",
            base="main",
            state="all",
            token="app-token",
        )

    assert [pull["number"] for pull in pulls] == [1, 2]
    assert len(seen) == 2
    for request in seen:
        assert request.headers["Authorization"] == "Bearer app-token"
        assert request.url.params["head"] == "owner:deck/attempt"
        assert request.url.params["base"] == "main"
        assert request.url.params["state"] == "all"
        assert request.url.params["per_page"] == "100"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.example/repos/owner/repo/pulls?head=owner%3Ax&state=all&per_page=100",
        "https://api.github.com/user?head=owner%3Ax&state=all&per_page=100",
        "https://api.github.com/repos/owner/repo/pulls?head=other%3Ax&state=all&per_page=100",
    ],
)
async def test_pull_pagination_rejects_unsafe_next_links(next_url):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            request=request,
            headers={"Link": f'<{next_url}>; rel="next"'},
            json=[],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        with pytest.raises(GithubClientResponseError, match="Unsafe"):
            await GithubClient(http=http).list_pulls_for_head(
                "owner",
                "repo",
                head="owner:x",
                state="all",
                token="do-not-forward",
            )
    assert calls == 1


@pytest.mark.asyncio
async def test_pull_pagination_rejects_cycles():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"Link": f'<{request.url}>; rel="next"'},
            json=[],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        with pytest.raises(GithubClientResponseError, match="cycle"):
            await GithubClient(http=http).list_pulls_for_head(
                "owner", "repo", head="owner:x", token="app-token"
            )


@pytest.mark.asyncio
async def test_pull_fetch_rejects_malformed_json_as_an_upstream_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, content=b"{")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        with pytest.raises(GithubClientResponseError, match="valid JSON"):
            await GithubClient(http=http).get_pull("owner", "repo", 7)


@pytest.mark.asyncio
async def test_pull_list_rejects_non_object_members():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=[{"number": 1}, 2])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        with pytest.raises(GithubClientResponseError, match="non-object"):
            await GithubClient(http=http).list_pulls_for_head(
                "owner",
                "repo",
                head="owner:x",
                token="app-token",
            )
