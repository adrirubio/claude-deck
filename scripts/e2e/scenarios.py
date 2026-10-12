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
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import timedelta
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
            read=at(days=2), acked=at(days=2), sender_type_director=True)
    message(s, 2, sender=None, recipient=2, subject="Progress check: issue #101",
            body="No PR yet for issue #101. Are you still making progress?",
            sent=at(hours=5), sender_type_director=True)
    message(s, 3, sender=3, recipient=1, subject="Plan for #102",
            body="Please approve the plan for #102.", kind="context_request",
            request_status="pending", sent=at(hours=4), read=at(hours=4))
    message(s, 4, sender=1, recipient=8, subject="Review PR #202",
            body="Please review PR #202 at its current head.", sent=at(hours=2))
    message(s, 5, sender=5, recipient=1, subject="Handoff: #103 docs",
            body="Synthetic handoff summary.", kind="handoff", request_status="pending",
            sent=at(minutes=50))

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
            ("continuation_paths_invalid", timedelta(hours=9)),
            ("continuation_paths_invalid", timedelta(hours=8, minutes=30)),
            ("continuation_actions_not_allowed", timedelta(hours=8)),
        ]
        for index, (code, ago) in enumerate(reasons):
            await audit.record_observation(
                db, event_kind="continuation_request", source="e2e_seed",
                occurred_at=SEED_NOW - ago, actor=member_actor, scope_id=RELEASE_SCOPE,
                item_id=ITEM_ATTENTION, action_outcome="rejected", sanitized_reason=code,
                correlation_id=f"continuation_request:rejected:seed:{index}",
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
