"""Unreadable CI is a safe observation, with a fixed grace period."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.services import required_ci_attention as attention
from app.services.github_check_observation import GithubCheckObservationError


@pytest.mark.parametrize("age,visible", [(-1, False), (899, False), (900, True), (901, True)])
@pytest.mark.parametrize("aware", [False, True])
def test_signal_uses_first_observation_and_utc_grace_boundary(age, visible, aware):
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    since = now - timedelta(seconds=age)
    if not aware:
        since = since.replace(tzinfo=None)
    item = SimpleNamespace(checks_unavailable_since=since, checks_unavailable_reason="api_error",
                           dispatch_status="verifying")
    signal = attention.signal(item, now=now)
    assert (signal is not None) == visible
    if signal is not None:
        assert signal.since == now - timedelta(seconds=age)
        assert signal.reason == "api_error"
        assert signal.label == "Required CI cannot be read"


@pytest.mark.parametrize("state", ["merged", "completed"])
def test_terminal_item_has_no_attention(state):
    item = SimpleNamespace(checks_unavailable_since=datetime.utcnow() - timedelta(hours=1),
                           checks_unavailable_reason="api_error", dispatch_status=state)
    assert attention.signal(item) is None


@pytest.mark.parametrize("status,message,reason", [
    (401, "Bad credentials", "permission_missing"),
    (403, "Resource not accessible by integration", "permission_missing"),
    (403, "Resource not accessible by personal access token", "permission_missing"),
    (403, "API rate limit exceeded", "api_error"),
    (403, {"synthetic": "private-error"}, "api_error"),
    (404, "Not Found", "api_error"),
    (503, "synthetic-private-error", "api_error"),
])
def test_http_reasons_use_known_codes_only(status, message, reason):
    response = httpx.Response(status, json={"message": message}, request=httpx.Request("GET", "https://example.test"))
    error = GithubCheckObservationError("github_checks_unavailable")
    error.__cause__ = httpx.HTTPStatusError("synthetic-private-error", request=response.request, response=response)
    assert attention.error_reason(error) == reason


@pytest.mark.parametrize("cause", [httpx.ConnectError("synthetic-private-error"), TimeoutError("synthetic-private-error")])
def test_transport_errors_have_a_fixed_reason(cause):
    error = GithubCheckObservationError("github_checks_unavailable")
    error.__cause__ = cause
    assert attention.error_reason(error) == "api_error"


@pytest.mark.parametrize("reason", [None, "synthetic-private-error", {}, "github_checks_unavailable"])
def test_unknown_reason_never_exposes_exception_prose(reason):
    item = SimpleNamespace(checks_unavailable_since=datetime.utcnow() - timedelta(hours=1),
                           checks_unavailable_reason=reason, dispatch_status="verifying")
    signal = attention.signal(item)
    assert signal.reason == "unknown"
    assert "synthetic-private-error" not in signal.model_dump_json()


def test_known_missing_workflow_reason_is_retained():
    assert attention.error_reason(GithubCheckObservationError("workflow_missing")) == "workflow_missing"
