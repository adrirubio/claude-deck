"""Companion paths: the checked-in map, the Leader-visible plan, and the amendment baseline."""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api.v1 import agent_mail
from app.models.database import GithubApprovalRequest, MailAgentSession, MailMessage
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
    assert result == {"allowed_paths": ["src/base.py"], "note": "x", "companion_paths": ["tests/test_base.py"]}
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
