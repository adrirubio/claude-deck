"""GitHub REST client for autonomous dispatch.

Mostly read-only, but NOT entirely: `merge_pull` and `mark_pull_ready_for_review`
both write. `merge_pull` is gated on `scope.merge_policy == "auto"` by its only
caller; `mark_pull_ready_for_review` is currently ungated. Deployments that must
not write to GitHub should enforce that with a read-only token rather than
relying on this module.
"""
from __future__ import annotations

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

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
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

    async def get_pull(self, owner: str, repo: str, pr_number: int) -> dict:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/pulls/{pr_number}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
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
