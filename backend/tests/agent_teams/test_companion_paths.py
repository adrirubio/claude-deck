"""Companion paths: the checked-in map, the Leader-visible plan, and the amendment baseline."""
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.api.v1 import agent_mail
from app.models.database import GithubApprovalRequest, MailAgentSession, MailMessage, MailReceipt
from app.models.schemas import MailApprovalRequestCreate
from app.services import companion_paths
from app.services.github_approval_service import github_approval_service
from tests.agent_teams.test_scope_amendments import amendment, db, healthy_attempt  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
MAPPED = {"src/base.py": [{"path": "tests/test_base.py", "kind": "test"}]}


def entry(source, *companions):
    return {"source": source, "companions": [{"path": path, "kind": kind} for path, kind in companions]}


def document(*entries):
    return {"version": 1, "entries": list(entries)}


@pytest.fixture
def companion_map(monkeypatch):
    """Install a small map before the healthy attempt files its initial plan."""
    state = {"map": dict(MAPPED)}
    monkeypatch.setattr(companion_paths, "load_map", lambda path=None: state["map"])
    return state


def test_the_checked_in_map_is_valid_and_every_mapped_path_exists_in_the_repository():
    mapping = companion_paths.load_map()
    assert mapping, "the map must not be empty"
    for source, companions in mapping.items():
        assert (REPO / source).is_file(), f"mapped source is missing: {source}"
        for companion in companions:
            assert (REPO / companion["path"]).is_file(), f"mapped companion is missing: {companion['path']}"


def test_a_schema_source_brings_its_contract_fixtures_and_manifests_in_both_lanes():
    found = companion_paths.companions_for(["backend/app/models/factory_schemas.py"])
    for lane in ("backend/tests/factory/fixtures/v1-p04", "frontend/tests/fixtures/factory/v1-p04"):
        assert f"{lane}/manifest.json" in found and f"{lane}/schema.json" in found


def test_a_service_source_brings_its_mapped_test_modules():
    found = companion_paths.companions_for(["backend/app/services/github_approval_service.py"])
    assert "backend/tests/agent_teams/test_github_approval_service.py" in found
    assert "backend/tests/agent_teams/test_scope_amendments.py" in found


@pytest.mark.parametrize("service", [
    "backend/app/services/github_approval_service.py", "backend/app/services/github_terminal_revision_service.py"])
def test_a_service_that_records_refusal_codes_brings_the_plain_language_catalogue_and_its_scan(service):
    found = companion_paths.companions_for([service])
    assert {"frontend/src/features/factory/auditRefusals.ts", "frontend/tests/audit-refusals.test.ts"} <= set(found)


def test_the_tool_surface_brings_the_inventory_tests_and_the_doc_page():
    found = companion_paths.companions_for(["backend/mcp_shim/agent_mail_server.py"])
    assert {"backend/tests/agent_mail/test_mcp_shim.py", "backend/tests/agent_mail/test_pi_shim.py",
            "backend/tests/agent_mail/test_tool_rename.py", "backend/tests/upgrade/test_provider_upgrade_startup.py",
            "integrations/pi-agent-mail/manifest.ts", "docs/api/agent-mail.md"} <= set(found)


def test_companions_are_sorted_unique_and_never_repeat_a_named_path():
    mapping = {"a.py": [{"path": "t/a.py", "kind": "test"}, {"path": "t/x.py", "kind": "test"}],
               "b.py": [{"path": "t/x.py", "kind": "test"}, {"path": "t/b.py", "kind": "test"}]}
    assert companion_paths.companions_for(["b.py", "a.py", "t/b.py"], mapping) == ["t/a.py", "t/x.py"]
    assert companion_paths.companions_for(["unmapped.py"], mapping) == []
    assert companion_paths.companions_for([], mapping) == []


def test_plan_metadata_gains_companions_only_when_it_names_paths_and_is_not_mutated():
    original = {"allowed_paths": ["src/base.py"], "note": "x"}
    result = companion_paths.with_companions(original, MAPPED)
    assert result == {"allowed_paths": ["src/base.py"], "note": "x", "companion_paths": ["tests/test_base.py"],
                      "companion_provenance": "checked-in-map-v1"}
    assert original == {"allowed_paths": ["src/base.py"], "note": "x"}
    assert companion_paths.with_companions({"note": "x"}, MAPPED) == {"note": "x"}
    assert companion_paths.with_companions({"allowed_paths": "src/base.py"}, MAPPED) == {"allowed_paths": "src/base.py"}
    assert companion_paths.with_companions({"allowed_paths": ["other.py"]}, MAPPED) == {"allowed_paths": ["other.py"]}
    assert companion_paths.with_companions(None, MAPPED) == {}


@pytest.mark.parametrize("bad", [
    document(entry("src/*.py", ("tests/a.py", "test"))),
    document(entry("/abs.py", ("tests/a.py", "test"))),
    document(entry("src/a.py", ("tests/../a.py", "test"))),
    document(entry("src/a.py", ("tests/", "test"))),
    document(entry("src/a.py", ("src/a.py", "test"))),
    document(entry("src/a.py", ("tests/a.py", "test"), ("tests/a.py", "test"))),
    document(entry("src/a.py", ("tests/a.py", "guess"))),
    document(entry("src/a.py", ("tests/a.py", "test")), entry("src/a.py", ("tests/b.py", "test"))),
    document(entry("src/a.py")),
    {"version": 2, "entries": []},
    {"entries": []},
    [],
])
def test_a_malformed_map_is_refused(tmp_path, bad):
    path = tmp_path / "map.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(companion_paths.CompanionMapError):
        companion_paths.load_map(path)


async def leader_message(db, approval):
    return await db.get(MailMessage, approval.request_message_id)


@pytest.mark.asyncio
async def test_the_leader_sees_the_companions_and_the_fingerprint_covers_them(db, companion_map, healthy_attempt):
    a = healthy_attempt
    message = await leader_message(db, a.approval)
    metadata = message.payload["plan_metadata"]
    assert metadata["allowed_paths"] == ["src/base.py"]
    assert metadata["companion_paths"] == ["tests/test_base.py"]
    assert "tests/test_base.py" in message.body_markdown and "ompanion" in message.body_markdown
    assert a.approval.request_fingerprint == github_approval_service.initial_request_fingerprint(
        summary=message.payload["summary"], plan_metadata=metadata)
    assert github_approval_service.matches_linked_request_message(
        a.approval, message, delivery_key=f"github-approval:{a.approval.id}:request")


@pytest.mark.asyncio
async def test_a_replay_after_the_map_changed_keeps_the_companions_the_leader_approved(db, companion_map, healthy_attempt):
    a = healthy_attempt
    companion_map["map"] = {"src/base.py": [{"path": "tests/other.py", "kind": "test"}]}
    session = await db.scalar(select(MailAgentSession).where(MailAgentSession.member_id == a.owner.id))
    replay = await agent_mail.request_work_item_approval(MailApprovalRequestCreate(
        work_item_id=a.item.id, dispatch_nonce=a.item.dispatch_nonce, summary="Initial closed scope",
        plan_metadata={"allowed_paths": ["src/base.py"]}), session, db)
    assert replay.id == a.approval.id
    rows = list((await db.scalars(select(GithubApprovalRequest).where(
        GithubApprovalRequest.work_item_id == a.item.id,
        GithubApprovalRequest.request_kind == "initial_plan"))).all())
    assert [row.id for row in rows] == [a.approval.id] and rows[0].status == "approved"
    message = await leader_message(db, rows[0])
    assert message.payload["plan_metadata"]["companion_paths"] == ["tests/test_base.py"]


@pytest.mark.asyncio
async def test_the_amendment_baseline_is_the_approved_paths_plus_the_approved_companions(db, companion_map, healthy_attempt):
    a = healthy_attempt
    base = await github_approval_service.amendment_base_paths(db, a.item, a.owner, a.leader)
    assert base == ["src/base.py", "tests/test_base.py"]


@pytest.mark.asyncio
async def test_a_companion_the_leader_never_saw_has_no_authority(db, companion_map, healthy_attempt):
    a = healthy_attempt
    companion_map["map"] = {"src/base.py": [{"path": "tests/test_base.py", "kind": "test"},
                                             {"path": "docs/later.md", "kind": "doc"}]}
    base = await github_approval_service.amendment_base_paths(db, a.item, a.owner, a.leader)
    assert "docs/later.md" not in base and base == ["src/base.py", "tests/test_base.py"]


@pytest.mark.asyncio
async def test_a_companion_only_change_needs_no_added_path(db, companion_map, healthy_attempt):
    a = healthy_attempt
    revision, _, _ = await github_approval_service.create_scope_amendment_request(
        db, a.item, a.scope, **amendment(a, ["src/base.py", "tests/test_base.py"]))
    assert revision.amendment_added_paths == []
    assert revision.amendment_base_paths == ["src/base.py", "tests/test_base.py"]


@pytest.mark.asyncio
async def test_a_path_that_is_not_a_companion_still_needs_an_amendment(db, companion_map, healthy_attempt):
    a = healthy_attempt
    revision, _, _ = await github_approval_service.create_scope_amendment_request(
        db, a.item, a.scope, **amendment(a, ["src/base.py", "src/unrelated.py"]))
    assert revision.amendment_added_paths == ["src/unrelated.py"]


@pytest.mark.asyncio
async def test_an_amendment_that_names_a_new_source_adds_its_companions_to_the_proposal(db, companion_map, healthy_attempt):
    a = healthy_attempt
    companion_map["map"] = {**MAPPED, "src/new.py": [{"path": "tests/test_new.py", "kind": "test"}]}
    revision, _, _ = await github_approval_service.create_scope_amendment_request(
        db, a.item, a.scope, **amendment(a, ["src/base.py", "src/new.py"]))
    assert revision.allowed_paths == ["src/base.py", "src/new.py", "tests/test_base.py", "tests/test_new.py"]
    assert revision.amendment_added_paths == ["src/new.py", "tests/test_new.py"]


# --- Review batch (PR 907): provenance, amendment replay, legacy repair, canonical lookup -------------------

from fastapi import HTTPException  # noqa: E402

from app.services.github_approval_service import GithubApprovalError  # noqa: E402


async def make_legacy(db, a, metadata):
    """Rewrite the approved plan as a record that predates this feature: summary-only Mail body."""
    message = await db.get(MailMessage, a.approval.request_message_id)
    summary = message.payload["summary"]
    message.payload = {**message.payload, "plan_metadata": metadata}
    message.body_markdown = summary
    a.approval.request_fingerprint = github_approval_service.initial_request_fingerprint(
        summary=summary, plan_metadata=metadata)
    await db.commit()


@pytest.mark.asyncio
async def test_a_new_plan_cannot_supply_the_server_owned_companion_keys(db, companion_map, healthy_attempt):
    a = healthy_attempt
    item_id, nonce, owner_id = a.item.id, a.item.dispatch_nonce, a.owner.id
    for forged in ({"companion_paths": ["src/unrelated.py"]}, {"companion_provenance": "checked-in-map-v1"}):
        # A refusal rolls the session back, so each call reads its own session row.
        session = await db.scalar(select(MailAgentSession).where(MailAgentSession.member_id == owner_id))
        with pytest.raises(HTTPException) as refused:
            await agent_mail.request_work_item_approval(MailApprovalRequestCreate(
                work_item_id=item_id, dispatch_nonce=nonce, summary="A different summary",
                plan_metadata={"allowed_paths": ["unmapped.py"], **forged}), session, db)
        assert refused.value.status_code == 400 and "plan_metadata_reserved_key" in str(refused.value.detail)


@pytest.mark.asyncio
async def test_a_legacy_plan_with_an_opaque_companion_key_keeps_its_original_authority(db, companion_map, healthy_attempt):
    a = healthy_attempt
    await make_legacy(db, a, {"allowed_paths": ["src/base.py"], "companion_paths": ["src/unapproved.py"]})
    base = await github_approval_service.amendment_base_paths(db, a.item, a.owner, a.leader)
    assert base == ["src/base.py"]


@pytest.mark.asyncio
async def test_a_forged_marker_without_the_server_written_body_has_no_authority(db, companion_map, healthy_attempt):
    a = healthy_attempt
    await make_legacy(db, a, {"allowed_paths": ["src/base.py"], "companion_paths": ["src/unapproved.py"],
                              "companion_provenance": "checked-in-map-v1"})
    base = await github_approval_service.amendment_base_paths(db, a.item, a.owner, a.leader)
    assert base == ["src/base.py"]


@pytest.mark.asyncio
async def test_a_pending_amendment_replays_after_the_map_changed(db, companion_map, healthy_attempt):
    a = healthy_attempt
    paths = ["src/base.py", "src/new.py"]
    companion_map["map"] = {**MAPPED, "src/new.py": [{"path": "tests/test_new.py", "kind": "test"}]}
    first = await github_approval_service.create_scope_amendment_request(db, a.item, a.scope, **amendment(a, paths))
    companion_map["map"] = {"src/base.py": [{"path": "tests/later.py", "kind": "test"}],
                            "src/new.py": [{"path": "tests/later_new.py", "kind": "test"}]}
    replay = await github_approval_service.create_scope_amendment_request(db, a.item, a.scope, **amendment(a, paths))
    assert first[2] and not replay[2]
    assert replay[0].id == first[0].id and replay[1].id == first[1].id
    assert "tests/test_new.py" in first[0].allowed_paths and "tests/later_new.py" not in replay[0].allowed_paths
    github_approval_service.verify_amendment_binding(replay[1], replay[0])


@pytest.mark.asyncio
async def test_a_decided_amendment_replays_after_the_map_changed(db, companion_map, healthy_attempt):
    a = healthy_attempt
    paths = ["src/base.py", "src/new.py"]
    companion_map["map"] = {**MAPPED, "src/new.py": [{"path": "tests/test_new.py", "kind": "test"}]}
    first = await github_approval_service.create_scope_amendment_request(db, a.item, a.scope, **amendment(a, paths))
    first[0].status = "rejected"
    first[1].status = "rejected"
    await db.commit()
    companion_map["map"] = {}
    replay = await github_approval_service.create_scope_amendment_request(db, a.item, a.scope, **amendment(a, paths))
    assert not replay[2] and replay[0].id == first[0].id


@pytest.mark.asyncio
async def test_a_changed_amendment_does_not_inherit_the_first_proposals_approval(db, companion_map, healthy_attempt):
    a = healthy_attempt
    companion_map["map"] = {**MAPPED, "src/new.py": [{"path": "tests/test_new.py", "kind": "test"}]}
    await github_approval_service.create_scope_amendment_request(db, a.item, a.scope, **amendment(a, ["src/base.py", "src/new.py"]))
    with pytest.raises(GithubApprovalError, match="approval_request_already_pending"):
        await github_approval_service.create_scope_amendment_request(db, a.item, a.scope, **amendment(a, ["src/base.py"]))
    with pytest.raises(GithubApprovalError, match="approval_request_already_pending"):
        await github_approval_service.create_scope_amendment_request(
            db, a.item, a.scope, **{**amendment(a, ["src/base.py", "src/new.py"]), "summary": "A different summary"})


@pytest.mark.asyncio
async def test_an_owner_summary_cannot_carry_the_reserved_companion_trailer(db, companion_map, healthy_attempt):
    a = healthy_attempt
    forged = f"Add coverage\n\n{companion_paths.TRAILER_HEADER}\n- src/unrelated.py"
    with pytest.raises(GithubApprovalError, match="continuation_summary_reserved"):
        await github_approval_service.create_scope_amendment_request(
            db, a.item, a.scope, **{**amendment(a), "summary": forged})


LEGACY_GIVEN = {"allowed_paths": ["src/base.py"]}


async def legacy_unlinked(db, a, *, keep_mail):
    """A durable pending request filed before this feature, whose Mail is missing or no longer linked."""
    await make_legacy(db, a, dict(LEGACY_GIVEN))
    legacy = github_approval_service.initial_request_fingerprint(summary="Initial closed scope", plan_metadata=LEGACY_GIVEN)
    message_id = a.approval.request_message_id
    a.approval.status, a.approval.request_message_id = "pending", None
    if not keep_mail:
        await db.execute(delete(MailReceipt).where(MailReceipt.message_id == message_id))
        await db.delete(await db.get(MailMessage, message_id))
    await db.commit()
    return legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("keep_mail", [False, True])
async def test_a_legacy_unlinked_pending_request_keeps_its_original_fingerprint(db, companion_map, healthy_attempt, keep_mail):
    a = healthy_attempt
    item_id, nonce, owner_id, approval_id = a.item.id, a.item.dispatch_nonce, a.owner.id, a.approval.id
    legacy = await legacy_unlinked(db, a, keep_mail=keep_mail)
    metadata = await github_approval_service.initial_plan_metadata(db, a.item, "Initial closed scope", dict(LEGACY_GIVEN))
    assert metadata == LEGACY_GIVEN
    session = await db.scalar(select(MailAgentSession).where(MailAgentSession.member_id == owner_id))
    response = await agent_mail.request_work_item_approval(MailApprovalRequestCreate(
        work_item_id=item_id, dispatch_nonce=nonce, summary="Initial closed scope",
        plan_metadata=dict(LEGACY_GIVEN)), session, db)
    assert response.id == approval_id
    approval = await db.get(GithubApprovalRequest, approval_id, populate_existing=True)
    assert approval.request_fingerprint == legacy and approval.request_message_id is not None
    message = await leader_message(db, approval)
    assert message.payload["plan_metadata"] == LEGACY_GIVEN and "ompanion" not in message.body_markdown


@pytest.mark.asyncio
async def test_the_initial_lookup_uses_the_canonical_form_of_the_paths(db, companion_map, healthy_attempt):
    a = healthy_attempt
    a.approval.status = "superseded"
    await db.commit()
    metadata = await github_approval_service.initial_plan_metadata(
        db, a.item, "Initial closed scope", {"allowed_paths": [" src/base.py "]})
    assert metadata["companion_paths"] == ["tests/test_base.py"]
    assert metadata["allowed_paths"] == [" src/base.py "]
    for malformed in (["../x"], ["src/*.py"], [""], 5, None):
        again = await github_approval_service.initial_plan_metadata(
            db, a.item, "Initial closed scope", {"allowed_paths": malformed})
        assert "companion_paths" not in again


IDENTITY = (1, "nonce", 0)


def test_a_stored_trailer_verifies_only_with_its_digest_identity_and_summary():
    stored = companion_paths.summary_with_trailer("Add tests", IDENTITY, ["src/a.py"], ["tests/a.py"])
    allowed = ["src/a.py", "tests/a.py"]
    assert companion_paths.split_summary(stored, IDENTITY, allowed) == ("Add tests", ["src/a.py"], ["tests/a.py"])
    assert companion_paths.summary_with_trailer("Add tests", IDENTITY, ["src/a.py"], []) == "Add tests"
    # Another attempt, a different revision, an edited summary or an edited list is plain summary text.
    assert companion_paths.split_summary(stored, (2, "nonce", 0), allowed) == (stored, allowed, [])
    assert companion_paths.split_summary(stored, (1, "nonce", 1), allowed) == (stored, allowed, [])
    assert companion_paths.split_summary(stored.replace("Add tests", "Add more", 1), IDENTITY, allowed)[2] == []
    assert companion_paths.split_summary(stored.replace("tests/a.py\n", "tests/b.py\n"), IDENTITY, allowed + ["tests/b.py"])[2] == []
    assert companion_paths.split_summary(stored, IDENTITY, ["src/a.py"])[2] == []


@pytest.mark.parametrize("similar", [
    f"Old summary\n\n{companion_paths.TRAILER_HEADER}\n- tests/a.py\n{'Companion digest:'} {'0' * 64}",
    f"Old summary\n\n{companion_paths.TRAILER_HEADER}\n- tests/a.py",
    f"Old summary mentions {companion_paths.TRAILER_HEADER} in prose.",
])
def test_older_summary_text_that_only_looks_like_a_trailer_is_plain_text(similar):
    assert companion_paths.split_summary(similar, IDENTITY, ["src/a.py", "tests/a.py"]) == (
        similar, ["src/a.py", "tests/a.py"], [])


@pytest.mark.asyncio
async def test_an_old_record_replays_exactly_even_though_it_carries_the_reserved_key(db, companion_map, healthy_attempt):
    a = healthy_attempt
    legacy = {"allowed_paths": ["src/base.py"], "companion_paths": ["src/unapproved.py"]}
    await make_legacy(db, a, legacy)
    same = await github_approval_service.initial_plan_metadata(db, a.item, "Initial closed scope", dict(legacy))
    assert same == legacy


# --- Review batch 2 (PR 907, amendment revision 3): legacy replay, malformed shapes, invalid lookup -----------

LEGACY_NOTE = f"Old summary that mentions {companion_paths.TRAILER_HEADER} in prose."


async def as_legacy_amendment(db, a, state, companion_map):
    """Create an amendment, then rewrite it as an old-format record whose plain summary contains the header text.

    An old record predates the map, so it is created while the map is empty and carries no trailer.
    """
    saved, companion_map["map"] = companion_map["map"], {}
    revision, request, _ = await github_approval_service.create_scope_amendment_request(
        db, a.item, a.scope, **{**amendment(a), "summary": "Placeholder summary"})
    companion_map["map"] = saved
    revision.summary = LEGACY_NOTE
    payload = github_approval_service.canonical_continuation_payload(phase=revision.phase,
        execution_target=revision.execution_target, summary=revision.summary, allowed_paths=revision.allowed_paths,
        allowed_actions=revision.allowed_actions, allowed_commands=revision.allowed_commands,
        prohibited_actions=revision.prohibited_actions, max_failed_heads=revision.max_failed_heads,
        tool_fallbacks=revision.tool_fallbacks, baseline_head_sha=revision.baseline_head_sha,
        baseline_tree_sha=revision.baseline_tree_sha, expected_workspace_id=revision.expected_workspace_id,
        originating_escalation_reason="")
    payload.update(origin_kind=revision.origin_kind, amendment_base_paths=revision.amendment_base_paths,
        amendment_added_paths=revision.amendment_added_paths, previous_scope_revision=revision.previous_scope_revision)
    request.request_fingerprint = github_approval_service.fingerprint_payload(payload)
    revision.status = state
    request.status = "pending" if state == "proposed" else ("approved" if state == "active" else state)
    await db.commit()
    return revision, request


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["proposed", "approved", "rejected", "active"])
async def test_an_old_plain_summary_that_mentions_the_reserved_text_replays_exactly(db, companion_map, healthy_attempt, state):
    a = healthy_attempt
    revision, request = await as_legacy_amendment(db, a, state, companion_map)
    replay = await github_approval_service.create_scope_amendment_request(
        db, a.item, a.scope, **{**amendment(a), "summary": LEGACY_NOTE})
    assert not replay[2] and replay[0].id == revision.id and replay[1].id == request.id


@pytest.mark.asyncio
async def test_the_reserved_text_is_still_refused_for_a_changed_or_new_request(db, companion_map, healthy_attempt):
    a = healthy_attempt
    await as_legacy_amendment(db, a, "rejected", companion_map)
    with pytest.raises(GithubApprovalError, match="continuation_summary_reserved"):
        await github_approval_service.create_scope_amendment_request(
            db, a.item, a.scope, **{**amendment(a), "summary": LEGACY_NOTE + " Changed."})
    with pytest.raises(GithubApprovalError, match="continuation_summary_reserved"):
        await github_approval_service.create_scope_amendment_request(
            db, a.item, a.scope, **{**amendment(a, ["src/base.py", "src/other.py"]), "summary": LEGACY_NOTE})


@pytest.mark.asyncio
@pytest.mark.parametrize("opaque", [[{}], [["nested"]], ["tests/test_base.py", 1], ["tests/test_base.py", None]])
async def test_unsupported_legacy_companion_shapes_keep_only_the_named_authority(db, companion_map, healthy_attempt, opaque):
    a = healthy_attempt
    await make_legacy(db, a, {"allowed_paths": ["src/base.py"], "companion_provenance": "checked-in-map-v1",
                              "companion_paths": opaque})
    base = await github_approval_service.amendment_base_paths(db, a.item, a.owner, a.leader)
    assert base == ["src/base.py"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [["src/base.py", "../x"], ["src/base.py", "src/*.py"], ["src/base.py", ""]])
async def test_a_path_list_that_fails_validation_gets_no_companions(db, companion_map, healthy_attempt, invalid):
    a = healthy_attempt
    item_id, nonce, owner_id, approval_id = a.item.id, a.item.dispatch_nonce, a.owner.id, a.approval.id
    a.approval.status = "superseded"
    await db.commit()
    direct = await github_approval_service.initial_plan_metadata(db, a.item, "A new plan", {"allowed_paths": invalid})
    assert "companion_paths" not in direct and "companion_provenance" not in direct
    session = await db.scalar(select(MailAgentSession).where(MailAgentSession.member_id == owner_id))
    response = await agent_mail.request_work_item_approval(MailApprovalRequestCreate(
        work_item_id=item_id, dispatch_nonce=nonce, summary="A new plan",
        plan_metadata={"allowed_paths": invalid}), session, db)
    assert response.id != approval_id
    message = await db.get(MailMessage, (await db.get(GithubApprovalRequest, response.id)).request_message_id)
    assert "companion_paths" not in message.payload["plan_metadata"] and "ompanion" not in message.body_markdown
