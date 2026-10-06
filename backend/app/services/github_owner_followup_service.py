"""Durable notifications for explicitly watched, unfinished initial attempts.

This service never wakes an owner or changes dispatch, approval or lease rows.
Native identities, watch challenges and authority material stay private.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import exists, func, select, update

from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, GithubApprovalRequest,
    GithubBacklogCoordination, GithubOwnerFollowup, GithubWorkItem, GithubWorkspace,
    MailAgentSession, MailMessage, MailPaneLifecycle, MailReceipt, MailTeamMember, TeamGithubScope,
)
from app.models.schemas import MailMessageCreate
from app.services.agent_activity_service import observe_private_team
from app.services.agent_mail_service import (
    AUTO_NUDGE_COOLDOWN_SECONDS, MCP_HEARTBEAT_TTL_SECONDS, MailWakeError, agent_mail_service,
)
from app.services.github_coordination_service import (
    CoordinationError, _MAX_SNAPSHOT_REQUESTS, _current_authority, _digest,
    github_coordination_service as coordination, hold_code,
)
from app.services.github_dispatch_service import github_dispatch_service as dispatch
from app.utils import peer_process

_SECRET = secrets.token_bytes(32)
_TTL = 300
_DEBOUNCE = 5
_MAX_DELIVERY_ATTEMPTS = 3
_ACTIVE = {"waiting", "pending", "notified", "delivered", "capped", "delivery_failed", "delivery_unknown"}


def _token(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True).encode()).decode()
    return payload + "." + hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def _claims(token):
    try:
        if len(token) > 2048:
            raise ValueError()
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature, hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()):
            raise ValueError()
        value = json.loads(base64.b64decode(payload, altchars=b"-_", validate=True))
        integers = {"scope", "item", "leader", "policy", "version", "sequence", "expires", "baseline_at"}
        if (set(value) != integers | {"purpose", "context", "nonce", "baseline_event", "settlement"}
                or value["purpose"] != "owner_followup"
                or any(type(value[k]) is not int or value[k] < 0 for k in integers)
                or not isinstance(value["context"], str) or len(value["context"]) != 64
                or any(not isinstance(value[k], str) or len(value[k]) != 64 for k in ("baseline_event", "settlement"))
                or not isinstance(value["nonce"], str) or len(value["nonce"]) != 32):
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise CoordinationError("followup_read_invalid") from None
    if not time.time() < value["expires"] <= time.time() + _TTL + 1:
        raise CoordinationError("followup_read_expired")
    return value


def _frozen(obj, fields):
    return {key: getattr(obj, key).isoformat() if isinstance(getattr(obj, key), datetime)
            else getattr(obj, key) for key in fields}


def _guard(model, obj, fields):
    return exists(select(model.id).where(model.id == obj.id,
                                        *(getattr(model, key) == getattr(obj, key) for key in fields)))


def _public(watch, item):
    return {"work_item_id": item.id, "issue_number": item.issue_number,
            "state": watch.state if watch else "available",
            "event_sequence": watch.sequence if watch else 0,
            "outcome": watch.outcome if watch else None,
            "settled_at": watch.settled_at if watch else None,
            "required_actor": "leader"}


class GithubOwnerFollowupService:
    async def watches(self, db, scope_id):
        policy = await coordination.state(db, scope_id)
        if policy is None:
            return []
        rows = list((await db.scalars(select(GithubOwnerFollowup).where(
            GithubOwnerFollowup.scope_id == scope_id,
            GithubOwnerFollowup.work_item_id.in_(select(GithubWorkItem.id).where(
                GithubWorkItem.scope_id == scope_id, GithubWorkItem.issue_number.in_(policy.issue_numbers))),
        ).order_by(GithubOwnerFollowup.work_item_id).limit(33).execution_options(populate_existing=True))).all())
        if len(rows) > 32:
            raise CoordinationError("followup_context_limit")
        return rows

    async def context(self, db, scope_id, item_id, activities):
        scope = await coordination.scope(db, scope_id)
        preset = await db.get(AgentTeamPreset, scope.preset_id, populate_existing=True)
        policy = await coordination.state(db, scope_id)
        if not policy or not policy.enabled or not scope.enabled or not preset.autonomy_enabled:
            raise CoordinationError("autonomy_off")
        if code := hold_code():
            raise CoordinationError(code)
        if await db.scalar(select(func.count()).select_from(TeamGithubScope).where(
                TeamGithubScope.preset_id == scope.preset_id, TeamGithubScope.enabled.is_(True))) != 1:
            raise CoordinationError("single_scope_required")
        leader, slots = await coordination.current_leader(db, scope)
        item = await db.get(GithubWorkItem, item_id, populate_existing=True)
        if (not item or item.scope_id != scope_id or item.issue_number not in policy.issue_numbers
                or item.dispatch_status != "dispatched" or item.attempt_phase != "implementation"
                or item.active_scope_revision != 0 or item.escalation_reason
                or item.retry_requested_at is not None or item.handoff_state is not None):
            raise CoordinationError("followup_attempt_ineligible")
        owner_member = await dispatch._owner_member(db, item)
        if (not owner_member or owner_member.id == leader.member_id
                or owner_member.team_preset_id != scope.preset_id
                or owner_member.team_slot_id != item.owner_slot_id
                or owner_member.participant_kind != "team_slot"):
            raise CoordinationError("followup_owner_unavailable")
        owner_slot = next((slot for slot in slots if slot.id == item.owner_slot_id and slot.enabled), None)
        if not owner_slot or owner_slot.provider not in {"codex-cli", "pi-cli"}:
            raise CoordinationError("followup_owner_unavailable")
        evidence = await dispatch._ack_evidence(db, item, slots)
        if (not evidence.ok or item.ack_enforcement_epoch != 1 or item.ack_received_at is None
                or item.dispatched_at is None or item.ack_received_at < item.dispatched_at
                or item.ack_approver_member_id != evidence.approver_member_id
                or item.ack_evidence_message_id != evidence.evidence_message_id
                or item.ack_approval_round != evidence.approval_round):
            raise CoordinationError("followup_initial_authority_invalid")
        approval = await db.scalar(select(GithubApprovalRequest).where(
            GithubApprovalRequest.work_item_id == item.id,
            GithubApprovalRequest.request_kind == "initial_plan").order_by(
                GithubApprovalRequest.id.desc()).limit(1).execution_options(populate_existing=True))
        answer = await db.get(MailMessage, evidence.evidence_message_id, populate_existing=True)
        owner_query = select(MailAgentSession).where(
            MailAgentSession.member_id == owner_member.id,
            MailAgentSession.team_preset_id == scope.preset_id,
            MailAgentSession.team_slot_id == item.owner_slot_id,
            MailAgentSession.provider == owner_slot.provider, MailAgentSession.source == "mcp",
            MailAgentSession.closed_at.is_(None), MailAgentSession.mailbox_status == "connected",
            MailAgentSession.wake_enabled.is_(True), MailAgentSession.capability_token_hash.is_not(None),
            MailAgentSession.last_seen_at >= datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS),
        )
        sessions = list((await db.scalars(owner_query.limit(65).execution_options(populate_existing=True))).all())
        if len(sessions) > 64:
            raise CoordinationError("followup_context_limit")
        live = [session for session in sessions if session.bound_pane_pid and session.bound_pane_proc_start
                and peer_process.pane_is_alive(session.bound_pane_pid, session.bound_pane_proc_start) is True
                and not (session.pid != session.bound_pane_pid and peer_process.process_is_confirmed_dead(session.pid))]
        if len(live) != 1:
            raise CoordinationError("followup_owner_unavailable")
        owner = live[0]
        workspace = await db.scalar(select(GithubWorkspace).where(
            GithubWorkspace.leased_item_id == item.id).execution_options(populate_existing=True))
        if (not workspace or not workspace.enabled or not workspace.dispatchable or workspace.provision_error
                or not workspace.lease_token or workspace.leased_owner_pid != owner.bound_pane_pid
                or workspace.leased_owner_proc_start != owner.bound_pane_proc_start
                or not owner.cwd or Path(owner.cwd).resolve() != Path(workspace.path).resolve()):
            raise CoordinationError("followup_workspace_authority_invalid")
        native_owner, native_leader = activities.get(item.owner_slot_id), activities.get(leader.team_slot_id)
        if not native_owner or not native_leader or not native_owner.identity or not native_leader.identity:
            raise CoordinationError("followup_observation_unknown")
        fields = {
            GithubWorkItem: (item, ("scope_id", "dispatch_status", "dispatch_nonce", "owner_slot_id",
                "active_scope_revision", "attempt_phase", "escalation_reason", "retry_requested_at",
                "handoff_state", "dispatched_at", "approval_round_count", "ack_enforcement_epoch",
                "ack_received_at", "ack_approver_member_id", "ack_evidence_message_id", "ack_approval_round")),
            GithubWorkspace: (workspace, ("scope_id", "path", "enabled", "dispatchable", "provision_error",
                "leased_item_id", "lease_token", "leased_owner_pid", "leased_owner_proc_start")),
            GithubApprovalRequest: (approval, ("work_item_id", "request_kind", "status", "approval_round",
                "dispatch_nonce", "owner_member_id", "leader_member_id", "request_message_id", "decision_message_id")),
            MailMessage: (answer, ("sender_member_id", "kind", "thread_root_id", "decision",
                "approval_round", "delivery_key", "payload")),
            AgentTeamSlot: (owner_slot, ("preset_id", "enabled", "provider", "updated_at")),
        }
        context = {model.__tablename__: {"id": obj.id, **_frozen(obj, names)}
                   for model, (obj, names) in fields.items()}
        authority = _current_authority(scope, preset, leader)
        authority &= _guard(MailTeamMember, owner_member,
                            ("team_preset_id", "team_slot_id", "participant_kind"))
        for model, (obj, names) in fields.items():
            authority &= _guard(model, obj, names)
        authority &= select(GithubApprovalRequest.id).where(
            GithubApprovalRequest.work_item_id == item.id,
            GithubApprovalRequest.request_kind == "initial_plan").order_by(
                GithubApprovalRequest.id.desc()).limit(1).scalar_subquery() == approval.id
        authority &= select(MailTeamMember.id).where(
            MailTeamMember.team_slot_id == item.owner_slot_id).order_by(
                MailTeamMember.updated_at.desc(), MailTeamMember.id.desc()).limit(1).scalar_subquery() == owner_member.id
        session_fields = ("member_id", "provider", "source", "team_preset_id", "team_slot_id", "pid",
                          "cwd", "created_at", "closed_at", "wake_enabled", "mailbox_status",
                          "capability_token_hash", "bound_pane_pid", "bound_pane_proc_start")
        leader_query = select(MailAgentSession).where(
            MailAgentSession.member_id == leader.member_id, MailAgentSession.team_preset_id == scope.preset_id,
            MailAgentSession.team_slot_id == leader.team_slot_id, MailAgentSession.source == "mcp",
            MailAgentSession.closed_at.is_(None), MailAgentSession.mailbox_status == "connected",
            MailAgentSession.wake_enabled.is_(True), MailAgentSession.capability_token_hash.is_not(None),
            MailAgentSession.last_seen_at >= datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS))
        leader_candidates = list((await db.scalars(leader_query.limit(65).execution_options(populate_existing=True))).all())
        if len(leader_candidates) > 64:
            raise CoordinationError("followup_context_limit")
        for session in [leader, *sessions]:
            authority &= _guard(MailAgentSession, session, session_fields)
        for candidate in leader_candidates:
            authority &= _guard(MailAgentSession, candidate, session_fields)
        authority &= select(func.count()).select_from(leader_query.order_by(None).subquery()).scalar_subquery() == len(leader_candidates)
        authority &= select(func.count()).select_from(owner_query.order_by(None).subquery()).scalar_subquery() == len(sessions)
        authority &= select(func.count()).select_from(TeamGithubScope).where(
            TeamGithubScope.preset_id == scope.preset_id, TeamGithubScope.enabled.is_(True),
        ).scalar_subquery() == 1
        roster_fields = ("preset_id", "enabled", "position", "role", "provider", "updated_at")
        for slot in slots:
            authority &= _guard(AgentTeamSlot, slot, roster_fields)
        authority &= select(func.count()).select_from(AgentTeamSlot).where(
            AgentTeamSlot.preset_id == scope.preset_id).scalar_subquery() == len(slots)
        for session in (owner, leader):
            authority &= exists(select(AgentPaneBinding.id).where(
                AgentPaneBinding.pane_pid == session.bound_pane_pid,
                AgentPaneBinding.pane_proc_start == session.bound_pane_proc_start,
                AgentPaneBinding.slot_id == session.team_slot_id, AgentPaneBinding.preset_id == scope.preset_id))
            authority &= ~exists(select(MailPaneLifecycle.pane_pid).where(
                MailPaneLifecycle.pane_pid == session.bound_pane_pid,
                MailPaneLifecycle.pane_proc_start == session.bound_pane_proc_start,
                MailPaneLifecycle.retired_at.is_not(None)))
        context.update(owner=_frozen(owner, session_fields), leader=_frozen(leader, session_fields),
                       owner_session=owner.id, leader_session=leader.id,
                       owner_native=native_owner.identity, leader_native=native_leader.identity,
                       preset_revision=preset.updated_at.isoformat(), scope_revision=scope.updated_at.isoformat(),
                       policy_revision=policy.policy_revision)
        context["roster"] = [{"id": slot.id, **_frozen(slot, roster_fields)} for slot in slots]
        context["leader_candidates"] = [{"id": candidate.id, **_frozen(candidate, session_fields)}
                                         for candidate in sorted(leader_candidates, key=lambda value: value.id)]
        return context, authority, leader, owner, item, policy

    async def summary(self, db, scope_id):
        result = []
        for watch in await self.watches(db, scope_id):
            item = await db.get(GithubWorkItem, watch.work_item_id, populate_existing=True)
            if item:
                result.append(_public(watch, item))
        return result

    async def requests(self, db, scope_id, principal):
        scope = await coordination.scope(db, scope_id)
        watches = {watch.work_item_id: watch for watch in await self.watches(db, scope_id)}
        policy = await coordination.state(db, scope_id)
        if not policy or not policy.enabled or hold_code():
            return await self.summary(db, scope_id)
        activities = await observe_private_team(db, scope.preset_id)
        items = list((await db.scalars(select(GithubWorkItem).where(
            GithubWorkItem.scope_id == scope_id, GithubWorkItem.issue_number.in_(policy.issue_numbers),
            GithubWorkItem.dispatch_status == "dispatched").order_by(GithubWorkItem.id).limit(33))).all())
        if len(items) > 32:
            raise CoordinationError("followup_context_limit")
        result = await self.summary(db, scope_id)
        by_id = {value["work_item_id"]: value for value in result}
        for item in items:
            watch = watches.get(item.id)
            value = by_id.get(item.id, _public(watch, item))
            if item.id not in by_id:
                result.append(value)
            try:
                context, guard, leader, _, _, policy = await self.context(db, scope_id, item.id, activities)
                if leader.id != principal.id or not await db.scalar(select(guard)):
                    raise CoordinationError("current_leader_required", 403)
            except CoordinationError as error:
                value["read_state"] = error.code
                continue
            value["followup_token"] = _token({"purpose": "owner_followup", "scope": scope_id,
                "item": item.id, "leader": leader.id, "policy": policy.policy_revision,
                "version": watch.version if watch else 0, "sequence": watch.sequence if watch else 0,
                "context": _digest(context), "expires": int(time.time()) + _TTL, "nonce": uuid4().hex,
                "settlement": _digest(watch.settlement_id if watch else None),
                "baseline_event": _digest(activities[item.owner_slot_id].cursor),
                "baseline_at": int(activities[item.owner_slot_id].observed_at.timestamp() * 1_000_000)
                    if activities[item.owner_slot_id].observed_at else 0})
        return result

    async def report(self, db, scope_id, principal, request):
        claims = _claims(request.followup_token)
        if (claims["scope"] != scope_id or claims["item"] != request.work_item_id
                or claims["leader"] != principal.id or claims["sequence"] != request.expected_sequence):
            raise CoordinationError("followup_read_changed")
        scope = await coordination.scope(db, scope_id)
        activities = await observe_private_team(db, scope.preset_id)
        context, guard, leader, owner, item, policy = await self.context(db, scope_id, request.work_item_id, activities)
        if leader.id != principal.id or claims["context"] != _digest(context) or claims["policy"] != policy.policy_revision:
            raise CoordinationError("followup_read_changed")
        watch = await db.get(GithubOwnerFollowup, item.id, populate_existing=True)
        action_hash = _digest(request.model_dump())
        if watch and watch.last_action_hash == action_hash:
            if not await db.scalar(select(guard)):
                raise CoordinationError("followup_read_changed")
            return _public(watch, item)  # Exact retry never rearms or consumes a later settlement.
        if (claims["version"] != (watch.version if watch else 0)
                or claims["sequence"] != (watch.sequence if watch else 0)
                or claims["settlement"] != _digest(watch.settlement_id if watch else None)):
            raise CoordinationError("followup_read_changed")
        if request.action == "watch" and watch and watch.state in _ACTIVE:
            raise CoordinationError("followup_already_watched")
        native_owner = activities[owner.team_slot_id]
        if request.action == "watch" and (native_owner.state != "working" and not native_owner.settlement_id):
            raise CoordinationError("followup_owner_not_working")
        if request.action == "assess" and (not watch or not watch.settlement_id or watch.state not in _ACTIVE):
            raise CoordinationError("followup_event_required")
        if (request.action == "assess" and activities[owner.team_slot_id].settlement_id
                and activities[owner.team_slot_id].settlement_id != watch.settlement_id):
            raise CoordinationError("followup_read_changed")
        now = datetime.utcnow()
        if request.action == "watch":
            baseline_at = datetime.fromtimestamp(claims["baseline_at"] / 1_000_000, timezone.utc).replace(tzinfo=None)
            if claims["baseline_at"] == 0 or baseline_at > now:
                raise CoordinationError("followup_read_changed")
            new_settlement = native_owner.settlement_id
            if watch and new_settlement == watch.settlement_id:
                new_settlement = None  # Rearm waits for a new event, not the event just assessed.
            settled_at = native_owner.observed_at.replace(tzinfo=None) if new_settlement else None
            values = dict(context=context, registered_at=baseline_at, baseline_event=claims["baseline_event"],
                          state="pending" if new_settlement else "waiting",
                          settlement_id=new_settlement, settled_at=settled_at,
                          sequence=claims["sequence"] + int(new_settlement is not None),
                          message_id=None, request_sequence=None, delivery_attempts=0, notification_count=0,
                          last_notified_at=None,
                          last_delivery_at=None, outcome=None)
        else:
            values = dict(state="assessed", outcome=request.reason)
        values.update(last_action_hash=action_hash, version=claims["version"] + 1)
        # Serialize with coordination configuration and all authority rows. No quota debit.
        claim = await db.execute(update(GithubBacklogCoordination).where(
            GithubBacklogCoordination.scope_id == scope_id, GithubBacklogCoordination.version == policy.version,
            GithubBacklogCoordination.policy_revision == claims["policy"],
            GithubBacklogCoordination.enabled.is_(True), guard,
        ).values(version=policy.version + 1).execution_options(synchronize_session=False))
        if claim.rowcount != 1 or hold_code():
            await db.rollback()
            raise CoordinationError("followup_read_changed")
        if watch:
            changed = await db.execute(update(GithubOwnerFollowup).where(
                GithubOwnerFollowup.work_item_id == item.id, GithubOwnerFollowup.version == claims["version"],
                GithubOwnerFollowup.sequence == claims["sequence"],
            ).values(**values).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                await db.rollback()
                raise CoordinationError("followup_read_changed")
        else:
            db.add(GithubOwnerFollowup(work_item_id=item.id, scope_id=scope_id, **values))
        if hold_code():
            await db.rollback()
            raise CoordinationError("hold")
        await db.commit()
        return _public(await db.get(GithubOwnerFollowup, item.id, populate_existing=True), item)

    async def _change(self, db, watch, guard, **values):
        result = await db.execute(update(GithubOwnerFollowup).where(
            GithubOwnerFollowup.work_item_id == watch.work_item_id,
            GithubOwnerFollowup.version == watch.version, guard,
        ).values(**values, version=watch.version + 1).execution_options(synchronize_session=False))
        if result.rowcount != 1 or hold_code():
            await db.rollback()
            return False
        await db.commit()
        return True

    async def poll(self, db, scope_id):
        policy = await coordination.state(db, scope_id)
        if not policy or not policy.enabled:
            return
        scope = await coordination.scope(db, scope_id)
        preset = await db.get(AgentTeamPreset, scope.preset_id, populate_existing=True)
        watches = await self.watches(db, scope_id)
        if hold_code() or not scope.enabled or not preset.autonomy_enabled:
            # Observing OFF/HOLD invalidates the old baseline. Resume needs a fresh watch.
            for watch in watches:
                if watch.state in _ACTIVE:
                    await db.execute(update(GithubOwnerFollowup).where(
                        GithubOwnerFollowup.work_item_id == watch.work_item_id,
                        GithubOwnerFollowup.version == watch.version,
                    ).values(state="paused", outcome="off_or_hold", version=watch.version + 1))
            await db.commit()
            return
        if not any(watch.state in _ACTIVE for watch in watches):
            return
        activities = await observe_private_team(db, scope.preset_id)
        watch_ids = [watch.work_item_id for watch in watches]
        for watch_id in watch_ids:
            watch = await db.get(GithubOwnerFollowup, watch_id, populate_existing=True)
            if watch.state not in _ACTIVE:
                continue
            try:
                context, guard, leader, owner, item, policy = await self.context(
                    db, scope_id, watch.work_item_id, activities)
            except CoordinationError as error:
                if error.code in {"hold", "hold_unavailable", "autonomy_off", "recovery_only"}:
                    await db.rollback()
                    return
                state = watch.state if error.code == "followup_observation_unknown" else "invalidated"
                await self._change(db, watch, True, state=state, outcome=error.code)
                continue
            if context != watch.context:
                await self._change(db, watch, guard, state="invalidated", outcome="authority_changed")
                continue
            native_owner = activities[owner.team_slot_id]
            native_leader = activities[leader.team_slot_id]
            if native_owner.state in {"unknown", "stopped"}:
                await self._change(db, watch, guard, outcome="observation_unknown")
                continue
            settled_at = native_owner.observed_at.replace(tzinfo=None) if native_owner.observed_at else None
            if (native_owner.settlement_id and settled_at and settled_at >= watch.registered_at
                    and _digest(native_owner.cursor) != watch.baseline_event
                    and native_owner.settlement_id != watch.settlement_id):
                unread = await db.scalar(select(MailReceipt.id).where(
                    MailReceipt.message_id == watch.message_id, MailReceipt.member_id == leader.member_id,
                    MailReceipt.read_at.is_(None))) if watch.message_id else None
                uncertain = watch.state == "delivery_unknown"
                # Coalesce only while the old Mail is unread. The event remains unacknowledged.
                changed = await self._change(db, watch, guard, settlement_id=native_owner.settlement_id,
                                   settled_at=settled_at, sequence=watch.sequence + 1,
                                   state=watch.state if uncertain else ("notified" if unread else "pending"),
                                   message_id=watch.message_id if (unread or uncertain) else None,
                                   outcome=watch.outcome if uncertain else "notification_pending")
                if not changed:
                    continue
                watch = await db.get(GithubOwnerFollowup, watch_id, populate_existing=True)
            if not watch.settlement_id:
                continue
            if (native_owner.settlement_id or native_owner.current_settlement_id) != watch.settlement_id:
                await self._change(db, watch, guard, outcome="waiting_for_owner")
                continue
            if native_leader.state != "idle" or native_leader.reason != "native_turn_completed":
                await self._change(db, watch, guard, outcome="waiting_for_leader")
                continue
            if (datetime.utcnow() - watch.settled_at).total_seconds() < _DEBOUNCE:
                continue
            if (watch.state == "delivered" and watch.last_notified_at
                    and (datetime.utcnow() - watch.last_notified_at).total_seconds() >= policy.fallback_seconds):
                if not await self._change(db, watch, guard, state="pending", message_id=None,
                                         outcome="assessment_overdue"):
                    continue
                watch = await db.get(GithubOwnerFollowup, watch_id, populate_existing=True)
            if watch.message_id is None:
                if not await self._notify(db, watch, context, guard, leader, item, policy):
                    continue
                watch = await db.get(GithubOwnerFollowup, watch_id, populate_existing=True)
            if watch.message_id is not None and watch.state in {"notified", "delivery_failed"}:
                await self._deliver(db, watch, context, leader)

    async def _notify(self, db, watch, context, guard, leader, item, policy):
        scope_id, item_id = watch.scope_id, watch.work_item_id
        scope = await coordination.scope(db, scope_id)
        fresh_activity = await observe_private_team(db, scope.preset_id)
        try:
            fresh, guard, leader, owner, item, policy = await self.context(db, scope_id, item_id, fresh_activity)
        except CoordinationError:
            await db.rollback()
            return False
        if (fresh != context or (fresh_activity[owner.team_slot_id].settlement_id
                                or fresh_activity[owner.team_slot_id].current_settlement_id) != watch.settlement_id
                or fresh_activity[leader.team_slot_id].state != "idle"
                or fresh_activity[leader.team_slot_id].reason != "native_turn_completed"):
            await db.rollback()
            return False
        now = datetime.utcnow()
        day = now.strftime("%Y-%m-%d")
        daily = policy.daily_requests if policy.budget_day == day else 0
        # Coalesce only with unread current-Leader Mail. A read receipt is not an event ACK.
        coalesced = None
        if (policy.message_id and policy.leader_session_id == leader.id
                and policy.assessed_sequence != policy.request_sequence):
            coalesced = await db.scalar(select(MailReceipt.message_id).where(
                MailReceipt.message_id == policy.message_id, MailReceipt.member_id == leader.member_id,
                MailReceipt.read_at.is_(None)))
        if coalesced is None:
            for other in await self.watches(db, watch.scope_id):
                if (other.state in _ACTIVE and other.context.get("leader_session") == leader.id and other.message_id):
                    coalesced = await db.scalar(select(MailReceipt.message_id).where(
                        MailReceipt.message_id == other.message_id, MailReceipt.member_id == leader.member_id,
                        MailReceipt.read_at.is_(None)))
                    if coalesced is not None:
                        break
        if watch.notification_count >= _MAX_DELIVERY_ATTEMPTS or watch.delivery_attempts >= _MAX_DELIVERY_ATTEMPTS:
            await self._change(db, watch, guard, state="capped", outcome="delivery_capped")
            return False
        if coalesced is None and (daily >= policy.max_daily_requests
                                  or policy.snapshot_requests >= _MAX_SNAPSHOT_REQUESTS):
            await self._change(db, watch, guard, state="capped", outcome="coordination_capped")
            return False
        values = {"version": policy.version + 1}
        if coalesced is None:
            values.update(budget_day=day, daily_requests=daily + 1,
                          snapshot_requests=policy.snapshot_requests + 1)
        claimed = await db.execute(update(GithubBacklogCoordination).where(
            GithubBacklogCoordination.scope_id == watch.scope_id,
            GithubBacklogCoordination.version == policy.version,
            GithubBacklogCoordination.policy_revision == context["policy_revision"],
            GithubBacklogCoordination.enabled.is_(True), guard,
        ).values(**values).execution_options(synchronize_session=False))
        watch_claim = await db.execute(update(GithubOwnerFollowup).where(
            GithubOwnerFollowup.work_item_id == watch.work_item_id,
            GithubOwnerFollowup.version == watch.version,
            GithubOwnerFollowup.sequence == watch.sequence,
            GithubOwnerFollowup.context == context,
        ).values(state="notified", outcome="coalesced" if coalesced else "notification_pending",
                 last_notified_at=now, notification_count=watch.notification_count + int(coalesced is None),
                 version=watch.version + 1).execution_options(synchronize_session=False))
        if claimed.rowcount != 1 or watch_claim.rowcount != 1 or hold_code():
            await db.rollback()
            return False
        if coalesced is None:
            message = await agent_mail_service.send_message(db, MailMessageCreate(
                kind="message", recipient_member_id=leader.member_id,
                subject=f"Owner turn completed: inspect remaining issue #{item.issue_number}",
                body_markdown=(f"The watched owner of issue #{item.issue_number} completed its native turn. "
                    f"Call deck_get_backlog_coordination(scope_id={watch.scope_id}). Inspect owner_followups "
                    "and current work evidence. Choose the next permitted action, a specific blocker, or an "
                    "evidenced completion. Use deck_report_owner_followup with the fresh private followup_token "
                    "and event_sequence to record that disposition. A Mail read or an older assessment does "
                    "not resolve this event. If work remains, arrange the next authorized chunk and register "
                    "a fresh watch before ending your turn. This notice grants no implementation, approval, "
                    "retry, lease, merge or milestone authority. Preserve all current gates. Stop on OFF/HOLD."),
                payload={"kind": "github_owner_followup", "scope_id": watch.scope_id,
                         "work_item_id": item.id, "event_sequence": watch.sequence},
            ), auto_nudge=False, commit=False,
                delivery_key=f"owner-followup:{watch.scope_id}:{item.id}:{watch.sequence}:{watch.notification_count + 1}")
            coalesced = message.id
        await db.execute(update(GithubOwnerFollowup).where(
            GithubOwnerFollowup.work_item_id == watch.work_item_id,
            GithubOwnerFollowup.version == watch.version + 1,
        ).values(message_id=coalesced, request_sequence=policy.request_sequence))
        final_activity = await observe_private_team(db, scope.preset_id)
        if (hold_code() or not await db.scalar(select(guard))
                or (final_activity[owner.team_slot_id].settlement_id
                    or final_activity[owner.team_slot_id].current_settlement_id) != watch.settlement_id
                or final_activity[leader.team_slot_id].state != "idle"
                or final_activity[leader.team_slot_id].reason != "native_turn_completed"):
            await db.rollback()
            return False
        await db.commit()  # Watch, stable Mail key, linkage and shared quota are atomic.
        return True

    async def _deliver(self, db, watch, context, leader):
        now = datetime.utcnow()
        last = watch.last_delivery_at
        cooldown = agent_mail_service._last_auto_nudge_at.get(leader.member_id)
        if ((last and (now - last).total_seconds() < AUTO_NUDGE_COOLDOWN_SECONDS)
                or (cooldown and (now - cooldown).total_seconds() < AUTO_NUDGE_COOLDOWN_SECONDS)):
            return
        if watch.delivery_attempts >= _MAX_DELIVERY_ATTEMPTS:
            await self._change(db, watch, True, state="capped", outcome="delivery_capped")
            return
        # Reserve an attempt before any physical wake. Restart cannot repeat it without a debit.
        if not await self._change(db, watch, True, delivery_attempts=watch.delivery_attempts + 1,
                                  last_delivery_at=now, state="delivery_unknown", outcome="delivery_pending"):
            return
        expected_version = watch.version + 1
        settlement_id = watch.settlement_id

        async def delivery_guard():
            if hold_code():
                return False
            scope = await coordination.scope(db, watch.scope_id)
            observations = await observe_private_team(db, scope.preset_id)
            try:
                fresh, guard, current_leader, owner, _, _ = await self.context(
                    db, watch.scope_id, watch.work_item_id, observations)
            except CoordinationError:
                return False
            live_watch = await db.get(GithubOwnerFollowup, watch.work_item_id, populate_existing=True)
            return (fresh == context and current_leader.id == leader.id
                    and (observations[owner.team_slot_id].settlement_id
                         or observations[owner.team_slot_id].current_settlement_id) == settlement_id
                    and observations[leader.team_slot_id].state == "idle"
                    and observations[leader.team_slot_id].reason == "native_turn_completed"
                    and live_watch.version == expected_version and live_watch.state == "delivery_unknown"
                    and not hold_code() and bool(await db.scalar(select(guard))))

        state, outcome = "delivered", "wake_succeeded"
        try:
            if not await delivery_guard():
                raise MailWakeError("wake_session_mismatch")
            await agent_mail_service.sync_observed_sessions(db)
            await agent_mail_service._wake_member(db, leader.member_id, now,
                expected_session_id=leader.id, delivery_guard=delivery_guard,
                transport_guard=lambda: hold_code() is None, source="owner_followup")
            agent_mail_service._last_auto_nudge_at[leader.member_id] = now
        except MailWakeError as error:
            if error.code in {"wake_transport_failed", "wake_transport_uncertain"}:
                state, outcome = "delivery_unknown", "transport_uncertain"
            elif error.code == "inbox_empty":
                state, outcome = "delivered", "mail_already_read"
            else:
                state, outcome = "delivery_failed", "wake_refused"
        current = await db.get(GithubOwnerFollowup, watch.work_item_id, populate_existing=True)
        if current.version == expected_version and current.state == "delivery_unknown":
            await self._change(db, current, True, state=state, outcome=outcome)


github_owner_followup_service = GithubOwnerFollowupService()
