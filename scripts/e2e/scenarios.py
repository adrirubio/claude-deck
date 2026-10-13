"""Synthetic E2E scenarios for the Deck v3.1 design reference.

Each scenario names the design-reference state it serves. IDs are fixed, so a
journey can open ``/work/2`` or ``/teams/1``. Journeys should still find rows
by their seeded names where they can.

| Scenario | Rows |
|---|---|
| Needs you | Release crew: item #102 waits for human review (PR #202). |
| Idle and paused | Quiet team: autonomy off, scope intake disabled, no open work. |
| Item that needs attention | Release crew: item #101 is escalated. |
| Refused agent requests | Three rejected continuation requests on item #101. |
| 8-member team | Release crew has eight slots; four have live fake panes. |
| Deleted team with history | Retired crew: audit events kept after the team is deleted. |
| Mail with unacknowledged messages | Director and member messages without an ack. |
| Locked Audit | Audit events exist; the browser has no Director key. |
| Lane C (#604) | #516 a live team named like the deleted one; #520 a second group of refused requests. |
| Lane G (#606) | #527 mail senders, #528 lease and reminders, #535 active revision, #549 supervisor. |
| One agent, one state (#540) | F2 Frontend: a live fake pane, a live MCP session and an observation 3 h old. |
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from seed import SEED_NOW, Seeder, at, digest, sha

RELEASE_TEAM = 1
QUIET_TEAM = 2
RETIRED_TEAM = 3

RELEASE_SCOPE = 1
QUIET_SCOPE = 2
RETIRED_SCOPE = 3

# Item IDs (database) and issue numbers (synthetic GitHub).
ITEM_ATTENTION = 1    # issue 101, escalated
ITEM_REVIEW = 2       # issue 102, awaiting human review, PR 202
ITEM_ACTIVE = 3       # issue 103, dispatched
ITEM_MERGED = 4       # issue 104, merged, PR 199
ITEM_QUEUED = 5       # issue 105, pending
ITEM_RETIRED = 6      # issue 7 in the retired scope

# #540: the idle agent with an old observation and a live MCP session.
IDLE_AGENT_SLOT = 5   # "F2 Frontend"; it also has a live fake pane

# One seeded moment shown on Teams, Work and Audit (#521 journey).
SHARED_MOMENT = SEED_NOW - timedelta(hours=3, minutes=17)

RELEASE_SLOTS: list[dict[str, Any]] = [
    {"id": 1, "name": "L1 Leader", "role": "leader", "provider": "claude-code", "color": "purple"},
    {"id": 2, "name": "B1 Backend", "role": "implementer", "provider": "claude-code", "color": "blue"},
    {"id": 3, "name": "B2 Backend", "role": "implementer", "provider": "claude-code", "color": "cyan"},
    {"id": 4, "name": "F1 Frontend", "role": "implementer", "provider": "codex-cli", "color": "green"},
    {"id": 5, "name": "F2 Frontend", "role": "implementer", "provider": "claude-code", "color": "amber"},
    {"id": 6, "name": "D1 Docs", "role": "implementer", "provider": "claude-code", "color": "slate"},
    {"id": 7, "name": "E1 E2E", "role": "implementer", "provider": "claude-code", "color": "red"},
    {"id": 8, "name": "V1 Verifier", "role": "reviewer", "provider": "claude-code", "color": "blue"},
]
QUIET_SLOTS: list[dict[str, Any]] = [
    {"id": 9, "name": "Q1 Leader", "role": "leader", "provider": "claude-code", "color": "purple"},
    {"id": 10, "name": "Q2 Implementer", "role": "implementer", "provider": "claude-code", "color": "green"},
]
RETIRED_SLOTS: list[dict[str, Any]] = [
    {"id": 11, "name": "R1 Leader", "role": "leader", "provider": "claude-code", "color": "slate"},
]
# Slots that get a live fake pane in the instance's tmux server.
LIVE_SLOTS = (1, 2, 3, 5)


def session_uuid(slot_id: int) -> str:
    return f"00000000-0000-4000-8000-{slot_id:012d}"


def make_repo(root: Path, name: str) -> Path:
    path = root / "repos" / name
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def preset(s: Seeder, preset_id: int, name: str, description: str, *, autonomy: bool,
           leader_slot: int | None) -> None:
    s.insert(
        "agent_team_presets", id=preset_id, name=name, description=description,
        created_by="e2e-seed", created_at=at(days=20), updated_at=at(days=1),
        autonomy_enabled=int(autonomy), leader_slot_id=leader_slot,
    )


def slots(s: Seeder, preset_id: int, rows: list[dict[str, Any]], repo: Path) -> None:
    for position, slot in enumerate(rows):
        s.insert(
            "agent_team_slots", id=slot["id"], preset_id=preset_id, position=position,
            display_name=slot["name"], provider=slot["provider"],
            repo_id=digest(str(repo))[:16], repo_path=str(repo), repo_name=repo.name,
            role=slot["role"], charter=f"Synthetic charter for {slot['name']}.",
            ui_color=slot["color"], bootstrap_prompt=None, controlled_language_enabled=1,
            launch_mode="plain", launch_options={"session_id": session_uuid(slot["id"])},
            area_labels=None, expertise=None, enabled=1,
            created_at=at(days=20), updated_at=at(days=1),
        )


def delivery_policy() -> dict[str, Any]:
    """A scope policy, validated by the API schema so the seed cannot drift."""
    from app.models.schemas import FactoryDeliveryPolicy

    policy = {"required_checks": [{"name": "e2e", "app_slug": "github-actions"}]}
    return FactoryDeliveryPolicy.model_validate(policy).model_dump(mode="json")


def scope(s: Seeder, scope_id: int, preset_id: int, owner: str, name: str, repo: Path, *,
          enabled: bool) -> None:
    s.insert(
        "team_github_scopes", id=scope_id, preset_id=preset_id, repo_owner=owner,
        repo_name=name, repo_path=str(repo), dispatch_label="deck-ready",
        design_label="deck-design", merge_policy="human",
        delivery_policy=delivery_policy(),
        delivery_policy_revision=1, max_approval_rounds=3, max_concurrent_dispatched=3,
        max_verification_retries=2, max_auto_merges_per_day=5, base_ref="origin/main",
        builds_out_of_tree=0, build_dir_template="build", build_command_hint=None,
        max_build_parallelism=2, github_auth_mode="token", github_app_installation_id=None,
        continuation_enabled=1, max_continuation_revisions=6,
        max_continuation_failed_heads=8, max_failed_heads_per_revision=2,
        max_scope_paths=32, max_scope_commands=16, enabled=int(enabled),
        last_polled_at=at(minutes=2), created_at=at(days=20), updated_at=at(days=1),
    )


def item(s: Seeder, item_id: int, scope_id: int, owner: str, repo: str, number: int,
         title: str, status: str, *, owner_slot: int | None = None, pr: int | None = None,
         escalation: str | None = None, note: str | None = None, updated: str | None = None,
         dispatched: str | None = None) -> None:
    nonce = f"seed{item_id:012d}" if owner_slot else None
    s.insert(
        "github_work_items", id=item_id, scope_id=scope_id, delivery_policy=None,
        delivery_policy_revision=None, issue_number=number, issue_title=title,
        issue_url=f"https://github.com/{owner}/{repo}/issues/{number}",
        github_updated_at=at(hours=6), issue_type="code", dispatch_status=status,
        pending_reason=None, launch_id=None, owner_slot_id=owner_slot,
        routing_method="label" if owner_slot else None, handoff_state=None,
        handoff_target_slot_id=None, approval_round_count=1 if owner_slot else 0,
        pr_number=pr, retry_count=0,
        last_verified_sha=sha(f"verified-{item_id}") if pr else None,
        verification_head_sha=None, verification_started_at=None,
        dispatched_at=dispatched or (at(days=2) if owner_slot else None),
        ack_received_at=at(days=2, hours=-1) if owner_slot else None,
        last_nudge_at=None, retry_requested_at=None, brief_delivery_nudge_at=None,
        brief_delivery_nudge_count=None, brief_message_id=None,
        ack_approver_member_id=1 if owner_slot else None, ack_evidence_message_id=None,
        dispatch_nonce=nonce, ack_enforcement_epoch=None,
        ack_approval_round=1 if owner_slot else None,
        dispatch_head_ref=f"deck/slot-{owner_slot}/issue-{number}-{nonce}" if owner_slot else None,
        dispatch_base_ref="origin/main" if owner_slot else None,
        escalation_reason=escalation, status_note=note, auto_merged_at=None,
        active_scope_revision=0, attempt_phase="implementation", diagnostic_retry_count=0,
        diagnostic_last_verified_sha=None, continuation_nudged_at=None,
        continuation_activated_at=None, created_at=at(days=3), updated_at=updated or at(hours=1),
    )


def member(s: Seeder, member_id: int, preset_id: int, slot: dict[str, Any], repo: Path) -> None:
    s.insert(
        "mail_team_members", id=member_id, identity_key=f"slot:{preset_id}:{slot['id']}:e2e-seed",
        repo_id=digest(str(repo))[:16], repo_path=str(repo), repo_name=repo.name,
        display_name=slot["name"], participant_kind="team_slot", team_preset_id=preset_id,
        team_slot_id=slot["id"], role=slot["role"], charter=None,
        last_inbox_checked_at=at(hours=2), created_at=at(days=20), updated_at=at(hours=2),
    )


def message(s: Seeder, message_id: int, *, sender: int | None, recipient: int | None,
            subject: str, body: str, kind: str = "message", thread: int | None = None,
            request_status: str | None = None, sent: str, read: str | None = None,
            acked: str | None = None, payload: dict | None = None,
            sender_type_director: bool = False) -> None:
    s.insert(
        "mail_messages", id=message_id, thread_root_id=thread, kind=kind,
        sender_member_id=sender, sender_actor_id=None, approval_round=None, decision=None,
        sender_type="member" if sender is not None else "director" if sender_type_director else "system",
        audience_type="member" if recipient else "team",
        audience_id=str(recipient) if recipient else str(RELEASE_TEAM),
        recipient_member_id=recipient, subject=subject, body_markdown=body,
        payload=payload if payload is not None else ({"sender_type": "director"} if sender_type_director else None),
        request_status=request_status, delivery_key=None, created_at=sent,
    )
    if recipient:
        s.insert(
            "mail_receipts", message_id=message_id, member_id=recipient, read_at=read,
            acked_at=acked, created_at=sent,
        )


def seed_core(s: Seeder, root: Path) -> None:
    sample = make_repo(root, "sample-app")
    quiet = make_repo(root, "quiet-lib")
    retired = make_repo(root, "retired-site")

    # Needs you, item that needs attention, 8-member team.
    preset(s, RELEASE_TEAM, "Release crew", "Ship the sample-app 2.0 release.",
           autonomy=True, leader_slot=1)
    slots(s, RELEASE_TEAM, RELEASE_SLOTS, sample)
    scope(s, RELEASE_SCOPE, RELEASE_TEAM, "example-org", "sample-app", sample, enabled=True)
    item(s, ITEM_ATTENTION, RELEASE_SCOPE, "example-org", "sample-app", 101,
         "Add the CSV export button", "escalated", owner_slot=2,
         escalation="owner_idle_timeout", note="The owner stopped responding.")
    item(s, ITEM_REVIEW, RELEASE_SCOPE, "example-org", "sample-app", 102,
         "Fix the settings page layout", "awaiting_human_review", owner_slot=3, pr=202,
         note="Ready for human review.")
    item(s, ITEM_ACTIVE, RELEASE_SCOPE, "example-org", "sample-app", 103,
         "Document the import format", "dispatched", owner_slot=5,
         updated=SHARED_MOMENT.isoformat(sep=" "),
         dispatched=SHARED_MOMENT.isoformat(sep=" "))
    item(s, ITEM_MERGED, RELEASE_SCOPE, "example-org", "sample-app", 104,
         "Rename the sync command", "merged", owner_slot=2, pr=199)
    item(s, ITEM_QUEUED, RELEASE_SCOPE, "example-org", "sample-app", 105,
         "Add keyboard shortcuts", "pending")

    # Idle and paused.
    preset(s, QUIET_TEAM, "Quiet team", "Maintain quiet-lib.", autonomy=False, leader_slot=9)
    slots(s, QUIET_TEAM, QUIET_SLOTS, quiet)
    scope(s, QUIET_SCOPE, QUIET_TEAM, "example-org", "quiet-lib", quiet, enabled=False)

    # Deleted team with history: deleted after its audit events (seed_history).
    preset(s, RETIRED_TEAM, "Retired crew", "Publish the old website.", autonomy=False,
           leader_slot=11)
    slots(s, RETIRED_TEAM, RETIRED_SLOTS, retired)
    scope(s, RETIRED_SCOPE, RETIRED_TEAM, "example-org", "retired-site", retired, enabled=False)
    item(s, ITEM_RETIRED, RETIRED_SCOPE, "example-org", "retired-site", 7,
         "Publish the launch page", "merged", owner_slot=11, pr=8)

    # Mail with unacknowledged messages. Member IDs equal slot IDs.
    for slot in RELEASE_SLOTS:
        member(s, slot["id"], RELEASE_TEAM, slot, sample)
    for slot in QUIET_SLOTS:
        member(s, slot["id"], QUIET_TEAM, slot, quiet)
    message(s, 1, sender=None, recipient=2, subject="Autonomous dispatch: issue #101",
            body="Synthetic dispatch brief for issue #101.", sent=at(days=2),
            read=at(days=2), acked=at(days=2),
            payload={"kind": "github_dispatch_assignment", "work_item_id": ITEM_ATTENTION,
                     "issue_number": 101, "scope_id": RELEASE_SCOPE})
    message(s, 2, sender=None, recipient=2, subject="Progress check: issue #101",
            body="No PR yet for issue #101. Are you still making progress?",
            sent=at(hours=5),
            payload={"kind": "github_dispatch_idle_nudge", "work_item_id": ITEM_ATTENTION,
                     "issue_number": 101})
    message(s, 3, sender=3, recipient=1, subject="Plan for #102",
            body="Please approve the plan for #102.", kind="context_request",
            request_status="pending", sent=at(hours=4), read=at(hours=4))
    message(s, 4, sender=1, recipient=8, subject="Review PR #202",
            body="Please review PR #202 at its current head.", sent=at(hours=2))
    message(s, 5, sender=5, recipient=1, subject="Handoff: #103 docs",
            body="Synthetic handoff summary.", kind="handoff", request_status="pending",
            sent=at(minutes=50))

    # One agent, one state (#540): slot 5 has a live fake pane (start_panes),
    # a live MCP session and an old observation. "Live" is relative to the
    # real clock: SEED_NOW can be up to an hour old, and Deck treats an MCP
    # heartbeat older than 3600 s as offline. Only this row uses the real clock.
    heartbeat = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)).isoformat(sep=" ")
    idle = next(slot for slot in RELEASE_SLOTS if slot["id"] == IDLE_AGENT_SLOT)
    for session_id, source, key, target, seen, status in (
        (1, "mcp", "mcp:e2e-seed-idle-agent", None, heartbeat, "connected"),
        (2, "observed", f"observed:deck-e2e-{IDLE_AGENT_SLOT}:0.0",
         f"deck-e2e-{IDLE_AGENT_SLOT}:0.0", at(hours=3), "observed"),
    ):
        s.insert(
            "mail_agent_sessions", id=session_id, member_id=IDLE_AGENT_SLOT,
            provider=idle["provider"], source=source, session_key=key, cwd=str(sample),
            tmux_target=target, pane_id=None, pid=None, team_preset_id=RELEASE_TEAM,
            team_slot_id=IDLE_AGENT_SLOT,
            capability_token_hash=digest("e2e-seed-idle-agent") if source == "mcp" else None,
            bound_pane_pid=None, bound_pane_proc_start=None, closed_at=None,
            wake_enabled=1, mailbox_status=status, activity=None, last_seen_at=seen,
            created_at=at(days=1),
        )

    # Backlog coordination for the release scope (observed state only).
    s.insert(
        "github_backlog_coordination", scope_id=RELEASE_SCOPE, enabled=1,
        issue_numbers=[101, 102, 103, 104, 105], fallback_seconds=1800,
        max_daily_requests=12, version=1, policy_revision=1, assessment_revision=0,
        last_assessment_token_hash=None, generation=1, request_sequence=0,
        requested_generation=None, budget_day=SEED_NOW.date().isoformat(), daily_requests=0,
        snapshot_requests=0, snapshot_hash=None, snapshot=None, assessments=[],
        assessed_generation=None, assessed_sequence=None, leader_session_id=None,
        message_id=None, last_polled_at=at(minutes=2), last_requested_at=None,
        last_assessed_at=None, error_code=None,
    )
    seed_lane_g(s, root, sample)
    seed_lane_c(s)


# Lane G (#606): states for the backend journeys in frontend/e2e/lane-g/.
# They attach to the existing items, so the Overview count stays "5 matching".
LANE_G_LEASE_TOKEN = "e2e-seed-lease-token-0001"
LANE_G_REMINDERS = 4          # capped workspace-release reminders (#528)
LANE_G_SUPERVISOR_ACTOR = 1   # external actor bound to Release crew (#549)


def seed_lane_g(s: Seeder, root: Path, sample: Path) -> None:
    # #527: a message that the Director wrote. Messages 1 and 2 come from the
    # scheduler (their payload kinds), so they must not show "Director".
    message(s, 6, sender=None, recipient=2, subject="Director note: keep #101 small",
            body="Please keep the CSV export change small.", sent=at(hours=1),
            payload={}, sender_type_director=True)

    # #528: merged item #104 still holds a workspace; its owner (B1 Backend)
    # has not answered the release reminders.
    workspace = root / "workspaces" / "dispatch-e2e"
    workspace.mkdir(parents=True, exist_ok=True)
    s.insert(
        "github_workspaces", id=1, scope_id=RELEASE_SCOPE, path=str(workspace),
        kind="worktree", dispatchable=1, leased_item_id=ITEM_MERGED, leased_at=at(hours=6),
        released_at=None, lease_token=LANE_G_LEASE_TOKEN, push_token_expires_at=None,
        leased_owner_pid=None, leased_owner_proc_start=None,
        lease_last_owner_contact_at=at(hours=6), lease_release_reminded_at=at(minutes=4),
        lease_release_reminder_count=LANE_G_REMINDERS,
        lease_release_reminder_started_at=at(hours=6),
        provision_error=None, enabled=1, created_at=at(days=3), updated_at=at(minutes=4),
    )
    for index in range(LANE_G_REMINDERS):
        message(s, 100 + index, sender=None, recipient=2, subject="Release needed: issue #104",
                body=f"Reminder {index + 1} of {LANE_G_REMINDERS}. Issue #104 still holds its workspace. Release it.",
                sent=at(minutes=4 * (LANE_G_REMINDERS - index)),
                payload={"kind": "github_lease_release_reminder", "work_item_id": ITEM_MERGED,
                         "issue_number": 104, "reminder_count": index + 1,
                         "reminder_cap": LANE_G_REMINDERS})

    # #535: merged item #104 still has a continuation revision in an active state.
    s.insert(
        "github_attempt_scope_revisions", id=1, work_item_id=ITEM_MERGED,
        dispatch_nonce=f"seed{ITEM_MERGED:012d}", revision=1, owner_slot_id=2, owner_member_id=2,
        phase="implementation", execution_target="workspace",
        summary="Synthetic recovery revision for #104.",
        allowed_paths=["scripts/sync.py"], allowed_actions=["edit"], allowed_commands=["pytest"],
        prohibited_actions=[], tool_fallbacks={},
        baseline_head_sha=sha("revision-baseline-104"), baseline_tree_sha=sha("revision-tree-104"),
        originating_escalation_reason="owner_idle_timeout", expected_workspace_id=1,
        expected_lease_token_hash=digest(LANE_G_LEASE_TOKEN), max_failed_heads=2,
        failed_head_count=0, last_failed_head_sha=None, status="active",
        recovery_checkpoint_stage=None, approval_request_id=None, delivery_message_id=None,
        approved_at=at(days=2), delivered_at=at(days=2), acknowledged_at=at(days=2),
        last_delivery_attempt_at=at(days=2), delivery_attempt_count=1, last_ack_nudge_at=None,
        result_summary=None, evidence=None, submitted_head_sha=None, submitted_at=None,
        completed_at=None, cancelled_at=None, cancellation_reason=None, expires_at=None,
        created_at=at(days=2),
    )

    # #549: a supervisor actor. It is bound to Release crew only when the #549
    # columns exist, so the seed works before and after #549 merges. "Healthy"
    # is relative to the real clock: the next check is 8 minutes from now.
    s.insert(
        "mail_external_actors", id=LANE_G_SUPERVISOR_ACTOR, actor_key="e2e-supervisor",
        display_name="Supervisor (e2e)", kind="external_tool",
        description="Synthetic outside supervisor.", token_hash=digest("e2e-supervisor-token"),
        created_at=at(days=1), last_used_at=at(minutes=2),
    )
    preset_columns = {name for name, _, _ in s.columns("agent_team_presets")}
    if {"supervisor_actor_id", "supervisor_checked_at", "supervisor_next_check_at"} <= preset_columns:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        s.conn.execute(
            "UPDATE agent_team_presets SET supervisor_actor_id = ?, supervisor_checked_at = ?, "
            "supervisor_next_check_at = ? WHERE id = ?",
            (LANE_G_SUPERVISOR_ACTOR, (now - timedelta(minutes=2)).isoformat(sep=" "),
             (now + timedelta(minutes=8)).isoformat(sep=" "), RELEASE_TEAM),
        )

    # #550: item #102 (PR #202) cannot have its required CI read for 2 hours,
    # past the 15-minute grace period. Its status stays "awaiting_human_review".
    # The columns exist from #621; an older database has none, so skip then.
    item_columns = {name for name, _, _ in s.columns("github_work_items")}
    if {"checks_unavailable_since", "checks_unavailable_reason"} <= item_columns:
        s.conn.execute(
            "UPDATE github_work_items SET checks_unavailable_since = ?, "
            "checks_unavailable_reason = ? WHERE id = ?",
            (at(hours=2), "permission_missing", ITEM_REVIEW),
        )


# Lane C (#604): states for the Audit journeys in frontend/e2e/lane-c/.
# A live team with the deleted team's name, so Audit must list two distinct
# "Retired crew" entries (#516). It has no slots, scope or work items, so the
# Overview count and the team filters on Overview and Work do not change.
DUPLICATE_NAME_TEAM = 4


def seed_lane_c(s: Seeder) -> None:
    preset(s, DUPLICATE_NAME_TEAM, "Retired crew", "A new team that reuses an old team name.",
           autonomy=False, leader_slot=None)


async def seed_history() -> None:
    """Audit events through the real ledger service, so shapes stay valid."""
    from app.database import AsyncSessionLocal
    from app.services import factory_audit_service as audit

    member_actor = audit.derive_actor(actor_kind="member", member_id=2)
    operator = audit.derive_actor(actor_kind="operator")
    scheduler = audit.derive_actor(actor_kind="scheduler", scheduler="github_dispatch_scheduler")

    async with AsyncSessionLocal() as db:
        # Refused agent requests: one owner asks to continue #101 three times.
        reasons = [
            ("allowed_paths_invalid", timedelta(hours=9)),
            ("allowed_paths_invalid", timedelta(hours=8, minutes=30)),
            ("allowed_actions_invalid", timedelta(hours=8)),
        ]
        for index, (code, ago) in enumerate(reasons):
            await audit.record_observation(
                db, event_kind="continuation_request", source="e2e_seed",
                occurred_at=SEED_NOW - ago, actor=member_actor, scope_id=RELEASE_SCOPE,
                item_id=ITEM_ATTENTION, action_outcome="rejected", sanitized_reason=code,
                correlation_id=f"continuation_request:rejected:seed:{index}",
            )
        # Lane C (#520): a second group, B2 Backend on #102. The last code is
        # unknown to the controller, so the panel needs its fallback sentence.
        second_actor = audit.derive_actor(actor_kind="member", member_id=3)
        for index, (code, ago) in enumerate([
            ("continuation_budget_exhausted", timedelta(hours=7)),
            ("e2e_unknown_reason_code", timedelta(hours=6, minutes=30)),
        ]):
            await audit.record_observation(
                db, event_kind="continuation_request", source="e2e_seed",
                occurred_at=SEED_NOW - ago, actor=second_actor, scope_id=RELEASE_SCOPE,
                item_id=ITEM_REVIEW, action_outcome="rejected", sanitized_reason=code,
                correlation_id=f"continuation_request:rejected:seed:second:{index}",
            )
        await audit.record_observation(
            db, event_kind="work_lifecycle", source="e2e_seed", occurred_at=SHARED_MOMENT,
            actor=scheduler, scope_id=RELEASE_SCOPE, item_id=ITEM_ACTIVE,
            action_outcome="applied", after_values={"dispatch_status": "dispatched"},
            sanitized_reason="dispatched", correlation_id="work_lifecycle:seed:active",
        )
        await audit.record_observation(
            db, event_kind="work_lifecycle", source="e2e_seed",
            occurred_at=SEED_NOW - timedelta(hours=10), actor=scheduler,
            scope_id=RELEASE_SCOPE, item_id=ITEM_ATTENTION, action_outcome="applied",
            after_values={"dispatch_status": "escalated"}, sanitized_reason="owner_idle_timeout",
            correlation_id="work_lifecycle:seed:escalated",
        )
        await audit.record_observation(
            db, event_kind="scope_policy_change", source="e2e_seed",
            occurred_at=SEED_NOW - timedelta(days=1), actor=operator, scope_id=QUIET_SCOPE,
            action_outcome="applied", before_values={"enabled": True},
            after_values={"enabled": False}, sanitized_reason="intake paused",
            correlation_id="scope_policy_change:seed:quiet",
        )
        # History of the team that the seed deletes next.
        await audit.record_observation(
            db, event_kind="work_lifecycle", source="e2e_seed",
            occurred_at=SEED_NOW - timedelta(days=5), actor=scheduler,
            scope_id=RETIRED_SCOPE, item_id=ITEM_RETIRED, action_outcome="applied",
            after_values={"dispatch_status": "merged"}, sanitized_reason="merged",
            correlation_id="work_lifecycle:seed:retired",
        )
        await audit.record_observation(
            db, event_kind="team_delete", source="e2e_seed",
            occurred_at=SEED_NOW - timedelta(days=4), actor=operator,
            team_preset_id=RETIRED_TEAM, action_outcome="applied",
            sanitized_reason="team retired", correlation_id="team_delete:seed:retired",
        )
        await db.commit()


def delete_retired_team(s: Seeder) -> None:
    # Cascades to the scope and item; audit references become NULL and the
    # context-key trigger retires the team, scope and item keys.
    s.conn.execute("DELETE FROM agent_team_presets WHERE id = ?", (RETIRED_TEAM,))


def start_panes(root: Path) -> None:
    """Start fake harness panes in the instance's own tmux server.

    scripts/e2e-instance.sh proves the private server first and exports its
    socket. The seed refuses to start a pane without that proof, and calls the
    instance's tmux shim and fake binaries by absolute path.
    """
    proven = os.environ.get("E2E_TMUX_PROVEN_SOCKET", "")
    shim = root / "bin" / "tmux"
    if (os.environ.get("TMUX") or not proven
            or not Path(proven).is_relative_to(root)
            or shutil.which("tmux") != str(shim)):
        raise SystemExit("seed: refusing to start panes outside the proven private tmux server")
    repo = root / "repos" / "sample-app"
    for slot in RELEASE_SLOTS:
        if slot["id"] not in LIVE_SLOTS:
            continue
        name = f"deck-e2e-{slot['id']}"
        binary = "codex" if slot["provider"] == "codex-cli" else "claude"
        env = {
            "CLAUDE_DECK_TEAM_PRESET_ID": str(RELEASE_TEAM),
            "CLAUDE_DECK_TEAM_PRESET_NAME": "Release crew",
            "CLAUDE_DECK_TEAM_SLOT_ID": str(slot["id"]),
            "CLAUDE_DECK_TEAM_SLOT_NAME": slot["name"],
            "CLAUDE_DECK_TEAM_SLOT_ROLE": slot["role"],
            "CLAUDE_DECK_TEAM_SLOT_COLOR": slot["color"],
        }
        cmd = [str(shim), "new-session", "-d", "-s", name, "-c", str(repo), "-x", "120", "-y", "32"]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [str(root / "bin" / binary), "--session-id", session_uuid(slot["id"])]
        subprocess.run(cmd, check=True)


def seed_all(s: Seeder, *, root: Path) -> None:
    seed_core(s, root)
    s.conn.commit()
    asyncio.run(seed_history())
    delete_retired_team(s)
    s.conn.commit()
    if os.environ.get("E2E_NO_PANES") != "1":
        start_panes(root)
