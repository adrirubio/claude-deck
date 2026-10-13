"""A test instance (``settings.test_instance``) is isolated from the host.

It runs no dispatch scheduler, never runs the start-up relay cleanup (which
signals every ``tmux attach-session`` on the host), and never contacts GitHub.
These tests replace the cleanup with a recorder: they never run the real one.
"""

import httpx
import pytest
from pydantic_settings import BaseSettings
from types import SimpleNamespace

from app import main
from app.config import Settings, settings
from app.services import github_app_auth_service, github_client
from app.services.cc_bridge import pty_relay
from app.services.github_offline import OFFLINE_MESSAGE, OfflineGithubTransport, github_http_client


@pytest.fixture
def startup_calls(monkeypatch):
    """Record the start-up actions instead of running them."""
    calls: list[str] = []

    async def no_db():
        calls.append("init_db")

    async def no_cleanup_expired(_db):
        return None

    async def scheduler_start():
        calls.append("scheduler_start")

    async def scheduler_shutdown():
        calls.append("scheduler_shutdown")

    async def close_relays():
        calls.append("close_all_relays")

    async def campaign_start():
        calls.append("campaign_start")

    async def campaign_shutdown():
        calls.append("campaign_shutdown")

    monkeypatch.setattr(main, "init_db", no_db)
    monkeypatch.setattr(main.agent_bridge_attachment_service, "cleanup_expired", no_cleanup_expired)
    monkeypatch.setattr(main.github_dispatch_scheduler, "start", scheduler_start)
    monkeypatch.setattr(main.github_dispatch_scheduler, "shutdown", scheduler_shutdown)
    monkeypatch.setattr(main, "test_instance_campaign_poller", SimpleNamespace(
        start=campaign_start, shutdown=campaign_shutdown), raising=False)
    monkeypatch.setattr(pty_relay, "cleanup_orphaned_relays", lambda: calls.append("relay_cleanup"))
    monkeypatch.setattr(pty_relay, "close_all_relays", close_relays)
    return calls


@pytest.mark.asyncio
async def test_test_instance_skips_scheduler_and_relay_cleanup(monkeypatch, startup_calls):
    monkeypatch.setattr(settings, "test_instance", True)

    async with main.lifespan(main.app):
        pass

    assert "relay_cleanup" not in startup_calls
    assert "scheduler_start" not in startup_calls
    assert startup_calls == ["init_db", "campaign_start", "campaign_shutdown",
                             "scheduler_shutdown", "close_all_relays"]


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [False, True])
async def test_normal_instance_keeps_scheduler_and_relay_cleanup(monkeypatch, startup_calls, identity):
    monkeypatch.setattr(settings, "test_instance", False)
    monkeypatch.setattr(settings, "test_instance_root", "/tmp/synthetic-instance" if identity else "")
    monkeypatch.setattr(settings, "test_instance_token", "synthetic-test-token" if identity else "")

    async with main.lifespan(main.app):
        pass

    assert startup_calls == [
        "init_db", "scheduler_start", "relay_cleanup", "scheduler_shutdown", "close_all_relays",
    ]


def _settings_from_environment() -> Settings:
    # The root conftest builds Settings() from defaults only. The instance
    # script sets TEST_INSTANCE in the environment, so read it the real way.
    built = Settings.__new__(Settings)
    BaseSettings.__init__(built, _env_file=None)
    return built


def test_test_instance_setting_reads_the_environment(monkeypatch):
    monkeypatch.setenv("TEST_INSTANCE", "1")
    assert _settings_from_environment().test_instance is True
    monkeypatch.delenv("TEST_INSTANCE")
    assert _settings_from_environment().test_instance is False


@pytest.mark.asyncio
async def test_offline_transport_refuses_every_request_without_a_socket():
    client = github_http_client("https://api.github.com", Settings(_env_file=None, test_instance=True))
    async with client:
        assert isinstance(client._transport, OfflineGithubTransport)
        with pytest.raises(httpx.ConnectError, match=OFFLINE_MESSAGE):
            await client.get("/repos/example-org/sample-app")


def test_normal_instance_uses_the_network_transport():
    client = github_http_client("https://api.github.com", Settings(_env_file=None, test_instance=False))
    assert not isinstance(client._transport, OfflineGithubTransport)


@pytest.mark.asyncio
async def test_github_client_is_offline_on_a_test_instance(monkeypatch):
    monkeypatch.setattr(settings, "test_instance", True)
    client = github_client.GithubClient(token="")
    http = client._client()
    async with http:
        assert isinstance(http._transport, OfflineGithubTransport)


@pytest.mark.asyncio
async def test_github_app_auth_is_offline_on_a_test_instance():
    service = github_app_auth_service.GithubAppAuthService(
        config=Settings(_env_file=None, test_instance=True)
    )
    http = service._client()
    async with http:
        assert isinstance(http._transport, OfflineGithubTransport)


@pytest.mark.asyncio
async def test_health_reports_the_run_identity_only_on_a_test_instance(monkeypatch):
    monkeypatch.setattr(settings, "test_instance", True)
    monkeypatch.setattr(settings, "test_instance_root", "/tmp/deck-e2e.synthetic")
    monkeypatch.setattr(settings, "test_instance_token", "synthetic-run-token-0001")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/health")).json()
    assert body["test_instance"] == {
        "root": "/tmp/deck-e2e.synthetic", "token": "synthetic-run-token-0001",
    }


@pytest.mark.asyncio
async def test_health_is_unchanged_on_a_normal_installation(monkeypatch):
    monkeypatch.setattr(settings, "test_instance", False)
    monkeypatch.setattr(settings, "test_instance_root", "/tmp/deck-e2e.synthetic")
    monkeypatch.setattr(settings, "test_instance_token", "synthetic-run-token-0001")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/health")).json()
    assert set(body) == {"name", "version", "status"}


def test_run_identity_settings_stay_out_of_repr():
    configured = Settings(_env_file=None, test_instance_root="/tmp/x", test_instance_token="secret-token")
    assert "secret-token" not in repr(configured)
    assert "/tmp/x" not in repr(configured)
