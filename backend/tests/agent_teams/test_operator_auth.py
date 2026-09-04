"""Spec §3.7 test 20 — require_operator refuses every credential an agent can obtain."""
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service

OPERATOR_TOKEN = "0f3c9a71b25e4d8fa6c1e07b9d24misalign"


@pytest_asyncio.fixture
async def client_and_db(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, maker
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def operator_token_configured(monkeypatch):
    """Configure the operator token for the duration of one test."""
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)
    return OPERATOR_TOKEN


@pytest.fixture
def operator_token_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "")


async def _leased_scope_and_workspace(maker, tmp_path: Path):
    """A scope with one leased workspace, so force-release reaches its own logic."""
    async with maker() as db:
        preset = AgentTeamPreset(
            name=f"Operator {tmp_path.name}", description="", created_by="test"
        )
        db.add(preset)
        await db.flush()
        repo_path = tmp_path / "repo"
        repo_path.mkdir(exist_ok=True)
        scope = TeamGithubScope(
            preset_id=preset.id,
            repo_owner="o",
            repo_name=f"r-{preset.id}",
            repo_path=str(repo_path),
        )
        db.add(scope)
        await db.flush()
        item = GithubWorkItem(
            scope_id=scope.id,
            issue_number=1,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="merged",
        )
        db.add(item)
        await db.flush()
        workspace = GithubWorkspace(
            scope_id=scope.id,
            path=str(tmp_path / "ws"),
            kind="worktree",
            leased_item_id=item.id,
            leased_at=datetime.utcnow(),
            lease_token="lease-current",
        )
        db.add(workspace)
        await db.commit()
        return scope.id, workspace.id, item.id


async def _agent_session_token(maker) -> str:
    """Create a real agent capability token for the negative credential test."""
    token = "agent-session-token-for-operator-test"
    async with maker() as db:
        member = MailTeamMember(
            identity_key="slot:operator-test",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Agent",
        )
        db.add(member)
        await db.flush()
        db.add(
            MailAgentSession(
                member_id=member.id,
                source="mcp",
                session_key="operator-test",
                capability_token_hash=agent_mail_service.hash_capability_token(token),
            )
        )
        await db.commit()
    return token


async def _external_actor_token(client: httpx.AsyncClient) -> str:
    """Mint a real external-actor token rather than testing a fabricated string."""
    response = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={
            "actor_key": "operator-auth-test",
            "display_name": "Operator Auth Test",
            "kind": "supervisor",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _routes(scope_id: int, workspace_id: int, item_id: int):
    listing = (
        "listing",
        "get",
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces",
        None,
    )
    force_release = (
        "force-release",
        "post",
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces/"
        f"{workspace_id}/force-release",
        {"force": True, "reason": "owner is unavailable"},
    )
    cancel_active_continuation = (
        "cancel-active-continuation",
        "post",
        f"/api/v1/agent-teams/github-work-items/{item_id}/scope-revisions/1/cancel",
        {
            "cancel": True,
            "dispatch_nonce": "operator-auth-test",
            "reason": "operator auth boundary test",
        },
    )
    return [listing, force_release, cancel_active_continuation]


async def _call(client, method, url, body, headers):
    if method == "get":
        return await client.get(url, headers=headers)
    return await client.post(url, json=body, headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "", "anything-at-all"])
async def test_unconfigured_install_refuses_with_503_whatever_the_header(
    client_and_db, tmp_path, operator_token_unconfigured, header
):
    """An empty configured secret refuses even absent and empty headers."""
    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)
    headers = {} if header is None else {"X-Deck-Operator-Token": header}

    for label, method, url, body in _routes(scope_id, workspace_id, item_id):
        response = await _call(client, method, url, body, headers)
        assert response.status_code == 503, f"{label}: {response.status_code} {response.text}"
        assert response.json()["detail"] == "operator_token_unconfigured", label


@pytest.mark.asyncio
async def test_no_header_is_required_and_a_wrong_one_is_invalid(
    client_and_db, tmp_path, operator_token_configured
):
    """The two 401 outcomes remain distinguishable."""
    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)

    for label, method, url, body in _routes(scope_id, workspace_id, item_id):
        absent = await _call(client, method, url, body, {})
        assert absent.status_code == 401, label
        assert absent.json()["detail"] == "operator_token_required", label

        wrong = await _call(client, method, url, body, {"X-Deck-Operator-Token": "wrong"})
        assert wrong.status_code == 401, label
        assert wrong.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token,why",
    [
        (OPERATOR_TOKEN[:-1], "a prefix of the real token"),
        (OPERATOR_TOKEN + "X", "the real token plus a trailing byte"),
        (OPERATOR_TOKEN.upper(), "the real token in the wrong case"),
    ],
)
async def test_near_miss_tokens_are_invalid(
    client_and_db, tmp_path, operator_token_configured, token, why
):
    """Reject the values a prefix, containment, or truncating check would accept."""
    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)

    for label, method, url, body in _routes(scope_id, workspace_id, item_id):
        response = await _call(
            client, method, url, body, {"X-Deck-Operator-Token": token}
        )
        assert response.status_code == 401, f"{label}: {why} was accepted"
        assert response.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
async def test_a_non_ascii_header_is_refused_rather_than_crashing(
    client_and_db, tmp_path, operator_token_configured
):
    """Compare bytes so a non-ASCII header produces 401 rather than TypeError."""
    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)
    headers = {"X-Deck-Operator-Token": "café-not-a-token".encode("latin-1")}

    for label, method, url, body in _routes(scope_id, workspace_id, item_id):
        response = await _call(client, method, url, body, headers)
        assert response.status_code == 401, f"{label}: {response.status_code}"
        assert response.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
async def test_an_agent_session_token_does_not_admit_an_operator_route(
    client_and_db, tmp_path, operator_token_configured
):
    """A real agent credential must not open any operator route."""
    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)
    session_token = await _agent_session_token(maker)
    headers = {"X-Deck-Session-Token": session_token}

    for label, method, url, body in _routes(scope_id, workspace_id, item_id):
        response = await _call(client, method, url, body, headers)
        assert response.status_code == 401, label
        assert response.json()["detail"] == "operator_token_required", label


@pytest.mark.asyncio
async def test_a_self_minted_external_actor_token_does_not_admit_an_operator_route(
    client_and_db, tmp_path, operator_token_configured
):
    """The cheapest local actor credential must not act as an operator token."""
    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)
    actor_token = await _external_actor_token(client)

    for label, method, url, body in _routes(scope_id, workspace_id, item_id):
        as_bearer = await _call(
            client, method, url, body, {"Authorization": f"Bearer {actor_token}"}
        )
        assert as_bearer.status_code == 401, f"{label}: bearer actor token admitted"
        assert as_bearer.json()["detail"] == "operator_token_required", label

        as_operator = await _call(
            client,
            method,
            url,
            body,
            {"X-Deck-Operator-Token": actor_token},
        )
        assert as_operator.status_code == 401, f"{label}: actor token admitted as operator"
        assert as_operator.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
async def test_the_configured_operator_token_is_accepted(
    client_and_db, tmp_path, operator_token_configured, monkeypatch
):
    """A valid credential reaches each route's own behavior."""
    from app.services import github_workspace_service as ws_module

    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)
    headers = {"X-Deck-Operator-Token": operator_token_configured}

    async def _fake_runner(args):
        return 0, ""

    monkeypatch.setattr(ws_module.github_workspace_service, "_runner", _fake_runner)

    listing = await client.get(
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces", headers=headers
    )
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["workspaces"]) == 1

    forced = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces/"
        f"{workspace_id}/force-release",
        json={"force": True, "reason": "owner is unavailable"},
        headers=headers,
    )
    assert forced.status_code not in (401, 503), forced.text

    cancelled = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item_id}/scope-revisions/1/cancel",
        json={
            "cancel": True,
            "dispatch_nonce": "operator-auth-test",
            "reason": "operator auth boundary test",
        },
        headers=headers,
    )
    assert cancelled.status_code not in (401, 503), cancelled.text


@pytest.mark.asyncio
async def test_the_credential_is_checked_before_the_scope_is_looked_up(
    client_and_db, tmp_path, operator_token_configured
):
    """An unauthenticated caller must not learn whether a scope exists."""
    client, _ = client_and_db
    missing_scope = "/api/v1/agent-teams/github-scopes/999999/workspaces"

    assert (await client.get(missing_scope)).status_code == 401
    assert (
        await client.get(
            missing_scope,
            headers={"X-Deck-Operator-Token": operator_token_configured},
        )
    ).status_code == 404
