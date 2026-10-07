import httpx
import pytest

from app.services.github_client import (
    GithubClient,
    GithubClientResponseError,
    GithubTreeEntry,
)


COMMIT_SHA = "a" * 40
TREE_SHA = "b" * 40
BLOB_SHA = "c" * 40


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "ahead", "identical", "behind", "diverged", "wrong_common", "wrong_base",
    "foreign_url", "missing_url", "malformed_url", "user_url", "missing_common",
    "malformed_common", "unknown_status", "malformed_status", "foreign_endpoint",
])
async def test_exact_source_import_ancestry_response(case):
    endpoint = f"/repos/owner/repo/compare/{COMMIT_SHA}...{TREE_SHA}"
    seen = []
    def handler(request):
        seen.append(request)
        # The real compare response has no head_commit field.
        body = {"url": "https://api.github.com" + endpoint,
                "base_commit": {"sha": COMMIT_SHA},
                "merge_base_commit": {"sha": COMMIT_SHA}, "status": "ahead"}
        if case in {"identical", "behind", "diverged"}: body["status"] = case
        elif case == "wrong_common": body["merge_base_commit"]["sha"] = BLOB_SHA
        elif case == "wrong_base": body["base_commit"]["sha"] = BLOB_SHA
        elif case == "foreign_url": body["url"] = "https://example.invalid" + endpoint
        elif case == "missing_url": body.pop("url")
        elif case == "malformed_url": body["url"] = {"url": "invalid"}
        elif case == "user_url": body["url"] = "https://user@api.github.com" + endpoint
        elif case == "missing_common": body.pop("merge_base_commit")
        elif case == "malformed_common": body["merge_base_commit"]["sha"] = "invalid"
        elif case == "unknown_status": body["status"] = "unknown"
        elif case == "malformed_status": body["status"] = []
        return httpx.Response(200, request=request, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=(
        "https://example.invalid" if case == "foreign_endpoint" else "https://api.github.com")) as http:
        client = GithubClient(http=http, token="ambient-token")
        if case in {"ahead", "identical", "behind", "diverged", "wrong_common"}:
            assert await client.is_commit_ancestor("owner", "repo", COMMIT_SHA, TREE_SHA,
                token="explicit-token") is (case in {"ahead", "identical"})
        else:
            with pytest.raises(GithubClientResponseError):
                await client.is_commit_ancestor("owner", "repo", COMMIT_SHA, TREE_SHA,
                    token="explicit-token")
    assert seen[0].url.path == endpoint and seen[0].method == "GET"
    assert seen[0].headers["Authorization"] == "Bearer explicit-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "missing", "wrong_number", "boolean", "pull", "foreign_url", "foreign_endpoint", "malformed"])
async def test_exact_progress_issue_endpoint(case):
    seen = []
    def handler(request):
        seen.append(request)
        payload = {"number": 7, "html_url": "https://github.com/owner/repo/issues/7", "body": "Public issue facts."}
        if case == "missing": return httpx.Response(404, request=request)
        if case == "wrong_number": payload["number"] = 8
        if case == "boolean": payload["number"] = True
        if case == "pull": payload["pull_request"] = {}
        if case == "foreign_url": payload["html_url"] = "https://github.com/other/repo/issues/7"
        if case == "malformed": return httpx.Response(200, request=request, content=b"not JSON")
        return httpx.Response(200, request=request, json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.invalid" if case == "foreign_endpoint" else "https://api.github.com") as http:
        client = GithubClient(http=http)
        if case not in {"valid", "missing"}:
            with pytest.raises(GithubClientResponseError):
                await client.get_issue("owner", "repo", 7, token="explicit-token")
        else:
            result = await client.get_issue("owner", "repo", 7, token="explicit-token")
            assert result is None if case == "missing" else result["number"] == 7
    assert seen[0].method == "GET" and seen[0].url.path == "/repos/owner/repo/issues/7"
    assert seen[0].headers["Authorization"] == "Bearer explicit-token"


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
async def test_repository_labels_follow_safe_pagination_links():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params.get("page") == "2":
            return httpx.Response(200, request=request, json=[{"name": "design"}])
        return httpx.Response(
            200,
            request=request,
            json=[{"name": "dispatch"}],
            headers={"Link": '<https://api.github.com/repos/owner/repo/labels?per_page=100&page=2>; rel="next"'},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http)
        labels = await client.list_repo_labels("owner", "repo")

    assert labels == ["dispatch", "design"]
    assert [request.url.params.get("page", "1") for request in seen] == ["1", "2"]


@pytest.mark.asyncio
async def test_repository_labels_reject_unsafe_pagination_links():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json=[{"name": "dispatch"}],
            headers={"Link": '<https://attacker.invalid/repos/owner/repo/labels?per_page=100&page=2>; rel="next"'},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http)
        with pytest.raises(GithubClientResponseError, match="Unsafe GitHub label pagination"):
            await client.list_repo_labels("owner", "repo")


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


@pytest.mark.asyncio
async def test_commit_and_recursive_tree_use_explicit_token_and_preserve_identity():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/git/commits/" in request.url.path:
            return httpx.Response(
                200,
                request=request,
                json={"sha": COMMIT_SHA, "tree": {"sha": TREE_SHA}},
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "sha": TREE_SHA,
                "truncated": False,
                "tree": [
                    {
                        "path": "src/a.py",
                        "mode": "100644",
                        "type": "blob",
                        "sha": BLOB_SHA,
                    },
                    {
                        "path": "src/b.py",
                        "mode": "100755",
                        "type": "blob",
                        "sha": BLOB_SHA,
                    },
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        client = GithubClient(http=http, token="ambient-token")
        commit = await client.get_commit_snapshot(
            "owner", "repo", COMMIT_SHA, token="app-token"
        )
        tree = await client.get_recursive_tree(
            "owner", "repo", commit.tree_sha, token="app-token"
        )

    assert commit.sha == COMMIT_SHA
    assert commit.tree_sha == TREE_SHA
    assert tree == {
        "src/a.py": GithubTreeEntry("src/a.py", "100644", "blob", BLOB_SHA),
        "src/b.py": GithubTreeEntry("src/b.py", "100755", "blob", BLOB_SHA),
    }
    assert all(request.headers["Authorization"] == "Bearer app-token" for request in seen)
    assert seen[1].url.params["recursive"] == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,match",
    [
        ({"sha": "short", "tree": {"sha": TREE_SHA}}, "SHA"),
        ({"sha": COMMIT_SHA}, "tree metadata"),
        ({"sha": COMMIT_SHA, "tree": {"sha": "short"}}, "SHA"),
        ({"sha": "d" * 40, "tree": {"sha": TREE_SHA}}, "requested SHA"),
    ],
)
async def test_commit_snapshot_rejects_inconclusive_payloads(body, match):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=body)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        with pytest.raises(GithubClientResponseError, match=match):
            await GithubClient(http=http).get_commit_snapshot(
                "owner", "repo", COMMIT_SHA, token="app-token"
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,match",
    [
        ({"sha": TREE_SHA, "truncated": True, "tree": []}, "truncated"),
        ({"sha": TREE_SHA, "truncated": False, "tree": [1]}, "non-object"),
        (
            {
                "sha": TREE_SHA,
                "truncated": False,
                "tree": [
                    {"path": "../x", "mode": "100644", "type": "blob", "sha": BLOB_SHA}
                ],
            },
            "path",
        ),
        (
            {
                "sha": TREE_SHA,
                "truncated": False,
                "tree": [
                    {"path": "x", "mode": "040000", "type": "blob", "sha": BLOB_SHA}
                ],
            },
            "mode",
        ),
        (
            {
                "sha": TREE_SHA,
                "truncated": False,
                "tree": [
                    {"path": "x", "mode": "100644", "type": "blob", "sha": BLOB_SHA},
                    {"path": "x", "mode": "100755", "type": "blob", "sha": BLOB_SHA},
                ],
            },
            "duplicate",
        ),
    ],
)
async def test_recursive_tree_rejects_unsafe_or_inconclusive_payloads(body, match):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=body)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as http:
        with pytest.raises(GithubClientResponseError, match=match):
            await GithubClient(http=http).get_recursive_tree(
                "owner", "repo", TREE_SHA, token="app-token"
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["commit", "tree"])
async def test_git_reads_reject_cross_origin_response_locations(kind):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                request=request,
                headers={"Location": f"https://evil.example{request.url.path}"},
            )
        body = (
            {"sha": COMMIT_SHA, "tree": {"sha": TREE_SHA}}
            if kind == "commit"
            else {"sha": TREE_SHA, "truncated": False, "tree": []}
        )
        return httpx.Response(200, request=request, json=body)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.github.com",
        follow_redirects=True,
    ) as http:
        with pytest.raises(GithubClientResponseError, match="Unsafe"):
            if kind == "commit":
                await GithubClient(http=http).get_commit_snapshot(
                    "owner", "repo", COMMIT_SHA, token="app-token"
                )
            else:
                await GithubClient(http=http).get_recursive_tree(
                    "owner", "repo", TREE_SHA, token="app-token"
                )
