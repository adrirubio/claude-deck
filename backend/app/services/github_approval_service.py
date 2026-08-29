"""Normalized approval authority for autonomous GitHub work items."""

import hashlib
import json
from datetime import datetime

from sqlalchemy import exists, select, update
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

    @classmethod
    def initial_request_fingerprint(
        cls,
        *,
        summary: str,
        plan_metadata: dict | None,
    ) -> str:
        return cls.fingerprint_payload(
            {
                "plan_metadata": plan_metadata or {},
                "summary": summary.strip(),
            }
        )

    @classmethod
    def matches_linked_request_message(
        cls,
        request: GithubApprovalRequest,
        message: MailMessage,
        *,
        delivery_key: str,
    ) -> bool:
        valid_request_statuses = (
            {"pending"}
            if request.status == "pending"
            else {"pending", "answered"}
        )
        if (
            message.kind != "context_request"
            or message.thread_root_id is not None
            or message.request_status not in valid_request_statuses
            or message.sender_member_id != request.owner_member_id
            or message.recipient_member_id != request.leader_member_id
            or message.delivery_key not in {None, delivery_key}
        ):
            return False
        payload = message.payload if isinstance(message.payload, dict) else {}
        if (
            payload.get("work_item_id") != request.work_item_id
            or payload.get("dispatch_nonce") != request.dispatch_nonce
            or payload.get("approval_round") != request.approval_round
        ):
            return False
        summary = payload.get("summary")
        if not isinstance(summary, str):
            summary = message.body_markdown
        plan_metadata = payload.get("plan_metadata")
        if not isinstance(plan_metadata, dict):
            plan_metadata = {}
        return request.request_fingerprint == cls.initial_request_fingerprint(
            summary=summary,
            plan_metadata=plan_metadata,
        )

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

    async def current_terminal_for_attempt(
        self,
        db: AsyncSession,
        *,
        work_item_id: int,
        dispatch_nonce: str,
        approval_round: int,
        owner_member_id: int,
        leader_member_id: int,
    ) -> GithubApprovalRequest | None:
        return (
            await db.execute(
                select(GithubApprovalRequest)
                .where(
                    GithubApprovalRequest.work_item_id == work_item_id,
                    GithubApprovalRequest.request_kind == "initial_plan",
                    GithubApprovalRequest.dispatch_nonce == dispatch_nonce,
                    GithubApprovalRequest.approval_round == approval_round,
                    GithubApprovalRequest.owner_member_id == owner_member_id,
                    GithubApprovalRequest.leader_member_id == leader_member_id,
                    GithubApprovalRequest.status.in_({"approved", "rejected"}),
                )
                .order_by(GithubApprovalRequest.id.desc())
                .limit(1)
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
        if owner.id == leader.id or owner.team_slot_id == leader.team_slot_id:
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
        if not summary.strip():
            raise GithubApprovalError("approval_summary_required", status_code=400)
        if item.dispatch_nonce is None:
            raise GithubApprovalError("dispatch_nonce_missing", status_code=409)
        if item.approval_round_count < 1:
            raise GithubApprovalError("approval_round_not_open", status_code=409)
        if item.dispatch_status == "escalated":
            raise GithubApprovalError("item_escalated", status_code=409)
        owner, leader = await self._current_participants(db, item)
        if owner.id != authenticated_owner_member_id:
            raise GithubApprovalError("not_item_owner", status_code=403)

        request_fingerprint = self.initial_request_fingerprint(
            summary=summary,
            plan_metadata=plan_metadata,
        )
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

        terminal = await self.current_terminal_for_attempt(
            db,
            work_item_id=item.id,
            dispatch_nonce=item.dispatch_nonce,
            approval_round=item.approval_round_count,
            owner_member_id=owner.id,
            leader_member_id=leader.id,
        )
        if terminal is not None:
            if self._same_request(terminal, **identity):
                return terminal, False
            raise GithubApprovalError("approval_request_already_decided")

        if pending is not None:
            pending.status = "superseded"
            pending.superseded_at = datetime.utcnow()
            if pending.request_message_id is not None:
                root = await db.get(MailMessage, pending.request_message_id)
                if root is not None and root.request_status == "pending":
                    root.request_status = "superseded"
            await db.flush()

        work_item_id = item.id
        if owner.team_slot_id is None:
            raise GithubApprovalError("stale_approval_owner")
        terminal_exists = exists(
            select(GithubApprovalRequest.id).where(
                GithubApprovalRequest.work_item_id == work_item_id,
                GithubApprovalRequest.request_kind == "initial_plan",
                GithubApprovalRequest.dispatch_nonce == item.dispatch_nonce,
                GithubApprovalRequest.approval_round == item.approval_round_count,
                GithubApprovalRequest.owner_member_id == owner.id,
                GithubApprovalRequest.leader_member_id == leader.id,
                GithubApprovalRequest.status.in_({"approved", "rejected"}),
            )
        )
        guard = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == work_item_id,
                GithubWorkItem.dispatch_status != "escalated",
                GithubWorkItem.dispatch_nonce == item.dispatch_nonce,
                GithubWorkItem.approval_round_count == item.approval_round_count,
                GithubWorkItem.owner_slot_id == owner.team_slot_id,
                ~terminal_exists,
            )
            .values(updated_at=GithubWorkItem.updated_at)
            .execution_options(synchronize_session=False)
        )
        if guard.rowcount != 1:
            await db.rollback()
            await db.refresh(item)
            if item.dispatch_status == "escalated":
                raise GithubApprovalError("item_escalated")
            if item.dispatch_nonce != identity["dispatch_nonce"]:
                raise GithubApprovalError("stale_nonce")
            if item.approval_round_count != identity["approval_round"]:
                raise GithubApprovalError("approval_round_mismatch")
            terminal = await self.current_terminal_for_attempt(
                db,
                work_item_id=work_item_id,
                dispatch_nonce=identity["dispatch_nonce"],
                approval_round=identity["approval_round"],
                owner_member_id=identity["owner_member_id"],
                leader_member_id=identity["leader_member_id"],
            )
            if terminal is not None:
                if self._same_request(terminal, **identity):
                    return terminal, False
                raise GithubApprovalError("approval_request_already_decided")
            raise GithubApprovalError("stale_approval_owner")
        request = GithubApprovalRequest(work_item_id=work_item_id, **identity)
        db.add(request)
        try:
            await db.commit()
            await db.refresh(request)
            return request, True
        except IntegrityError:
            await db.rollback()
            winner = await self.current_pending(db, work_item_id)
            if winner is not None and self._same_request(winner, **identity):
                return winner, False
            raise GithubApprovalError("approval_request_already_pending")

    async def resolve_for_decision(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        request_id: int,
    ) -> GithubApprovalRequest:
        request = await db.get(GithubApprovalRequest, request_id)
        if request is None or request.work_item_id != item.id:
            raise GithubApprovalError("approval_request_not_found", status_code=404)
        if request.request_kind != "initial_plan":
            raise GithubApprovalError("approval_request_not_found", status_code=404)
        return request

    async def decide(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        authenticated_leader_member_id: int,
        decision: str,
        reason: str,
        request_id: int,
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
        if request.request_message_id is None:
            raise GithubApprovalError("approval_request_delivery_pending")
        if request.status != "pending":
            if request.status not in {"approved", "rejected"}:
                raise GithubApprovalError("request_not_pending")
            if request.status == decision and request.reason == reason:
                valid_rounds = {request.approval_round}
                if decision == "rejected":
                    valid_rounds.add(request.approval_round + 1)
                if item.approval_round_count not in valid_rounds:
                    raise GithubApprovalError("approval_round_mismatch")
                return request, False
            raise GithubApprovalError("approval_request_already_decided")
        if item.dispatch_status == "escalated":
            raise GithubApprovalError("item_escalated")
        if request.approval_round != item.approval_round_count:
            raise GithubApprovalError("approval_round_mismatch")
        if owner.team_slot_id is None:
            raise GithubApprovalError("stale_approval_owner")
        item_guard = await db.execute(
            update(GithubWorkItem)
            .where(
                GithubWorkItem.id == item.id,
                GithubWorkItem.dispatch_status != "escalated",
                GithubWorkItem.dispatch_nonce == request.dispatch_nonce,
                GithubWorkItem.approval_round_count == request.approval_round,
                GithubWorkItem.owner_slot_id == owner.team_slot_id,
            )
            .values(updated_at=GithubWorkItem.updated_at)
            .execution_options(synchronize_session=False)
        )
        if item_guard.rowcount != 1:
            await db.rollback()
            await db.refresh(item)
            if item.dispatch_status == "escalated":
                raise GithubApprovalError("item_escalated")
            if item.dispatch_nonce != request.dispatch_nonce:
                raise GithubApprovalError("stale_nonce")
            if item.approval_round_count != request.approval_round:
                raise GithubApprovalError("approval_round_mismatch")
            raise GithubApprovalError("stale_approval_owner")
        result = await db.execute(
            update(GithubApprovalRequest)
            .where(
                GithubApprovalRequest.id == request.id,
                GithubApprovalRequest.status == "pending",
                GithubApprovalRequest.request_kind == "initial_plan",
                GithubApprovalRequest.dispatch_nonce == item.dispatch_nonce,
                GithubApprovalRequest.approval_round == item.approval_round_count,
                GithubApprovalRequest.owner_member_id == owner.id,
                GithubApprovalRequest.leader_member_id == leader.id,
                exists(
                    select(GithubWorkItem.id).where(
                        GithubWorkItem.id == request.work_item_id,
                        GithubWorkItem.dispatch_status != "escalated",
                        GithubWorkItem.dispatch_nonce == request.dispatch_nonce,
                        GithubWorkItem.approval_round_count
                        == request.approval_round,
                        GithubWorkItem.owner_slot_id == owner.team_slot_id,
                    )
                ),
            )
            .values(
                status=decision,
                reason=reason,
                decided_at=datetime.utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        await db.refresh(request)
        if result.rowcount == 1:
            return request, True
        if request.status == decision and request.reason == reason:
            return request, False
        await db.refresh(item)
        if item.dispatch_status == "escalated":
            raise GithubApprovalError("item_escalated")
        if item.dispatch_nonce != request.dispatch_nonce:
            raise GithubApprovalError("stale_nonce")
        if item.approval_round_count != request.approval_round:
            raise GithubApprovalError("approval_round_mismatch")
        if item.owner_slot_id != owner.team_slot_id:
            raise GithubApprovalError("stale_approval_owner")
        raise GithubApprovalError("approval_request_already_decided")

    async def cancel(
        self,
        db: AsyncSession,
        request: GithubApprovalRequest,
        *,
        requester_member_id: int,
    ) -> tuple[GithubApprovalRequest, bool]:
        if requester_member_id != request.owner_member_id:
            raise GithubApprovalError("not_approval_requester", status_code=403)
        return await self._cancel_authorized(db, request)

    async def _cancel_authorized(
        self,
        db: AsyncSession,
        request: GithubApprovalRequest,
    ) -> tuple[GithubApprovalRequest, bool]:
        if request.status == "superseded":
            return request, False
        if request.status != "pending":
            raise GithubApprovalError("request_not_pending")
        current = await self.current_pending(db, request.work_item_id)
        if current is None or current.id != request.id:
            raise GithubApprovalError("request_not_pending")
        revision = None
        if request.scope_revision_id is not None:
            revision = await db.get(
                GithubAttemptScopeRevision,
                request.scope_revision_id,
            )
            if revision is None or revision.status != "proposed":
                raise GithubApprovalError("request_not_pending")
        now = datetime.utcnow()
        result = await db.execute(
            update(GithubApprovalRequest)
            .where(
                GithubApprovalRequest.id == request.id,
                GithubApprovalRequest.status == "pending",
            )
            .values(status="superseded", superseded_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await db.rollback()
            await db.refresh(request)
            if request.status == "superseded":
                return request, False
            raise GithubApprovalError("request_not_pending")
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
