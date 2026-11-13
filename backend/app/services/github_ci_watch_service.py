"""Durable required-check notices. Observations and watches grant no authority."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select, update
from sqlalchemy.exc import OperationalError

from app.models.database import (AgentTeamPreset, AgentTeamSlot, GithubOwnerObservationPause,
    GithubRequiredCheckRecipient, GithubRequiredCheckWatch, GithubWorkItem, GithubWorkspace,
    MailAgentSession, MailTeamMember, TeamGithubScope)
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service, MailWakeError, MCP_HEARTBEAT_TTL_SECONDS
from app.services.factory_delivery_policy import effective_policy, policy_context, policy_context_conditions
from app.services.github_coordination_service import hold_code
from app.services.factory_audit_service import sanitize_text

_SHA = re.compile(r'[0-9a-f]{40}')
_ACTIVE = ('dispatched', 'verifying', 'ready_for_review', 'awaiting_human_review')
_FAILURES = {'failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure', 'stale', 'skipped', 'neutral'}


def _digest(policy):
    return hashlib.sha256(json.dumps(policy.model_dump(mode='json'), sort_keys=True).encode()).hexdigest()


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def check_matrix(policy, checks, head):
    """Only a single, exact app/name/head match is authoritative for each requirement."""
    result = []
    for required in policy.required_checks:
        rows = [r for r in checks if isinstance(r, dict) and r.get('name') == required.name
            and isinstance(r.get('app'), dict) and r['app'].get('slug') == required.app_slug
            and r.get('head_sha') == head]
        state = 'unknown'
        if len(rows) == 1:
            row = rows[0]
            if row.get('status') in {'queued', 'in_progress', 'waiting', 'pending', 'requested'}:
                state = 'pending'
            elif row.get('status') == 'completed' and row.get('conclusion') in {'success', *_FAILURES}:
                state = row['conclusion']
        result.append({'name': required.name, 'app_slug': required.app_slug, 'result': state})
    return result


class GithubCIWatchService:
    async def capture(self, db, scope, item):
        """Capture before GitHub awaits. Private lease values stay inside the SQL fence."""
        expected = {k: getattr(item, k) for k in ('id', 'scope_id', 'dispatch_nonce', 'owner_slot_id',
            'active_scope_revision', 'attempt_phase', 'dispatch_status', 'pr_number',
            'verification_head_sha', 'ack_received_at', 'dispatch_head_ref', 'dispatch_base_ref')}
        expected['policy'] = policy_context(item)
        if (hold_code() or expected['dispatch_status'] not in _ACTIVE or not expected['dispatch_nonce']
                or not expected['owner_slot_id'] or not expected['pr_number']):
            return None
        team = await db.get(AgentTeamPreset, scope.preset_id, populate_existing=True)
        fresh_scope = await db.get(TeamGithubScope, expected['scope_id'], populate_existing=True)
        if not team or not fresh_scope or not team.autonomy_enabled or not fresh_scope.enabled:
            return None
        workspace = (await db.execute(select(GithubWorkspace).where(
            GithubWorkspace.leased_item_id == expected['id']))).scalar_one_or_none()
        if workspace is None or not workspace.lease_token:
            return None
        expected.update(team_id=team.id, leader_slot_id=team.leader_slot_id,
            workspace_id=workspace.id, lease_token=workspace.lease_token, leased_at=workspace.leased_at,
            repo_owner=fresh_scope.repo_owner, repo_name=fresh_scope.repo_name, github_auth_mode=fresh_scope.github_auth_mode)
        return expected

    @staticmethod
    def conditions(context):
        c = context
        fields = ('scope_id', 'dispatch_nonce', 'owner_slot_id', 'active_scope_revision', 'attempt_phase',
                  'dispatch_status', 'pr_number', 'verification_head_sha', 'ack_received_at',
                  'dispatch_head_ref', 'dispatch_base_ref')
        return [GithubWorkItem.id == c['id'],
            *(getattr(GithubWorkItem, key) == c[key] for key in fields),
            *policy_context_conditions(c['policy']),
            exists(select(AgentTeamPreset.id).where(AgentTeamPreset.id == c['team_id'],
                AgentTeamPreset.autonomy_enabled.is_(True), AgentTeamPreset.leader_slot_id == c['leader_slot_id'])),
            exists(select(TeamGithubScope.id).where(TeamGithubScope.id == c['scope_id'],
                TeamGithubScope.preset_id == c['team_id'], TeamGithubScope.enabled.is_(True),
                TeamGithubScope.repo_owner == c['repo_owner'], TeamGithubScope.repo_name == c['repo_name'],
                TeamGithubScope.github_auth_mode == c['github_auth_mode'])),
            exists(select(AgentTeamSlot.id).where(AgentTeamSlot.id == c['owner_slot_id'],
                AgentTeamSlot.preset_id == c['team_id'], AgentTeamSlot.enabled.is_(True))),
            exists(select(GithubWorkspace.id).where(GithubWorkspace.id == c['workspace_id'],
                GithubWorkspace.leased_item_id == c['id'], GithubWorkspace.lease_token == c['lease_token'],
                GithubWorkspace.leased_at == c['leased_at'])),
            *(exists(select(MailTeamMember.id).join(AgentTeamSlot,
                AgentTeamSlot.id == MailTeamMember.team_slot_id).where(
                    MailTeamMember.id == member_id, MailTeamMember.team_slot_id == slot_id,
                    MailTeamMember.team_preset_id == c['team_id'], AgentTeamSlot.preset_id == c['team_id'],
                    AgentTeamSlot.enabled.is_(True)))
                for member_id, slot_id in c.get('recipient_bindings', ())),
            ~exists(select(GithubOwnerObservationPause.id).where(
                GithubOwnerObservationPause.work_item_id == c['id'],
                GithubOwnerObservationPause.status == 'paused'))]

    async def _claim(self, db, context):
        if not context or hold_code():
            return False
        result = await db.execute(update(GithubWorkItem).where(*self.conditions(context))
            .values(updated_at=GithubWorkItem.updated_at).execution_options(synchronize_session=False))
        return result.rowcount == 1 and not hold_code()

    async def _member(self, db, team_id, slot_id):
        if not slot_id:
            return None
        rows = (await db.execute(select(MailTeamMember.id).join(AgentTeamSlot,
            AgentTeamSlot.id == MailTeamMember.team_slot_id).where(
            AgentTeamSlot.id == slot_id, AgentTeamSlot.preset_id == team_id, AgentTeamSlot.enabled.is_(True),
            MailTeamMember.team_preset_id == team_id).limit(2))).scalars().all()
        return rows[0] if len(rows) == 1 else None

    async def _reviewer(self, db, context, member_id):
        if member_id is None:
            return None
        slot = (await db.execute(select(MailTeamMember.team_slot_id).where(
            MailTeamMember.id == member_id, MailTeamMember.team_preset_id == context['team_id']))).scalar_one_or_none()
        if slot == context['owner_slot_id'] or await self._member(db, context['team_id'], slot) != member_id:
            raise ValueError('reviewer_not_current_team_member')
        return member_id

    async def _watch(self, db, context, head, policy, now):
        watch = (await db.execute(select(GithubRequiredCheckWatch).where(
            GithubRequiredCheckWatch.work_item_id == context['id'],
            GithubRequiredCheckWatch.dispatch_nonce == context['dispatch_nonce'],
            GithubRequiredCheckWatch.scope_revision == context['active_scope_revision'],
            GithubRequiredCheckWatch.head_sha == head))).scalar_one_or_none()
        if watch is None:
            watch = GithubRequiredCheckWatch(work_item_id=context['id'], dispatch_nonce=context['dispatch_nonce'],
                scope_revision=context['active_scope_revision'], pr_number=context['pr_number'], head_sha=head,
                owner_slot_id=context['owner_slot_id'], policy_digest=_digest(policy), checks=[],
                observed_at=now, changed_at=now)
            db.add(watch); await db.flush()
        if (watch.pr_number != context['pr_number'] or watch.owner_slot_id != context['owner_slot_id']
                or watch.policy_digest != _digest(policy)):
            # A changed policy cannot recycle an old completion or silently widen a watch.
            return None
        return watch

    async def _read_pull(self, scope, pr_number):
        from app.services.github_approval_service import github_approval_service
        from app.services.github_client import github_client
        token = await github_approval_service.github_read_token(scope)
        return await github_client.get_pull(scope.repo_owner, scope.repo_name, pr_number, token=token)

    async def register(self, db, *, work_item_id, dispatch_nonce, scope_revision, head_sha,
                       reviewer_member_id, actor_member_id, session=None):
        session_binding = self._session_binding(session) if session is not None else None
        if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha):
            raise ValueError('full_head_required')
        item = await db.get(GithubWorkItem, work_item_id, populate_existing=True)
        scope = await db.get(TeamGithubScope, item.scope_id) if item else None
        context = await self.capture(db, scope, item) if scope else None
        if (not context or context['dispatch_nonce'] != dispatch_nonce
                or context['active_scope_revision'] != scope_revision):
            raise ValueError('stale_check_watch_context')
        leader = await self._member(db, context['team_id'], context['leader_slot_id'])
        if leader != actor_member_id or actor_member_id is None:
            raise PermissionError('current_leader_required')
        await self._reviewer(db, context, reviewer_member_id)
        policy = effective_policy(item, scope)
        if not policy.required_checks:
            raise ValueError('named_required_checks_required')
        pull = await self._read_pull(scope, context['pr_number'])
        head = pull.get('head') or {}
        repo = (head.get('repo') or {}).get('full_name')
        if (type(pull.get('number')) is not int or pull['number'] != context['pr_number']
                or pull.get('merged_at', True) is not None or pull.get('state') != 'open' or head.get('sha') != head_sha
                or head.get('ref') != item.dispatch_head_ref
                or repo != f'{scope.repo_owner}/{scope.repo_name}'):
            raise ValueError('current_pr_head_required')
        if not await self._claim(db, context):
            await db.rollback(); raise ValueError('stale_check_watch_context')
        # The authenticated caller and current role must still be bound after the remote await.
        if await self._member(db, context['team_id'], context['leader_slot_id']) != actor_member_id:
            await db.rollback(); raise PermissionError('current_leader_required')
        await self._require_leader_session(db, context, actor_member_id, session_binding)
        await self._reviewer(db, context, reviewer_member_id)
        watch = await self._watch(db, context, head_sha, policy, datetime.utcnow())
        if watch is None:
            await db.rollback(); raise ValueError('check_watch_policy_changed')
        if item.verification_head_sha != head_sha:
            item.verification_head_sha = head_sha
            item.verification_started_at = datetime.utcnow()
            context['verification_head_sha'] = head_sha
        watch.reviewer_member_id = reviewer_member_id
        await db.flush()
        await self._deliver(db, context, watch)
        if not await self._claim(db, context):
            await db.rollback(); raise ValueError('stale_check_watch_context')
        await self._require_leader_session(db, context, actor_member_id, session_binding)
        await db.commit()
        await self._wake(db, context, watch.id)
        return {'work_item_id': work_item_id, 'head_sha': head_sha, 'reviewer_member_id': reviewer_member_id}

    @staticmethod
    def _session_binding(session):
        return tuple(getattr(session, field) for field in ('id', 'member_id', 'team_preset_id',
            'team_slot_id', 'capability_token_hash', 'bound_pane_pid', 'bound_pane_proc_start'))

    async def _require_leader_session(self, db, context, actor_member_id, binding):
        if binding is None:
            return  # Internal callers have no HTTP capability; the API always supplies one.
        from fastapi import HTTPException
        from app.api.v1.deps import require_current_mail_session
        current = await db.get(MailAgentSession, binding[0], populate_existing=True)
        if (current is None or self._session_binding(current) != binding
                or current.member_id != actor_member_id or current.team_preset_id != context['team_id']
                or current.team_slot_id != context['leader_slot_id']):
            await db.rollback(); raise PermissionError('current_mail_session_required')
        try:
            require_current_mail_session(current)
        except HTTPException:
            await db.rollback(); raise PermissionError('current_mail_session_required') from None

    async def observe(self, db, scope, item, head_sha, checks, policy, *, context=...):
        """Return whether this head's required-failure owner notice is already durable."""
        if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha) or not policy.required_checks:
            return False
        if context is ...:
            context = await self.capture(db, scope, item)
        if not context:
            return False
        try:
            if not await self._claim(db, context):
                await db.rollback(); return None
            watch = await self._watch(db, context, head_sha, policy, datetime.utcnow())
            if watch is None:
                return False
            now = datetime.utcnow()
            matrix = check_matrix(policy, checks, head_sha)
            if matrix != watch.checks:
                watch.checks, watch.changed_at = matrix, now
            watch.observed_at = now
            failure = any(r['result'] in _FAILURES for r in matrix)
            if not watch.completion_kind and (failure or all(r['result'] == 'success' for r in matrix)):
                watch.completion_kind = 'failure' if failure else 'success'
                watch.completion_checks = matrix
                watch.completed_at = now
            await db.flush()
            await self._deliver(db, context, watch)
            watch_id = watch.id
            owner_id = await self._member(db, context['team_id'], context['owner_slot_id'])
            notified = bool(failure and owner_id and await db.scalar(select(GithubRequiredCheckRecipient.id).where(
                GithubRequiredCheckRecipient.watch_id == watch_id, GithubRequiredCheckRecipient.member_id == owner_id,
                GithubRequiredCheckRecipient.message_id.is_not(None))))
            if not await self._claim(db, context):
                await db.rollback(); return None
            await db.commit()
            if not await self._wake(db, context, watch_id):
                return None
            return notified
        except OperationalError:
            # A contended/stale SQLite read snapshot is retried by the next normal monitor poll.
            await db.rollback()
            return None

    async def _deliver(self, db, context, watch):
        if not watch.completion_kind or not await self._claim(db, context):
            return
        leader = await self._member(db, context['team_id'], context['leader_slot_id'])
        owner = await self._member(db, context['team_id'], context['owner_slot_id'])
        recipients = {leader}
        if watch.completion_kind == 'failure':
            recipients.add(owner)
        else:
            try:
                recipients.add(await self._reviewer(db, context, watch.reviewer_member_id))
            except ValueError:
                pass  # A removed or rebound reviewer has no continuing delivery entitlement.
        context['recipient_bindings'] = (await db.execute(select(MailTeamMember.id, MailTeamMember.team_slot_id)
            .where(MailTeamMember.id.in_(recipients - {None})))).all()
        for member_id in sorted(recipients - {None}):
            old = await db.scalar(select(GithubRequiredCheckRecipient.id).where(
                GithubRequiredCheckRecipient.watch_id == watch.id, GithubRequiredCheckRecipient.member_id == member_id))
            if old:
                continue
            results = '\n'.join(f"- {sanitize_text(r['name'], limit=200)}: {r['result']}" for r in watch.completion_checks)
            action = ('Owner: correct the failed checks and publish current-head evidence.'
                if watch.completion_kind == 'failure' else
                'Leader and assigned reviewer: perform the final exact-head review read. Independent acceptance and merge gates remain.')
            message = await agent_mail_service.send_message(db, MailMessageCreate(recipient_member_id=member_id,
                subject=f'Required checks {watch.completion_kind}: PR #{watch.pr_number}',
                body_markdown=f'Current PR head: {watch.head_sha}\n\n{results}\n\n{action}',
                payload={'kind': 'github_required_checks_finished', 'work_item_id': watch.work_item_id,
                    'pr_number': watch.pr_number, 'head_sha': watch.head_sha}),
                delivery_key=f'required-checks:{watch.id}:member:{member_id}', auto_nudge=False, commit=False)
            db.add(GithubRequiredCheckRecipient(watch_id=watch.id, member_id=member_id,
                message_id=message.id, wake_state='pending'))
        await db.flush()

    async def _wake(self, db, context, watch_id):
        intact = True
        ids = (await db.execute(select(GithubRequiredCheckRecipient.id).where(
            GithubRequiredCheckRecipient.watch_id == watch_id,
            GithubRequiredCheckRecipient.wake_state == 'pending'))).scalars().all()
        for recipient_id in ids:
            if not await self._claim(db, context):
                await db.rollback(); return False
            watch = await db.get(GithubRequiredCheckWatch, watch_id, populate_existing=True)
            recipient = await db.get(GithubRequiredCheckRecipient, recipient_id, populate_existing=True)
            leader = await self._member(db, context['team_id'], context['leader_slot_id'])
            owner = await self._member(db, context['team_id'], context['owner_slot_id'])
            valid = {leader, owner} if watch.completion_kind == 'failure' else {leader}
            if watch.completion_kind == 'success':
                try: valid.add(await self._reviewer(db, context, watch.reviewer_member_id))
                except ValueError: pass
            if recipient.member_id not in valid:
                continue
            member_id = recipient.member_id
            claim = await db.execute(update(GithubRequiredCheckRecipient).where(
                GithubRequiredCheckRecipient.id == recipient_id, GithubRequiredCheckRecipient.wake_state == 'pending')
                .values(wake_state='claimed').execution_options(synchronize_session=False))
            if claim.rowcount != 1:
                continue
            await db.commit()  # Durable before the external side effect; crashes stay visibly unconfirmed.
            try:
                async def delivery_guard():
                    if not await self._claim(db, context):
                        return False
                    live = await db.get(GithubRequiredCheckWatch, watch_id, populate_existing=True)
                    claimed = await db.get(GithubRequiredCheckRecipient, recipient_id, populate_existing=True)
                    if (live is None or claimed is None or claimed.watch_id != watch_id
                            or claimed.member_id != member_id or claimed.wake_state != 'claimed'
                            or live.work_item_id != context['id'] or live.dispatch_nonce != context['dispatch_nonce']
                            or live.scope_revision != context['active_scope_revision']
                            or live.pr_number != context['pr_number'] or live.owner_slot_id != context['owner_slot_id']
                            or live.head_sha != context['verification_head_sha']):
                        return False
                    leader = await self._member(db, context['team_id'], context['leader_slot_id'])
                    valid = {leader}
                    if live.completion_kind == 'failure':
                        valid.add(await self._member(db, context['team_id'], context['owner_slot_id']))
                    elif live.completion_kind == 'success':
                        try: valid.add(await self._reviewer(db, context, live.reviewer_member_id))
                        except ValueError: pass
                    else:
                        return False
                    return member_id in valid and not hold_code()

                if not await delivery_guard():
                    raise MailWakeError('wake_session_mismatch')
                await agent_mail_service.sync_observed_sessions(db)
                if not await delivery_guard():
                    raise MailWakeError('wake_session_mismatch')
                now = datetime.utcnow()
                pane = await agent_mail_service._nudge_session_for_member(db, member_id, now)
                bindings = (await db.execute(select(MailAgentSession).where(
                    MailAgentSession.member_id == member_id, MailAgentSession.source == 'mcp',
                    MailAgentSession.team_preset_id == context['team_id'],
                    MailAgentSession.team_slot_id == pane.team_slot_id,
                    MailAgentSession.bound_pane_pid == pane.pid,
                    MailAgentSession.bound_pane_proc_start.is_not(None),
                    MailAgentSession.closed_at.is_(None), MailAgentSession.mailbox_status == 'connected',
                    MailAgentSession.wake_enabled.is_(True), MailAgentSession.capability_token_hash.is_not(None),
                    MailAgentSession.last_seen_at >= now - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS))
                    .limit(2))).scalars().all()
                if len(bindings) != 1:
                    raise MailWakeError('wake_session_mismatch')
                binding = self._session_binding(bindings[0])
                recipient_guard = delivery_guard

                async def delivery_guard():
                    from app.utils import peer_process
                    if not await recipient_guard():
                        return False
                    session = await db.get(MailAgentSession, binding[0], populate_existing=True)
                    return (session is not None and self._session_binding(session) == binding
                        and session.source == 'mcp' and session.closed_at is None
                        and session.mailbox_status == 'connected' and session.wake_enabled
                        and bool(session.capability_token_hash)
                        and session.last_seen_at >= datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS)
                        and peer_process.pane_is_alive(session.bound_pane_pid, session.bound_pane_proc_start) is True
                        and not hold_code())

                result = await agent_mail_service._wake_member(db, member_id, now,
                    expected_session_id=binding[0], delivery_guard=delivery_guard,
                    transport_guard=lambda: hold_code() is None, source='required_checks')
                state = 'confirmed' if result else 'unknown'
                if result:
                    agent_mail_service._last_auto_nudge_at[member_id] = now
            except Exception:
                await db.rollback()
                intact = False
                state = 'unknown'
            await db.execute(update(GithubRequiredCheckRecipient).where(
                GithubRequiredCheckRecipient.id == recipient_id, GithubRequiredCheckRecipient.wake_state == 'claimed')
                .values(wake_state=state).execution_options(synchronize_session=False))
            await db.commit()
        return intact

    async def completion_id(self, db, item):
        scope = await db.get(TeamGithubScope, item.scope_id)
        if scope is None:
            return None
        return await db.scalar(select(GithubRequiredCheckWatch.id).where(
            GithubRequiredCheckWatch.work_item_id == item.id,
            GithubRequiredCheckWatch.dispatch_nonce == item.dispatch_nonce,
            GithubRequiredCheckWatch.scope_revision == item.active_scope_revision,
            GithubRequiredCheckWatch.pr_number == item.pr_number,
            GithubRequiredCheckWatch.owner_slot_id == item.owner_slot_id,
            GithubRequiredCheckWatch.policy_digest == _digest(effective_policy(item, scope)),
            GithubRequiredCheckWatch.head_sha == item.last_verified_sha,
            GithubRequiredCheckWatch.completion_kind == 'success'))

    async def view(self, db, item, *, now=None):
        head = item.verification_head_sha
        if not head or not item.dispatch_nonce:
            return None
        watch = (await db.execute(select(GithubRequiredCheckWatch).where(
            GithubRequiredCheckWatch.work_item_id == item.id,
            GithubRequiredCheckWatch.dispatch_nonce == item.dispatch_nonce,
            GithubRequiredCheckWatch.scope_revision == item.active_scope_revision,
            GithubRequiredCheckWatch.head_sha == head,
            GithubRequiredCheckWatch.pr_number == item.pr_number,
            GithubRequiredCheckWatch.owner_slot_id == item.owner_slot_id))).scalar_one_or_none()
        if watch is None or not watch.checks:
            return None
        scope = await db.get(TeamGithubScope, item.scope_id)
        if scope is None or watch.policy_digest != _digest(effective_policy(item, scope)):
            return None
        current = _utc(now or datetime.utcnow())
        # A persisted historical success must not be shown as freshly authoritative.
        if current - _utc(watch.observed_at) > timedelta(minutes=5):
            return None
        done = sum(r['result'] not in {'pending', 'unknown'} for r in watch.checks)
        total = len(watch.checks)
        failure = any(r['result'] in _FAILURES for r in watch.checks)
        finished = failure or done == total
        recipients = (await db.execute(select(GithubRequiredCheckRecipient).where(
            GithubRequiredCheckRecipient.watch_id == watch.id))).scalars().all()
        scope = await db.get(TeamGithubScope, item.scope_id)
        team = await db.get(AgentTeamPreset, scope.preset_id) if scope else None
        leader = await self._member(db, team.id, team.leader_slot_id) if team else None
        expected = {leader}
        if team and watch.completion_kind == 'failure':
            expected.add(await self._member(db, team.id, item.owner_slot_id))
        elif team and watch.reviewer_member_id:
            try:
                expected.add(await self._reviewer(db, {'team_id':team.id, 'owner_slot_id':item.owner_slot_id}, watch.reviewer_member_id))
            except ValueError:
                expected.add(None)
        confirmed = {r.member_id for r in recipients if r.wake_state == 'confirmed'}
        all_woken = None not in expected and bool(expected) and expected.issubset(confirmed)
        return {'head_sha': head, 'completed': done, 'total': total,
            'state': ('finished' if all_woken else 'no_next_actor') if finished else 'waiting',
            'result': 'failure' if failure else 'success' if done == total else 'pending',
            'observed_at': watch.observed_at, 'changed_at': watch.changed_at}


github_ci_watch_service = GithubCIWatchService()
