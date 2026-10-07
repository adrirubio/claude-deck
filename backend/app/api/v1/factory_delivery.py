"""Operator APIs for team scope delivery choices and explicit attempt adoption."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_operator
from app.database import get_db
from app.models.database import GithubDeliveryPolicyEvent, GithubWorkItem, TeamGithubScope
from app.models.schemas import GithubAttemptDeliveryPolicyUpdate, TeamGithubDeliveryPolicyUpdate
from app.services.factory_delivery_policy import (
    adopt_attempt_policy, effective_policy, scope_policy, update_scope_policy,
)

router = APIRouter(dependencies=[Depends(require_operator)])


@router.patch("/github-scopes/{scope_id}/delivery-policy")
async def set_scope_policy(scope_id: int, request: TeamGithubDeliveryPolicyUpdate,
                           db: AsyncSession = Depends(get_db)):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(404, "GitHub scope not found")
    if not await update_scope_policy(db, scope, expected_revision=request.expected_revision,
                                      policy=request.policy, reason=request.reason):
        raise HTTPException(409, "delivery_policy_revision_changed")
    return {"scope_id": scope.id, "revision": scope.delivery_policy_revision,
            "policy": scope_policy(scope)}


@router.patch("/github-work-items/{item_id}/delivery-policy")
async def set_attempt_policy(item_id: int, request: GithubAttemptDeliveryPolicyUpdate,
                             db: AsyncSession = Depends(get_db)):
    item = await db.get(GithubWorkItem, item_id)
    if item is None:
        raise HTTPException(404, "GitHub work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(404, "GitHub scope not found")
    if not await adopt_attempt_policy(
        db, item, scope,
        expected_dispatch_nonce=request.expected_dispatch_nonce,
        expected_scope_revision=request.expected_scope_revision,
        expected_policy_revision=request.expected_policy_revision,
        target_policy_revision=request.target_policy_revision,
        reason=request.reason,
    ):
        raise HTTPException(409, "attempt_delivery_policy_context_changed")
    return {"work_item_id": item.id, "scope_id": scope.id,
            "revision": item.delivery_policy_revision, "policy": effective_policy(item, scope)}


@router.get("/github-scopes/{scope_id}/delivery-policy/history")
async def scope_policy_history(scope_id: int, db: AsyncSession = Depends(get_db)):
    if await db.get(TeamGithubScope, scope_id) is None:
        raise HTTPException(404, "GitHub scope not found")
    events = (await db.execute(select(GithubDeliveryPolicyEvent).where(
        GithubDeliveryPolicyEvent.scope_id == scope_id,
    ).order_by(GithubDeliveryPolicyEvent.id.desc()).limit(100))).scalars().all()
    return {"events": [{"id": event.id, "scope_id": event.scope_id,
                         "work_item_id": event.work_item_id, "revision": event.revision,
                         "policy": event.policy, "reason": event.reason,
                         "actor": event.actor, "created_at": event.created_at}
                        for event in events]}
