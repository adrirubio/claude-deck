"""Ordinary review guidance must not manufacture recovery authority."""

from types import SimpleNamespace

import pytest

from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_verification_service import github_verification_service
from tests.agent_teams.test_github_verification_service import _item, _scope


def test_initial_review_guidance_requires_existing_authority():
    text = github_dispatch_service.review_rework_guidance(
        SimpleNamespace(active_scope_revision=0, attempt_phase="implementation",
                        dispatch_status="ready_for_review"))
    for required in ("still-approved initial", "owner binding", "dispatch nonce",
                     "workspace lease", "normalized", "acknowledgement",
                     "stale", "operator pause", "safety hold",
                     "continuation_disabled", "new full SHA", "not approval"):
        assert required in text
    assert "Do not manufacture an escalation" in text
    assert "Do not submit a second PR-open report" in text


@pytest.mark.parametrize("revision,phase", [(1, "implementation"), (0, "diagnostic"),
                                             (1, "diagnostic")])
def test_scoped_guidance_preserves_completion_and_budgets(revision, phase):
    text = github_dispatch_service.review_rework_guidance(
        SimpleNamespace(active_scope_revision=revision, attempt_phase=phase,
                        dispatch_status="ready_for_review"))
    assert "finite budgets" in text
    assert "completed revision does not authorize another head" in text
    assert "does not grant approval" in text
    assert "ORDINARY PR REVIEW CORRECTIONS" not in text


def test_owner_and_leader_receive_same_review_rule():
    item = SimpleNamespace(id=12, dispatch_nonce="fixture-attempt", issue_type="code",
                           active_scope_revision=0, attempt_phase="implementation",
                           dispatch_status="dispatched")
    guidance = github_dispatch_service.review_rework_guidance(item)
    owner = github_dispatch_service._leader_ack_instruction(
        None, None, before="editing", item=item)
    leader = github_dispatch_service._leader_unblock_instructions()
    assert guidance in owner and guidance in leader
    assert "deck_approve_work_item" in owner
    assert "PR REVIEW LOOP" in leader


@pytest.mark.parametrize("status", ["escalated", "merged", "failed", "cancelled",
                                    "done", "unknown", None])
def test_stopped_or_unknown_attempts_get_no_ordinary_rework_instruction(status):
    text = github_dispatch_service.review_rework_guidance(
        SimpleNamespace(active_scope_revision=0, attempt_phase="implementation",
                        dispatch_status=status))
    assert "Do not make ordinary review corrections" in text
    assert "supported recovery" in text
    assert "does not grant approval" in text
    assert "ORDINARY PR REVIEW CORRECTIONS" not in text


@pytest.mark.asyncio
async def test_ready_mail_identifies_verified_head_and_review_loop(db, monkeypatch):
    scope = await _scope(db, merge_policy="human")
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5,
                       last_verified_sha="verified-head")
    notifications = []

    async def capture(_db, **kwargs):
        notifications.append(kwargs)

    monkeypatch.setattr(github_dispatch_service, "notify_team", capture)
    await github_verification_service._notify_code_pr_ready_for_review(db, item)
    sent = notifications[0]
    assert sent["payload"]["verified_head_sha"] == "verified-head"
    assert "Verified head: verified-head" in sent["body_markdown"]
    assert github_dispatch_service.review_rework_guidance(item) in sent["body_markdown"]
    assert "does not establish independent review acceptance" in sent["body_markdown"]
