"""GitHub REST client for autonomous dispatch.

Mostly read-only, but NOT entirely: `create_pull`, `merge_pull`, and
`mark_pull_ready_for_review` write. `merge_pull` is gated on
`scope.merge_policy == "auto"` by its only caller; the other writes have their
own dispatch-stage gates. Deployments that must not write to GitHub should
enforce that with a read-only token rather than relying on this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from app.config import settings

_GITHUB_API = "https://api.github.com"
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_GIT_ENTRY_MODES = {
    "blob": {"100644", "100755", "120000"},
    "tree": {"040000"},
    "commit": {"160000"},
}


class GithubClientResponseError(RuntimeError):
    """GitHub returned a response Deck cannot safely interpret."""


@dataclass(frozen=True)
class GithubCommitSnapshot:
    sha: str
    tree_sha: str


@dataclass(frozen=True)
class GithubTreeEntry:
    path: str
    mode: str
    object_type: str
    sha: str


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

    @staticmethod
    def _git_sha(value: object, label: str) -> str:
        if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
            raise GithubClientResponseError(f"GitHub {label} SHA was invalid")
        return value

    @staticmethod
    def _require_expected_response(
        response: httpx.Response,
        *,
        endpoint: str,
        label: str,
    ) -> None:
        parsed = urlsplit(str(response.request.url))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.github.com"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != endpoint
        ):
            raise GithubClientResponseError(
                f"Unsafe GitHub {label} response location"
            )

    @staticmethod
    def _git_path(value: object) -> str:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise GithubClientResponseError("GitHub tree entry path was invalid")
        if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
            raise GithubClientResponseError("GitHub tree entry path was invalid")
        return value

    @staticmethod
    def _json_object(response: httpx.Response, label: str) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise GithubClientResponseError(
                f"GitHub {label} response was not valid JSON"
            ) from exc
        if not isinstance(body, dict):
            raise GithubClientResponseError(
                f"GitHub {label} response was not an object"
            )
        return body

    @staticmethod
    def _json_list(response: httpx.Response, label: str) -> list:
        try:
            body = response.json()
        except ValueError as exc:
            raise GithubClientResponseError(
                f"GitHub {label} response was not valid JSON"
            ) from exc
        if not isinstance(body, list):
            raise GithubClientResponseError(
                f"GitHub {label} response was not a list"
            )
        return body

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
            return self._json_object(resp, "pull request")
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
            return self._json_object(response, "git ref")
        finally:
            if self._http is None:
                await client.aclose()

    async def get_commit_snapshot(
        self,
        owner: str,
        repo: str,
        sha: str,
        *,
        token: str,
    ) -> GithubCommitSnapshot:
        requested_sha = self._git_sha(sha, "commit request")
        endpoint = f"/repos/{owner}/{repo}/git/commits/{requested_sha}"
        client = self._client()
        try:
            response = await client.get(endpoint, headers=self._headers(token))
            response.raise_for_status()
            self._require_expected_response(
                response,
                endpoint=endpoint,
                label="commit",
            )
            body = self._json_object(response, "commit")
            response_sha = self._git_sha(body.get("sha"), "commit response")
            if response_sha != requested_sha:
                raise GithubClientResponseError(
                    "GitHub commit response did not match the requested SHA"
                )
            tree = body.get("tree")
            if not isinstance(tree, dict):
                raise GithubClientResponseError(
                    "GitHub commit response did not contain tree metadata"
                )
            return GithubCommitSnapshot(
                sha=response_sha,
                tree_sha=self._git_sha(tree.get("sha"), "commit tree"),
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def get_recursive_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        *,
        token: str,
    ) -> dict[str, GithubTreeEntry]:
        requested_sha = self._git_sha(tree_sha, "tree request")
        endpoint = f"/repos/{owner}/{repo}/git/trees/{requested_sha}"
        client = self._client()
        try:
            response = await client.get(
                endpoint,
                params={"recursive": "1"},
                headers=self._headers(token),
            )
            response.raise_for_status()
            self._require_expected_response(
                response,
                endpoint=endpoint,
                label="tree",
            )
            body = self._json_object(response, "tree")
            response_sha = self._git_sha(body.get("sha"), "tree response")
            if response_sha != requested_sha:
                raise GithubClientResponseError(
                    "GitHub tree response did not match the requested SHA"
                )
            if body.get("truncated") is not False:
                raise GithubClientResponseError(
                    "GitHub recursive tree response was truncated or inconclusive"
                )
            raw_entries = body.get("tree")
            if not isinstance(raw_entries, list):
                raise GithubClientResponseError(
                    "GitHub tree response did not contain an entry list"
                )
            entries: dict[str, GithubTreeEntry] = {}
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    raise GithubClientResponseError(
                        "GitHub tree response contained a non-object entry"
                    )
                path = self._git_path(raw_entry.get("path"))
                mode = raw_entry.get("mode")
                object_type = raw_entry.get("type")
                if (
                    not isinstance(mode, str)
                    or not isinstance(object_type, str)
                    or mode not in _GIT_ENTRY_MODES.get(object_type, set())
                ):
                    raise GithubClientResponseError(
                        "GitHub tree entry mode or object type was invalid"
                    )
                entry = GithubTreeEntry(
                    path=path,
                    mode=mode,
                    object_type=object_type,
                    sha=self._git_sha(raw_entry.get("sha"), "tree entry"),
                )
                existing = entries.get(path)
                if existing is not None and existing != entry:
                    raise GithubClientResponseError(
                        "GitHub tree response contained conflicting duplicate paths"
                    )
                entries[path] = entry
            return entries
        finally:
            if self._http is None:
                await client.aclose()

    async def get_repository(
        self,
        owner: str,
        repo: str,
        *,
        token: str | None = None,
    ) -> dict:
        client = self._client()
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}",
                headers=self._headers(token),
            )
            response.raise_for_status()
            return self._json_object(response, "repository")
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
                    raise GithubClientResponseError(
                        "GitHub pull pagination cycle detected"
                    )
                seen_urls.add(current_url)
                body = self._json_list(response, "pull list")
                if not all(isinstance(pull, dict) for pull in body):
                    raise GithubClientResponseError(
                        "GitHub pull list response contained a non-object"
                    )
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
                    raise GithubClientResponseError(
                        "Unsafe GitHub pull pagination link"
                    )
                candidate_text = str(candidate)
                if candidate_text in seen_urls:
                    raise GithubClientResponseError(
                        "GitHub pull pagination cycle detected"
                    )
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
            return self._json_object(response, "pull creation")
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
            body = self._json_object(resp, "check runs")
            check_runs = body.get("check_runs", [])
            if not isinstance(check_runs, list) or not all(
                isinstance(check, dict) for check in check_runs
            ):
                raise GithubClientResponseError(
                    "GitHub check runs response contained invalid entries"
                )
            return check_runs
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
            return self._json_object(resp, "combined status")
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
            body = self._json_object(resp, "GraphQL")
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
            return self._json_object(resp, "merge")
        finally:
            if self._http is None:
                await client.aclose()


github_client = GithubClient()
