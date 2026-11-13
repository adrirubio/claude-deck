"""Bounded, read-only view of explicit requests that an idle team member has not answered (#752).

The signal is a pending ``context_request`` or ``handoff`` addressed to a member of the team. Prose is
never classified. A plain message that asks for something carries no request marker and is not covered.

A request is reported only when all of these hold at observation time:
  * it is a root request (``thread_root_id`` is null), still ``pending``, and not an approval request;
  * it is at least ``mail_request_unanswered_seconds`` old (equal counts);
  * its addressee's native state is ``idle`` (working is active; stopped and unknown are not proven);
  * the addressee sent no ``message`` or ``answer`` in the request's canonical thread after it.

The view is COMPLETE only when nothing was truncated or left unproven. Otherwise it carries a fixed
reason word, in this priority: candidate_limit, native_unknown, ambiguous_legacy_request,
reply_scan_limit, entry_limit. Nested pending requests (older releases allowed them) can never be
cleared by a plain reply, so they are never entries; they make the view ambiguous instead.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import aliased

from app.config import settings
from app.models.database import MailExternalActor, MailMessage, MailTeamMember
from app.models.schemas import MAIL_REQUEST_KINDS, UnansweredRequestItem, UnansweredRequestView
from app.services.factory_audit_service import sanitize_text

CANDIDATE_LIMIT = 64          # one query reads 65 rows; a 65th row means "more than we evaluate"
ENTRY_LIMIT = 16
REPLY_QUERY_LIMIT = 33        # per candidate; reaching it without a match is a sentinel, not "no reply"
REPLY_ROW_BUDGET = 256        # total reply rows read in one observation
ANCESTRY_READ_BUDGET = 512    # total ancestry reads in one observation
MAX_ANCESTRY_HOPS = 32
NATIVE_INPUT_ROWS = 256      # the native input read bound the fence is checked with
SNAPSHOT_ATTEMPTS = 3        # coherent-snapshot attempts before the read fails closed
REASON_PRIORITY = ("candidate_limit", "native_unknown", "ambiguous_legacy_request", "reply_scan_limit",
                   "entry_limit")


class _BudgetExhausted(Exception):
    pass


class _IncoherentRead(ValueError):
    """A native observation that could not be shown to come from one unchanged database state."""


_UNSET = object()    # an omitted baseline; None means the early capture FAILED and is untrusted


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


class MailRequestStallService:
    deadline_seconds = 5.0

    # -- native activity (read only) ---------------------------------------------------------------

    async def _native_states(self, db, preset_id) -> tuple[dict[int, str], bool, dict]:
        """Slot states, whether the inputs were stable, and the fence they were observed against.

        The same bounded, read-only observation the summary uses. The fence is kept so the mail reads
        can be revalidated against it afterwards.
        """
        from app.services.agent_activity_service import _team_inputs, observe_team

        fence: dict = {}
        native = await observe_team(db, preset_id, include_agent_status=False, persist_identities=False,
                                    max_input_rows=256, input_fence=fence)
        current = {entry[0]: entry for entry in await _team_inputs(db, preset_id, 256)}
        return {entry.slot_id: entry.state for entry in native.slots}, current == fence, dict(fence)

    async def projection(self, db, preset_id, *, now: datetime | None = None) -> UnansweredRequestView:
        """The view for a caller that holds no observation of its own (the Supervisor check-in)."""
        # One absolute deadline, taken before the native phase, covers the native and the mail phase.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.deadline_seconds
        # The baseline is taken BEFORE the native phase. A failed capture is None (untrusted); it is
        # never replaced by a later one.
        try:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            baseline = await asyncio.wait_for(self._coherent_snapshot(db, preset_id), timeout=remaining)
        except (TimeoutError, OSError, ValueError, OperationalError):
            if db.in_transaction():
                await db.rollback()
            baseline = None
        try:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            states, ok, fence = await asyncio.wait_for(self._native_states(db, preset_id), timeout=remaining)
        except (TimeoutError, OSError, ValueError, OperationalError):
            if db.in_transaction():
                await db.rollback()
            states, ok, fence = {}, False, None
        return await self.observe(db, preset_id, now=now or datetime.now(timezone.utc),
                                  native_states=states, native_ok=ok, deadline=deadline, native_fence=fence,
                                  native_baseline=baseline)

    # -- the view ----------------------------------------------------------------------------------

    async def observe(self, db, preset_id, *, now: datetime, native_states: dict[int, str],
                      native_ok: bool, deadline: float | None = None,
                      native_fence: dict | None = None, native_baseline=_UNSET) -> UnansweredRequestView:
        """``deadline`` is an absolute monotonic loop time; omitted, the view gets its own full budget.

        ``native_fence`` is the native input fence the states were observed against. When given, it is
        compared with the current inputs after all mail reads; a difference is not a stable observation.
        ``native_baseline`` is a coherent snapshot taken before the native phase: omitted, one is taken at
        the start of the view; None means the caller's early capture failed, which is never replaced.
        """
        loop = asyncio.get_running_loop()
        limit = loop.time() + self.deadline_seconds if deadline is None else deadline
        try:
            remaining = limit - loop.time()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(
                self._observe(db, preset_id, _naive_utc(now), native_states, native_ok, native_fence,
                                native_baseline),
                timeout=remaining)
        except (TimeoutError, OSError, ValueError, OperationalError):
            if db.in_transaction():
                await db.rollback()
            return UnansweredRequestView(items=[], complete=False, reason="native_unknown")

    @staticmethod
    def _request_filters(preset_id):
        return (
            MailTeamMember.team_preset_id == preset_id,
            MailMessage.kind.in_(MAIL_REQUEST_KINDS),
            MailMessage.request_status == "pending",
            # Approval requests have their own window and timeout flow.
            func.json_extract(MailMessage.payload, "$.approval_request_id").is_(None),
        )

    async def _candidates(self, db, preset_id):
        reply = aliased(MailMessage)
        rows = (await db.execute(
            select(MailMessage.id, MailMessage.kind, MailMessage.created_at, MailMessage.recipient_member_id,
                   MailMessage.sender_member_id, MailMessage.sender_actor_id,
                   MailTeamMember.display_name.label("recipient_name"),
                   MailTeamMember.team_slot_id.label("slot_id"), MailTeamMember.updated_at.label("member_updated"))
            .join(MailTeamMember, MailTeamMember.id == MailMessage.recipient_member_id)
            .where(*self._request_filters(preset_id), MailMessage.thread_root_id.is_(None),
                   # A plain reply by the addressed member in the request's own thread answers it.
                   # An answer that names another request (reserved resolves_request_id) does not.
                   ~exists().where(reply.sender_member_id == MailMessage.recipient_member_id,
                                   reply.thread_root_id == MailMessage.id, reply.id > MailMessage.id,
                                   reply.kind.in_(("message", "answer")),
                                   func.json_extract(reply.payload, "$.resolves_request_id").is_(None)))
            .order_by(MailMessage.created_at.asc(), MailMessage.id.asc())
            .limit(CANDIDATE_LIMIT + 1))).all()
        return rows[:CANDIDATE_LIMIT], len(rows) > CANDIDATE_LIMIT

    async def _nested_ambiguous(self, db, preset_id, now, threshold_seconds) -> bool:
        from datetime import timedelta

        found = await db.scalar(
            select(MailMessage.id)
            .join(MailTeamMember, MailTeamMember.id == MailMessage.recipient_member_id)
            .where(*self._request_filters(preset_id), MailMessage.thread_root_id.is_not(None),
                   MailMessage.created_at <= now - timedelta(seconds=threshold_seconds))
            .limit(1))
        return found is not None

    async def _signatures(self, db, member_ids):
        if not member_ids:
            return {}
        rows = (await db.execute(
            select(MailTeamMember.id, MailTeamMember.team_slot_id, MailTeamMember.team_preset_id,
                   MailTeamMember.updated_at).where(MailTeamMember.id.in_(member_ids)))).all()
        return {row.id: tuple(row)[1:] for row in rows}

    async def _canonical_root(self, db, message_id, cache, counter):
        """Canonical root id of a message, or None when its ancestry is missing, cyclic or too deep."""
        path, seen, current, root = [], set(), message_id, None
        for _hop in range(MAX_ANCESTRY_HOPS + 1):
            if current in cache:
                root = cache[current]
                break
            counter[0] += 1
            if counter[0] > ANCESTRY_READ_BUDGET:
                raise _BudgetExhausted
            row = (await db.execute(select(MailMessage.thread_root_id).where(MailMessage.id == current))).first()
            if row is None or current in seen:
                break
            seen.add(current)
            path.append(current)
            if row.thread_root_id is None:
                root = current
                break
            current = row.thread_root_id
        for node in path:
            cache[node] = root
        return root

    async def _legacy_reply_clears(self, db, candidate, rows_left, cache, counter):
        """(cleared, proven). Proven means the absence of a reply was established inside the bounds."""
        limit = min(REPLY_QUERY_LIMIT, rows_left)
        if limit <= 0:
            return False, False, 0
        replies = (await db.execute(
            select(MailMessage.id, MailMessage.thread_root_id,
                   func.json_extract(MailMessage.payload, "$.resolves_request_id").label("resolves"))
            .where(MailMessage.sender_member_id == candidate.recipient_member_id,
                   MailMessage.id > candidate.id, MailMessage.thread_root_id.is_not(None),
                   MailMessage.kind.in_(("message", "answer")))
            .order_by(MailMessage.id.asc()).limit(limit))).all()
        broken = False
        try:
            for reply in replies:
                if reply.resolves is not None:      # it answers another request: it never clears this one
                    continue
                root = await self._canonical_root(db, reply.thread_root_id, cache, counter)
                if root == candidate.id:
                    return True, True, len(replies)
                broken = broken or root is None
        except _BudgetExhausted:
            return False, False, len(replies)
        capped = len(replies) >= limit
        return False, not (capped or broken), len(replies)

    async def _names(self, db, candidates):
        member_ids = {row.sender_member_id for row in candidates if row.sender_member_id is not None}
        actor_ids = {row.sender_actor_id for row in candidates if row.sender_actor_id is not None}
        members = dict((await db.execute(select(MailTeamMember.id, MailTeamMember.display_name)
                                         .where(MailTeamMember.id.in_(member_ids)))).all()) if member_ids else {}
        actors = dict((await db.execute(select(MailExternalActor.id, MailExternalActor.display_name)
                                        .where(MailExternalActor.id.in_(actor_ids)))).all()) if actor_ids else {}
        return members, actors

    @staticmethod
    def _clean(value: str | None, fallback: str) -> str:
        cleaned = sanitize_text(value or "", limit=80).strip()
        return (cleaned or fallback)[:80]

    async def _pinned_driver(self, db):
        """The physical (driver) connection the session is using."""
        connection = await db.connection()
        return (await connection.get_raw_connection()).driver_connection

    async def _coherent_snapshot(self, db, preset_id):
        """(native inputs by slot, identity by slot) proven to come from one unchanged database state.

        An attempt runs on one pinned physical connection that holds no open transaction (an open
        transaction can pin an old snapshot, whatever the data version says), and is accepted only if
        PRAGMA data_version is the same before and after the builder: that value changes if and only if
        another connection committed in between. Three attempts, then it fails closed.
        """
        from app.services.agent_activity_service import _team_inputs

        parameters = inspect.signature(_team_inputs).parameters
        if "identity" not in parameters and not any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
            # A builder that cannot report identity cannot prove it: fail closed.
            raise _IncoherentRead("the native input builder does not report identity")
        for _attempt in range(SNAPSHOT_ATTEMPTS):
            driver = await self._pinned_driver(db)
            if driver.in_transaction:
                raise _IncoherentRead("an open transaction can pin an old snapshot")
            before = await db.scalar(text("PRAGMA data_version"))
            identity: dict = {}
            entries = await _team_inputs(db, preset_id, NATIVE_INPUT_ROWS, identity=identity)
            closing = await self._pinned_driver(db)
            after = await db.scalar(text("PRAGMA data_version"))
            if closing is not driver or closing.in_transaction:
                raise _IncoherentRead("the observation was not pinned to one connection")
            if before is not None and before == after:
                return {entry[0]: entry for entry in entries}, identity
        raise _IncoherentRead("the native inputs kept changing")

    async def _revalidate(self, db, preset_id, rows, native_fence, baseline):
        """Entries still proven by ONE fresh coherent snapshot, and the reasons for dropping the rest.

        The snapshot is the last read of the view. Each entry needs: its addressee is the snapshot's
        current member of the slot, the slot's identity (member and sessions) equals the baseline's,
        and, when a fence was passed, the snapshot's native inputs equal it.
        """
        inputs, identity = await self._coherent_snapshot(db, preset_id)
        reasons: set[str] = set()
        kept = []
        for row in rows:
            now_id, base_id = identity.get(row.slot_id), baseline[1].get(row.slot_id)
            if now_id is None or now_id != base_id or now_id[0] != row.recipient_member_id:
                reasons.add("native_unknown")
                continue
            kept.append(row)
        if native_fence is not None and inputs != native_fence:
            reasons.add("native_unknown")
            kept = []
        return kept, reasons

    async def _observe(self, db, preset_id, now, native_states, native_ok,
                       native_fence=None, native_baseline=_UNSET) -> UnansweredRequestView:
        threshold = int(settings.mail_request_unanswered_seconds)
        candidates, over_limit = await self._candidates(db, preset_id)
        reasons: set[str] = set()
        if over_limit:
            reasons.add("candidate_limit")
        if await self._nested_ambiguous(db, preset_id, now, threshold):
            reasons.add("ambiguous_legacy_request")
        before = await self._signatures(db, {row.recipient_member_id for row in candidates})
        # None is a failed early capture: untrusted, and never replaced by a baseline taken now.
        baseline = (await self._coherent_snapshot(db, preset_id)) if native_baseline is _UNSET else native_baseline

        qualified = []
        for row in candidates:
            if (now - row.created_at).total_seconds() < threshold:
                continue
            if baseline is None or baseline[1].get(row.slot_id, (None,))[0] != row.recipient_member_id:
                # No trusted baseline, or the slot's native state describes another member.
                reasons.add("native_unknown")
                continue
            state = native_states.get(row.slot_id) if native_ok and row.slot_id is not None else None
            if state == "working":
                continue
            if state != "idle":
                reasons.add("native_unknown")    # stopped, unknown, missing binding or a failed read
                continue
            qualified.append(row)

        proven, cache, counter, rows_left = [], {}, [0], REPLY_ROW_BUDGET
        for row in qualified:
            cleared, is_proven, used = await self._legacy_reply_clears(db, row, rows_left, cache, counter)
            rows_left -= used
            if cleared:
                continue
            if not is_proven:
                reasons.add("reply_scan_limit")
                continue
            proven.append(row)

        # A binding that changed during the reads is not a stable observation.
        after = await self._signatures(db, {row.recipient_member_id for row in proven})
        stable = []
        for row in proven:
            if after.get(row.recipient_member_id) != before.get(row.recipient_member_id):
                reasons.add("native_unknown")
                continue
            stable.append(row)

        # Names are read first; the revalidation is the last read before the entries are built.
        members, actors = await self._names(db, stable)
        if baseline is None:
            stable, dropped = [], {"native_unknown"}
        else:
            stable, dropped = await self._revalidate(db, preset_id, stable, native_fence, baseline)
        reasons |= dropped
        omitted = max(0, len(stable) - ENTRY_LIMIT)
        if omitted:
            reasons.add("entry_limit")
        shown = stable[:ENTRY_LIMIT]
        items = []
        for row in shown:
            seconds = max(0, int((now - row.created_at).total_seconds()))
            requester = (self._clean(members.get(row.sender_member_id), "a team member")
                         if row.sender_member_id is not None
                         else self._clean(actors.get(row.sender_actor_id), "an external actor"))
            recipient = self._clean(row.recipient_name, "a team member")
            label = "handoff" if row.kind == "handoff" else "request"
            items.append(UnansweredRequestItem(
                request_id=row.id, kind=row.kind, requester=requester, recipient=recipient,
                requested_at=row.created_at.replace(tzinfo=timezone.utc), unanswered_seconds=seconds,
                threshold_seconds=threshold,
                text=f"{recipient} has not answered {requester}'s {label} for {seconds // 60} min."))
        reason = next((word for word in REASON_PRIORITY if word in reasons), None)
        return UnansweredRequestView(items=items, complete=reason is None, reason=reason, omitted_count=omitted)


mail_request_stall_service = MailRequestStallService()
