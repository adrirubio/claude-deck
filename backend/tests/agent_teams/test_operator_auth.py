"""Spec §3.7 test 20 — require_operator refuses every credential an agent can obtain."""
from datetime import datetime, timedelta
import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
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
    abandon = (
        "abandon",
        "post",
        f"/api/v1/agent-teams/github-work-items/{item_id}/abandon",
        {"reason": "operator auth boundary test"},
    )
    arming = [
        ("preset-update", "patch", "/api/v1/agent-teams/presets/999999", {"autonomy_enabled": True}),
        ("preset-delete", "delete", "/api/v1/agent-teams/presets/999999", None),
        ("scope-create", "post", "/api/v1/agent-teams/presets/999999/github-scopes", {"repo_owner": "o", "repo_name": "r", "repo_path": "/tmp/r"}),
        ("scope-update", "patch", f"/api/v1/agent-teams/github-scopes/{scope_id}", {"merge_policy": "auto"}),
        ("scope-delete", "delete", "/api/v1/agent-teams/github-scopes/999999", None),
        ("workspace-register", "post", "/api/v1/agent-teams/github-scopes/999999/workspaces", {"path": "/tmp/ws", "kind": "worktree"}),
        ("workspace-reprobe", "post", "/api/v1/agent-teams/github-scopes/999999/workspaces/999999/reprobe", None),
        ("slot-add", "post", "/api/v1/agent-teams/presets/999999/slots", {"display_name": "x", "provider": "codex-cli", "repo_path": "/tmp/r"}),
        ("slot-update", "patch", "/api/v1/agent-teams/slots/999999", {"enabled": False}),
        ("slot-delete", "delete", "/api/v1/agent-teams/slots/999999", None),
        ("slot-reorder", "post", "/api/v1/agent-teams/presets/999999/slots/reorder", {"slot_ids": []}),
    ]
    return [listing, force_release, cancel_active_continuation, abandon, *arming]


async def _call(client, method, url, body, headers):
    if method == "get":
        return await client.get(url, headers=headers)
    if method == "patch":
        return await client.patch(url, json=body, headers=headers)
    if method == "delete":
        return await client.delete(url, headers=headers)
    return await client.post(url, json=body, headers=headers)


@pytest.mark.asyncio
async def test_operator_arming_routes_refuse_anonymous_and_agent_but_accept_operator(
    client_and_db, tmp_path, operator_token_configured
):
    client, maker = client_and_db
    scope_id, workspace_id, item_id = await _leased_scope_and_workspace(maker, tmp_path)
    session_token = await _agent_session_token(maker)
    for label, method, url, body in _routes(scope_id, workspace_id, item_id)[4:]:
        anonymous = await _call(client, method, url, body, {})
        agent = await _call(client, method, url, body, {"X-Deck-Session-Token": session_token})
        operator = await _call(client, method, url, body, {"X-Deck-Operator-Token": OPERATOR_TOKEN})
        assert anonymous.status_code == 401, label
        assert agent.status_code == 401, label
        assert operator.status_code not in (401, 503), label
        if label == "scope-update":
            assert operator.status_code == 200
            assert operator.json()["merge_policy"] == "auto"


@pytest.mark.asyncio
async def test_workspace_reprobe_form_post_needs_operator(
    client_and_db, tmp_path, operator_token_configured
):
    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)
    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces/{workspace_id}/reprobe",
        data={"submit": "reprobe"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "operator_token_required"


@pytest.mark.asyncio
async def test_retry_requires_current_bound_leader_or_operator(
    client_and_db, tmp_path, operator_token_configured, monkeypatch
):
    client, maker = client_and_db
    scope_id, _, item_id = await _leased_scope_and_workspace(maker, tmp_path)
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr("app.api.v1.deps.peer_process.pane_is_alive", lambda *_: True)
    async with maker() as db:
        scope = await db.get(TeamGithubScope, scope_id)
        leader_slot = AgentTeamSlot(
            preset_id=scope.preset_id, position=0, display_name="Leader",
            provider="codex-cli", repo_id="r", repo_path="/tmp/r", repo_name="r",
        )
        other_slot = AgentTeamSlot(
            preset_id=scope.preset_id, position=1, display_name="Specialist",
            provider="codex-cli", repo_id="r", repo_path="/tmp/r", repo_name="r",
        )
        db.add_all([leader_slot, other_slot])
        await db.flush()
        tokens = {}
        members = {}
        for name, slot in (("leader", leader_slot), ("other", other_slot)):
            member = MailTeamMember(
                identity_key=f"retry:{name}:{item_id}", repo_id="r", repo_path="/tmp/r",
                repo_name="r", display_name=name, participant_kind="team_slot",
                team_preset_id=scope.preset_id, team_slot_id=slot.id,
            )
            db.add(member)
            await db.flush()
            members[name] = member
            token = f"retry-{name}-{item_id}"
            db.add(MailAgentSession(
                member_id=member.id, source="mcp", session_key=f"retry:{name}:{item_id}",
                team_preset_id=scope.preset_id, team_slot_id=slot.id,
                bound_pane_pid=1234, bound_pane_proc_start="1",
                capability_token_hash=agent_mail_service.hash_capability_token(token),
            ))
            tokens[name] = token
        other_preset = AgentTeamPreset(name="Other retry team")
        db.add(other_preset)
        await db.flush()
        for name, source, preset_id in (
            ("hook", "hook", scope.preset_id),
            ("cross_preset", "mcp", other_preset.id),
        ):
            token = f"retry-{name}-{item_id}"
            db.add(MailAgentSession(
                member_id=members["leader"].id, source=source,
                session_key=f"retry:{name}:{item_id}",
                team_preset_id=preset_id, team_slot_id=leader_slot.id,
                bound_pane_pid=1234, bound_pane_proc_start="1",
                capability_token_hash=agent_mail_service.hash_capability_token(token),
            ))
            tokens[name] = token
        eligible = GithubWorkItem(
            scope_id=scope_id, issue_number=2, issue_title="Retry eligible",
            issue_url="u", github_updated_at=datetime.utcnow(),
            dispatch_status="escalated", escalation_reason="plan_blocked",
        )
        db.add(eligible)
        await db.commit()
        eligible_id = eligible.id

    url = f"/api/v1/agent-teams/github-work-items/{item_id}/retry"
    assert (await client.post(url)).status_code == 401
    invalid = await client.post(url, headers={"X-Deck-Operator-Token": "invalid"})
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "operator_token_invalid"
    nonleader = await client.post(url, headers={"X-Deck-Session-Token": tokens["other"]})
    assert nonleader.status_code == 403
    assert nonleader.json()["detail"] == "current_leader_required"
    for name in ("hook", "cross_preset"):
        refused = await client.post(url, headers={"X-Deck-Session-Token": tokens[name]})
        assert refused.status_code == 403, name
        assert refused.json()["detail"] == "current_leader_required"
    operator = await client.post(url, headers={"X-Deck-Operator-Token": OPERATOR_TOKEN})
    assert operator.status_code == 409
    leader = await client.post(url, headers={"X-Deck-Session-Token": tokens["leader"]})
    assert leader.status_code == 409
    eligible_retry = await client.post(
        f"/api/v1/agent-teams/github-work-items/{eligible_id}/retry",
        headers={"X-Deck-Session-Token": tokens["leader"]},
    )
    assert eligible_retry.status_code == 200
    assert eligible_retry.json()["dispatch_status"] == "pending"

    monkeypatch.setattr(settings, "mail_capability_tokens_required", False)
    unenforced = await client.post(url, headers={"X-Deck-Session-Token": tokens["leader"]})
    assert unenforced.status_code == 403
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)

    async with maker() as db:
        leader_member = (
            await db.execute(
                select(MailTeamMember).where(MailTeamMember.identity_key == f"retry:leader:{item_id}")
            )
        ).scalar_one()
        db.add(MailTeamMember(
            identity_key=f"retry:replacement:{item_id}", repo_id="r", repo_path="/tmp/r",
            repo_name="r", display_name="replacement", participant_kind="team_slot",
            team_preset_id=leader_member.team_preset_id, team_slot_id=leader_member.team_slot_id,
            updated_at=datetime.utcnow() + timedelta(seconds=1),
        ))
        await db.commit()
    replaced = await client.post(url, headers={"X-Deck-Session-Token": tokens["leader"]})
    assert replaced.status_code == 403

    monkeypatch.setattr("app.api.v1.deps.peer_process.pane_is_alive", lambda *_: False)
    stale = await client.post(url, headers={"X-Deck-Session-Token": tokens["leader"]})
    assert stale.status_code == 401


@pytest.mark.asyncio
async def test_team_launch_requires_authority_and_agents_cannot_override(
    client_and_db, operator_token_configured, monkeypatch
):
    client, maker = client_and_db
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    session_token = await _agent_session_token(maker)
    async with maker() as db:
        preset = AgentTeamPreset(name="Launch authority", description="", created_by="test")
        db.add(preset)
        await db.commit()
        preset_id = preset.id

    base = f"/api/v1/agent-teams/presets/{preset_id}"
    session_headers = {"X-Deck-Session-Token": session_token}
    operator_headers = {"X-Deck-Operator-Token": OPERATOR_TOKEN}
    for path in ("plan-launch", "launch/plan", "launch"):
        anonymous = await client.post(f"{base}/{path}", json={})
        assert anonymous.status_code == 401, path
        assert anonymous.json()["detail"] == "operator_token_required"

    plan = await client.post(f"{base}/plan-launch", json={}, headers=session_headers)
    assert plan.status_code == 200
    assert plan.json()["spawn_count"] == 0
    launched = await client.post(
        f"{base}/launch",
        json={"confirm_plan_hash": plan.json()["plan_hash"]},
        headers=session_headers,
    )
    assert launched.status_code == 200

    for payload in (
        {"slot_prompt_overrides": {"1": "untrusted prompt"}},
        {"repo_path_override": "/tmp"},
        {"include_disabled": True},
        {"reuse_existing": False},
        {"skip_plan_confirmation": True},
    ):
        for path in ("plan-launch", "launch/plan", "launch"):
            refused = await client.post(f"{base}/{path}", json=payload, headers=session_headers)
            assert refused.status_code == 403, (path, payload)
            assert refused.json()["detail"]["block_code"] == "operator_launch_override_required"
    operator_plan = await client.post(
        f"{base}/plan-launch", json={"reuse_existing": False}, headers=operator_headers
    )
    assert operator_plan.status_code == 200

    monkeypatch.setattr(settings, "mail_capability_tokens_required", False)
    unenforced = await client.post(f"{base}/plan-launch", json={}, headers=session_headers)
    assert unenforced.status_code == 403
    assert unenforced.json()["detail"] == "authenticated_mcp_session_required"


@pytest.mark.asyncio
async def test_session_kill_requires_operator_before_termination(
    client_and_db, operator_token_configured, monkeypatch
):
    client, maker = client_and_db
    session_token = await _agent_session_token(maker)
    bridge = importlib.import_module("app.api.v1.agent_bridge.router")
    killed = []

    def fake_kill(*, session_name, cleanup_worktree):
        killed.append((session_name, cleanup_worktree))
        return {"status": "killed"}

    monkeypatch.setattr(bridge, "kill_session", fake_kill)
    url = "/api/v1/agent-bridge/sessions/not-the-leader"
    assert (await client.delete(url)).status_code == 401
    assert (
        await client.delete(url, headers={"X-Deck-Session-Token": session_token})
    ).status_code == 401
    assert killed == []
    operator = await client.delete(url, headers={"X-Deck-Operator-Token": OPERATOR_TOKEN})
    assert operator.status_code == 200
    assert killed == [("not-the-leader", False)]


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

    abandoned = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item_id}/abandon",
        json={"reason": "operator auth boundary test"},
        headers=headers,
    )
    assert abandoned.status_code == 409
    assert abandoned.json()["detail"]["block_code"] == "work_item_not_abandonable"


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
