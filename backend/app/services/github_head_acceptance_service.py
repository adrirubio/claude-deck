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


async def _fresh_item(db, item_id: int):
    """The work item's authority columns read straight from the database, never from a cached ORM object."""
    return (await db.execute(select(GithubWorkItem.scope_id, GithubWorkItem.owner_slot_id,
        GithubWorkItem.dispatch_nonce, GithubWorkItem.pr_number, GithubWorkItem.active_scope_revision)
        .where(GithubWorkItem.id == item_id).execution_options(populate_existing=True))).one_or_none()


async def current_reviewer(db, scope: TeamGithubScope, item: GithubWorkItem, member_id) -> int | None:
    """The member id if it is, now, the current member of an enabled verifier slot that is not the owner or Leader.

    Every input is read with a column-level SELECT so a change committed by another connection is seen even when
    the session still holds the old ORM objects. Nothing here uses db.get or an entity query.
    """
    if not isinstance(member_id, int):
        return None
    fresh = await _fresh_item(db, item.id)
    if fresh is None:
        return None
    member = (await db.execute(select(MailTeamMember.id, MailTeamMember.team_preset_id, MailTeamMember.team_slot_id)
        .where(MailTeamMember.id == member_id))).one_or_none()
    if member is None or member.team_preset_id != scope.preset_id or member.team_slot_id is None:
        return None
    slot = (await db.execute(select(AgentTeamSlot.id, AgentTeamSlot.preset_id, AgentTeamSlot.enabled, AgentTeamSlot.role)
        .where(AgentTeamSlot.id == member.team_slot_id))).one_or_none()
    leader_slot_id = (await db.execute(select(AgentTeamPreset.leader_slot_id)
        .where(AgentTeamPreset.id == scope.preset_id))).scalar_one_or_none()
    if (slot is None or slot.preset_id != scope.preset_id or not slot.enabled
            or (slot.role or "").strip(_ROLE_TRIM).lower() != VERIFIER_ROLE
            or slot.id == fresh.owner_slot_id or slot.id == leader_slot_id):
        return None
    current = (await db.execute(select(MailTeamMember.id).where(MailTeamMember.team_slot_id == slot.id)
        .order_by(MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).limit(1))).scalar_one_or_none()
    return member.id if current == member.id else None


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
    # The read above awaited GitHub. Authority and dispatch identity can change meanwhile, so read them again,
    # fresh, before any fact is superseded or inserted.
    fresh = await _fresh_item(db, item.id)
    if (fresh is None or fresh.dispatch_nonce != dispatch_nonce or fresh.pr_number != item.pr_number
            or fresh.scope_id != item.scope_id):
        raise GithubApprovalError("stale_revision_review")
    if await current_reviewer(db, scope, item, reviewer_member_id) is None:
        raise GithubApprovalError("current_independent_reviewer_required", status_code=403)
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
    """None when the current head carries a valid acceptance; otherwise the work-view note that blocks the merge.

    The work item identity and every fact are read fresh, so a second connection's change is never hidden by a
    cached object.
    """
    head = _short(head_sha)
    fresh = await _fresh_item(db, item.id)
    if fresh is None or fresh.pr_number is None:
        return f"Waiting for reviewer acceptance at {head}."
    base = (GithubHeadReview.work_item_id == item.id, GithubHeadReview.dispatch_nonce == fresh.dispatch_nonce,
            GithubHeadReview.pr_number == fresh.pr_number, GithubHeadReview.status == "active")
    latest = await db.scalar(select(GithubHeadReview).where(*base, GithubHeadReview.head_sha == head_sha)
        .order_by(GithubHeadReview.id.desc()).limit(1).execution_options(populate_existing=True))
    if latest is not None:
        if latest.verdict != "accepted":
            return f"Reviewer requires changes at head {head}."
        if await current_reviewer(db, scope, item, latest.reviewer_member_id) is None:
            return f"The acceptance at head {head} is no longer from a current verifier; a new acceptance is needed."
        return None
    earlier = await db.scalar(select(GithubHeadReview).where(*base, GithubHeadReview.verdict == "accepted")
        .order_by(GithubHeadReview.id.desc()).limit(1).execution_options(populate_existing=True))
    if earlier is not None:
        return f"Head changed since acceptance (accepted at {_short(earlier.head_sha)}, head is {head})."
    return f"Waiting for reviewer acceptance at {head}."
