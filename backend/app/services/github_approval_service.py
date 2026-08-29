"""Normalized approval authority for autonomous GitHub work items."""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    MailMessage,
)
from app.services.agent_mail_service import agent_mail_service


class GithubApprovalError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 409):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class GithubApprovalService:
    @staticmethod
    def canonical_payload_bytes(payload: dict) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @classmethod
    def fingerprint_payload(cls, payload: dict) -> str:
        return hashlib.sha256(cls.canonical_payload_bytes(payload)).hexdigest()

    async def current_pending(
        self,
        db: AsyncSession,
        work_item_id: int,
    ) -> GithubApprovalRequest | None:
        return (
            await db.execute(
                select(GithubApprovalRequest).where(
                    GithubApprovalRequest.work_item_id == work_item_id,
                    GithubApprovalRequest.status == "pending",
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    def _same_request(
        request: GithubApprovalRequest,
        *,
        request_kind: str,
        dispatch_nonce: str,
        approval_round: int,
        owner_member_id: int,
        leader_member_id: int,
        request_fingerprint: str,
    ) -> bool:
        return (
            request.request_kind == request_kind
            and request.dispatch_nonce == dispatch_nonce
            and request.approval_round == approval_round
            and request.owner_member_id == owner_member_id
            and request.leader_member_id == leader_member_id
            and request.request_fingerprint == request_fingerprint
        )

    @staticmethod
    def _attempt_identity_changed(
        request: GithubApprovalRequest,
        *,
        dispatch_nonce: str,
        approval_round: int,
        owner_member_id: int,
        leader_member_id: int,
    ) -> bool:
        return (
            request.dispatch_nonce != dispatch_nonce
            or request.approval_round != approval_round
            or request.owner_member_id != owner_member_id
            or request.leader_member_id != leader_member_id
        )

    async def _current_participants(self, db: AsyncSession, item: GithubWorkItem):
        owner, leader = await agent_mail_service._dispatch_participants(db, item)
        if owner is None:
            raise GithubApprovalError("owner_not_registered", status_code=409)
        if leader is None:
            raise GithubApprovalError("leader_not_registered", status_code=409)
        if owner.id == leader.id:
            raise GithubApprovalError("owner_cannot_approve_own_work", status_code=409)
        return owner, leader

    async def create_initial_request(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        authenticated_owner_member_id: int,
        summary: str,
        plan_metadata: dict | None = None,
    ) -> tuple[GithubApprovalRequest, bool]:
        if item.dispatch_nonce is None:
            raise GithubApprovalError("dispatch_nonce_missing", status_code=409)
        if item.approval_round_count < 1:
            raise GithubApprovalError("approval_round_not_open", status_code=409)
        if item.dispatch_status == "escalated":
            raise GithubApprovalError("item_escalated", status_code=409)
        owner, leader = await self._current_participants(db, item)
        if owner.id != authenticated_owner_member_id:
            raise GithubApprovalError("not_item_owner", status_code=403)

        canonical_payload = {
            "plan_metadata": plan_metadata or {},
            "summary": summary.strip(),
        }
        request_fingerprint = self.fingerprint_payload(canonical_payload)
        identity = {
            "request_kind": "initial_plan",
            "dispatch_nonce": item.dispatch_nonce,
            "approval_round": item.approval_round_count,
            "owner_member_id": owner.id,
            "leader_member_id": leader.id,
            "request_fingerprint": request_fingerprint,
        }
        pending = await self.current_pending(db, item.id)
        if pending is not None:
            if self._same_request(pending, **identity):
                return pending, False
            if not self._attempt_identity_changed(
                pending,
                dispatch_nonce=item.dispatch_nonce,
                approval_round=item.approval_round_count,
                owner_member_id=owner.id,
                leader_member_id=leader.id,
            ):
                raise GithubApprovalError("approval_request_already_pending")
            pending.status = "superseded"
            pending.superseded_at = datetime.utcnow()
            if pending.request_message_id is not None:
                root = await db.get(MailMessage, pending.request_message_id)
                if root is not None and root.request_status == "pending":
                    root.request_status = "superseded"
            await db.flush()

        request = GithubApprovalRequest(work_item_id=item.id, **identity)
        db.add(request)
        try:
            await db.commit()
            await db.refresh(request)
            return request, True
        except IntegrityError:
            await db.rollback()
            winner = await self.current_pending(db, item.id)
            if winner is not None and self._same_request(winner, **identity):
                return winner, False
            raise GithubApprovalError("approval_request_already_pending")

    async def resolve_for_decision(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        request_id: int | None,
    ) -> GithubApprovalRequest:
        if request_id is not None:
            request = await db.get(GithubApprovalRequest, request_id)
            if request is None or request.work_item_id != item.id:
                raise GithubApprovalError("approval_request_not_found", status_code=404)
            return request
        pending = await self.current_pending(db, item.id)
        if pending is not None:
            return pending
        request = (
            await db.execute(
                select(GithubApprovalRequest)
                .where(
                    GithubApprovalRequest.work_item_id == item.id,
                    GithubApprovalRequest.request_kind == "initial_plan",
                    GithubApprovalRequest.dispatch_nonce == item.dispatch_nonce,
                    GithubApprovalRequest.approval_round == item.approval_round_count,
                    GithubApprovalRequest.status.in_(("approved", "rejected")),
                )
                .order_by(GithubApprovalRequest.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if request is None:
            raise GithubApprovalError("no_current_approval_request", status_code=404)
        return request

    async def decide(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        authenticated_leader_member_id: int,
        decision: str,
        reason: str,
        request_id: int | None = None,
    ) -> tuple[GithubApprovalRequest, bool]:
        request = await self.resolve_for_decision(db, item, request_id=request_id)
        owner, leader = await self._current_participants(db, item)
        if leader.id != authenticated_leader_member_id:
            raise GithubApprovalError("not_designated_leader", status_code=403)
        if request.owner_member_id != owner.id:
            raise GithubApprovalError("stale_approval_owner")
        if request.leader_member_id != leader.id:
            raise GithubApprovalError("stale_approval_recipient")
        if request.dispatch_nonce != item.dispatch_nonce:
            raise GithubApprovalError("stale_nonce")
        if request.approval_round != item.approval_round_count:
            raise GithubApprovalError("approval_round_mismatch")
        if request.status != "pending":
            if request.status == decision and request.reason == reason:
                return request, False
            raise GithubApprovalError("approval_request_already_decided")
        request.status = decision
        request.reason = reason
        request.decided_at = datetime.utcnow()
        await db.commit()
        await db.refresh(request)
        return request, True

    async def cancel(
        self,
        db: AsyncSession,
        request: GithubApprovalRequest,
        *,
        requester_member_id: int | None = None,
        operator: bool = False,
    ) -> tuple[GithubApprovalRequest, bool]:
        if not operator and requester_member_id != request.owner_member_id:
            raise GithubApprovalError("not_approval_requester", status_code=403)
        if request.status == "superseded":
            return request, False
        if request.status != "pending":
            raise GithubApprovalError("request_not_pending")
        now = datetime.utcnow()
        request.status = "superseded"
        request.superseded_at = now
        if request.scope_revision_id is not None:
            revision = await db.get(
                GithubAttemptScopeRevision,
                request.scope_revision_id,
            )
            if revision is not None:
                revision.status = "superseded"
        if request.request_message_id is not None:
            root = await db.get(MailMessage, request.request_message_id)
            if root is not None:
                root.request_status = "superseded"
        await db.commit()
        await db.refresh(request)
        return request, True


github_approval_service = GithubApprovalService()
