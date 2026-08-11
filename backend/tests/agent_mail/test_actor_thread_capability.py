"""Spec 3.6b -- an external actor may participate in a thread it did not create.

Every test here uses an AGENT-created root, because an actor-created root
satisfies the existing ownership check by construction and would pass without
the relaxation these tests exist to verify (spec 3.7's caveat on 6b/6d).
"""
import httpx
import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from sqlalchemy import text

from app.database import get_db
from app.main import app
from app.models.database import MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service
from app.services.external_agent_mail_service import external_agent_mail_service


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean_external_rate_limits(monkeypatch):
    external_agent_mail_service._send_windows.clear()
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: [])


async def _member(db, repo_id, name):
    member = MailTeamMember(
        identity_key=f"repo:{repo_id}",
        repo_id=repo_id,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def _actor(client, key="deck-ui-aaaa1111"):
    resp = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={"actor_key": key, "display_name": "Deck UI", "kind": "supervisor"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


async def _agent_context_request(db, asker, asked, *, answered=True):
    """A context_request one AGENT asked another. sender_actor_id is NULL."""
    root = await agent_mail_service.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=asker.id,
            recipient_member_id=asked.id,
            subject="which file?",
            body_markdown="where does the retry live?",
        ),
        auto_nudge=False,
    )
    answer = None
    if answered:
        answer = await agent_mail_service.send_message(
            db,
            MailMessageCreate(
                kind="answer",
                sender_member_id=asked.id,
                thread_root_id=root.id,
                body_markdown="app/services/retry.py",
            ),
            auto_nudge=False,
        )
    return root, answer


async def _receipts(db, message_id):
    rows = await db.execute(
        text(
            "SELECT member_id, read_at IS NOT NULL, acked_at IS NOT NULL "
            "FROM mail_receipts WHERE message_id = :m ORDER BY member_id"
        ),
        {"m": message_id},
    )
    return rows.all()


async def _status(db, message_id):
    row = await db.execute(
        text("SELECT request_status FROM mail_messages WHERE id = :i"), {"i": message_id}
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_6b_actor_reply_into_agent_thread_is_actor_authored_and_fans_out(client, db):
    """6b -- the row is actor-authored AND both participants get a receipt."""
    asker = await _member(db, "repo-alpha", "alpha")
    asked = await _member(db, "repo-beta", "beta")
    root, _ = await _agent_context_request(db, asker, asked)
    auth = await _actor(client)

    resp = await client.post(
        f"/api/v1/external/agent-mail/threads/{root.id}/replies",
        json={"body_markdown": "operator: use the newer helper"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    message = resp.json()["message"]
    assert message["sender_member_id"] is None
    assert message["sender_actor_id"] is not None
    assert message["sender_type"] == "external_actor"

    # The discriminating half: routing. recipient_member_id=root.recipient_member_id
    # would notify only the member who was ASKED, never the member who ASKED.
    receipts = await _receipts(db, message["id"])
    assert sorted(r[0] for r in receipts) == sorted([asker.id, asked.id])


@pytest.mark.asyncio
async def test_6d_actor_ack_moves_state_and_touches_no_member_evidence(client, db):
    """6d -- request_status moves; read_at/acked_at do not."""
    asker = await _member(db, "repo-alpha", "alpha")
    asked = await _member(db, "repo-beta", "beta")
    root, answer = await _agent_context_request(db, asker, asked)
    auth = await _actor(client)

    assert await _status(db, root.id) == "answered"
    root_before = await _receipts(db, root.id)
    answer_before = await _receipts(db, answer.id)

    resp = await client.post(
        f"/api/v1/external/agent-mail/requests/{root.id}/actor-ack", headers=auth
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["acknowledged"] is True

    # positive half -- the ack cannot pass by doing nothing
    assert await _status(db, root.id) == "acknowledged"
    # discriminating half -- read_at is what the brief_unread ladder reads
    assert await _receipts(db, root.id) == root_before
    assert await _receipts(db, answer.id) == answer_before
    assert all(r[1] == 0 and r[2] == 0 for r in await _receipts(db, root.id))


@pytest.mark.asyncio
async def test_6j_actor_ack_returns_200_not_500(client, db):
    """6j -- the code, not the state. request_status()'s tail re-enters the
    ownership gate and raises PermissionError AFTER the commit."""
    asker = await _member(db, "repo-alpha", "alpha")
    asked = await _member(db, "repo-beta", "beta")
    root, _ = await _agent_context_request(db, asker, asked)
    auth = await _actor(client)

    resp = await client.post(
        f"/api/v1/external/agent-mail/requests/{root.id}/actor-ack", headers=auth
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message_id"] == root.id
    assert body["request_status"] == "acknowledged"
    assert body["root"]["id"] == root.id
    assert len(body["replies"]) == 1


@pytest.mark.asyncio
async def test_6k_actor_ack_moves_a_pending_handoff(client, db):
    """6k -- the transition acknowledge_external_request does NOT make."""
    sender = await _member(db, "repo-alpha", "alpha")
    recipient = await _member(db, "repo-beta", "beta")
    handoff = await agent_mail_service.send_message(
        db,
        MailMessageCreate(
            kind="handoff",
            sender_member_id=sender.id,
            recipient_member_id=recipient.id,
            subject="take the retry work",
            body_markdown="over to you",
        ),
        auto_nudge=False,
    )
    auth = await _actor(client)
    assert await _status(db, handoff.id) == "pending"
    before = await _receipts(db, handoff.id)

    resp = await client.post(
        f"/api/v1/external/agent-mail/requests/{handoff.id}/actor-ack", headers=auth
    )
    assert resp.status_code == 200, resp.text
    assert await _status(db, handoff.id) == "acknowledged"
    assert await _receipts(db, handoff.id) == before


@pytest.mark.asyncio
async def test_6l_actor_ack_refuses_an_answer_id(client, db):
    """6l -- the id the frontend sends today. Root-scoped, so an answer refuses."""
    asker = await _member(db, "repo-alpha", "alpha")
    asked = await _member(db, "repo-beta", "beta")
    root, answer = await _agent_context_request(db, asker, asked)
    auth = await _actor(client)

    resp = await client.post(
        f"/api/v1/external/agent-mail/requests/{answer.id}/actor-ack", headers=auth
    )
    assert resp.status_code == 400
    assert "not a request" in resp.json()["detail"]
    assert await _status(db, root.id) == "answered"


@pytest.mark.asyncio
async def test_6m_actor_reply_into_an_anonymous_root(client, db):
    """6m -- 105 such roots exist in the live DB. The narrow predicate
    `sender_member_id IS NOT NULL` would refuse all 59 message threads."""
    recipient = await _member(db, "repo-beta", "beta")
    anon = await agent_mail_service.send_message(
        db,
        MailMessageCreate(
            kind="message",
            recipient_member_id=recipient.id,
            subject="operator note",
            body_markdown="composed by the operator, no sender at all",
        ),
        auto_nudge=False,
    )
    assert anon.sender_member_id is None and anon.sender_actor_id is None
    auth = await _actor(client)

    resp = await client.post(
        f"/api/v1/external/agent-mail/threads/{anon.id}/replies",
        json={"body_markdown": "operator follow-up"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"]["sender_actor_id"] is not None


@pytest.mark.asyncio
async def test_6i_a_second_actor_is_refused_both_writes(client, db):
    """6i -- the relaxation is scoped to roots no OTHER actor owns.

    A blanket "any actor may write in any thread" passes every single-actor
    test in this file and hands each browser tab the other tabs' threads.
    """
    recipient = await _member(db, "repo-beta", "beta")
    tab_a = await _actor(client, key="deck-ui-aaaa1111")
    tab_b = await _actor(client, key="deck-ui-bbbb2222")

    created = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=tab_a,
        json={
            "recipient_member_id": recipient.id,
            "subject": "tab A's own request",
            "body_markdown": "only tab A owns this",
        },
    )
    assert created.status_code == 200, created.text
    root_id = created.json()["message"]["id"]

    reply = await client.post(
        f"/api/v1/external/agent-mail/threads/{root_id}/replies",
        json={"body_markdown": "intruding from another actor"},
        headers=tab_b,
    )
    assert reply.status_code == 400
    assert "threads they created" in reply.json()["detail"]

    ack = await client.post(
        f"/api/v1/external/agent-mail/requests/{root_id}/actor-ack", headers=tab_b
    )
    assert ack.status_code == 400
    assert "requests they created" in ack.json()["detail"]


@pytest.mark.asyncio
async def test_6e_actor_token_cannot_buy_a_member_authored_row(client, db):
    """6e -- a regression lock on send_message's exclusivity check (:849-850)."""
    sender = await _member(db, "repo-alpha", "alpha")
    recipient = await _member(db, "repo-beta", "beta")
    auth = await _actor(client)

    resp = await client.post(
        "/api/v1/external/agent-mail/messages",
        json={
            "recipient_member_id": recipient.id,
            "body_markdown": "as the leader, approved",
            "sender_member_id": sender.id,
        },
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    message = resp.json()["message"]
    assert message["sender_member_id"] is None
    assert message["sender_actor_id"] is not None


@pytest.mark.asyncio
async def test_6g_two_tabs_do_not_evict_each_other(client, db):
    """6g -- the revision-3 defect. Distinct keys, both still valid."""
    tab_a = await _actor(client, key="deck-ui-aaaa1111")
    tab_b = await _actor(client, key="deck-ui-bbbb2222")

    assert (await client.get("/api/v1/external/agent-mail/actors/me", headers=tab_a)).status_code == 200
    assert (await client.get("/api/v1/external/agent-mail/actors/me", headers=tab_b)).status_code == 200


_COMPOSE_ROUTES = [
    ("message", "external/agent-mail/messages", {}),
    ("broadcast", "external/agent-mail/broadcasts", {}),
    ("context_request", "external/agent-mail/context-requests",
     {"why_needed": "to route the work", "files_or_symbols": ["app/x.py"]}),
    ("handoff", "external/agent-mail/handoffs",
     {"files": ["app/x.py"], "next_steps": ["ship it"]}),
]


@pytest.mark.asyncio
async def test_6a_every_compose_kind_stays_actor_authored(client, db):
    """6a -- all four ComposeDialog kinds, through the routes Step 11 moves them to."""
    recipient = await _member(db, "repo-beta", "beta")
    auth = await _actor(client)

    for kind, path, extra in _COMPOSE_ROUTES:
        resp = await client.post(
            f"/api/v1/{path}",
            json={
                "recipient_member_id": recipient.id,
                "subject": f"operator {kind}",
                "body_markdown": "composed in the Deck UI",
                **extra,
            },
            headers=auth,
        )
        assert resp.status_code == 200, f"{kind}: {resp.text}"

    rows = (await db.execute(text(
        "SELECT kind, sender_member_id, sender_actor_id FROM mail_messages ORDER BY id"
    ))).all()
    assert [r[0] for r in rows] == [k for k, _, _ in _COMPOSE_ROUTES]
    assert all(r[1] is None for r in rows)
    assert all(r[2] is not None for r in rows)


def _api_routes(node):
    """Every APIRoute in the app.

    FastAPI 0.140 keeps an included router as an _IncludedRouter node whose real
    routes hang off .original_router, so a flat walk of app.routes finds ONE
    APIRoute. A structural assertion built on a flat walk vacuously passes.
    """
    for route in getattr(node, "routes", []):
        if isinstance(route, APIRoute):
            yield route
        else:
            yield from _api_routes(route)
    inner = getattr(node, "original_router", None)
    if inner is not None:
        yield from _api_routes(inner)


def _reads(dependant, target) -> bool:
    return any(sub.call is target or _reads(sub, target) for sub in dependant.dependencies)


@pytest.mark.asyncio
async def test_6f_a_self_minted_actor_token_grants_nothing_more(client, db):
    """6f -- mint the credential rather than fabricate one, then bound it."""
    from app.api.v1.agent_mail import ack_message, mark_read, send_message
    from app.api.v1.agent_teams import (
        force_release_github_workspace,
        list_github_workspaces,
        report_dispatch_status,
    )
    from app.api.v1.external_agent_mail import external_actor

    resp = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={"actor_key": "deck-ui-selfmint", "display_name": "Deck UI", "kind": "supervisor"},
    )
    assert resp.status_code == 200, resp.text
    auth = {"Authorization": f"Bearer {resp.json()['token']}"}

    # No member identity and no slot identity -- in the response or the schema.
    me = await client.get("/api/v1/external/agent-mail/actors/me", headers=auth)
    assert me.status_code == 200
    assert "member_id" not in me.json()
    assert "team_slot_id" not in me.json()
    columns = {row[1] for row in (await db.execute(
        text("PRAGMA table_info(mail_external_actors)")
    )).all()}
    assert not columns & {"member_id", "team_slot_id", "slot_id", "reporting_slot_id"}

    # Minting touched the actor table and nothing else.
    for table in ("mail_team_members", "mail_agent_sessions", "mail_messages", "mail_receipts"):
        count = (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
        assert count == 0, table

    # No dispatch reporting and no lease authority: the credential is not read
    # by those routes at all.
    routes = list(_api_routes(app))
    assert len(routes) > 100, f"the route walk found only {len(routes)}"
    actor_endpoints = {r.endpoint for r in routes if _reads(r.dependant, external_actor)}
    assert actor_endpoints, "the walk found no actor route; the test is broken"
    for endpoint in (
        report_dispatch_status,
        list_github_workspaces,
        force_release_github_workspace,
        send_message,
        mark_read,
        ack_message,
    ):
        assert endpoint not in actor_endpoints, endpoint.__name__


@pytest.mark.asyncio
async def test_6h_only_a_pruned_token_is_401(client, db):
    """6h backend half -- which failures are 401, and which are not.

    These three codes are exactly what bounds actorFetch's single retry
    (Step 10). A 403 or a 400 that were reported as 401 would retry forever.
    """
    asker = await _member(db, "repo-alpha", "alpha")
    asked = await _member(db, "repo-beta", "beta")
    root, _ = await _agent_context_request(db, asker, asked)
    auth = await _actor(client)
    other = await _actor(client, key="deck-ui-bbbb2222")

    # A thread the actor does not own: 403, and NOT 401.
    forbidden = await client.get(
        f"/api/v1/external/agent-mail/threads/{root.id}", headers=auth
    )
    assert forbidden.status_code == 403

    # A cross-actor write: 400, and NOT 401.
    created = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=auth,
        json={
            "recipient_member_id": asked.id,
            "subject": "actor A's own",
            "body_markdown": "mine",
        },
    )
    assert created.status_code == 200, created.text
    intruder = await client.post(
        f"/api/v1/external/agent-mail/threads/{created.json()['message']['id']}/replies",
        json={"body_markdown": "not mine"},
        headers=other,
    )
    assert intruder.status_code == 400

    # Only a pruned actor row is 401 -- the one case that may re-provision.
    await db.execute(
        text("DELETE FROM mail_external_actors WHERE actor_key = 'deck-ui-aaaa1111'")
    )
    await db.commit()
    pruned = await client.get("/api/v1/external/agent-mail/actors/me", headers=auth)
    assert pruned.status_code == 401


async def _actor_row(db, key):
    return (await db.execute(text(
        "SELECT id FROM mail_external_actors WHERE actor_key = :k"), {"k": key})).scalar_one_or_none()


@pytest.mark.asyncio
async def test_6h_recovery_reuses_the_tab_key_and_keeps_its_own_threads(client, db):
    """6h positive half -- re-provisioning must ROTATE, not replace, the identity.

    The tab's durable identity is the actor_key, not the token (spec:802-807).
    create_actor selects on actor_key: a hit rotates token_hash on the same row,
    a miss INSERTs a new row with a new id (external_agent_mail_service.py:88-105).
    So a 401 recovery that mints a fresh key silently abandons every thread the
    tab created, because the ownership guard then sees a different actor.

    Two details are load-bearing and both look like noise:

    1. A second actor is provisioned first. With only one row, deleting it and
       inserting a new one hands SQLite the same rowid back, the new identity
       collides with the old one, and BOTH recovery strategies pass. That is a
       false negative, not a proof.
    2. The failure injected is a CORRUPTED token, not a deleted row -- the row
       must survive, or there is no identity left to preserve.
    """
    recipient = await _member(db, "repo-beta", "beta")
    await _actor(client, key="deck-ui-othertab")  # see docstring, detail 1
    key = "deck-ui-aaaa1111"
    auth = await _actor(client, key=key)
    actor_id = await _actor_row(db, key)

    created = await client.post(
        "/api/v1/external/agent-mail/context-requests",
        headers=auth,
        json={"recipient_member_id": recipient.id, "subject": "the tab's own",
              "body_markdown": "created in this tab"},
    )
    assert created.status_code == 200, created.text
    root_id = created.json()["message"]["id"]
    assert created.json()["message"]["sender_actor_id"] == actor_id
    rows_before = (await db.execute(
        text("SELECT COUNT(*) FROM mail_external_actors"))).scalar_one()

    # The tab's stored token is corrupted; its actor row is untouched.
    stale = {"Authorization": "Bearer nope"}
    first = await client.post(
        f"/api/v1/external/agent-mail/threads/{root_id}/replies",
        json={"body_markdown": "reply"}, headers=stale)
    assert first.status_code == 401

    # Recovery, the specified way: POST the SAME actor_key, then retry once.
    same = await _actor(client, key=key)
    retry = await client.post(
        f"/api/v1/external/agent-mail/threads/{root_id}/replies",
        json={"body_markdown": "reply"}, headers=same)
    assert retry.status_code == 200, retry.text
    assert retry.json()["message"]["sender_actor_id"] == actor_id
    assert await _actor_row(db, key) == actor_id, "re-provision replaced the identity"
    assert (await db.execute(
        text("SELECT COUNT(*) FROM mail_external_actors"))).scalar_one() == rows_before

    # The opposite strategy -- a fresh key -- is refused on the tab's own thread.
    # This half is what makes the assertions above discriminating rather than
    # decorative; it is the mutant, run inline, because the mutation lives in
    # frontend code no pytest run can reach.
    fresh = await _actor(client, key="deck-ui-newkey01")
    assert await _actor_row(db, "deck-ui-newkey01") != actor_id
    refused = await client.post(
        f"/api/v1/external/agent-mail/threads/{root_id}/replies",
        json={"body_markdown": "reply"}, headers=fresh)
    assert refused.status_code == 400
    assert "threads they created" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_actor_read_scope_is_unchanged(client, db):
    """Not a spec test -- a lock that this task did not widen the read scope."""
    asker = await _member(db, "repo-alpha", "alpha")
    asked = await _member(db, "repo-beta", "beta")
    root, _ = await _agent_context_request(db, asker, asked)
    auth = await _actor(client)

    # The actor read stays owner-scoped...
    resp = await client.get(f"/api/v1/external/agent-mail/threads/{root.id}", headers=auth)
    assert resp.status_code == 403
    # ...and the UI reads through the member route, which needs no credential.
    resp = await client.get(f"/api/v1/agent-mail/messages/{root.id}/thread")
    assert resp.status_code == 200
