"""Read-only GitHub REST client for autonomous dispatch."""
from __future__ import annotations

import httpx

from app.config import settings

_GITHUB_API = "https://api.github.com"


class GithubClient:
    """Thin async wrapper over the read-only GitHub calls dispatch needs."""

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
                if issue.get("state") == "open" and "pull_request" not in issue:
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


github_client = GithubClient()
