"""Reviewer verdicts bound to an exact PR head, and the fail-closed auto-merge acceptance gate (#904).

A fact is recorded by an authenticated current team verifier who is not the owner or the Leader, for the PR's
current head, with the source review linked. The gate reads the latest active fact for the current head and
re-checks the reviewer, so rebinding the slot or changing its role after the fact withdraws its effect.
"""
import re
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, update

from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubHeadReview,
    GithubWorkItem,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.github_approval_service import GithubApprovalError, github_approval_service
from app.services.github_client import GithubClientResponseError, github_client

VERIFIER_ROLE = "verifier"
VERDICTS = frozenset({"accepted", "changes_required"})
_ROLE_TRIM = " \t\r\n"


def _short(sha) -> str:
    return str(sha)[:7]


async def current_reviewer(db, scope: TeamGithubScope, item: GithubWorkItem, member_id) -> MailTeamMember | None:
    """The member if it is, now, the current member of an enabled verifier slot that is not the owner or Leader."""
    from app.services.github_dispatch_service import github_dispatch_service
    if not isinstance(member_id, int):
        return None
    member = await db.get(MailTeamMember, member_id)
    if member is None or member.team_preset_id != scope.preset_id or member.team_slot_id is None:
        return None
    slot = await db.get(AgentTeamSlot, member.team_slot_id)
    preset = await db.get(AgentTeamPreset, scope.preset_id)
    if (slot is None or slot.preset_id != scope.preset_id or not slot.enabled
            or (slot.role or "").strip(_ROLE_TRIM).lower() != VERIFIER_ROLE
            or slot.id == item.owner_slot_id or (preset is not None and slot.id == preset.leader_slot_id)):
        return None
    current = await github_dispatch_service._slot_member(db, slot.id)
    if current is None or current.id != member.id:
        return None
    return member


def _valid_evidence(scope: TeamGithubScope, item: GithubWorkItem, evidence_url) -> bool:
    if not isinstance(evidence_url, str):
        return False
    url = urlsplit(evidence_url)
    return (url.scheme == "https" and url.netloc == "github.com" and not url.username and not url.password
            and url.path == f"/{scope.repo_owner}/{scope.repo_name}/pull/{item.pr_number}"
            and url.fragment.startswith("pullrequestreview-"))


async def record_head_review(db, item: GithubWorkItem, *, dispatch_nonce, head_sha, reviewer_member_id, verdict,
                             summary, evidence_url, actor=None) -> GithubHeadReview:
    if verdict not in VERDICTS or not isinstance(summary, str) or not summary.strip():
        raise GithubApprovalError("structured_review_required", status_code=400)
    if (item.dispatch_nonce != dispatch_nonce or item.pr_number is None or not isinstance(head_sha, str)
            or not re.fullmatch(r"[0-9a-f]{40}", head_sha)):
        raise GithubApprovalError("stale_revision_review")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if not _valid_evidence(scope, item, evidence_url):
        raise GithubApprovalError("revision_review_evidence_invalid", status_code=400)
    if await current_reviewer(db, scope, item, reviewer_member_id) is None:
        raise GithubApprovalError("current_independent_reviewer_required", status_code=403)
    try:
        pull = await github_client.get_pull(scope.repo_owner, scope.repo_name, item.pr_number,
                                            token=await github_approval_service.github_read_token(scope))
    except (httpx.HTTPError, GithubClientResponseError) as exc:
        raise GithubApprovalError("revision_review_head_changed") from exc
    head = (pull.get("head") or {}) if isinstance(pull, dict) else {}
    if (not isinstance(pull, dict) or pull.get("number") != item.pr_number or pull.get("state") != "open"
            or pull.get("merged_at") or head.get("sha") != head_sha):
        raise GithubApprovalError("revision_review_head_changed")
    where = (GithubHeadReview.work_item_id == item.id, GithubHeadReview.dispatch_nonce == dispatch_nonce,
             GithubHeadReview.pr_number == item.pr_number, GithubHeadReview.head_sha == head_sha,
             GithubHeadReview.status == "active")
    active = list((await db.scalars(select(GithubHeadReview).where(*where).order_by(GithubHeadReview.id))).all())
    for row in active:
        if (row.reviewer_member_id == reviewer_member_id and row.verdict == verdict
                and row.summary == summary.strip() and row.evidence_url == evidence_url):
            return row
    now = datetime.utcnow()
    await db.execute(update(GithubHeadReview).where(*where).values(status="superseded", ended_at=now)
                     .execution_options(synchronize_session=False))
    fact = GithubHeadReview(work_item_id=item.id, dispatch_nonce=dispatch_nonce, pr_number=item.pr_number,
        head_sha=head_sha, scope_revision=item.active_scope_revision or 0, reviewer_member_id=reviewer_member_id,
        verdict=verdict, summary=summary.strip(), evidence_url=evidence_url)
    db.add(fact)
    item.status_note = (f"Reviewer accepted head {_short(head_sha)}; merge gates still apply." if verdict == "accepted"
                        else f"Reviewer requires changes at head {_short(head_sha)}.")
    item.updated_at = now
    await db.commit()
    return fact


async def gate_note(db, scope: TeamGithubScope, item: GithubWorkItem, head_sha) -> str | None:
    """None when the current head carries a valid acceptance; otherwise the work-view note that blocks the merge."""
    head = _short(head_sha)
    latest = await db.scalar(select(GithubHeadReview).where(
        GithubHeadReview.work_item_id == item.id, GithubHeadReview.dispatch_nonce == item.dispatch_nonce,
        GithubHeadReview.pr_number == item.pr_number, GithubHeadReview.head_sha == head_sha,
        GithubHeadReview.status == "active").order_by(GithubHeadReview.id.desc()).limit(1))
    if latest is not None:
        if latest.verdict != "accepted":
            return f"Reviewer requires changes at head {head}."
        if await current_reviewer(db, scope, item, latest.reviewer_member_id) is None:
            return f"The acceptance at head {head} is no longer from a current verifier; a new acceptance is needed."
        return None
    earlier = await db.scalar(select(GithubHeadReview).where(
        GithubHeadReview.work_item_id == item.id, GithubHeadReview.dispatch_nonce == item.dispatch_nonce,
        GithubHeadReview.pr_number == item.pr_number, GithubHeadReview.verdict == "accepted",
        GithubHeadReview.status == "active").order_by(GithubHeadReview.id.desc()).limit(1))
    if earlier is not None:
        return f"Head changed since acceptance (accepted at {_short(earlier.head_sha)}, head is {head})."
    return f"Waiting for reviewer acceptance at {head}."
