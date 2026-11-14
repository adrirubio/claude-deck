"""Bounded semantic progress observations; idle attention is advisory only."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import settings
from app.models.database import (AgentTeamPreset, FactoryAuditEvent,
    GithubOwnerObservationPause, GithubRequiredCheckWatch, GithubTeamProgress, GithubWorkItem, MailMessage,
    MailReceipt, MailTeamMember, TeamGithubScope)
from app.services.factory_audit_service import sanitize_text
from app.services.github_coordination_service import hold_code
from app.services.github_ci_watch_service import github_ci_watch_service

_MUTATIONS = {'owner_status_report', 'approval_decision', 'handoff_reassignment', 'handoff_acceptance',
    'continuation_decision', 'continuation_request', 'prepared_attempt_resume', 'recovery_cancellation',
    'request_cancellation', 'workspace_release', 'review_acceptance_declared'}
_TERMINAL = ('merged', 'completed')


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class GithubTeamIdleService:
    async def projection(self, db, preset_id, *, now=None):
        from app.services.agent_activity_service import observe_team, _team_inputs
        from app.services.github_operator_attention_service import github_operator_attention_service
        async def read():
            fence = {}
            native = await observe_team(db, preset_id, include_agent_status=False,
                persist_identities=False, max_input_rows=256, input_fence=fence)
            human = await github_operator_attention_service.summary(db, preset_id)
            current = {entry[0]: entry for entry in await _team_inputs(db, preset_id, 256)}
            complete = (current == fence and human["coverage_complete"]
                and len(human["actions"]) <= 64 and all(s.state != "unknown" for s in native.slots))
            external_wait = (any(s.waiting_input is not None for s in native.slots)
                or any(a.get("state") not in {"resolved", "historical"} for a in human["actions"]))
            return await self.observe(db, preset_id, now=now, coverage_complete=complete,
                                      external_wait=external_wait)
        try:
            return await asyncio.wait_for(read(), timeout=8)
        except (TimeoutError, OSError, ValueError, OperationalError):
            await db.rollback()
            return await self._unavailable(db, preset_id, now)

    async def _unavailable(self, db, preset_id, now):
        # Unknown time is not evidence of an eligible idle interval. Invalidate once;
        # continued observation failures never renew this baseline on every poll.
        try:
            await db.execute(update(GithubTeamProgress).where(GithubTeamProgress.preset_id == preset_id,
                GithubTeamProgress.fingerprint != 'unknown').values(fingerprint='unknown',
                last_progress_at=_utc(now or datetime.utcnow()).replace(tzinfo=None), items={}))
            await db.commit()
        except (OperationalError, IntegrityError):
            await db.rollback()
        return []

    async def observe(self, db, preset_id, *, now=None, coverage_complete=True, external_wait=False):
        now = _utc(now or datetime.utcnow())
        team = await db.get(AgentTeamPreset, preset_id, populate_existing=True)
        if team is None:
            return []
        rows = (await db.execute(select(GithubWorkItem, TeamGithubScope).join(TeamGithubScope,
            TeamGithubScope.id == GithubWorkItem.scope_id).where(TeamGithubScope.preset_id == preset_id,
            GithubWorkItem.dispatch_status.not_in(_TERMINAL)).order_by(GithubWorkItem.id).limit(65)
            .execution_options(populate_existing=True))).all()
        if len(rows) > 64 or not coverage_complete:
            return await self._unavailable(db, preset_id, now)
        item_ids = [item.id for item, _ in rows]
        team_mail = select(MailMessage).where(
            or_(MailMessage.sender_member_id.is_not(None), MailMessage.sender_actor_id.is_not(None)),
            or_(MailMessage.sender_member_id.in_(select(MailTeamMember.id).where(
                    MailTeamMember.team_preset_id == preset_id)),
                MailMessage.id.in_(select(MailReceipt.message_id).join(MailTeamMember,
                    MailTeamMember.id == MailReceipt.member_id).where(MailTeamMember.team_preset_id == preset_id)),
                (MailMessage.audience_type == 'team_preset') & (MailMessage.audience_id == str(preset_id))))
        mail = (await db.execute(team_mail.order_by(MailMessage.created_at.desc(), MailMessage.id.desc())
            .limit(1))).scalar_one_or_none()
        latest = select(func.max(FactoryAuditEvent.id)).where(
            FactoryAuditEvent.item_id.in_(item_ids), FactoryAuditEvent.event_kind.in_(_MUTATIONS),
            FactoryAuditEvent.record_kind == 'observed',
            FactoryAuditEvent.actor_kind.in_(('member', 'operator', 'external_actor'))
        ).group_by(FactoryAuditEvent.item_id)
        audits = (await db.execute(select(FactoryAuditEvent).where(FactoryAuditEvent.id.in_(latest))
            .order_by(FactoryAuditEvent.occurred_at.desc(), FactoryAuditEvent.id.desc()))).scalars().all()
        paused = bool(await db.scalar(select(GithubOwnerObservationPause.id).where(
            GithubOwnerObservationPause.work_item_id.in_(item_ids), GithubOwnerObservationPause.status == 'paused').limit(1)))
        blocked = bool(hold_code() or not team.autonomy_enabled or external_wait or paused)
        values, public = {}, []
        latest_audit = {}
        for event in audits:
            latest_audit.setdefault(event.item_id, event)
        for item, scope in rows:
            ci = await github_ci_watch_service.view(db, item, now=now)
            # Freshness controls eligibility, not semantic progress. The expiration
            # of a read must never masquerade as a changed check result.
            check_changed_at = await db.scalar(select(GithubRequiredCheckWatch.changed_at).where(
                GithubRequiredCheckWatch.work_item_id == item.id,
                GithubRequiredCheckWatch.dispatch_nonce == item.dispatch_nonce,
                GithubRequiredCheckWatch.scope_revision == item.active_scope_revision,
                GithubRequiredCheckWatch.head_sha == item.verification_head_sha,
                GithubRequiredCheckWatch.pr_number == item.pr_number,
                GithubRequiredCheckWatch.owner_slot_id == item.owner_slot_id))
            waiting_checks = item.dispatch_status in {'verifying', 'pr_opened'} and (ci is None or ci['state'] == 'waiting')
            if (not scope.enabled or item.dispatch_status in {'awaiting_human_review', 'escalated', 'failed'}
                    or waiting_checks
                    or (item.dispatch_status == 'ready_for_review' and scope.merge_policy == 'human')):
                blocked = True
            actor, actor_member_id = 'Unknown', None
            event = latest_audit.get(item.id)
            evidence_at = event.occurred_at if event else None
            if event:
                if event.actor_kind == 'operator':
                    actor = 'Operator'
                elif event.actor_member_id:
                    actor_member_id = event.actor_member_id
                elif event.actor_kind == 'external_actor':
                    actor = 'External actor'
            # At most one evidence row per unfinished item (at most 64 items).
            # New mail for another item must not erase this item's authenticated actor.
            item_mail = (await db.execute(team_mail.where(or_(
                MailMessage.payload['work_item_id'].as_integer() == item.id,
                (MailMessage.audience_type == 'work_item') & (MailMessage.audience_id == str(item.id))))
                .order_by(MailMessage.created_at.desc(), MailMessage.id.desc()).limit(1))).scalar_one_or_none()
            if item_mail and (evidence_at is None or item_mail.created_at > evidence_at):
                actor_member_id = item_mail.sender_member_id
                actor = 'External actor' if item_mail.sender_actor_id else 'Unknown'
            if actor_member_id:
                member = await db.get(MailTeamMember, actor_member_id)
                if member and member.team_preset_id == preset_id:
                    actor = sanitize_text(member.display_name, limit=80) or 'Unknown'
            semantic = [item.dispatch_nonce, item.active_scope_revision, item.dispatch_status,
                item.owner_slot_id, item.attempt_phase, item.pr_number, item.verification_head_sha,
                item.last_verified_sha, item.retry_count, item.handoff_state, item.escalation_reason,
                item.ack_received_at, item.delivery_policy_revision, item.delivery_policy, check_changed_at]
            values[str(item.id)] = {'state': _digest(semantic), 'last_actor': actor}
            public.append({'work_item_id': item.id, 'scope_id': scope.id,
                'issue_number': item.issue_number, 'last_actor': actor})
        fingerprint = _digest({'items': {k:v['state'] for k,v in values.items()}, 'mail': mail.id if mail else None,
            'audit': [a.id for a in audits], 'blocked': blocked})
        saved = await db.get(GithubTeamProgress, preset_id, populate_existing=True)
        try:
            if saved is None:
                db.add(GithubTeamProgress(preset_id=preset_id, fingerprint=fingerprint,
                    last_progress_at=now.replace(tzinfo=None), items=values))
                await db.commit()
                return []  # No pre-upgrade activity time is invented.
            if saved.fingerprint != fingerprint:
                await db.execute(update(GithubTeamProgress).where(GithubTeamProgress.preset_id == preset_id,
                    GithubTeamProgress.fingerprint == saved.fingerprint).values(fingerprint=fingerprint,
                    last_progress_at=now.replace(tzinfo=None), items=values).execution_options(synchronize_session=False))
                await db.commit()
                return []
            since = _utc(saved.last_progress_at)
            if blocked or not public or now - since < timedelta(seconds=settings.github_team_idle_timeout_seconds):
                return []
            # Re-read the critical automation bits after all awaits. This grants no execution authority.
            await db.refresh(team)
            if hold_code() or not team.autonomy_enabled:
                return []
            for _, scope in rows:
                await db.refresh(scope)
                if not scope.enabled:
                    return []
            return [{**entry, 'last_progress_at': since} for entry in public]
        except (IntegrityError, OperationalError):
            await db.rollback()
            return []  # A concurrent observation wins; never guess through an incomplete snapshot.


github_team_idle_service = GithubTeamIdleService()
