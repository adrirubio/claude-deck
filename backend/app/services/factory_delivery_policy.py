"""Delivery choices are scoped data. Authentication and approvals remain separate."""
from __future__ import annotations

from copy import deepcopy

from sqlalchemy import JSON, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import GithubDeliveryPolicyEvent, GithubWorkItem, TeamGithubScope
from app.models.schemas import FactoryDeliveryPolicy


def scope_policy(scope: TeamGithubScope) -> FactoryDeliveryPolicy:
    return FactoryDeliveryPolicy.model_validate(scope.delivery_policy or {})


def effective_policy(item: GithubWorkItem, scope: TeamGithubScope) -> FactoryDeliveryPolicy:
    # Pre-upgrade active attempts retain legacy rules until explicit adoption.
    value = item.delivery_policy if item.delivery_policy is not None else (
        {} if item.dispatch_nonce else scope.delivery_policy or {})
    return FactoryDeliveryPolicy.model_validate(value)


def policy_context(item: GithubWorkItem) -> tuple:
    return item.delivery_policy_revision, deepcopy(item.delivery_policy)


def policy_context_conditions(context: tuple) -> list:
    revision, policy = context
    value = (or_(GithubWorkItem.delivery_policy.is_(None), GithubWorkItem.delivery_policy == JSON.NULL)
             if policy is None else GithubWorkItem.delivery_policy == policy)
    return [GithubWorkItem.delivery_policy_revision == revision, value]


async def claim_policy_context(db: AsyncSession, item: GithubWorkItem, context: tuple) -> bool:
    result = await db.execute(update(GithubWorkItem).where(
        GithubWorkItem.id == item.id, GithubWorkItem.dispatch_nonce == item.dispatch_nonce,
        GithubWorkItem.owner_slot_id == item.owner_slot_id,
        GithubWorkItem.active_scope_revision == item.active_scope_revision,
        GithubWorkItem.dispatch_status == item.dispatch_status,
        *policy_context_conditions(context),
    ).values(updated_at=GithubWorkItem.updated_at).execution_options(synchronize_session=False))
    if result.rowcount == 1:
        return True
    await db.rollback()
    return False


async def update_scope_policy(db: AsyncSession, scope: TeamGithubScope, *,
                              expected_revision: int, policy: FactoryDeliveryPolicy,
                              reason: str) -> bool:
    value = policy.model_dump(mode="json")
    result = await db.execute(update(TeamGithubScope).where(
        TeamGithubScope.id == scope.id,
        TeamGithubScope.delivery_policy_revision == expected_revision,
    ).values(delivery_policy=value, delivery_policy_revision=expected_revision + 1)
      .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        await db.refresh(scope)
        return False
    db.add(GithubDeliveryPolicyEvent(scope_id=scope.id, revision=expected_revision + 1,
                                    policy=value, reason=reason))
    await db.commit()
    await db.refresh(scope)
    return True


async def adopt_attempt_policy(db: AsyncSession, item: GithubWorkItem, scope: TeamGithubScope,
                               *, expected_dispatch_nonce: str, expected_scope_revision: int,
                               expected_policy_revision: int | None,
                               target_policy_revision: int, reason: str) -> bool:
    # Do not modify a verification or review that already has candidate evidence.
    value = scope_policy(scope).model_dump(mode="json")
    result = await db.execute(update(GithubWorkItem).where(
        GithubWorkItem.id == item.id, GithubWorkItem.scope_id == scope.id,
        GithubWorkItem.dispatch_nonce == expected_dispatch_nonce,
        GithubWorkItem.active_scope_revision == expected_scope_revision,
        GithubWorkItem.delivery_policy_revision == expected_policy_revision,
        GithubWorkItem.dispatch_status.in_(("pending", "dispatched", "escalated")),
        exists(select(TeamGithubScope.id).where(
            TeamGithubScope.id == scope.id,
            TeamGithubScope.delivery_policy_revision == target_policy_revision,
            TeamGithubScope.delivery_policy == (scope.delivery_policy or {}),
        )),
    ).values(delivery_policy=value, delivery_policy_revision=target_policy_revision)
      .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        await db.refresh(item)
        await db.refresh(scope)
        return False
    db.add(GithubDeliveryPolicyEvent(scope_id=scope.id, work_item_id=item.id,
                                    revision=target_policy_revision, policy=value, reason=reason))
    await db.commit()
    await db.refresh(item)
    return True


def required_check_blockers(policy: FactoryDeliveryPolicy, checks: list[dict],
                            head_sha: str | None) -> list[str]:
    blockers = []
    for required in policy.required_checks:
        rows = [row for row in checks if row.get("name") == required.name
                and (row.get("app") or {}).get("slug") == required.app_slug
                and row.get("head_sha") == head_sha]
        if not rows:
            blockers.append(f"{required.name}: missing")
        elif any(row.get("status") != "completed" or row.get("conclusion") != "success"
                 for row in rows):
            blockers.append(f"{required.name}: success required")
    return blockers


def policy_guidance(policy: FactoryDeliveryPolicy, revision: int | None) -> str:
    lines = [f"Delivery policy revision: {revision or 'legacy'}. Review one complete correction batch."]
    if policy.required_checks:
        names = ", ".join(check.name for check in policy.required_checks)
        lines.append(f"Required hosted jobs: {names}. Each job must succeed on the candidate commit.")
    if policy.broad_checks == "hosted":
        lines.append("Run focused checks locally. Use the required hosted broad checks for final evidence.")
    else:
        lines.append("Run the agreed broad checks once before publishing a complete shared-service batch.")
    if policy.owner_contact == "native":
        lines.append("Fresh bound native work can renew owner contact. It grants no approval or scope.")
        lines.append("Use progress reports when native evidence is unknown or idle. Report state changes through Mail.")
        if policy.owner_observation_wait_seconds is not None:
            lines.append(f"Unknown native evidence can use a bounded {policy.owner_observation_wait_seconds}-second observation wait after the usual nudge.")
            lines.append("A recorded observation pause preserves approval and budgets. Only the operator can resume its unchanged context.")
    else:
        lines.append("Use owner progress reports before the configured idle timeout.")
    if policy.checkpoint_delay_report_seconds is not None:
        lines.append(f"Report a checkpoint publication delay after {policy.checkpoint_delay_report_seconds} seconds.")
    if policy.caller_inventory_required:
        lines.append("Record and review the caller inventory before shared-consumer edits. Label design advice separately from acceptance.")
    if policy.regression_proof_required:
        lines.append("For each regression, show an assertion failure on its known defective source and a pass on the candidate.")
        lines.append("Keep the baseline production code intact. Import and fixture errors are not regression proof.")
    lines.append("The work-item plan owns effort limits and acceptance criteria. Record work and wait intervals. Ask the operator at the limit.")
    return "\n".join(lines)
