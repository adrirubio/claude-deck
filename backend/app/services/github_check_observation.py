"""Read a bounded, consistent view of the current GitHub Actions executions.

GitHub returns checks from replaced runs and attempts for the same commit.
Only proven replacement executions can remove these checks from verification.
An incomplete observation raises an error. It never supplies a green fallback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import httpx

_ACTIONS_APP_ID = 15368
_PENDING = {"queued", "requested", "waiting", "pending", "in_progress"}
_CONCLUSIONS = {
    "success", "failure", "neutral", "cancelled", "skipped", "timed_out",
    "action_required", "stale", "startup_failure",
}
_MAX_PAGES = 5
_MAX_REQUESTS = 64
_MAX_CONTEXTS = 16
_DEADLINE_SECONDS = 45


class GithubCheckObservationError(RuntimeError):
    """Checks are unavailable. This is not a failed implementation check."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise GithubCheckObservationError(reason)


def _positive(value: object) -> int:
    _require(type(value) is int and value > 0, "invalid_execution_identity")
    return value


def _state(row: dict) -> None:
    status, conclusion = row.get("status"), row.get("conclusion")
    _require(
        isinstance(status, str) and (
            (status in _PENDING and conclusion is None)
            or (status == "completed" and isinstance(conclusion, str) and conclusion in _CONCLUSIONS)
        ),
        "invalid_execution_state",
    )


@dataclass(frozen=True)
class _Run:
    id: int
    suite: int
    number: int
    attempt: int
    context: tuple
    status: str
    conclusion: str | None


class _Reader:
    def __init__(self, http: httpx.AsyncClient, headers: dict, owner: str, repo: str, sha: str):
        self.http, self.headers = http, headers
        self.prefix = f"/repos/{owner}/{repo}"
        self.repository, self.sha = f"{owner}/{repo}", sha
        self.remaining = _MAX_REQUESTS
        self.deadline = monotonic() + _DEADLINE_SECONDS
        self.pull_contexts: dict[tuple, tuple[int, ...]] = {}

    async def get(self, path: str, params: dict) -> tuple[object, httpx.Response]:
        self.remaining -= 1
        _require(self.remaining >= 0 and monotonic() < self.deadline, "observation_limit")
        response = await self.http.get(
            path, params=params, headers=self.headers, follow_redirects=False,
            timeout=max(0.01, self.deadline - monotonic()),
        )
        response.raise_for_status()
        url = urlsplit(str(response.request.url))
        _require(
            url.scheme == "https" and url.netloc == "api.github.com" and url.path == path,
            "unsafe_observation_location",
        )
        try:
            return response.json(), response
        except ValueError as exc:
            raise GithubCheckObservationError("invalid_observation_json") from exc

    async def pages(self, path: str, key: str | None, params: dict) -> list[dict]:
        rows: list[dict] = []
        seen: set[int] = set()
        total: int | None = None
        for page in range(1, _MAX_PAGES + 1):
            query = {**params, "per_page": 100, "page": page}
            body, response = await self.get(path, query)
            if key is None:
                entries = body
            else:
                _require(isinstance(body, dict), "invalid_observation_page")
                count = body.get("total_count")
                _require(type(count) is int and 0 <= count <= 100 * _MAX_PAGES, "observation_limit")
                _require(total is None or count == total, "observation_changed")
                total, entries = count, body.get(key)
            _require(isinstance(entries, list) and len(entries) <= 100, "invalid_observation_page")
            for row in entries:
                _require(isinstance(row, dict), "invalid_observation_entry")
                identity = _positive(row.get("id"))
                _require(identity not in seen, "duplicate_observation_identity")
                seen.add(identity)
                rows.append(row)
            next_link = response.links.get("next", {}).get("url")
            if next_link:
                url = urlsplit(str(response.request.url.join(next_link)))
                expected = {str(k): [str(v)] for k, v in {**query, "page": page + 1}.items()}
                _require(
                    url.scheme == "https" and url.netloc == "api.github.com"
                    and url.path == path and parse_qs(url.query) == expected,
                    "unsafe_observation_pagination",
                )
            if total is not None:
                _require(len(rows) <= total, "invalid_observation_count")
                if len(rows) == total:
                    _require(not next_link, "invalid_observation_count")
                    return rows
                _require(len(entries) == 100 and bool(next_link), "incomplete_observation")
            elif not next_link:
                return rows
        raise GithubCheckObservationError("observation_limit")

    async def runs(self) -> list[_Run]:
        rows = await self.pages(self.prefix + "/actions/runs", "workflow_runs", {"head_sha": self.sha})
        runs: list[_Run] = []
        repo_ids: set[int] = set()
        for row in rows:
            _require(row.get("head_sha") == self.sha, "execution_head_mismatch")
            repository, head_repo = row.get("repository"), row.get("head_repository")
            _require(isinstance(repository, dict) and isinstance(head_repo, dict), "invalid_execution_repository")
            full_name = repository.get("full_name")
            _require(isinstance(full_name, str) and full_name.casefold() == self.repository.casefold(), "execution_repository_mismatch")
            repo_id, head_repo_id = _positive(repository.get("id")), _positive(head_repo.get("id"))
            repo_ids.add(repo_id)
            head_name = head_repo.get("full_name")
            _require(isinstance(head_name, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", head_name) is not None, "invalid_execution_repository")
            event, branch, pulls = row.get("event"), row.get("head_branch"), row.get("pull_requests")
            _require(isinstance(event, str) and bool(event) and isinstance(branch, str) and bool(branch), "invalid_execution_context")
            _require(isinstance(pulls, list) and all(isinstance(p, dict) for p in pulls), "invalid_execution_context")
            numbers = tuple(sorted(_positive(p.get("number")) for p in pulls))
            if event in {"pull_request", "pull_request_target"}:
                cache_key = (head_repo_id, head_name, branch, repo_id)
                if cache_key not in self.pull_contexts:
                    candidates = await self.pages(
                        self.prefix + "/pulls", None,
                        {"head": head_name.split("/")[0] + ":" + branch, "state": "all"},
                    )
                    matches = []
                    for pull in candidates:
                        head, base = pull.get("head") or {}, pull.get("base") or {}
                        _require(isinstance(head, dict) and isinstance(base, dict), "invalid_pull_context")
                        head_repository, base_repository = head.get("repo") or {}, base.get("repo") or {}
                        _require(isinstance(head_repository, dict) and isinstance(base_repository, dict), "invalid_pull_context")
                        if (head.get("sha") == self.sha and head.get("ref") == branch
                                and head_repository.get("id") == head_repo_id
                                and base_repository.get("id") == repo_id):
                            matches.append(_positive(pull.get("number")))
                    _require(len(matches) == 1, "ambiguous_pull_execution_context")
                    self.pull_contexts[cache_key] = tuple(matches)
                resolved = self.pull_contexts[cache_key]
                _require(not numbers or numbers == resolved, "execution_pull_mismatch")
                numbers = resolved
            _state(row)
            runs.append(_Run(
                _positive(row.get("id")), _positive(row.get("check_suite_id")),
                _positive(row.get("run_number")), _positive(row.get("run_attempt")),
                (_positive(row.get("workflow_id")), event, branch, head_repo_id, numbers),
                row["status"], row.get("conclusion"),
            ))
        _require(len(repo_ids) <= 1, "execution_repository_mismatch")
        _require(len({run.suite for run in runs}) == len(runs), "duplicate_execution_suite")
        return runs

    async def observe(self) -> list[dict]:
        checks_path = self.prefix + f"/commits/{self.sha}/check-runs"
        checks = await self.pages(checks_path, "check_runs", {"filter": "all"})
        runs = await self.runs()
        suites = {run.suite: run for run in runs}
        external: list[dict] = []
        action_checks: dict[int, dict] = {}
        for check in checks:
            _require(check.get("head_sha") == self.sha, "check_head_mismatch")
            _state(check)
            app = check.get("app")
            _require(isinstance(app, dict), "invalid_check_application")
            app_id = _positive(app.get("id"))
            is_actions = app_id == _ACTIONS_APP_ID
            _require(is_actions == (app.get("slug") == "github-actions"), "invalid_actions_application")
            if not is_actions:
                external.append(check)
                continue
            suite_row = check.get("check_suite")
            _require(isinstance(suite_row, dict), "invalid_check_suite")
            suite = _positive(suite_row.get("id"))
            _require(suite in suites, "unresolved_check_execution")
            action_checks[check["id"]] = check
        selected: dict[tuple, _Run] = {}
        execution_numbers: set[tuple] = set()
        for run in runs:
            number_key = (run.context, run.number)
            _require(number_key not in execution_numbers, "duplicate_execution_number")
            execution_numbers.add(number_key)
            current = selected.get(run.context)
            if current is None or run.number > current.number:
                selected[run.context] = run
        _require(len(selected) <= _MAX_CONTEXTS, "observation_limit")
        effective = list(external)
        for run in selected.values():
            jobs = await self.pages(self.prefix + f"/actions/runs/{run.id}/jobs", "jobs", {"filter": "latest"})
            _require(bool(jobs) or run.status in _PENDING or run.conclusion not in {"success", "neutral", "skipped"}, "incomplete_current_jobs")
            job_checks: set[int] = set()
            for job in jobs:
                _require(job.get("run_id") == run.id and job.get("head_sha") == self.sha, "job_execution_mismatch")
                attempt = _positive(job.get("run_attempt"))
                _require(attempt <= run.attempt, "job_attempt_mismatch")
                _state(job)
                # The latest-jobs API can still expose the old attempt while a
                # rerun is queued. No old red result can spend budget then.
                if run.status in _PENDING and attempt < run.attempt:
                    _require(job.get("conclusion") in {"success", "neutral", "skipped"}, "unresolved_pending_attempt")
                url = urlsplit(str(job.get("check_run_url") or ""))
                prefix = self.prefix + "/check-runs/"
                _require(url.scheme == "https" and url.netloc == "api.github.com" and url.path.startswith(prefix) and not url.query and not url.fragment, "invalid_job_check_identity")
                suffix = url.path[len(prefix):]
                _require(suffix.isascii() and suffix.isdecimal(), "invalid_job_check_identity")
                check_id = _positive(int(suffix))
                _require(check_id not in job_checks, "duplicate_job_check_identity")
                job_checks.add(check_id)
                check = action_checks.get(check_id)
                _require(check is not None and check["check_suite"]["id"] == run.suite, "unresolved_job_check")
                _require(check.get("status") == job.get("status") and check.get("conclusion") == job.get("conclusion"), "observation_changed")
                effective.append({**check, "evidence_source": "github_actions_job", "workflow_run_id": run.id, "run_attempt": attempt})
            excluded = {
                check_id for check_id, check in action_checks.items()
                if check["check_suite"]["id"] == run.suite and check_id not in job_checks
            }
            if excluded:
                # The suite is reused on a rerun. Prove that omitted check IDs
                # belong to older attempts. Names do not establish replacement.
                _require(run.attempt > 1, "unresolved_current_checks")
                history = await self.pages(
                    self.prefix + f"/actions/runs/{run.id}/jobs", "jobs", {"filter": "all"},
                )
                proven_old: set[int] = set()
                for job in history:
                    _require(job.get("run_id") == run.id and job.get("head_sha") == self.sha, "job_execution_mismatch")
                    attempt = _positive(job.get("run_attempt"))
                    _require(attempt <= run.attempt, "job_attempt_mismatch")
                    if attempt < run.attempt:
                        url = urlsplit(str(job.get("check_run_url") or ""))
                        prefix = self.prefix + "/check-runs/"
                        _require(url.scheme == "https" and url.netloc == "api.github.com" and url.path.startswith(prefix) and not url.query and not url.fragment, "invalid_job_check_identity")
                        suffix = url.path[len(prefix):]
                        _require(suffix.isascii() and suffix.isdecimal(), "invalid_job_check_identity")
                        proven_old.add(_positive(int(suffix)))
                _require(excluded <= proven_old, "unresolved_current_checks")
            # This row is workflow evidence, not an invented aggregate check.
            effective.append({
                "name": f"GitHub Actions workflow {run.context[0]} (run {run.id}, attempt {run.attempt})",
                "status": run.status, "conclusion": run.conclusion,
                "evidence_source": "github_actions_workflow", "workflow_run_id": run.id,
                "run_attempt": run.attempt,
            })
        # Refuse an attempt or generation that changed during the job reads.
        self.pull_contexts.clear()
        _require(sorted(runs, key=lambda r: r.id) == sorted(await self.runs(), key=lambda r: r.id), "observation_changed")
        final_checks = await self.pages(checks_path, "check_runs", {"filter": "all"})
        _require(checks == final_checks, "observation_changed")
        return effective


async def observe_checks(http: httpx.AsyncClient, headers: dict, owner: str, repo: str, sha: str) -> list[dict]:
    _require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "invalid_check_head")
    _require(all(isinstance(v, str) and re.fullmatch(r"[\w.-]+", v) is not None for v in (owner, repo)), "invalid_check_repository")
    try:
        async with asyncio.timeout(_DEADLINE_SECONDS):
            return await _Reader(http, headers, owner, repo, sha).observe()
    except (httpx.HTTPError, TimeoutError) as exc:
        raise GithubCheckObservationError("github_checks_unavailable") from exc
