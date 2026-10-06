"""Shared executable restored-copy procedure for the documented V37 rehearsal.

One callable procedure (``run_restored_copy_procedure``) implements the nine
documented steps of the paused rollback procedure from
``architecture-contracts.md:328`` and ``onboarding-and-roles.md:54``:

    1. Pause automation before downgrade
    2. Quiesce attempts, approvals, revisions and leases
    3. Stop relevant writers after quiescence
    4. Back up the database
    5. Record each explicit assignment against the legacy (position, id) resolver
    6. Refuse ordinary downgrade for divergent or unrepresentable assignments
    7. Validate the downgrade against a restored backup for a representable assignment
    8. Compare every authority reference before production use
    9. Restored pre-upgrade database is a separate release decision, never automatic

Every V37 ADMIT or REFUSE claim runs through this same procedure and returns a
step log with the explicit outcome. The procedure only accepts disposable
targets (below the system temp directory). It never restores or downgrades a
production database and never performs a real restore, downgrade, or live
mutation outside disposable copies. Synthetic quiescence in tests is not a
real work-completion claim. V14 remains NOT_PERFORMED.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

PROCEDURE_NAME = "restored_copy_procedure.v1"
DOWNGRADE_SQL = "ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"

# The nine literal documented steps, in order. The step log references these
# labels; no step may be omitted or reordered.
PROCEDURE_STEPS = (
    "1. pause automation before downgrade",
    "2. quiesce attempts, approvals, revisions, and leases",
    "3. stop relevant writers after quiescence",
    "4. back up the database",
    "5. record each explicit assignment against the legacy (position, id) resolver",
    "6. refuse ordinary downgrade for divergent or unrepresentable assignments",
    "7. validate the downgrade against a restored backup for a representable assignment",
    "8. compare every authority reference before production use",
    "9. restored pre-upgrade database is a separate release decision, never automatic",
)

DISPOSABLE_MARKER_NAME = ".disposable-restored-copy-target"

PROCEDURE_LIMITS = {
    "synthetic_quiescence": (
        "Quiescence in disposable fixtures is synthetic. It is not a real "
        "work-completion claim."
    ),
    "v14": "NOT_PERFORMED",
    "real_restore_or_downgrade": "NOT_PERFORMED",
    "production_target": "REFUSED at the procedure interface",
    "separate_release_required": True,
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_set(path: Path) -> dict[str, str]:
    """Digest the main database and any WAL or SHM side files.

    A released lock and a main-file digest do not establish stopped writers;
    WAL side files carry committed changes that the main file alone misses.
    """
    digests = {"main": _digest(path)}
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.exists():
            digests[suffix] = _digest(side)
    return digests


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql).fetchall()]


def capture_reference_scope(conn: sqlite3.Connection) -> dict[str, object]:
    """Capture every authority reference the comparison must cover.

    Scope: explicit assignments with approver source, member and session
    team-slot bindings with mailbox status and owner-followup session identity
    binding, pane identity, owner process identity, push-token expiry, residual
    lease tokens, leased_item_id, owner lifetime fields, workspace authority
    rows, work-state rows (initial_plan and continuation approval requests with
    message-backed references, nonterminal revisions, active attempts), and
    item nonce values. Private fixture values stay inside disposable copies and
    are never published.
    """
    preset_columns = {row[1] for row in conn.execute(
        "PRAGMA table_info(agent_team_presets)").fetchall()}
    leader_select = "p.leader_slot_id" if "leader_slot_id" in preset_columns else "NULL AS leader_slot_id"
    return {
        "explicit_assignments": _rows(conn, (
            f"SELECT p.id AS preset_id, {leader_select}, p.autonomy_enabled,"
            " (SELECT s.id FROM agent_team_slots s WHERE s.preset_id = p.id AND s.enabled = 1"
            "  ORDER BY s.position, s.id LIMIT 1) AS legacy_resolution"
            " FROM agent_team_presets p ORDER BY p.id")),
        "members": _rows(conn, (
            "SELECT id, identity_key, display_name, participant_kind,"
            " team_preset_id, team_slot_id FROM mail_team_members ORDER BY id")),
        "slots": _rows(conn, (
            "SELECT id, preset_id, position, display_name, provider, repo_id, repo_path,"
            " repo_name, launch_mode, enabled FROM agent_team_slots ORDER BY id")),
        "sessions": _rows(conn, (
            "SELECT id, member_id, pid, provider, source, session_key, wake_enabled,"
            " mailbox_status, team_preset_id, team_slot_id, bound_pane_pid,"
            " bound_pane_proc_start, capability_token_hash, last_seen_at, closed_at, created_at"
            " FROM mail_agent_sessions ORDER BY id")),
        "pane_bindings": _rows(conn, (
            "SELECT pane_pid, pane_proc_start, slot_id, preset_id, tmux_target"
            " FROM agent_pane_bindings ORDER BY preset_id, slot_id, pane_pid")),
        "items": _rows(conn, (
            "SELECT id, scope_id, dispatch_status, attempt_phase, owner_slot_id,"
            " handoff_target_slot_id, ack_approver_member_id, active_scope_revision,"
            " approval_round_count, retry_count, diagnostic_retry_count, dispatch_nonce"
            " FROM github_work_items ORDER BY id")),
        "messages": _rows(conn, (
            "SELECT id, thread_root_id, kind, sender_member_id, approval_round, decision,"
            " audience_type, audience_id, recipient_member_id, subject, body_markdown,"
            " request_status, created_at FROM mail_messages ORDER BY id")),
        "presets": _rows(conn, (
            "SELECT id, name, autonomy_enabled, created_at, updated_at"
            " FROM agent_team_presets ORDER BY id")),
        "workspaces": _rows(conn, (
            "SELECT id, scope_id, kind, dispatchable, enabled, leased_item_id, lease_token,"
            " leased_owner_pid, leased_owner_proc_start, push_token_expires_at,"
            " leased_at, released_at, created_at, updated_at"
            " FROM github_workspaces ORDER BY id")),
        "scope_policy": _rows(conn, (
            "SELECT id, preset_id, repo_owner, repo_name, dispatch_label, design_label,"
            " merge_policy, github_auth_mode, base_ref, max_approval_rounds,"
            " max_concurrent_dispatched, max_verification_retries, max_auto_merges_per_day,"
            " max_build_parallelism, builds_out_of_tree, continuation_enabled,"
            " max_continuation_revisions, max_continuation_failed_heads,"
            " max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled"
            " FROM team_github_scopes ORDER BY id")),
        "approval_requests": _rows(conn, (
            "SELECT id, work_item_id, request_kind, dispatch_nonce, approval_round,"
            " owner_member_id, leader_member_id, request_fingerprint, status,"
            " request_message_id, decision_message_id, scope_revision_id"
            " FROM github_approval_requests ORDER BY id")),
        "revisions": _rows(conn, (
            "SELECT id, work_item_id, dispatch_nonce, revision, owner_slot_id, owner_member_id,"
            " phase, execution_target, status, approval_request_id, expected_workspace_id,"
            " expected_lease_token_hash, baseline_head_sha, baseline_tree_sha,"
            " originating_escalation_reason, max_failed_heads, failed_head_count,"
            " delivery_attempt_count FROM github_attempt_scope_revisions ORDER BY id")),
    }


def _quiescence_findings(conn: sqlite3.Connection) -> list[str]:
    """S2: every quiescence predicate and residual authority field."""
    findings: list[str] = []
    checks = {
        "active autonomy": (
            "SELECT COUNT(*) FROM agent_team_presets WHERE autonomy_enabled != 0"),
        "nonterminal attempt": (
            "SELECT COUNT(*) FROM github_work_items WHERE dispatch_status IN"
            " ('dispatched', 'verifying', 'review', 'retry_requested')"),
        "residual workspace authority": (
            "SELECT COUNT(*) FROM github_workspaces WHERE leased_item_id IS NOT NULL"
            " OR lease_token IS NOT NULL OR leased_owner_pid IS NOT NULL"
            " OR leased_owner_proc_start IS NOT NULL OR push_token_expires_at IS NOT NULL"
            " OR (leased_at IS NOT NULL AND released_at IS NULL)"),
        "pending approval": (
            "SELECT COUNT(*) FROM github_approval_requests WHERE status = 'pending'"),
        "nonterminal revision": (
            "SELECT COUNT(*) FROM github_attempt_scope_revisions"
            " WHERE status NOT IN ('completed', 'cancelled')"),
    }
    for label, sql in checks.items():
        count = conn.execute(sql).fetchone()[0]
        if count:
            findings.append(f"{label}: {count}")
    return findings


def run_restored_copy_procedure(
    *,
    source_path: Path,
    work_root: Path,
    pause_state: dict[str, bool],
    downgrade_sql: str = DOWNGRADE_SQL,
) -> dict[str, object]:
    """Run the shared procedure against a disposable database copy.

    Returns a record with ``outcome`` ("ADMIT" or "REFUSE"), an optional
    ``refusal_code``, the nine-entry ``step_log``, the full
    ``comparison_record`` when reached, and the explicit procedure limits.
    Refusal evidence always shows unchanged digests and rows before any
    mutation.
    """
    recorded: dict[str, dict[str, str]] = {}

    def record(step: str, state: str, detail: str) -> None:
        recorded[step] = {"step": step, "state": state, "detail": detail}

    def final_log() -> list[dict[str, str]]:
        return [recorded.get(step, {"step": step, "state": "NOT_REACHED",
                                    "detail": "Stopped at refusal before mutation."})
                for step in PROCEDURE_STEPS]

    def refuse(code: str, step: str, detail: str) -> dict[str, object]:
        record(step, "REFUSE", detail)
        return {
            "procedure": PROCEDURE_NAME,
            "outcome": "REFUSE",
            "refusal_code": code,
            "step_log": final_log(),
            "unchanged_evidence": unchanged_evidence,
            "limits": dict(PROCEDURE_LIMITS),
        }

    unchanged_evidence: dict[str, object] = {}

    # Step 9 guard first: the procedure interface refuses any target that is
    # not an explicitly marked disposable copy. Path heuristics cannot prove
    # disposability; a checkout under a temp directory is not disposable.
    resolved_root = Path(work_root).resolve()
    resolved_source = Path(source_path).resolve()
    marker = resolved_root / DISPOSABLE_MARKER_NAME
    if (not marker.is_file()
            or not resolved_source.is_relative_to(resolved_root)):
        unchanged_evidence = {"refused_target": str(resolved_source)}
        return refuse("production_target_refused", PROCEDURE_STEPS[8],
                      "The target is not an explicitly marked disposable copy.")

    # Step 1: pause automation before downgrade.
    if not pause_state.get("automation_paused"):
        unchanged_evidence = {"source_digest": _digest_set(resolved_source)}
        return refuse("pause_unverified", PROCEDURE_STEPS[0],
                      "Pause state cannot be verified. No backup is taken.")
    record(PROCEDURE_STEPS[0], "ADMIT", "Pause state recorded and verified.")

    conn = sqlite3.connect(resolved_source)
    try:
        # Step 2: quiesce attempts, approvals, revisions and leases.
        findings = _quiescence_findings(conn)
        if findings:
            unchanged_evidence = {
                "source_digest": _digest_set(resolved_source),
                "reference_scope": capture_reference_scope(conn),
            }
            return refuse("quiescence_residual", PROCEDURE_STEPS[1],
                          "Residual authority: " + "; ".join(sorted(findings)))
        record(PROCEDURE_STEPS[1], "ADMIT",
               "No nonterminal attempt, pending approval, nonterminal revision, active lease or residual authority.")

        # C-6: force rollback journal mode on the disposable copy so the
        # exclusive stop proof covers writers; WAL side files cannot then
        # carry unaccounted changes.
        conn.execute("PRAGMA journal_mode=DELETE")
        # Step 3: stop relevant writers after quiescence (exclusive lock proof).
        try:
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            unchanged_evidence = {
                "source_digest": _digest_set(resolved_source),
                "reference_scope": capture_reference_scope(conn),
            }
            return refuse("writer_open", PROCEDURE_STEPS[2], f"A writer remains open: {exc}")
        record(PROCEDURE_STEPS[2], "ADMIT", "Exclusive lock acquired; no writer remains open.")

        pre_mutation_scope = capture_reference_scope(conn)
    finally:
        conn.close()

    # Step 4: back up the database, digesting main and side files.
    backup_path = resolved_root / "procedure-backup.db"
    restored_path = resolved_root / "procedure-restored.db"
    source_digest_before = _digest_set(resolved_source)
    shutil.copy(resolved_source, backup_path)
    source_digest_after = _digest_set(resolved_source)
    if source_digest_after != source_digest_before:
        unchanged_evidence = {"source_digest": source_digest_before}
        return refuse("backup_diverged", PROCEDURE_STEPS[3], "The source digests changed during the copy.")
    record(PROCEDURE_STEPS[3], "ADMIT",
           f"Backup created; source digest unchanged ({source_digest_before}).")

    shutil.copy(backup_path, restored_path)
    if _digest_set(restored_path) != _digest_set(backup_path):
        unchanged_evidence = {"source_digest": source_digest_after}
        return refuse("backup_diverged", PROCEDURE_STEPS[3],
                      "The restored copy does not match the backup snapshot.")
    restored = sqlite3.connect(restored_path)
    try:
        # Step 5: record each explicit assignment against the legacy resolver.
        assignments = capture_reference_scope(restored)["explicit_assignments"]
        unresolved = [row["preset_id"] for row in assignments
                      if row["leader_slot_id"] is None]
        if unresolved:
            unchanged_evidence = {
                "source_digest": source_digest_after,
                "reference_scope": capture_reference_scope(restored),
                "pre_mutation_reference_scope": pre_mutation_scope,
            }
            return refuse("assignment_unresolved", PROCEDURE_STEPS[4],
                          f"Assignments cannot be resolved for comparison: {sorted(unresolved)}")
        record(PROCEDURE_STEPS[4], "ADMIT",
               f"Recorded {len(assignments)} explicit assignment(s) against the legacy resolver.")

        # Step 6: refuse ordinary downgrade for divergent or unrepresentable
        # assignments, before any mutation, keeping the explicit-authority
        # version. Evidence shows unchanged digests and rows.
        divergent = [row["preset_id"] for row in assignments
                     if row["leader_slot_id"] != row["legacy_resolution"]]
        if divergent:
            unchanged_evidence = {
                "source_digest": source_digest_after,
                "reference_scope": capture_reference_scope(restored),
                "pre_mutation_reference_scope": pre_mutation_scope,
            }
            return refuse("assignment_unrepresentable", PROCEDURE_STEPS[5],
                          f"Divergent or unrepresentable assignments kept: {sorted(divergent)}")
        record(PROCEDURE_STEPS[5], "ADMIT",
               "Every explicit assignment equals its legacy resolution.")

        # Step 7: validate the downgrade against a restored backup copy only.
        restored.execute(downgrade_sql)
        restored.commit()
        post_scope = capture_reference_scope(restored)
        record(PROCEDURE_STEPS[6], "ADMIT",
               "Representable downgrade applied to the restored copy only.")

        # Step 8: compare every authority reference before production use.
        # The downgraded copy drops the explicit column; the assignment must
        # survive through the legacy resolver instead.
        mismatches = [key for key in pre_mutation_scope
                      if key != "explicit_assignments" and post_scope.get(key) != pre_mutation_scope[key]]
        for pre_row, post_row in zip(pre_mutation_scope["presets"], post_scope["presets"]):
            if pre_row != post_row:
                mismatches.append(f"preset:{pre_row['id']}")
        pre_assignments = {row["preset_id"]: row["leader_slot_id"]
                           for row in pre_mutation_scope["explicit_assignments"]}
        for row in post_scope["explicit_assignments"]:
            if row["legacy_resolution"] != pre_assignments.get(row["preset_id"]):
                mismatches.append(f"assignment:{row['preset_id']}")
        if mismatches:
            unchanged_evidence = {
                "source_digest": source_digest_after,
                "pre_mutation_reference_scope": pre_mutation_scope,
            }
            return refuse("restored_copy_diverged", PROCEDURE_STEPS[7],
                          f"Authority references differ: {sorted(mismatches)}")
        record(PROCEDURE_STEPS[7], "ADMIT",
               "Every authority reference equals the pre-migration snapshot.")

        record(PROCEDURE_STEPS[8], "ADMIT",
               "Restoring a pre-upgrade database stays a separate release decision; never automatic.")
    finally:
        restored.close()

    # Writer-stop proof through the WAL-aware boundary digests: any source
    # change after the stop claim, including side-file writes from other
    # connections, refuses the procedure instead of admitting it.
    if _digest_set(resolved_source) != source_digest_after:
        unchanged_evidence = {
            "source_digest_after_stop_claim": source_digest_after,
            "source_digest_final": _digest_set(resolved_source),
        }
        return refuse("writer_after_stop", PROCEDURE_STEPS[2],
                      "A writer changed the source or its side files after the stop claim.")

    return {
        "procedure": PROCEDURE_NAME,
        "outcome": "ADMIT",
        "refusal_code": None,
        "step_log": final_log(),
        "comparison_record": pre_mutation_scope,
        "unchanged_evidence": {"source_digest": source_digest_after},
        "limits": dict(PROCEDURE_LIMITS),
    }
