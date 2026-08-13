"""GitHub REST client for autonomous dispatch.

Mostly read-only, but NOT entirely: `create_pull`, `merge_pull`, and
`mark_pull_ready_for_review` write. `merge_pull` is gated on
`scope.merge_policy == "auto"` by its only caller; the other writes have their
own dispatch-stage gates. Deployments that must not write to GitHub should
enforce that with a read-only token rather than relying on this module.
"""
from __future__ import annotations

from urllib.parse import parse_qs, quote, urlsplit

import httpx

from app.config import settings

_GITHUB_API = "https://api.github.com"


class GithubClient:
    """Thin async wrapper over the GitHub calls dispatch needs."""

    def __init__(self, http: httpx.AsyncClient | None = None, token: str | None = None):
        self._http = http
        self._token = token if token is not None else settings.github_token

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        return httpx.AsyncClient(base_url=_GITHUB_API, timeout=30.0)

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        authorization = self._token if token is None else token
        if authorization:
            headers["Authorization"] = f"Bearer {authorization}"
        return headers

    async def list_issues_with_label(self, owner: str, repo: str, label: str) -> list[dict]:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/issues",
                params={"labels": label, "state": "open", "per_page": 100},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return [issue for issue in resp.json() if "pull_request" not in issue]
        finally:
            if self._http is None:
                await client.aclose()

    async def get_open_issues_by_number(
        self, owner: str, repo: str, numbers: list[int]
    ) -> dict[int, dict]:
        issues = await self.get_issues_by_number(owner, repo, numbers)
        return {
            number: issue
            for number, issue in issues.items()
            if issue.get("state") == "open" and "pull_request" not in issue
        }

    async def get_issues_by_number(
        self, owner: str, repo: str, numbers: list[int]
    ) -> dict[int, dict]:
        if not numbers:
            return {}
        client = self._client()
        result: dict[int, dict] = {}
        try:
            for number in numbers:
                resp = await client.get(
                    f"/repos/{owner}/{repo}/issues/{number}",
                    headers=self._headers(),
                )
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                issue = resp.json()
                if "pull_request" not in issue:
                    result[number] = issue
            return result
        finally:
            if self._http is None:
                await client.aclose()

    async def list_repo_labels(self, owner: str, repo: str) -> list[str]:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/labels",
                params={"per_page": 100},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return [label["name"] for label in resp.json()]
        finally:
            if self._http is None:
                await client.aclose()

    async def get_pull(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        token: str | None = None,
    ) -> dict:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/pulls/{pr_number}",
                headers=self._headers(token),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._http is None:
                await client.aclose()

    async def get_ref(
        self,
        owner: str,
        repo: str,
        head: str,
        *,
        token: str,
    ) -> dict | None:
        client = self._client()
        encoded_ref = quote(f"heads/{head}", safe="")
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/git/ref/{encoded_ref}",
                headers=self._headers(token),
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        finally:
            if self._http is None:
                await client.aclose()

    async def get_repository(
        self,
        owner: str,
        repo: str,
        *,
        token: str,
    ) -> dict:
        client = self._client()
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}",
                headers=self._headers(token),
            )
            response.raise_for_status()
            return response.json()
        finally:
            if self._http is None:
                await client.aclose()

    async def list_pulls_for_head(
        self,
        owner: str,
        repo: str,
        *,
        head: str,
        base: str | None = None,
        state: str = "all",
        token: str,
    ) -> list[dict]:
        client = self._client()
        endpoint = f"/repos/{owner}/{repo}/pulls"
        params = {
            "head": head,
            "state": state,
            "per_page": "100",
        }
        if base is not None:
            params["base"] = base
        pulls: list[dict] = []
        seen_urls: set[str] = set()
        next_url: str | None = endpoint
        first = True
        try:
            while next_url is not None:
                if first:
                    response = await client.get(
                        next_url,
                        params=params,
                        headers=self._headers(token),
                    )
                    first = False
                else:
                    response = await client.get(
                        next_url,
                        headers=self._headers(token),
                    )
                response.raise_for_status()
                current_url = str(response.request.url)
                if current_url in seen_urls:
                    raise ValueError("GitHub pull pagination cycle detected")
                seen_urls.add(current_url)
                body = response.json()
                if not isinstance(body, list):
                    raise ValueError("GitHub pull list response was not a list")
                pulls.extend(body)
                next_link = response.links.get("next", {}).get("url")
                if not next_link:
                    next_url = None
                    continue
                candidate = response.request.url.join(next_link)
                parsed = urlsplit(str(candidate))
                query = parse_qs(parsed.query, keep_blank_values=True)
                expected_query = {key: [value] for key, value in params.items()}
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != "api.github.com"
                    or parsed.port is not None
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.path != endpoint
                    or any(query.get(key) != value for key, value in expected_query.items())
                ):
                    raise ValueError("Unsafe GitHub pull pagination link")
                candidate_text = str(candidate)
                if candidate_text in seen_urls:
                    raise ValueError("GitHub pull pagination cycle detected")
                next_url = candidate_text
            return pulls
        finally:
            if self._http is None:
                await client.aclose()

    async def create_pull(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        head: str,
        base: str,
        body: str,
        draft: bool,
        token: str,
    ) -> dict:
        client = self._client()
        try:
            response = await client.post(
                f"/repos/{owner}/{repo}/pulls",
                headers=self._headers(token),
                json={
                    "title": title,
                    "head": head,
                    "base": base,
                    "body": body,
                    "draft": draft,
                },
            )
            response.raise_for_status()
            return response.json()
        finally:
            if self._http is None:
                await client.aclose()

    async def list_check_runs_for_ref(self, owner: str, repo: str, ref: str) -> list[dict]:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/commits/{ref}/check-runs",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("check_runs", [])
        finally:
            if self._http is None:
                await client.aclose()

    async def get_combined_status_for_ref(self, owner: str, repo: str, ref: str) -> dict:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/commits/{ref}/status",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._http is None:
                await client.aclose()

    async def mark_pull_ready_for_review(self, pull_node_id: str) -> dict:
        client = self._client()
        try:
            resp = await client.post(
                "/graphql",
                headers=self._headers(),
                json={
                    "query": (
                        "mutation($pullRequestId: ID!) { "
                        "markPullRequestReadyForReview(input: { pullRequestId: $pullRequestId }) { "
                        "pullRequest { id } } }"
                    ),
                    "variables": {"pullRequestId": pull_node_id},
                },
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("errors"):
                raise httpx.HTTPStatusError(
                    str(body["errors"]),
                    request=resp.request,
                    response=resp,
                )
            return body
        finally:
            if self._http is None:
                await client.aclose()

    async def merge_pull(self, owner: str, repo: str, pr_number: int) -> dict:
        client = self._client()
        try:
            resp = await client.put(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._http is None:
                await client.aclose()


github_client = GithubClient()
