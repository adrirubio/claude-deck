"""GitHub clients that respect the test-instance setting.

A test instance (``settings.test_instance``) must never contact GitHub. Its
clients use a transport that fails every request as a connection error, so
callers take their existing "GitHub unreachable" paths and no socket opens.
The separate campaign client reads fixed milestone data from the seed.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

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


class OfflineCampaignClient:
    """Read fixed milestone data from the isolated test-instance seed."""

    def __init__(self, config: Settings, repositories: dict):
        if not config.test_instance:
            raise RuntimeError("Offline campaign data requires a test instance")
        self._repositories = copy.deepcopy(repositories)

    @classmethod
    def from_seed(cls, config: Settings):
        if not config.test_instance:
            raise RuntimeError("Offline campaign data requires a test instance")
        if not config.test_instance_root:
            return cls(config, {})
        repositories = {}
        try:
            path = Path(config.test_instance_root) / "campaign-backlog.json"
            with path.open("rb") as seed:
                raw = seed.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Campaign seed is too large")
            data = json.loads(raw)
            for row in data["repositories"]:
                key = (row["owner"], row["repo"])
                if key in repositories or not isinstance(row["milestones"], list) or not isinstance(row["issues"], list):
                    raise ValueError("Invalid campaign seed")
                repositories[key] = row
        except (OSError, ValueError, KeyError, TypeError):
            repositories = {}
        return cls(config, repositories)

    def _repo(self, owner, repo):
        row = self._repositories.get((owner, repo))
        if row is None or row.get("available") is not True:
            raise LookupError("Offline campaign backlog unavailable")
        return row

    async def list_milestones(self, owner, repo):
        return copy.deepcopy(self._repo(owner, repo)["milestones"])

    async def get_issue(self, owner, repo, number):
        for issue in self._repo(owner, repo)["issues"]:
            if issue.get("number") == number:
                return copy.deepcopy(issue)
        raise LookupError("Offline campaign issue unavailable")

    async def list_milestone_issues(self, owner, repo, milestone):
        return copy.deepcopy([issue for issue in self._repo(owner, repo)["issues"]
                              if issue.get("milestone", {}).get("number") == milestone])
