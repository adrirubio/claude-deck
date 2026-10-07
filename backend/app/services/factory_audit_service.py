"""Factory audit ledger service (P05).

Observation-only ledger. The ledger observes actual results. It never
approves plans, raises limits, retries work, releases a workspace or replays
a mutation because an event is present or absent.

Actor derivation uses actual authentication or scheduler context. A shared
operator credential is recorded as an operator role, never a named person.
No credential, credential hash or agent token is ever stored.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import FactoryAuditEvent, FactoryContextKey

# Allowlisted value keys for before/after snapshots. Values outside this
# allowlist are dropped at write time.
SAFE_VALUE_FIELDS = {
    "status", "dispatch_status", "attempt_phase", "enabled", "autonomy_enabled",
    "leader_slot_id", "owner_slot_id", "owner_member_id", "approval_round",
    "approval_round_count", "retry_count", "diagnostic_retry_count",
    "delivery_outcome", "completion_kind", "action_outcome", "provider",
    "display_name", "name", "repo_owner", "repo_name", "issue_type",
    "merge_policy", "dispatch_label", "design_label", "base_ref",
    "wake_enabled", "mailbox_status", "kind", "request_kind", "decision",
    "status_note", "phase", "execution_target", "failed_head_count",
    "max_failed_heads", "workspace_enabled", "dispatchable",
    "recovery_checkpoint_stage", "active_scope_revision",
    # C11: typed finite continuation policy settings.
    "continuation_enabled", "max_continuation_revisions",
    "max_continuation_failed_heads", "max_failed_heads_per_revision",
    "max_scope_paths", "max_scope_commands",
    # R05: every audited finite scope policy setting. Command hints and
    # templates are free text that can hold commands; they stay excluded.
    "max_approval_rounds", "max_concurrent_dispatched", "max_verification_retries",
    "max_auto_merges_per_day", "max_build_parallelism", "builds_out_of_tree",
}

# C10: typed, named fields for event-time snapshots. Values are primitive
# and bounded; nested dictionaries and lists of objects are never stored.
SAFE_SNAPSHOT_FIELDS = {
    "github_auth_mode", "configured_provider", "observed_runtime_provider",
    "repo_owner", "repo_name", "scope_created_at", "scope_updated_at",
    "team_created_at", "team_display_name", "slot_display_name",
    "issue_number", "pr_number", "issue_type", "artifact", "fact_source",
    "event_time_labels",
    # C06/C12: stable non-secret attempt identities and the retry class.
    "attempt", "launch_attempt", "retry_class",
    # A20: native runtime observation results; no argument value is stored.
    "runtime_provider_evidence", "runtime_session_id", "claimed_runtime_provider",
    # A30/A32: the exact artifact version and separate source times.
    "artifact_version", "pull_closed_at", "issue_closed_at",
    # T05: original typed identities and creation times.
    "original_team_id", "original_scope_id", "original_item_id", "original_slot_id",
    "item_created_at", "slot_created_at",
}

# C10/C03: the typed fields of a human review evidence record.
SAFE_REVIEW_FIELDS = {"fact_kind", "artifact", "version", "actor", "source",
                      "actor_kind", "independent", "decision", "declared_by"}

_MAX_TEXT = 200
_MAX_REASON = 500

# Keys whose values are never stored, whatever their content.
_SECRET_KEY = re.compile(
    r"(?:^|[_\-\s])(?:token|secret|password|passwd|credential|capability|"
    r"api[_\-]?key|authorization|cookie|nonce)(?:$|[_\-\s])",
    re.IGNORECASE)

_SECRET_WORDS = (
    r"token|secret|password|passwd|pwd|credential|credentials|capability[_\-]?hash|"
    r"lease[_\-]?token|api[_\-]?key|access[_\-]?key|private[_\-]?key|authorization|"
    r"cookie|session[_\-]?token|nonce|bearer|basic"
)

# C10: credential-shaped text in free-form values, applied in order. Each
# entry keeps its leading label and replaces only the value.
_REDACTIONS = (
    # Assignment and header forms: "token=x", "password: x", '"secret": "x"',
    # "Authorization: Bearer x".
    # Prefixed names such as "github_token" or "X-Api-Key" count too.
    (re.compile(
        rf"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_\-])*(?:{_SECRET_WORDS})s?)"
        r"([\"']?\s*[:=]\s*)(?:bearer\s+|basic\s+)?[\"']?[^\s\"',;}]+"),
     r"\1\2[redacted]"),
    # Scheme forms without a separator: "Bearer x", "Basic x".
    (re.compile(r"(?i)\b((?:bearer|basic)\s+)[A-Za-z0-9._~+/\-]{8,}=*"),
     r"\1[redacted]"),
    # A credential word followed by any value: "token abc". This is
    # conservative; the next word is redacted even when it is ordinary text.
    (re.compile(
        rf"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_\-])*(?:{_SECRET_WORDS})s?\s+)"
        r"(?!\[redacted\])[^\s\"',;]+"),
     r"\1[redacted]"),
    # Known credential formats.
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"),
     "[redacted]"),
    (re.compile(r"\b(?:xox[abpr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{16,})\b"),
     "[redacted]"),
    # URLs with embedded user information.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"),
     r"\1[redacted]@"),
    # Opaque hex values of 16 or more characters (lease tokens, nonces,
    # digests). A 40-character Git commit SHA is public identity and stays.
    (re.compile(r"\b(?![A-Fa-f0-9]{40}\b)[A-Fa-f0-9]{16,}\b"), "[redacted]"),
    # Long opaque token-like blobs that mix letters and digits. Paths with
    # "/" separators are not matched. A 40-character commit SHA stays.
    (re.compile(
        r"\b(?![A-Fa-f0-9]{40}\b)(?=[A-Za-z0-9+_\-]*\d)(?=[A-Za-z0-9+_\-]*[A-Za-z])"
        r"[A-Za-z0-9+_\-]{40,}={0,2}"),
     "[redacted]"),
)


class AuditWriteError(RuntimeError):
    """An audit write failed; the caller must roll back its own change."""


class ReplayConflictError(AuditWriteError):
    """R09: a replayed operation identity carries a different canonical fact.

    The existing fact stands. The caller's transaction must roll back, so the
    conflicting action is never committed and never misreported.
    """


def sanitize_text(value: str, *, limit: int = _MAX_TEXT) -> str:
    """C10: remove credential-shaped content from one free-text value.

    Keyword forms keep the keyword and redact the value that follows it, so
    ordinary words such as "release" stay readable. Known token formats,
    URL user information and long opaque blobs are redacted wherever they
    appear. The result is bounded.
    """
    cleaned = str(value)
    for pattern, replacement in _REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned[:limit]


def sanitize_reason(reason: str | None) -> str | None:
    """Keep a short sanitized reason with no credential-shaped content."""
    if reason is None:
        return None
    return sanitize_text(str(reason), limit=_MAX_REASON)


def _safe_primitive(value: Any) -> tuple[bool, Any]:
    """Accept only bounded primitives; sanitize text. Returns (keep, value)."""
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return True, value
    if isinstance(value, str):
        return True, sanitize_text(value)
    return False, None


def allowlist_values(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep allowlisted keys with safe primitive values only.

    C10: a value under an allowed key is sanitized too. Nested objects are
    dropped; no arbitrary dictionary is copied into the ledger.
    """
    if not values or not isinstance(values, dict):
        return None
    safe: dict[str, Any] = {}
    for key, value in values.items():
        if key not in SAFE_VALUE_FIELDS or _SECRET_KEY.search(str(key)):
            continue
        keep, projected = _safe_primitive(value)
        if keep:
            safe[key] = projected
    return safe or None


def project_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """C10: a typed, bounded projection of an event-time snapshot."""
    if not snapshot or not isinstance(snapshot, dict):
        return None
    safe: dict[str, Any] = {}
    for key, value in snapshot.items():
        if key not in SAFE_SNAPSHOT_FIELDS:
            continue
        if key == "event_time_labels":
            if isinstance(value, (list, tuple)):
                safe[key] = [
                    label for label in value
                    if isinstance(label, str) and label in SAFE_SNAPSHOT_FIELDS
                ]
            continue
        keep, projected = _safe_primitive(value)
        if keep:
            safe[key] = projected
    return safe or None


def project_review_evidence(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    """C10/C03: a typed projection of a review evidence record."""
    if not evidence or not isinstance(evidence, dict):
        return None
    safe: dict[str, Any] = {}
    for key in SAFE_REVIEW_FIELDS:
        if key in evidence:
            keep, projected = _safe_primitive(evidence[key])
            if keep:
                safe[key] = projected
    return safe or None


def derive_actor(
    *,
    actor_kind: str,
    member_id: int | None = None,
    session_id: int | None = None,
    scheduler: str | None = None,
) -> dict[str, Any]:
    """Derive the recorded actor from actual authentication context.

    ``operator`` records the shared operator credential with no invented
    personal identity. ``member`` records an authenticated member reference.
    ``scheduler`` records the scheduler identity used by scheduled work.
    """
    if actor_kind not in {"operator", "member", "scheduler", "system"}:
        raise ValueError(f"unsupported actor kind: {actor_kind}")
    # C08: client-supplied identity claims are never trusted. The shared
    # operator credential cannot also assert a personal member identity.
    if actor_kind == "operator" and (member_id is not None or session_id is not None):
        raise ValueError("operator_role_cannot_assert_identity")
    reference = None
    if actor_kind == "operator":
        reference = "shared-operator-credential"
    elif actor_kind == "scheduler":
        reference = scheduler
    elif actor_kind == "member" and member_id is not None:
        reference = f"member:{member_id}"
    return {
        "actor_kind": actor_kind,
        "actor_member_id": member_id if actor_kind == "member" else None,
        "actor_session_id": session_id,
        "actor_reference": reference,
    }


async def current_context_key(
    db: AsyncSession, key_kind: str, numeric_id: int
) -> str | None:
    """R01: the active key of the current resource lifetime, read-only.

    Reads use this. It never allocates, so a factory GET performs no write.
    None means no event has been recorded for the current lifetime.
    """
    return (await db.scalars(
        select(FactoryContextKey.context_key).where(
            FactoryContextKey.key_kind == key_kind,
            FactoryContextKey.numeric_id == numeric_id,
            FactoryContextKey.retired_at.is_(None),
        ).limit(1)
    )).first()


async def context_key_for(db: AsyncSession, key_kind: str, numeric_id: int) -> str:
    """Allocate or reuse the context key of the current resource lifetime.

    Only authorized write and migration transactions call this. A deleted
    resource's key is retired by trigger, so a reused numeric ID receives a
    new key and never joins the old history.
    """
    existing = await current_context_key(db, key_kind, numeric_id)
    if existing is not None:
        return existing
    key = f"{key_kind}:{numeric_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    db.add(FactoryContextKey(key_kind=key_kind, numeric_id=numeric_id, context_key=key))
    await db.flush()
    return key


async def context_key_is_current(db: AsyncSession, key: str, key_kind: str) -> int | None:
    """R01: the numeric ID of a key only while its lifetime is current."""
    return (await db.scalars(
        select(FactoryContextKey.numeric_id).where(
            FactoryContextKey.context_key == key,
            FactoryContextKey.key_kind == key_kind,
            FactoryContextKey.retired_at.is_(None),
        ).limit(1)
    )).first()


def _canonical_fact(**fields: Any) -> tuple:
    """R09: the fact payload an exact replay must repeat."""
    return tuple(
        (name, tuple(sorted(value.items())) if isinstance(value, dict) else value)
        for name, value in sorted(fields.items()))


# T02: snapshot fields that are evidence of the fact itself. Live labels
# (names, types, runtime observations) are enrichment and may change.
_STABLE_EVIDENCE_FIELDS = (
    "attempt", "launch_attempt", "artifact", "artifact_version", "fact_source",
    "pull_closed_at", "issue_closed_at", "retry_class",
)


def _stable_evidence(snapshot: dict | None) -> dict:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    return {key: snapshot.get(key) for key in _STABLE_EVIDENCE_FIELDS if snapshot.get(key) is not None}


def _naive(value: datetime | None) -> datetime | None:
    if isinstance(value, str):
        value = _parse_time(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


async def _resolve_parents(
    db: AsyncSession,
    *,
    team_preset_id: int | None,
    scope_id: int | None,
    item_id: int | None,
) -> tuple[int | None, int | None]:
    """R04: the live scope of an item and the live team of a scope.

    Only missing parents are resolved, from the current live rows. An
    explicitly supplied parent is kept. A deleted parent stays unknown.
    """
    from app.models.database import GithubWorkItem, TeamGithubScope

    if scope_id is None and item_id is not None:
        scope_id = (await db.scalars(
            select(GithubWorkItem.scope_id).where(GithubWorkItem.id == item_id).limit(1)
        )).first()
    if team_preset_id is None and scope_id is not None:
        team_preset_id = (await db.scalars(
            select(TeamGithubScope.preset_id).where(TeamGithubScope.id == scope_id).limit(1)
        )).first()
    return team_preset_id, scope_id


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


async def event_time_snapshot(
    db: AsyncSession,
    *,
    team_preset_id: int | None,
    scope_id: int | None,
    item_id: int | None,
) -> dict[str, Any]:
    """R04: safe identity labels of the live resources at event time.

    The configured harness is the trusted slot configuration: the item's
    owner slot, or the team's Leader slot for team and scope facts. GitHub
    authentication mode is its own label. The observed runtime provider comes
    only from the owner's bound live session; otherwise it stays unknown.
    """
    from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, TeamGithubScope

    snapshot: dict[str, Any] = {}
    slot_id = None
    if item_id is not None:
        item = await db.get(GithubWorkItem, item_id)
        if item is not None:
            # T05: the original item identity and creation time are retained
            # as typed fields, so deletion and numeric reuse lose nothing.
            snapshot.update({
                "issue_number": item.issue_number, "issue_type": item.issue_type,
                "pr_number": item.pr_number, "original_item_id": item.id,
                "item_created_at": _iso(item.created_at)})
            slot_id = item.owner_slot_id
    if scope_id is not None:
        scope = await db.get(TeamGithubScope, scope_id)
        if scope is not None:
            snapshot.update({
                "repo_owner": scope.repo_owner, "repo_name": scope.repo_name,
                "github_auth_mode": scope.github_auth_mode,
                "original_scope_id": scope.id,
                "scope_created_at": _iso(scope.created_at),
                "scope_updated_at": _iso(scope.updated_at)})
    if team_preset_id is not None:
        preset = await db.get(AgentTeamPreset, team_preset_id)
        if preset is not None:
            snapshot.update({
                "team_display_name": preset.name, "original_team_id": preset.id,
                "team_created_at": _iso(preset.created_at)})
            if slot_id is None:
                slot_id = preset.leader_slot_id
    if slot_id is not None:
        slot = await db.get(AgentTeamSlot, slot_id)
        if slot is not None:
            snapshot.update({
                "slot_display_name": slot.display_name, "configured_provider": slot.provider,
                "original_slot_id": slot.id,
                "slot_created_at": _iso(getattr(slot, "created_at", None))})
    if slot_id is not None:
        # A20: the observed runtime harness comes only from the native
        # process of the event-time slot's current authenticated MCP
        # generation (the item owner, or the team Leader for team and scope
        # facts). A registered provider is a claim and only corroborates it.
        observation = await observe_runtime_provider(db, slot_id)
        snapshot["observed_runtime_provider"] = observation.provider
        snapshot["runtime_provider_evidence"] = observation.evidence
        snapshot["runtime_session_id"] = observation.session_id
        snapshot["claimed_runtime_provider"] = observation.claimed_provider
    if snapshot:
        snapshot.setdefault("observed_runtime_provider", None)
        snapshot["event_time_labels"] = sorted(
            key for key in snapshot if key not in _RUNTIME_OBSERVATION_FIELDS)
    return snapshot


# A20: the runtime observation fields. They are observations, not labels.
_RUNTIME_OBSERVATION_FIELDS = {
    "observed_runtime_provider", "runtime_provider_evidence", "runtime_session_id",
    "claimed_runtime_provider",
}

# A20: the supported agent executables, from the process matchers of the
# provider modules in app.services.providers. Only the executable name is
# read. Server and helper executables (codex-exec-server, codex-cli,
# copilot-language-server, opencode-server) are not in the table.
_AGENT_EXECUTABLES = {
    "claude": "claude-code",
    "codex": "codex-cli",
    "copilot": "copilot-cli",
    "opencode": "opencode-cli",
}
# The pi-cli matcher accepts a case-sensitive "pi" executable, or node with
# this bundle as its first argument.
_PI_NODE_BUNDLE = "/@earendil-works/pi-coding-agent/dist/bundle/cli.js"


def classify_agent_argv(argv: list[str] | None) -> str | None:
    """A20: the provider proven by one native argument vector, or None.

    Argument boundaries are kept. Only argv[0] is classified, plus argv[1]
    for the pi node bundle form. Other arguments are never searched, so an
    unrelated argument named like a provider proves nothing. A wrapper form
    that the provider modules prove only through child processes stays
    unsupported.
    """
    if not argv or not isinstance(argv[0], str) or not argv[0]:
        return None
    name = argv[0].rsplit("/", 1)[-1]
    if name == "pi":
        return "pi-cli"
    provider = _AGENT_EXECUTABLES.get(name.lower())
    if provider is not None:
        return provider
    if (name.lower() == "node" and len(argv) > 1 and isinstance(argv[1], str)
            and argv[1].endswith(_PI_NODE_BUNDLE)):
        return "pi-cli"
    return None


class RuntimeObservation:
    """A20: one native runtime observation; no argument value is kept."""

    __slots__ = ("provider", "evidence", "session_id", "claimed_provider")

    def __init__(self, provider: str | None, evidence: str,
                 session_id: int | None = None, claimed_provider: str | None = None):
        self.provider = provider
        self.evidence = evidence
        self.session_id = session_id
        self.claimed_provider = claimed_provider


async def _current_generation(db: AsyncSession, slot_id: int) -> tuple[str, Any]:
    """A20: the slot's current authenticated MCP generation.

    No generation counter exists, so the generation is the one session row
    that is an open, connected, token-holding MCP session of the slot's
    current member, bound to the slot's current pane binding on a pane that
    is not retired. Observed-only, hook, old and unbound sessions never
    qualify. Returns ("ok", row) or (reason, None).
    """
    from app.models.database import (
        AgentPaneBinding, MailAgentSession, MailPaneLifecycle, MailTeamMember)

    members = (await db.scalars(select(MailTeamMember.id).where(
        MailTeamMember.team_slot_id == slot_id,
        MailTeamMember.participant_kind == "team_slot",
    ).execution_options(populate_existing=True))).all()
    if not members:
        return "absent", None
    if len(members) > 1:
        return "ambiguous", None
    binding = (await db.execute(select(
        AgentPaneBinding.id, AgentPaneBinding.pane_pid, AgentPaneBinding.pane_proc_start,
    ).where(AgentPaneBinding.slot_id == slot_id).order_by(
        AgentPaneBinding.id.desc()).limit(1))).first()
    if binding is None:
        return "absent", None
    sessions = (await db.execute(select(
        MailAgentSession.id, MailAgentSession.session_key, MailAgentSession.member_id,
        MailAgentSession.provider, MailAgentSession.bound_pane_pid,
        MailAgentSession.bound_pane_proc_start, MailAgentSession.last_seen_at,
    ).where(
        MailAgentSession.member_id == members[0],
        MailAgentSession.team_slot_id == slot_id,
        MailAgentSession.source == "mcp",
        MailAgentSession.closed_at.is_(None),
        MailAgentSession.mailbox_status == "connected",
        MailAgentSession.capability_token_hash.is_not(None),
        MailAgentSession.bound_pane_pid == binding.pane_pid,
        MailAgentSession.bound_pane_proc_start == binding.pane_proc_start,
    ))).all()
    if not sessions:
        return "absent", None
    if len(sessions) > 1:
        return "ambiguous", None
    # T10: the existing authenticated MCP freshness rule
    # (agent_mail_service.MCP_HEARTBEAT_TTL_SECONDS, imported only). An
    # expired generation proves nothing, however live its pane is.
    from datetime import timedelta

    from app.services.agent_mail_service import MCP_HEARTBEAT_TTL_SECONDS

    cutoff = datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS)
    seen = sessions[0].last_seen_at
    if seen is None or _naive(seen) < cutoff:
        return "stale", None
    retired = (await db.execute(select(MailPaneLifecycle.retired_at).where(
        MailPaneLifecycle.pane_pid == binding.pane_pid,
        MailPaneLifecycle.pane_proc_start == binding.pane_proc_start,
    ))).first()
    if retired is None or retired.retired_at is not None:
        return "absent", None
    return "ok", (sessions[0], binding.id)


async def observe_runtime_provider(db: AsyncSession, slot_id: int) -> RuntimeObservation:
    """A20: observe the runtime provider of a slot from native identity.

    The generation is captured, the bound pane's argument vector is read
    with lifetime checks before and after the read, and the generation,
    member, binding and pane lifetime are rechecked afterward. Absent,
    ambiguous, unavailable, unsupported or changed evidence stays unknown.
    """
    import asyncio

    from app.utils import peer_process

    reason, current = await _current_generation(db, slot_id)
    if current is None:
        return RuntimeObservation(None, reason)
    session, binding_id = current
    pid, start = session.bound_pane_pid, session.bound_pane_proc_start
    argv = await asyncio.to_thread(peer_process.pane_agent_argv, pid, start)
    if argv is None:
        return RuntimeObservation(None, "unavailable", session.id, session.provider)
    provider = classify_agent_argv(argv)
    del argv
    reason, after = await _current_generation(db, slot_id)
    alive = await asyncio.to_thread(peer_process.pane_is_alive_strict, pid, start)
    if (after is None or after[1] != binding_id or alive is not True
            or (after[0].id, after[0].session_key, after[0].member_id,
                after[0].bound_pane_pid, after[0].bound_pane_proc_start)
            != (session.id, session.session_key, session.member_id, pid, start)):
        return RuntimeObservation(None, "lifetime_changed", session.id, session.provider)
    if provider is None:
        return RuntimeObservation(None, "unsupported_form", session.id, session.provider)
    return RuntimeObservation(provider, "native_argv", session.id, session.provider)


async def item_attempt(db: AsyncSession, item: Any) -> tuple[str, int | None, str]:
    """R02: the attempt, revision and launch identity of an item now.

    Matches the watcher's identity: the revision row of this item, dispatch
    attempt and active revision number.
    """
    from app.models.database import GithubAttemptScopeRevision

    revision_id = None
    if item.dispatch_nonce is not None:
        revision_id = (await db.scalars(
            select(GithubAttemptScopeRevision.id).where(
                GithubAttemptScopeRevision.work_item_id == item.id,
                GithubAttemptScopeRevision.dispatch_nonce == item.dispatch_nonce,
                GithubAttemptScopeRevision.revision == item.active_scope_revision,
            ).limit(1)
        )).first()
    attempt = f"item:{item.id}:launch:{item.launch_id}:revision:{revision_id}"
    return attempt, revision_id, launch_attempt_key(item.id, item.launch_id)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


async def record_merged_delivery(
    db: AsyncSession, item: Any, pull: dict | None, *, source: str,
    attempt_identity: tuple[str, int | None, str] | None = None,
    original_context: dict[str, Any] | None = None,
) -> FactoryAuditEvent:
    """R02: the sourced delivery fact of a merged pull request.

    Called by the verification merge paths in the merge transaction. The
    PR's own merge time is the fact time; an absent time stays unknown.
    Independent human review is not inferred from a merge. A34: a later
    reconciliation passes the original ``attempt_identity`` (attempt key,
    revision ID, launch key) so that the fact stays on its original attempt.
    """
    from app.models.database import TeamGithubScope

    if attempt_identity is not None:
        attempt, revision_id, launch = attempt_identity
    else:
        attempt, revision_id, launch = await item_attempt(db, item)
    pull = pull if isinstance(pull, dict) else {}
    pr_number = pull.get("number") or item.pr_number
    scope = await db.get(TeamGithubScope, item.scope_id)
    # The artifact names the repository and pull request, so equal PR numbers
    # in different repositories never collide.
    artifact = None
    if pr_number:
        repository = f"{scope.repo_owner}/{scope.repo_name}" if scope is not None else "unknown"
        artifact = f"{repository}/pull/{pr_number}"
    # A32: the exact delivered version is the verified pull head; an absent
    # head stays unknown and is never taken from mutable item state.
    head = pull.get("head")
    version = head.get("sha") if isinstance(head, dict) else None
    snapshot: dict[str, Any] = {}
    if isinstance(version, str) and version:
        snapshot["artifact_version"] = version
    # T04: a later fact keeps the original attempt's type and lifetime keys.
    original = original_context or {}
    issue_type = original.get("issue_type") or item.issue_type
    snapshot["issue_type"] = issue_type
    return await record_delivery_fact(
        db, item_id=item.id, revision_id=revision_id, scope_id=item.scope_id,
        team_context_key=original.get("team_context_key"),
        scope_context_key=original.get("scope_context_key"),
        item_context_key=original.get("item_context_key"),
        delivery_outcome="delivered",
        completion_kind="merged_design" if issue_type == "design" else "merged_code",
        fact_source="github_pull_request_merged",
        fact_time=_parse_time(pull.get("merged_at")),
        artifact=artifact,
        actor=derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler"),
        attempt=attempt, launch_attempt=launch, snapshot=snapshot, source=source)


async def record_revision_outcome(
    db: AsyncSession, *, item_id: int, revision_id: int, status: str, source: str
) -> FactoryAuditEvent:
    """R08: one preserved revision result fact, in the result's transaction.

    T02: the identity names the observing call site, so a second site that
    observes the same result appends rather than conflicts; recovery counts
    distinct revisions.
    """
    operation_id = f"revision_outcome:{revision_id}:{status}:{source}"
    return await record_event(
        db, event_kind="revision_outcome", source=source, occurred_at=datetime.utcnow(),
        actor=derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler"),
        item_id=item_id, revision_id=revision_id, after_values={"status": status},
        action_outcome="applied", sanitized_reason=f"revision {status}",
        operation_id=operation_id, correlation_id=operation_id)


def replay_key_for(
    operation_id: str,
    event_kind: str,
    *,
    team_preset_id: int | None = None,
    team_slot_id: int | None = None,
    scope_id: int | None = None,
    item_id: int | None = None,
    revision_id: int | None = None,
    request_id: int | None = None,
) -> str:
    """C07: one replay identity per action and exact resource.

    The same supplied operation id used for different resources produces
    distinct replay keys; cross-resource collisions are impossible.
    """
    resource = "|".join(str(value) for value in (
        team_preset_id, team_slot_id, scope_id, item_id, revision_id, request_id))
    return f"{operation_id}|{event_kind}|{resource}"


async def find_by_operation(
    db: AsyncSession, replay_key: str
) -> FactoryAuditEvent | None:
    """Replay protection: one accepted action or terminal event per identity."""
    return (await db.scalars(
        select(FactoryAuditEvent).where(
            FactoryAuditEvent.replay_key == replay_key,
        ).limit(1)
    )).first()


async def record_event(
    db: AsyncSession,
    *,
    event_kind: str,
    source: str,
    occurred_at: datetime,
    actor: dict[str, Any],
    action_outcome: str | None = None,
    record_kind: str = "observed",
    fact_source: str | None = None,
    fact_time: datetime | None = None,
    team_preset_id: int | None = None,
    team_slot_id: int | None = None,
    scope_id: int | None = None,
    item_id: int | None = None,
    revision_id: int | None = None,
    request_id: int | None = None,
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
    item_context_key: str | None = None,
    context_snapshot: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    operation_id: str | None = None,
    sanitized_reason: str | None = None,
    before_values: dict[str, Any] | None = None,
    after_values: dict[str, Any] | None = None,
    delivery_outcome: str | None = None,
    completion_kind: str | None = None,
    human_review_evidence: dict[str, Any] | None = None,
) -> FactoryAuditEvent:
    """Record one event inside the caller's transaction.

    The caller's transaction must include any audited change. If this insert
    raises, the caller must roll back the change. Replay protection applies
    only when an explicit operation id is supplied; legacy callers keep their
    existing guards and are never blocked by missing ledger state.
    """
    # R04: resolve parent identities from the live child before allocation,
    # so team and scope filters include item- and scope-level facts.
    team_preset_id, scope_id = await _resolve_parents(
        db, team_preset_id=team_preset_id, scope_id=scope_id, item_id=item_id)
    # C05/R01: every event site allocates the context keys of the current
    # resource lifetime. Numeric ID reuse can never reattach old history.
    if team_preset_id is not None and team_context_key is None:
        team_context_key = await context_key_for(db, "team", team_preset_id)
    if scope_id is not None and scope_context_key is None:
        scope_context_key = await context_key_for(db, "scope", scope_id)
    if item_id is not None and item_context_key is None:
        item_context_key = await context_key_for(db, "item", item_id)
    # R04: one typed event-time snapshot from the actual live resources. The
    # caller's known values win; missing labels are filled before commit.
    enriched = await event_time_snapshot(
        db, team_preset_id=team_preset_id, scope_id=scope_id, item_id=item_id)
    for key, value in (context_snapshot or {}).items():
        if value is not None or key not in enriched:
            enriched[key] = value
    projected_snapshot = project_snapshot(enriched)
    projected_before = allowlist_values(before_values)
    projected_after = allowlist_values(after_values)
    replay_key = None
    if operation_id:
        # R09: the replay identity binds the operation to immutable resource
        # lifetimes (context keys), not to reusable numeric IDs.
        replay_key = replay_key_for(
            operation_id, event_kind, team_preset_id=team_context_key,
            team_slot_id=team_slot_id, scope_id=scope_context_key, item_id=item_context_key,
            revision_id=revision_id, request_id=request_id)
        existing = await find_by_operation(db, replay_key)
        if existing is not None:
            # T02: the complete stable evidence payload. Only observation-time
            # and runtime fields (occurred_at, the actor's session and the
            # runtime observation labels) may differ in an exact retry.
            canonical = _canonical_fact(
                action_outcome=action_outcome, delivery_outcome=delivery_outcome,
                completion_kind=completion_kind, fact_source=fact_source,
                fact_time=_naive(fact_time), source=source,
                actor_kind=actor["actor_kind"], actor_reference=actor.get("actor_reference"),
                actor_member_id=actor.get("actor_member_id"),
                before_values=projected_before, after_values=projected_after,
                evidence=_stable_evidence(projected_snapshot),
                human_review_evidence=project_review_evidence(human_review_evidence))
            if canonical != _canonical_fact(
                    action_outcome=existing.action_outcome,
                    delivery_outcome=existing.delivery_outcome,
                    completion_kind=existing.completion_kind,
                    fact_source=existing.fact_source,
                    fact_time=_naive(existing.fact_time), source=existing.source,
                    actor_kind=existing.actor_kind, actor_reference=existing.actor_reference,
                    actor_member_id=existing.actor_member_id,
                    before_values=existing.before_values,
                    after_values=existing.after_values,
                    evidence=_stable_evidence(existing.context_snapshot),
                    human_review_evidence=existing.human_review_evidence):
                raise ReplayConflictError(f"replay conflict for {event_kind}")
            return existing
    event = FactoryAuditEvent(
        occurred_at=occurred_at,
        event_kind=event_kind,
        source=source,
        record_kind=record_kind,
        fact_source=fact_source,
        fact_time=fact_time,
        actor_kind=actor["actor_kind"],
        actor_member_id=actor.get("actor_member_id"),
        actor_session_id=actor.get("actor_session_id"),
        actor_reference=actor.get("actor_reference"),
        team_preset_id=team_preset_id,
        team_slot_id=team_slot_id,
        scope_id=scope_id,
        item_id=item_id,
        revision_id=revision_id,
        request_id=request_id,
        team_context_key=team_context_key,
        scope_context_key=scope_context_key,
        item_context_key=item_context_key,
        # C10: every stored value passes a typed, bounded projection.
        context_snapshot=projected_snapshot,
        correlation_id=correlation_id,
        operation_id=operation_id,
        replay_key=replay_key,
        sanitized_reason=sanitize_reason(sanitized_reason),
        before_values=projected_before,
        after_values=projected_after,
        action_outcome=action_outcome,
        delivery_outcome=delivery_outcome,
        completion_kind=completion_kind,
        human_review_evidence=project_review_evidence(human_review_evidence),
    )
    # A failed insert, including a concurrent duplicate on the unique replay
    # key, propagates. The caller owns the transaction: the audited change
    # must never commit when its fact did not, and a duplicate winner never
    # stands in for a change that this transaction lost.
    db.add(event)
    await db.flush()
    return event


async def record_observation(db: AsyncSession, **fields: Any) -> FactoryAuditEvent | None:
    """C09: record a refusal or uncertainty in its own observation transaction.

    Use this only after the observed action's own transaction has ended.
    Services roll back their guarded writes before they refuse. Pending ORM
    changes are rolled back here and are never committed with the
    observation. A clean session is not rolled back, so rows the caller still
    reads stay loaded. Observation failure never masks the original result
    and never replays the action.
    """
    if db.new or db.dirty or db.deleted:
        try:
            await db.rollback()
        except Exception:
            pass
    # A failed earlier flush leaves the transaction unusable without pending
    # objects; one retry after rollback records the observation then.
    for attempt in range(2):
        try:
            event = await record_event(db, **fields)
            await db.commit()
            return event
        except Exception:
            try:
                await db.rollback()
            except Exception:
                return None
            if attempt:
                return None
    return None


async def record_observed_snapshot(
    db: AsyncSession,
    *,
    event_kind: str,
    source: str,
    observed_at: datetime,
    actor: dict[str, Any],
    fact_source: str | None = None,
    fact_time: datetime | None = None,
    team_preset_id: int | None = None,
    scope_id: int | None = None,
    item_id: int | None = None,
    context_snapshot: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    after_values: dict[str, Any] | None = None,
    operation_id: str | None = None,
) -> FactoryAuditEvent:
    """A13/A14: record imported current state as an observed snapshot.

    The import observation time is the event occurrence time. A reliable
    external fact keeps its own source and fact time distinct from the
    import time. Unknown historical times remain unavailable and are never
    inferred from generic row timestamps. C12: an operation identity makes
    a repeated import return the existing snapshot.
    """
    return await record_event(
        db,
        event_kind=event_kind,
        source=source,
        occurred_at=observed_at,
        actor=actor,
        record_kind="observed_snapshot",
        fact_source=fact_source,
        fact_time=fact_time,
        team_preset_id=team_preset_id,
        scope_id=scope_id,
        item_id=item_id,
        context_snapshot=context_snapshot,
        correlation_id=correlation_id or operation_id,
        operation_id=operation_id,
        after_values=after_values,
        action_outcome="applied",
    )


# C12: the stable forward-coverage marker. Its migration row time is the
# instrumentation start; it never moves when events are added or removed.
COVERAGE_MARKER = "p05_factory_audit_coverage"

_IMPORT_SOURCE = "factory_audit_service.import_observed_state"


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


async def coverage_marker_time(conn: Any) -> datetime | None:
    """Read the installed coverage marker from a session or connection."""
    table = (await conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table'"
        " AND name = 'deck_compat_migrations'"))).first()
    if table is None:
        return None
    value = (await conn.execute(text(
        "SELECT applied_at FROM deck_compat_migrations WHERE name = :name"),
        {"name": COVERAGE_MARKER})).scalar_one_or_none()
    return _as_datetime(value)


async def install_forward_coverage(
    conn: Any, *, installed_at: datetime | None = None
) -> datetime:
    """C12: install the coverage marker and import observed state once.

    Called from the SQLite compatibility migrations. A second run finds the
    marker and changes nothing. The import records the persisted state of
    each existing work item as an observed snapshot at the marker time; it
    never reconstructs history or infers fact times from row timestamps.
    """
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS deck_compat_migrations ("
        "name VARCHAR PRIMARY KEY, applied_at DATETIME NOT NULL)"))
    existing = await coverage_marker_time(conn)
    if existing is not None:
        return existing
    marker = (installed_at or datetime.utcnow()).replace(tzinfo=None)
    await conn.execute(text(
        "INSERT OR IGNORE INTO deck_compat_migrations (name, applied_at)"
        " VALUES (:name, :applied_at)"),
        {"name": COVERAGE_MARKER, "applied_at": marker})
    marker = await coverage_marker_time(conn) or marker
    await import_observed_state(conn, observed_at=marker)
    return marker


async def import_observed_state(conn: Any, *, observed_at: datetime) -> int:
    """C12: one idempotent observed snapshot per existing work item."""
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    from app.models.database import GithubWorkItem

    actor = derive_actor(actor_kind="system")
    imported = 0
    # The session joins the migration transaction; the caller commits it.
    session = _AsyncSession(bind=conn, expire_on_commit=False, autoflush=False)
    try:
        rows = (await session.execute(select(
            GithubWorkItem.id, GithubWorkItem.scope_id, GithubWorkItem.issue_number,
            GithubWorkItem.issue_type, GithubWorkItem.pr_number,
            GithubWorkItem.dispatch_status, GithubWorkItem.attempt_phase,
            GithubWorkItem.retry_count, GithubWorkItem.diagnostic_retry_count,
            GithubWorkItem.active_scope_revision,
        ).order_by(GithubWorkItem.id))).all()
        for row in rows:
            await record_observed_snapshot(
                session,
                event_kind="work_state_import",
                source=_IMPORT_SOURCE,
                observed_at=observed_at,
                actor=actor,
                fact_source="github_work_items persisted state",
                fact_time=None,
                scope_id=row.scope_id,
                item_id=row.id,
                context_snapshot={"issue_number": row.issue_number,
                                  "issue_type": row.issue_type,
                                  "pr_number": row.pr_number},
                after_values={
                    "dispatch_status": row.dispatch_status,
                    "attempt_phase": row.attempt_phase,
                    "retry_count": row.retry_count,
                    "diagnostic_retry_count": row.diagnostic_retry_count,
                    "active_scope_revision": row.active_scope_revision,
                },
                operation_id=f"{COVERAGE_MARKER}:item:{row.id}",
            )
            imported += 1
        await session.flush()
    finally:
        await session.close()
    return imported


def launch_attempt_key(item_id: int, launch_id: int | None) -> str:
    """C12: the non-secret identity of one launched attempt."""
    return f"item:{item_id}:launch:{launch_id}"


async def record_retry_charge(
    db: AsyncSession,
    *,
    item_id: int,
    scope_id: int | None,
    revision_id: int | None,
    retry_class: str,
    counter_value: int,
    reason_code: str,
    source: str,
) -> FactoryAuditEvent:
    """C12: evidence for one charged retry, in the charge's transaction.

    The counter stays authoritative; this fact only classifies the charge as
    an implementation or diagnostic retry. An audit-write failure surfaces
    and rolls back the charge, like other in-transaction facts.
    """
    if retry_class not in {"implementation", "diagnostic"}:
        raise ValueError(f"unsupported retry class: {retry_class}")
    counter = "diagnostic_retry_count" if retry_class == "diagnostic" else "retry_count"
    return await record_event(
        db,
        event_kind="retry_charge",
        source=source,
        occurred_at=datetime.utcnow(),
        actor=derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler"),
        scope_id=scope_id,
        item_id=item_id,
        revision_id=revision_id,
        after_values={counter: counter_value},
        context_snapshot={"retry_class": retry_class},
        sanitized_reason=reason_code,
        action_outcome="applied",
    )


def validated_review_evidence(evidence: dict | None) -> bool:
    """A33/C03: only validated independent review facts count.

    The evidence must name the review fact kind, the exact design artifact
    and version, an independent human actor (not the shared operator
    credential) and its review source. Absent, JSON-null, empty or partial
    evidence never counts.
    """
    if not isinstance(evidence, dict) or not evidence:
        return False
    if evidence.get("fact_kind") != "human_review_acceptance":
        return False
    if not evidence.get("artifact") or not evidence.get("version"):
        return False
    actor = evidence.get("actor")
    if not isinstance(actor, str) or actor in {"shared-operator-credential", "operator"}:
        return False
    # R06: independence is never inferred from a non-operator string. The
    # evidence must attest a human actor and independence, and an agent
    # member reference never qualifies.
    if actor.startswith("member:") or evidence.get("actor_kind") != "human":
        return False
    if evidence.get("independent") is not True:
        return False
    if not evidence.get("source"):
        return False
    # A32: a declared rejection is stored but never counts. Older evidence
    # without a decision field is an acceptance record by its fact kind.
    if evidence.get("decision", "accepted") != "accepted":
        return False
    return True


class ReviewDeclarationRefused(ValueError):
    """A32: a declaration does not bind to a recorded attempt and version."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_ATTEMPT_KEY = re.compile(r"^item:(\d+):launch:(\d+|None):revision:(\d+|None)$")
_ARTIFACT = re.compile(r"^([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)/pull/(\d+)$")


def _optional_int(value: str) -> int | None:
    return None if value == "None" else int(value)


async def record_review_acceptance(
    db: AsyncSession, declaration: Any, *, recording_actor: dict[str, Any]
) -> tuple[FactoryAuditEvent, bool, bool]:
    """A32: record one protected acceptance declaration in the caller's transaction.

    The declaration binds to an immutable attempt of the item, to the pull
    request that attempt recorded, and to a head version that the server
    recorded for that attempt. A changed or unrelated version is refused.
    The recording actor (the operator credential) stays separate from the
    attributed reviewer; human identity and independence are recorded only
    as declared by the trusted source, never derived from a credential or
    account type. For a design item, an accepted, independent, human
    declaration also establishes delivery of that exact version, before or
    after a merge. It never changes work state, approvals or merges.

    Returns (review event, counted, delivery established). Raises
    ReviewDeclarationRefused or ReplayConflictError.
    """
    from app.models.database import GithubWorkItem, TeamGithubScope

    item = await db.get(GithubWorkItem, declaration.work_item_id)
    if item is None:
        raise ReviewDeclarationRefused("work_item_not_found")
    attempt_match = _ATTEMPT_KEY.match(declaration.attempt)
    if attempt_match is None or int(attempt_match.group(1)) != item.id:
        raise ReviewDeclarationRefused("attempt_unrelated")
    artifact_match = _ARTIFACT.match(declaration.artifact)
    scope = await db.get(TeamGithubScope, item.scope_id)
    if (artifact_match is None or scope is None
            or (artifact_match.group(1), artifact_match.group(2))
            != (scope.repo_owner, scope.repo_name)):
        raise ReviewDeclarationRefused("artifact_unrelated")
    pr_number = int(artifact_match.group(3))
    launch_id = _optional_int(attempt_match.group(2))
    revision_id = _optional_int(attempt_match.group(3))

    def _bindings() -> tuple[bool, bool, str | None]:
        current = current_attempt == declaration.attempt
        return (current, current and item.pr_number == pr_number,
                item.verification_head_sha if current else None)

    current_attempt, _, _ = await item_attempt(db, item)
    facts = (await db.scalars(select(FactoryAuditEvent).where(
        FactoryAuditEvent.item_id == item.id))).all()
    attempt_facts = [
        fact for fact in facts
        if isinstance(fact.context_snapshot, dict)
        and fact.context_snapshot.get("attempt") == declaration.attempt]
    is_current, current_artifact, current_head = _bindings()
    if not is_current and not attempt_facts:
        raise ReviewDeclarationRefused("attempt_unrelated")
    artifact_facts = [
        fact for fact in attempt_facts
        if fact.context_snapshot.get("artifact") == declaration.artifact]
    if not current_artifact and not artifact_facts:
        raise ReviewDeclarationRefused("artifact_unrelated")
    recorded = {fact.context_snapshot.get("artifact_version") for fact in artifact_facts}
    if declaration.version not in recorded and current_head != declaration.version:
        if current_artifact and current_head is not None:
            raise ReviewDeclarationRefused("version_changed")
        raise ReviewDeclarationRefused("version_unrelated")

    # Recheck the current binding at write time when it was used.
    if declaration.version not in recorded:
        refreshed = (await db.scalars(select(GithubWorkItem).where(
            GithubWorkItem.id == item.id).execution_options(populate_existing=True))).first()
        if refreshed is None:
            raise ReviewDeclarationRefused("version_changed")
        item = refreshed
        current_attempt, _, _ = await item_attempt(db, item)
        _, current_artifact, current_head = _bindings()
        if not current_artifact or current_head != declaration.version:
            raise ReviewDeclarationRefused("version_changed")

    occurred_at = declaration.occurred_at
    if occurred_at.tzinfo is not None:
        occurred_at = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    fact_source = sanitize_text(f"{declaration.source_kind}:{declaration.source_ref}")
    evidence = project_review_evidence({
        "fact_kind": "human_review_acceptance",
        "artifact": declaration.artifact,
        "version": declaration.version,
        "actor": declaration.reviewer,
        "actor_kind": declaration.reviewer_kind,
        "independent": declaration.independent,
        "decision": declaration.decision,
        "source": fact_source,
        "declared_by": recording_actor.get("actor_reference"),
    })
    operation_id = f"review_acceptance:{declaration.declaration_id}"
    snapshot = {"attempt": declaration.attempt, "artifact": declaration.artifact,
                "artifact_version": declaration.version,
                "launch_attempt": launch_attempt_key(item.id, launch_id)}
    existing = (await db.scalars(select(FactoryAuditEvent).where(
        FactoryAuditEvent.operation_id == operation_id,
        FactoryAuditEvent.event_kind == "review_acceptance_declared",
    ).limit(1))).first()
    if existing is not None:
        same = (existing.item_id == item.id
                and existing.human_review_evidence == evidence
                and existing.fact_time == occurred_at
                and (existing.context_snapshot or {}).get("attempt") == declaration.attempt)
        if not same:
            raise ReplayConflictError("replay conflict for review_acceptance_declared")
        counted = validated_review_evidence(existing.human_review_evidence)
        return existing, counted, counted and item.issue_type == "design"
    event = await record_event(
        db, event_kind="review_acceptance_declared", source="operator_declaration",
        occurred_at=datetime.utcnow(), actor=recording_actor, record_kind="declared",
        fact_source=fact_source, fact_time=occurred_at, item_id=item.id,
        revision_id=revision_id, context_snapshot=snapshot, action_outcome="applied",
        operation_id=operation_id, correlation_id=operation_id,
        sanitized_reason=f"review declaration: {declaration.decision}",
        human_review_evidence=evidence)
    counted = validated_review_evidence(evidence)
    delivered = counted and item.issue_type == "design"
    if delivered:
        await record_delivery_fact(
            db, item_id=item.id, revision_id=revision_id, scope_id=item.scope_id,
            delivery_outcome="delivered", completion_kind="design_artifact_accepted",
            fact_source=fact_source, fact_time=occurred_at, artifact=declaration.artifact,
            actor=recording_actor, attempt=declaration.attempt,
            launch_attempt=launch_attempt_key(item.id, launch_id),
            snapshot={"artifact_version": declaration.version},
            source="operator_declaration")
    return event, counted, delivered


async def record_delivery_fact(
    db: AsyncSession,
    *,
    item_id: int | None,
    revision_id: int | None = None,
    scope_id: int | None = None,
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
    item_context_key: str | None = None,
    delivery_outcome: str,
    completion_kind: str,
    fact_source: str,
    fact_time: datetime | None,
    artifact: str | None = None,
    actor: dict[str, Any] | None = None,
    attempt: str | None = None,
    launch_attempt: str | None = None,
    snapshot: dict[str, Any] | None = None,
    source: str | None = None,
) -> FactoryAuditEvent:
    """A28-A35: record one sourced delivery outcome fact per tracked attempt.

    Later facts reconcile the classification without double-counting
    delivery: the non-secret operation identity binds the fact to the
    attempt and artifact, so repeated evidence returns the same event.
    ``attempt`` is a stable non-secret attempt identity; a later attempt on
    the same item therefore records its own fact. Raw dispatch state is
    never rewritten. Merge evidence and independent human review stay
    distinct fields. C12: ``launch_attempt`` binds the terminal boundary to
    the launch that started the attempt, for same-attempt durations.
    """
    # R03: the operation identity includes the fact itself, so a repeated
    # identical fact deduplicates while later, different evidence for the same
    # attempt and artifact is appended, never suppressed.
    attempt_identity = attempt or f"item:{item_id}"
    # T02: the immutable fact identity also names the exact version, the
    # reliable fact time and the observing call site. Distinct versions and
    # times append; two call sites observing one merge record two facts that
    # reduce to one result per attempt.
    version = (snapshot or {}).get("artifact_version") or "unversioned"
    when = _naive(fact_time).isoformat() if fact_time is not None else "unknown"
    operation_id = (f"delivery:{attempt_identity}:{artifact or 'attempt'}:"
                    f"{delivery_outcome}:{completion_kind}:{fact_source}:"
                    f"{version}:{when}:{source or fact_source}")
    context_snapshot: dict[str, Any] = dict(snapshot or {})
    context_snapshot["attempt"] = attempt_identity
    context_snapshot["fact_source"] = fact_source
    if artifact:
        context_snapshot["artifact"] = artifact
    if launch_attempt:
        context_snapshot["launch_attempt"] = launch_attempt
    return await record_event(
        db,
        event_kind="delivery_evidence",
        source=source or fact_source,
        # R02/F09: the observation time is the occurrence of this record; the
        # sourced fact keeps its own source and time, and an unknown fact time
        # stays null.
        occurred_at=datetime.utcnow(),
        fact_source=fact_source,
        fact_time=fact_time,
        actor=actor or derive_actor(actor_kind="scheduler", scheduler="github_watcher"),
        item_id=item_id,
        revision_id=revision_id,
        scope_id=scope_id,
        team_context_key=team_context_key,
        scope_context_key=scope_context_key,
        item_context_key=item_context_key,
        context_snapshot=context_snapshot,
        delivery_outcome=delivery_outcome,
        completion_kind=completion_kind,
        action_outcome="applied",
        operation_id=operation_id,
        correlation_id=operation_id,
        sanitized_reason=f"delivery fact: {completion_kind}",
    )


async def current_delivery_outcome(db: AsyncSession, item_id: int) -> str | None:
    """One current outcome per tracked attempt from its recorded facts.

    Delivered is retained through routine closure. Repeated delivered facts
    never change the count. A later non-delivery fact does not downgrade a
    proven delivery.
    """
    rows = (await db.scalars(
        select(FactoryAuditEvent).where(
            FactoryAuditEvent.item_id == item_id,
            FactoryAuditEvent.event_kind == "delivery_evidence",
        ).order_by(FactoryAuditEvent.occurred_at.asc(), FactoryAuditEvent.id.asc())
    )).all()
    outcome = None
    for row in rows:
        if row.delivery_outcome == "delivered":
            return "delivered"
        outcome = row.delivery_outcome
    return outcome


async def instrumentation_start(db: AsyncSession) -> datetime | None:
    """C12: the installed forward-coverage marker, or None when absent.

    The first event is never the coverage start. Without the marker no
    interval is covered; missing intervals stay unavailable rather than
    reconstructed.
    """
    return await coverage_marker_time(db)
