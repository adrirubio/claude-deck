"""Current CI execution selection. No live GitHub or production state."""
from copy import deepcopy

import httpx
import pytest

from app.services.github_check_observation import GithubCheckObservationError
from app.services.github_client import GithubClient

SHA = "a" * 40
PREFIX = "/repos/owner/repo"


def run(identity=10, *, number=None, suite=None, attempt=1, status="completed", conclusion="success", workflow=1, event="push", branch="work"):
    return {
        "id": identity, "run_number": number or identity, "check_suite_id": suite or identity,
        "run_attempt": attempt, "head_sha": SHA, "status": status, "conclusion": conclusion,
        "workflow_id": workflow, "event": event, "head_branch": branch, "pull_requests": [],
        "repository": {"id": 1, "full_name": "owner/repo"},
        "head_repository": {"id": 1, "full_name": "owner/repo"},
    }


def check(identity=100, *, suite=10, status="completed", conclusion="success", app=15368, name="CI"):
    return {
        "id": identity, "head_sha": SHA, "check_suite": {"id": suite},
        "status": status, "conclusion": conclusion, "name": name,
        "app": {"id": app, "slug": "github-actions" if app == 15368 else "external"},
    }


def job(identity=100, *, execution=10, attempt=1, status="completed", conclusion="success", name="CI"):
    return {
        "id": identity, "run_id": execution, "run_attempt": attempt, "head_sha": SHA,
        "status": status, "conclusion": conclusion, "name": name,
        "check_run_url": f"https://api.github.com{PREFIX}/check-runs/{identity}",
    }


class API:
    def __init__(self, checks=None, runs=None, jobs=None, history=None, pulls=None, latest=None):
        self.checks = checks or []
        self.latest = latest
        self.runs = runs or []
        self.jobs = jobs or {}
        self.history = history or {}
        self.pulls = pulls or []
        self.requests = []
        self.after_jobs = None

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer polling-token"
        assert request.url.host == "api.github.com"
        if path.endswith("/check-runs"):
            assert request.url.params["filter"] in {"all", "latest"}
            checks = self.latest if request.url.params["filter"] == "latest" and self.latest is not None else self.checks
            body = {"total_count": len(checks), "check_runs": checks}
        elif path.endswith("/actions/runs"):
            assert request.url.params["head_sha"] == SHA
            body = {"total_count": len(self.runs), "workflow_runs": self.runs}
        elif path.endswith("/jobs"):
            identity = int(path.split("/")[-2])
            rows = self.history.get(identity, []) if request.url.params["filter"] == "all" else self.jobs.get(identity, [])
            body = {"total_count": len(rows), "jobs": rows}
            if self.after_jobs:
                self.after_jobs(self)
        elif path.endswith("/pulls"):
            assert request.url.params["state"] == "all"
            body = self.pulls
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=deepcopy(body), request=request)


async def observe(api):
    async with httpx.AsyncClient(transport=httpx.MockTransport(api), base_url="https://api.github.com") as http:
        return await GithubClient(http=http, token="polling-token").list_check_runs_for_ref("owner", "repo", SHA)


@pytest.mark.asyncio
async def test_old_cancelled_failure_and_jobless_replacement_are_pending():
    api = API([check(conclusion="failure")], [run(conclusion="cancelled"), run(11, status="queued", conclusion=None)])
    result = await observe(api)
    assert len(result) == 1
    assert result[0]["status"] == "queued"
    assert result[0]["workflow_run_id"] == 11
    assert "id" not in result[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("conclusion", ["success", "failure"])
async def test_replacement_result_excludes_old_failure(conclusion):
    api = API(
        [check(conclusion="failure"), check(101, suite=11, conclusion=conclusion)],
        [run(conclusion="cancelled"), run(11, conclusion=conclusion)],
        {11: [job(101, execution=11, conclusion=conclusion)]},
    )
    result = await observe(api)
    assert {row.get("id") for row in result} == {101, None}
    assert {row["conclusion"] for row in result} == {conclusion}


@pytest.mark.asyncio
@pytest.mark.parametrize("difference", ["workflow_id", "event", "head_branch"])
async def test_unrelated_execution_cannot_replace_a_failure(difference):
    newer = run(11)
    newer[difference] = {"workflow_id": 2, "event": "workflow_dispatch", "head_branch": "other"}[difference]
    api = API([check(conclusion="failure"), check(101, suite=11)], [run(conclusion="failure"), newer], {10: [job(conclusion="failure")], 11: [job(101, execution=11)]})
    result = await observe(api)
    assert any(row.get("id") == 100 and row["conclusion"] == "failure" for row in result)


@pytest.mark.asyncio
async def test_duplicate_names_external_failure_and_allowed_job_failure_remain():
    api = API([check(conclusion="failure"), check(101, app=2, conclusion="failure"), check(102, suite=12)], [run(), run(12, workflow=2)], {10: [job(conclusion="failure")], 12: [job(102, execution=12)]})
    result = await observe(api)
    assert {row.get("id") for row in result if row["conclusion"] == "failure"} == {100, 101}


@pytest.mark.asyncio
async def test_external_rerun_keeps_github_latest_selection():
    current = check(101, app=2)
    api = API([check(app=2, conclusion="failure"), current], latest=[current])
    result = await observe(api)
    assert result == [current]


@pytest.mark.asyncio
async def test_external_current_failure_is_retained_after_rerun():
    current = check(101, app=2, conclusion="failure")
    api = API([check(app=2), current], latest=[current])
    assert await observe(api) == [current]


@pytest.mark.asyncio
async def test_same_suite_rerun_uses_check_ids_and_retains_prior_success():
    api = API(
        [check(conclusion="failure"), check(101), check(102)],
        [run(attempt=2)],
        {10: [job(101, attempt=2), job(102, attempt=1)]},
        {10: [job(conclusion="failure"), job(101, attempt=2), job(102)]},
    )
    result = await observe(api)
    assert {row.get("id") for row in result} == {101, 102, None}
    assert all(row["conclusion"] == "success" for row in result)


@pytest.mark.asyncio
async def test_same_suite_pending_rerun_ignores_proven_old_checks():
    api = API([check(conclusion="failure")], [run(attempt=2, status="queued", conclusion=None)], history={10: [job(conclusion="failure")]})
    result = await observe(api)
    assert len(result) == 1 and result[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_current_failed_job_remains_failed_while_workflow_runs():
    api = API([check(conclusion="failure")], [run(status="in_progress", conclusion=None)], {10: [job(conclusion="failure")]})
    result = await observe(api)
    assert result[0]["conclusion"] == "failure"
    assert result[1]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_empty_pr_metadata_resolves_unique_actual_pull():
    pull = {"id": 700, "number": 7, "head": {"sha": SHA, "ref": "work", "repo": {"id": 1}}, "base": {"repo": {"id": 1}}}
    api = API([check()], [run(event="pull_request")], {10: [job()]}, pulls=[pull])
    assert (await observe(api))[0]["conclusion"] == "success"
    assert sum(r.url.path.endswith("/pulls") for r in api.requests) == 2


@pytest.mark.asyncio
async def test_ambiguous_pr_context_is_unavailable():
    pull = {"id": 700, "number": 7, "head": {"sha": SHA, "ref": "work", "repo": {"id": 1}}, "base": {"repo": {"id": 1}}}
    api = API([check()], [run(event="pull_request")], {10: [job()]}, pulls=[pull, {**pull, "id": 701, "number": 8}])
    with pytest.raises(GithubCheckObservationError, match="ambiguous_pull"):
        await observe(api)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["run_attempt", "new_run", "status", "new_external_check"])
async def test_change_during_observation_is_unavailable(mutation):
    api = API([check()], [run()], {10: [job()]})
    def mutate(api):
        if mutation == "run_attempt":
            api.runs[0]["run_attempt"] = 2
        elif mutation == "new_run":
            api.runs.append(run(11, status="queued", conclusion=None))
        elif mutation == "status":
            api.runs[0].update(status="in_progress", conclusion=None)
        else:
            api.checks.append(check(101, app=2, conclusion="failure"))
        api.after_jobs = None
    api.after_jobs = mutate
    with pytest.raises(GithubCheckObservationError, match="observation_changed"):
        await observe(api)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing_suite", "wrong_head", "wrong_repo", "orphan_check", "missing_jobs", "missing_job_check", "wrong_attempt", "duplicate_id", "unknown_check_in_current_suite", "invalid_status"])
async def test_incomplete_identity_is_unavailable(mutation):
    api = API([check()], [run()], {10: [job()]})
    if mutation == "missing_suite": api.runs[0].pop("check_suite_id")
    elif mutation == "wrong_head": api.runs[0]["head_sha"] = "b" * 40
    elif mutation == "wrong_repo": api.runs[0]["repository"]["full_name"] = "other/repo"
    elif mutation == "orphan_check": api.checks[0]["check_suite"]["id"] = 999
    elif mutation == "missing_jobs": api.jobs = {}
    elif mutation == "missing_job_check": api.jobs[10][0]["check_run_url"] = f"https://evil.test{PREFIX}/check-runs/100"
    elif mutation == "wrong_attempt": api.jobs[10][0]["run_attempt"] = 2
    elif mutation == "duplicate_id": api.checks.append(deepcopy(api.checks[0]))
    elif mutation == "unknown_check_in_current_suite": api.checks.append(check(101))
    else: api.runs[0]["status"] = ["completed"]
    with pytest.raises(GithubCheckObservationError):
        await observe(api)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 500])
async def test_actions_read_failure_is_sanitized(status):
    api = API()
    def handler(request):
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(status, request=request, json={"message": "secret response"})
        return api(request)
    with pytest.raises(GithubCheckObservationError, match="^github_checks_unavailable$"):
        await observe(handler)


@pytest.mark.asyncio
async def test_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("secret transport", request=request)
    with pytest.raises(GithubCheckObservationError, match="^github_checks_unavailable$"):
        await observe(handler)


@pytest.mark.asyncio
async def test_pagination_reads_later_external_failure():
    api = API()
    def handler(request):
        if request.url.path.endswith("/check-runs"):
            page = int(request.url.params["page"])
            rows = [check(i + 1, app=2) for i in range(100)] if page == 1 else [check(101, app=2, conclusion="failure")]
            check_filter = request.url.params["filter"]
            headers = {"Link": f'<https://api.github.com{PREFIX}/commits/{SHA}/check-runs?filter={check_filter}&per_page=100&page=2>; rel="next"'} if page == 1 else {}
            return httpx.Response(200, request=request, headers=headers, json={"total_count": 101, "check_runs": rows})
        return api(request)
    result = await observe(handler)
    assert len(result) == 101 and result[-1]["conclusion"] == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["cap", "missing_page", "unsafe_link"])
async def test_incomplete_pagination_is_unavailable(case):
    def handler(request):
        count = 501 if case == "cap" else 101
        rows = [check(i + 1, app=2) for i in range(100)]
        headers = {"Link": '<https://evil.test/next>; rel="next"'} if case == "unsafe_link" else {}
        return httpx.Response(200, request=request, headers=headers, json={"total_count": count, "check_runs": rows})
    with pytest.raises(GithubCheckObservationError):
        await observe(handler)
