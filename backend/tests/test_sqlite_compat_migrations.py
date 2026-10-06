"""SQLite compatibility migration regressions."""

import hashlib
import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models.database  # noqa: F401
from app.database import (
    Base,
    _run_sqlite_compat_migrations,
    _sqlite_agent_team_slots_has_unique_preset_repo_index,
    _sqlite_columns,
    _sqlite_rebuild_agent_team_slots,
)


@pytest.mark.asyncio
async def test_coordination_revisions_migrate_without_resetting_quota_or_linkage():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for column in ("policy_revision", "assessment_revision", "last_assessment_token_hash"):
                await conn.execute(text(f"ALTER TABLE github_backlog_coordination DROP COLUMN {column}"))
            await conn.execute(text(
                "INSERT INTO github_backlog_coordination "
                "(scope_id, enabled, issue_numbers, version, generation, request_sequence, "
                "requested_generation, message_id, daily_requests, snapshot_requests, "
                "budget_day, assessments, fallback_seconds, max_daily_requests) VALUES "
                "(1, 1, '[7,8]', 29, 4, 12, 4, 31, 12, 2, '2026-10-04', "
                "'[]', 3600, 24)"
            ))
            before = (await conn.execute(text("SELECT * FROM github_backlog_coordination"))).mappings().one()
            await conn.commit()
            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)
            after = (await conn.execute(text("SELECT * FROM github_backlog_coordination"))).mappings().one()
            assert all(after[key] == value for key, value in before.items())
            assert after["policy_revision"] == 1
            assert after["assessment_revision"] == 0
            assert after["last_assessment_token_hash"] is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migrations_repair_misdefined_named_indexes():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("DROP INDEX ix_mail_messages_delivery_key"))
            await conn.execute(
                text(
                    "CREATE INDEX ix_mail_messages_delivery_key "
                    "ON mail_messages (id)"
                )
            )
            await conn.execute(
                text(
                    "DROP INDEX uix_github_approval_requests_pending_work_item"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX uix_github_approval_requests_pending_work_item "
                    "ON github_approval_requests (status)"
                )
            )
            await conn.commit()

            await _run_sqlite_compat_migrations(conn)

            mail_index = next(
                row
                for row in (
                    await conn.execute(text("PRAGMA index_list(mail_messages)"))
                ).all()
                if row[1] == "ix_mail_messages_delivery_key"
            )
            approval_index = next(
                row
                for row in (
                    await conn.execute(
                        text("PRAGMA index_list(github_approval_requests)")
                    )
                ).all()
                if row[1] == "uix_github_approval_requests_pending_work_item"
            )
            assert (mail_index[2], mail_index[4]) == (1, 1)
            assert (approval_index[2], approval_index[4]) == (1, 1)
            assert [
                row[2]
                for row in (
                    await conn.execute(
                        text("PRAGMA index_info(ix_mail_messages_delivery_key)")
                    )
                ).all()
            ] == ["delivery_key"]
            assert [
                row[2]
                for row in (
                    await conn.execute(
                        text(
                            "PRAGMA index_info("
                            "uix_github_approval_requests_pending_work_item)"
                        )
                    )
                ).all()
            ] == ["work_item_id"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migration_refuses_index_repair_over_duplicate_data():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("DROP INDEX ix_mail_messages_delivery_key"))
            await conn.execute(
                text(
                    "CREATE INDEX ix_mail_messages_delivery_key "
                    "ON mail_messages (delivery_key)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO mail_messages "
                    "(kind, body_markdown, delivery_key, created_at) "
                    "VALUES ('message', 'one', 'duplicate', CURRENT_TIMESTAMP), "
                    "('message', 'two', 'duplicate', CURRENT_TIMESTAMP)"
                )
            )
            await conn.commit()

            with pytest.raises(RuntimeError, match="duplicate constrained rows"):
                await _run_sqlite_compat_migrations(conn)

            assert (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM mail_messages "
                        "WHERE delivery_key = 'duplicate'"
                    )
                )
            ).scalar_one() == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migrations_add_capability_columns_idempotently():
    """A pre-PR0 mail_agent_sessions table gains the three columns, twice over."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE mail_agent_sessions (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        member_id INTEGER NOT NULL,
                        provider VARCHAR NOT NULL,
                        source VARCHAR NOT NULL,
                        session_key VARCHAR NOT NULL,
                        mailbox_status VARCHAR NOT NULL,
                        last_seen_at DATETIME NOT NULL,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )
            expected = {"capability_token_hash", "bound_pane_pid", "bound_pane_proc_start"}
            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)
                columns = await _sqlite_columns(conn, "mail_agent_sessions")
                assert expected <= columns
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_leader_migration_preserves_legacy_order_once():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"))
            await conn.execute(text(
                "INSERT INTO agent_team_presets (id, name, created_at, updated_at, autonomy_enabled) "
                "VALUES (1, 'tied', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
                "(2, 'disabled', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
                "(3, 'empty', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            ))
            await conn.execute(text(
                "INSERT INTO agent_team_slots "
                "(id, preset_id, position, display_name, provider, repo_id, repo_path, repo_name, "
                "controlled_language_enabled, launch_mode, enabled, created_at, updated_at) VALUES "
                "(10, 1, 0, 'first', 'codex-cli', 'a', '/a', 'a', 1, 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(11, 1, 0, 'second', 'codex-cli', 'b', '/b', 'b', 1, 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(20, 2, 0, 'disabled', 'codex-cli', 'c', '/c', 'c', 1, 'plain', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.commit()
            await _run_sqlite_compat_migrations(conn)
            first = (await conn.execute(text(
                "SELECT leader_slot_id FROM agent_team_presets WHERE id = 1"
            ))).scalar_one()
            assert first == 10
            assert (await conn.execute(text(
                "SELECT leader_slot_id FROM agent_team_presets WHERE id = 2"
            ))).scalar_one() is None
            assert (await conn.execute(text(
                "SELECT leader_slot_id FROM agent_team_presets WHERE id = 3"
            ))).scalar_one() is None
            await conn.execute(text(
                "UPDATE agent_team_presets SET leader_slot_id = 11 WHERE id = 1"
            ))
            await conn.commit()
            await _run_sqlite_compat_migrations(conn)
            assert (await conn.execute(text(
                "SELECT leader_slot_id FROM agent_team_presets WHERE id = 1"
            ))).scalar_one() == 11
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migration_backfills_wake_participation_once_without_changing_ids():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(
                "CREATE TABLE mail_agent_sessions ("
                "id INTEGER NOT NULL PRIMARY KEY, member_id INTEGER NOT NULL, "
                "provider VARCHAR NOT NULL, source VARCHAR NOT NULL, "
                "session_key VARCHAR NOT NULL, team_preset_id INTEGER, "
                "team_slot_id INTEGER, mailbox_status VARCHAR NOT NULL, "
                "last_seen_at DATETIME NOT NULL, created_at DATETIME NOT NULL)"
            ))
            await conn.execute(text(
                "INSERT INTO mail_agent_sessions "
                "(id, member_id, provider, source, session_key, team_preset_id, "
                "team_slot_id, mailbox_status, last_seen_at, created_at) VALUES "
                "(11, 1, 'codex-cli', 'mcp', 'mcp:slot', 2, 3, 'connected', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(12, 1, 'codex-cli', 'mcp', 'mcp:repo', NULL, NULL, 'connected', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(13, 1, 'codex-cli', 'hook', 'hook:slot', 2, 3, 'connected', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(14, 1, 'codex-cli', 'observed', 'tmux:%1', 2, 3, 'observed', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.commit()

            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)

            rows = (await conn.execute(text(
                "SELECT id, session_key, wake_enabled FROM mail_agent_sessions ORDER BY id"
            ))).all()
            assert [tuple(row) for row in rows] == [
                (11, "mcp:slot", 1),
                (12, "mcp:repo", 0),
                (13, "hook:slot", 0),
                (14, "tmux:%1", 0),
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migrations_add_pr1_approval_columns_idempotently():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE github_work_items (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE mail_messages (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT
                    )
                    """
                )
            )
            work_item_columns = {
                "ack_approver_member_id",
                "ack_evidence_message_id",
                "dispatch_nonce",
                "ack_enforcement_epoch",
                "ack_approval_round",
                "dispatch_head_ref",
                "dispatch_base_ref",
            }
            message_columns = {"approval_round", "decision", "delivery_key"}
            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)
                assert work_item_columns <= await _sqlite_columns(
                    conn, "github_work_items"
                )
                assert message_columns <= await _sqlite_columns(conn, "mail_messages")
            tables = {
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type = 'table'"
                        )
                    )
                ).all()
            }
            assert {
                "github_approval_requests",
                "github_attempt_scope_revisions",
            } <= tables
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migration_adds_mail_audience_columns_without_changing_history():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE mail_messages ("
                    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                    "kind VARCHAR NOT NULL, body_markdown VARCHAR NOT NULL, "
                    "created_at DATETIME NOT NULL)"
                )
            )
            await conn.execute(
                text(
                    "CREATE TABLE mail_receipts ("
                    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                    "message_id INTEGER NOT NULL, member_id INTEGER NOT NULL, "
                    "read_at DATETIME, acked_at DATETIME)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO mail_messages "
                    "(id, kind, body_markdown, created_at) "
                    "VALUES (7, 'message', 'historical body', '2024-01-02 03:04:05')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO mail_receipts "
                    "(id, message_id, member_id, read_at, acked_at) "
                    "VALUES (11, 7, 13, '2024-02-03 04:05:06', NULL)"
                )
            )
            await conn.commit()

            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)

            columns = await _sqlite_columns(conn, "mail_messages")
            assert {"audience_type", "audience_id"} <= columns
            assert (
                await conn.execute(
                    text(
                        "SELECT id, kind, body_markdown, audience_type, audience_id "
                        "FROM mail_messages WHERE id = 7"
                    )
                )
            ).one() == (7, "message", "historical body", None, None)
            assert (
                await conn.execute(
                    text(
                        "SELECT id, message_id, member_id, read_at, acked_at "
                        "FROM mail_receipts WHERE id = 11"
                    )
                )
            ).one() == (11, 7, 13, "2024-02-03 04:05:06", None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migrations_add_pr2_continuation_columns_idempotently():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE team_github_scopes ("
                    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                    "repo_owner VARCHAR NOT NULL)"
                )
            )
            await conn.execute(
                text(
                    "CREATE TABLE github_work_items ("
                    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                    "pr_number INTEGER, retry_count INTEGER NOT NULL, "
                    "dispatch_nonce VARCHAR, status_note VARCHAR)"
                )
            )
            await conn.execute(
                text(
                    "CREATE TABLE github_attempt_scope_revisions ("
                    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                    "work_item_id INTEGER NOT NULL)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO team_github_scopes (id, repo_owner) "
                    "VALUES (1, 'owner')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO github_work_items "
                    "(id, pr_number, retry_count, dispatch_nonce, status_note) "
                    "VALUES (1, 42, 7, '0123456789abcdef', 'preserve me')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO github_attempt_scope_revisions "
                    "(id, work_item_id) VALUES (1, 1)"
                )
            )
            await conn.commit()

            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)

            scope = (
                await conn.execute(
                    text(
                        "SELECT continuation_enabled, max_continuation_revisions, "
                        "max_continuation_failed_heads, max_failed_heads_per_revision, "
                        "max_scope_paths, max_scope_commands "
                        "FROM team_github_scopes WHERE id = 1"
                    )
                )
            ).one()
            item = (
                await conn.execute(
                    text(
                        "SELECT active_scope_revision, attempt_phase, "
                        "diagnostic_retry_count, diagnostic_last_verified_sha, "
                        "continuation_nudged_at, continuation_activated_at, "
                        "pr_number, retry_count, dispatch_nonce, status_note "
                        "FROM github_work_items WHERE id = 1"
                    )
                )
            ).one()

            assert tuple(scope) == (0, 6, 8, 2, 32, 16)
            assert tuple(item) == (
                0,
                "implementation",
                0,
                None,
                None,
                None,
                42,
                7,
                "0123456789abcdef",
                "preserve me",
            )
            assert "submitted_head_sha" in await _sqlite_columns(
                conn, "github_attempt_scope_revisions"
            )
            assert "submitted_at" in await _sqlite_columns(
                conn, "github_attempt_scope_revisions"
            )
            assert "cancelled_at" in await _sqlite_columns(
                conn, "github_attempt_scope_revisions"
            )
            assert "cancellation_reason" in await _sqlite_columns(
                conn, "github_attempt_scope_revisions"
            )
            assert "recovery_checkpoint_stage" in await _sqlite_columns(
                conn, "github_attempt_scope_revisions"
            )
            assert (
                await conn.execute(
                    text(
                        "SELECT recovery_checkpoint_stage "
                        "FROM github_attempt_scope_revisions WHERE id = 1"
                    )
                )
            ).scalar_one() is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pr1_approval_reconciliation_is_idempotent_and_chooses_no_ambiguous_root():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            statements = [
                """
                CREATE TABLE agent_team_presets (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    autonomy_enabled BOOLEAN DEFAULT 0 NOT NULL
                )
                """,
                """
                CREATE TABLE agent_team_slots (
                    id INTEGER PRIMARY KEY,
                    preset_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    display_name VARCHAR NOT NULL,
                    provider VARCHAR NOT NULL,
                    repo_id VARCHAR NOT NULL,
                    repo_path VARCHAR NOT NULL,
                    repo_name VARCHAR NOT NULL,
                    launch_mode VARCHAR DEFAULT 'plain' NOT NULL,
                    enabled BOOLEAN DEFAULT 1 NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """,
                """
                CREATE TABLE team_github_scopes (
                    id INTEGER PRIMARY KEY,
                    preset_id INTEGER NOT NULL,
                    repo_owner VARCHAR NOT NULL,
                    repo_name VARCHAR NOT NULL
                )
                """,
                """
                CREATE TABLE github_work_items (
                    id INTEGER PRIMARY KEY,
                    scope_id INTEGER NOT NULL,
                    owner_slot_id INTEGER,
                    dispatch_nonce VARCHAR,
                    approval_round_count INTEGER DEFAULT 0 NOT NULL,
                    pr_number INTEGER,
                    retry_requested_at DATETIME,
                    status_note VARCHAR,
                    issue_title VARCHAR,
                    github_updated_at DATETIME
                )
                """,
                """
                CREATE TABLE mail_team_members (
                    id INTEGER PRIMARY KEY,
                    identity_key VARCHAR,
                    repo_id VARCHAR NOT NULL,
                    repo_path VARCHAR NOT NULL,
                    repo_name VARCHAR NOT NULL,
                    display_name VARCHAR NOT NULL,
                    participant_kind VARCHAR DEFAULT 'repo',
                    team_preset_id INTEGER,
                    team_slot_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """,
                """
                CREATE TABLE mail_messages (
                    id INTEGER PRIMARY KEY,
                    thread_root_id INTEGER,
                    kind VARCHAR NOT NULL,
                    sender_member_id INTEGER,
                    recipient_member_id INTEGER,
                    payload JSON,
                    request_status VARCHAR,
                    body_markdown VARCHAR NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """,
            ]
            for statement in statements:
                await conn.execute(text(statement))
            await conn.execute(
                text("INSERT INTO agent_team_presets (id, name) VALUES (1, 'Tizonia')")
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_team_slots "
                    "(id, preset_id, position, display_name, provider, repo_id, "
                    "repo_path, repo_name) VALUES "
                    "(1, 1, 0, 'Leader', 'codex-cli', 'repo', '/tmp/repo', 'repo'), "
                    "(2, 1, 1, 'Owner', 'codex-cli', 'repo', '/tmp/repo', 'repo')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO team_github_scopes "
                    "(id, preset_id, repo_owner, repo_name) VALUES (1, 1, 'o', 'r')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO github_work_items "
                    "(id, scope_id, owner_slot_id, dispatch_nonce, approval_round_count, "
                    "pr_number, retry_requested_at, issue_title, github_updated_at) VALUES "
                    "(1, 1, 2, 'nonce-1', 1, 101, '2026-08-01', 'one', '2026-08-01'), "
                    "(2, 1, 2, 'nonce-2', 1, NULL, '2026-08-02', 'two', '2026-08-02'), "
                    "(3, 1, 2, 'nonce-3', 1, NULL, NULL, 'three', '2026-08-03')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO mail_team_members "
                    "(id, identity_key, repo_id, repo_path, repo_name, display_name, "
                    "team_preset_id, team_slot_id, updated_at) VALUES "
                    "(1, 'slot:old-leader', 'repo', '/tmp/repo', 'repo', "
                    "'Old Leader', 1, 1, '2026-01-01'), "
                    "(2, 'slot:old-owner', 'repo', '/tmp/repo', 'repo', "
                    "'Old Owner', 1, 2, '2026-01-01'), "
                    "(3, 'slot:leader', 'repo', '/tmp/repo', 'repo', "
                    "'Leader', 1, 1, '2026-08-01'), "
                    "(4, 'slot:owner', 'repo', '/tmp/repo', 'repo', "
                    "'Owner', 1, 2, '2026-08-01')"
                )
            )
            payload_one = (
                '{"work_item_id":1,"dispatch_nonce":"nonce-1",'
                '"approval_round":1,"summary":"one"}'
            )
            payload_two = (
                '{"work_item_id":2,"dispatch_nonce":"nonce-2",'
                '"approval_round":1,"summary":"two"}'
            )
            await conn.execute(
                text(
                    "INSERT INTO mail_messages "
                    "(id, thread_root_id, kind, sender_member_id, recipient_member_id, payload, "
                    "request_status, body_markdown) VALUES "
                    "(9, NULL, 'context_request', 2, 1, :payload_one, 'pending', 'old'), "
                    "(10, NULL, 'context_request', 4, 3, :payload_one, 'pending', 'one'), "
                    "(11, 10, 'context_request', 4, 3, :payload_one, 'pending', 'child'), "
                    "(20, NULL, 'context_request', 4, 3, :payload_two, 'pending', 'two-a'), "
                    "(21, NULL, 'context_request', 4, 3, :payload_two, 'pending', 'two-b')"
                ),
                {"payload_one": payload_one, "payload_two": payload_two},
            )
            await conn.commit()

            snapshots = []
            for migration_run in range(2):
                await _run_sqlite_compat_migrations(conn)
                if migration_run == 0:
                    await conn.execute(
                        text(
                            "INSERT INTO mail_messages "
                            "(id, thread_root_id, kind, sender_member_id, "
                            "recipient_member_id, payload, request_status, body_markdown) "
                            "VALUES (30, NULL, 'context_request', 4, 3, :payload, "
                            "'pending', 'post-upgrade generic question')"
                        ),
                        {
                            "payload": (
                                '{"work_item_id":3,"dispatch_nonce":"nonce-3",'
                                '"approval_round":1,"summary":"not approval"}'
                            )
                        },
                    )
                    await conn.commit()
                approvals = (
                    await conn.execute(
                        text(
                            "SELECT work_item_id, owner_member_id, leader_member_id, "
                            "request_message_id, request_fingerprint, status "
                            "FROM github_approval_requests ORDER BY id"
                        )
                    )
                ).all()
                messages = (
                    await conn.execute(
                        text(
                            "SELECT id, request_status FROM mail_messages "
                            "WHERE id IN (9, 10, 11, 20, 21) ORDER BY id"
                        )
                    )
                ).all()
                items = (
                    await conn.execute(
                        text(
                            "SELECT id, retry_requested_at, status_note, issue_title, "
                            "github_updated_at FROM github_work_items ORDER BY id"
                        )
                    )
                ).all()
                snapshots.append((approvals, messages, items))

            assert snapshots[0] == snapshots[1]
            approvals, messages, items = snapshots[0]
            expected_fingerprint = hashlib.sha256(
                json.dumps(
                    {"plan_metadata": {}, "summary": "one"},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            assert approvals == [(1, 4, 3, 10, expected_fingerprint, "pending")]
            assert messages == [
                (9, "pending"),
                (10, "pending"),
                (11, "pending"),
                (20, "superseded"),
                (21, "superseded"),
            ]
            assert items[0][1:] == (None, None, "one", "2026-08-01")
            assert items[1][1] == "2026-08-02"
            assert "submit one fresh approval request" in items[1][2]
            assert items[2][1:] == (None, None, "three", "2026-08-03")
            assert (
                await conn.execute(
                    text(
                        "SELECT request_status FROM mail_messages WHERE id = 30"
                    )
                )
            ).scalar_one() == "pending"

            indexes = {
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type = 'index'"
                        )
                    )
                ).all()
            }
            assert "ix_mail_messages_delivery_key" in indexes
            assert "uix_github_approval_requests_pending_work_item" in indexes
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_migrations_add_pr2_github_auth_columns_idempotently():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE team_github_scopes (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        repo_owner VARCHAR NOT NULL,
                        repo_name VARCHAR NOT NULL
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO team_github_scopes (repo_owner, repo_name) "
                    "VALUES ('owner', 'repo')"
                )
            )
            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)
                columns = await _sqlite_columns(conn, "team_github_scopes")
                assert {"github_auth_mode", "github_app_installation_id"} <= columns
            row = (
                await conn.execute(
                    text(
                        "SELECT github_auth_mode, github_app_installation_id "
                        "FROM team_github_scopes"
                    )
                )
            ).one()
            assert row == ("unknown", None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pr2_base_migration_does_not_invent_historical_attempt_identity():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE team_github_scopes (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        base_ref VARCHAR DEFAULT 'origin/HEAD' NOT NULL
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE github_work_items (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        scope_id INTEGER NOT NULL,
                        dispatch_head_ref VARCHAR
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO team_github_scopes (id, base_ref) "
                    "VALUES (1, 'origin/release')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO github_work_items (id, scope_id, dispatch_head_ref) "
                    "VALUES (1, 1, 'deck/slot-1/issue-1-nonce'), (2, 1, NULL)"
                )
            )

            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)

            rows = (
                await conn.execute(
                    text(
                        "SELECT id, dispatch_base_ref FROM github_work_items "
                        "ORDER BY id"
                    )
                )
            ).all()
            assert rows == [(1, None), (2, None)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pr2_workspace_migration_adds_push_token_expiry_idempotently():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE github_workspaces (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT
                    )
                    """
                )
            )

            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)

            assert "push_token_expires_at" in await _sqlite_columns(
                conn,
                "github_workspaces",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rebuild_agent_team_slots_removes_legacy_same_repo_unique_constraint():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE agent_team_presets (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR NOT NULL
                    )
                    """
                )
            )
            await conn.execute(text("INSERT INTO agent_team_presets (id, name) VALUES (1, 'E2E')"))
            await conn.execute(
                text(
                    """
                    CREATE TABLE agent_team_slots (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        preset_id INTEGER NOT NULL,
                        position INTEGER NOT NULL,
                        display_name VARCHAR NOT NULL,
                        provider VARCHAR NOT NULL,
                        repo_id VARCHAR NOT NULL,
                        repo_path VARCHAR NOT NULL,
                        repo_name VARCHAR NOT NULL,
                        role VARCHAR,
                        charter VARCHAR,
                        launch_mode VARCHAR NOT NULL,
                        launch_options JSON,
                        enabled BOOLEAN NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        UNIQUE (preset_id, repo_id),
                        FOREIGN KEY(preset_id) REFERENCES agent_team_presets (id) ON DELETE CASCADE
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_team_slots (
                        preset_id,
                        position,
                        display_name,
                        provider,
                        repo_id,
                        repo_path,
                        repo_name,
                        launch_mode,
                        enabled,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        1,
                        0,
                        'Planner',
                        'codex-cli',
                        'repo-1',
                        '/home/user/repo',
                        'repo',
                        'plain',
                        1,
                        '2026-06-21 00:00:00',
                        '2026-06-21 00:00:00'
                    )
                    """
                )
            )
            await conn.commit()

            assert await _sqlite_agent_team_slots_has_unique_preset_repo_index(conn)

            columns = await _sqlite_columns(conn, "agent_team_slots")
            await _sqlite_rebuild_agent_team_slots(conn, columns)

            assert not await _sqlite_agent_team_slots_has_unique_preset_repo_index(conn)
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_team_slots (
                        preset_id,
                        position,
                        display_name,
                        provider,
                        repo_id,
                        repo_path,
                        repo_name,
                        launch_mode,
                        enabled,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        1,
                        1,
                        'Reviewer',
                        'codex-cli',
                        'repo-1',
                        '/home/user/repo',
                        'repo',
                        'plain',
                        1,
                        '2026-06-21 00:00:00',
                        '2026-06-21 00:00:00'
                    )
                    """
                )
            )
            count = (
                await conn.execute(text("SELECT COUNT(*) FROM agent_team_slots WHERE repo_id = 'repo-1'"))
            ).scalar_one()
            assert count == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compat_adds_verification_clock_columns_without_changing_rows():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE github_work_items DROP COLUMN verification_head_sha"))
            await conn.execute(text("ALTER TABLE github_work_items DROP COLUMN verification_started_at"))
            await conn.execute(text(
                "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, "
                "issue_url, github_updated_at, dispatch_status, issue_type, retry_count, "
                "approval_round_count, active_scope_revision, attempt_phase, diagnostic_retry_count, "
                "created_at, updated_at) VALUES (1, 1, 5, 'guard', 'url', CURRENT_TIMESTAMP, "
                "'verifying', 'code', 0, 1, 0, 'implementation', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)
                columns = await _sqlite_columns(conn, "github_work_items")
                assert {"verification_head_sha", "verification_started_at"} <= columns
                row = (await conn.execute(text(
                    "SELECT dispatch_status, verification_head_sha, verification_started_at "
                    "FROM github_work_items WHERE id = 1"))).one()
                assert tuple(row) == ("verifying", None, None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_v37_rollback_comparison_refuses_divergent_leader_assignments():
    """V37: a restored legacy copy must not silently reinterpret explicit authority.

    The documented rollback procedure records each explicit assignment against
    the legacy (position, id) resolver before downgrade. A restored legacy copy
    recomputes assignments through that resolver. Equal references are
    representable; any difference or unrepresentable assignment refuses the
    ordinary downgrade.
    """

    async def authority_references(conn):
        rows = (await conn.execute(text(
            "SELECT p.id, p.leader_slot_id, "
            "(SELECT s.id FROM agent_team_slots s WHERE s.preset_id = p.id AND s.enabled = 1 "
            " ORDER BY s.position, s.id LIMIT 1) AS legacy_id FROM agent_team_presets p"
        ))).all()
        return {row.id: (row.leader_slot_id, row.legacy_id) for row in rows}

    async def build(upgraded: bool):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        conn = await engine.connect()
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"))
        await conn.execute(text(
            "INSERT INTO agent_team_presets (id, name, created_at, updated_at, autonomy_enabled) "
            "VALUES (1, 'representable', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
            "(2, 'divergent', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
            "(3, 'unrepresentable', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
        ))
        await conn.execute(text(
            "INSERT INTO agent_team_slots "
            "(id, preset_id, position, display_name, provider, repo_id, repo_path, repo_name, "
            "controlled_language_enabled, launch_mode, enabled, created_at, updated_at) VALUES "
            "(10, 1, 0, 'first', 'codex-cli', 'a', '/a', 'a', 1, 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(11, 1, 1, 'second', 'codex-cli', 'b', '/b', 'b', 1, 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(20, 2, 0, 'first', 'codex-cli', 'c', '/c', 'c', 1, 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(21, 2, 1, 'second', 'codex-cli', 'd', '/d', 'd', 1, 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(30, 3, 0, 'first', 'codex-cli', 'e', '/e', 'e', 1, 'plain', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        await conn.commit()
        await _run_sqlite_compat_migrations(conn)
        if upgraded:
            # Record explicit assignments as the rollback procedure requires.
            await conn.execute(text(
                "UPDATE agent_team_presets SET leader_slot_id = 21 WHERE id = 2"
            ))
            await conn.execute(text(
                "UPDATE agent_team_presets SET leader_slot_id = 30 WHERE id = 3"
            ))
            await conn.commit()
        refs = await authority_references(conn)
        await conn.close()
        return engine, refs

    upgraded_engine, upgraded = await build(True)
    restored_engine, restored = await build(False)
    try:
        assert upgraded[1] == (10, 10)
        assert upgraded[2] == (21, 20)
        assert upgraded[3] == (30, None)
        # The restored legacy copy recomputes every assignment through the legacy resolver.
        assert restored[1] == (10, 10)
        assert restored[2] == (20, 20)
        assert restored[3] == (None, None)
        representable = sorted(
            preset_id for preset_id, (explicit, _) in upgraded.items()
            if explicit is not None and restored[preset_id][0] == explicit
        )
        refused = sorted(
            preset_id for preset_id, (explicit, _) in upgraded.items()
            if restored[preset_id][0] != explicit
        )
        assert representable == [1]
        assert refused == [2, 3]
    finally:
        await upgraded_engine.dispose()
        await restored_engine.dispose()



async def _v37_seed_authority_records(conn, *, divergent: bool):
    presets = [(1, "representable", 1)]
    slots = [
        (10, 1, 0, 1), (11, 1, 1, 1),
    ]
    if divergent:
        presets += [(2, "divergent", 1), (3, "unrepresentable", 0)]
        slots += [(20, 2, 0, 1), (21, 2, 1, 1), (30, 3, 0, 0)]
    for preset_id, name, enabled in presets:
        await conn.execute(text(
            "INSERT INTO agent_team_presets (id, name, created_at, updated_at, autonomy_enabled, leader_slot_id) "
            "VALUES (:id, :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, "
            " CASE WHEN :id = 1 THEN 10 WHEN :id = 2 THEN 21 ELSE 30 END)"
        ), {"id": preset_id, "name": name})
    for slot_id, preset_id, position, enabled in slots:
        await conn.execute(text(
            "INSERT INTO agent_team_slots (id, preset_id, position, display_name, provider, repo_id, repo_path, "
            "repo_name, launch_mode, enabled, created_at, updated_at) VALUES "
            "(:id, :preset_id, :position, :name, 'codex-cli', :repo, :path, :repo, 'plain', :enabled, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"id": slot_id, "preset_id": preset_id, "position": position, "name": f"slot-{slot_id}",
            "repo": f"repo-{slot_id}", "path": f"/{slot_id}", "enabled": enabled})
    for member_id, name in ((7, "owner-member"), (8, "leader-member")):
        await conn.execute(text(
            "INSERT INTO mail_team_members (id, identity_key, repo_id, repo_path, repo_name, display_name, "
            "participant_kind, team_preset_id, team_slot_id, created_at, updated_at) VALUES (:id, :key, 'repo-10', '/10', 'repo-10', :name, "
            "'team_slot', 1, :slot, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"id": member_id, "key": f"slot:{member_id}", "name": name, "slot": 11 if member_id == 7 else 10})
    for session_id, member_id in ((21, 7), (22, 8)):
        await conn.execute(text(
            "INSERT INTO mail_agent_sessions (id, member_id, provider, source, session_key, wake_enabled, "
            "mailbox_status, last_seen_at, team_preset_id, team_slot_id, bound_pane_pid, "
            "bound_pane_proc_start, capability_token_hash, created_at) VALUES (:id, :member, 'codex-cli', 'mcp', :key, 1, "
            "'connected', CURRENT_TIMESTAMP, 1, :slot, :pane, '1', :cap, CURRENT_TIMESTAMP)"
        ), {"id": session_id, "member": member_id, "key": f"mcp:{session_id}",
            "slot": 11 if member_id == 7 else 10, "pane": 1000 + session_id,
            "cap": f"test-cap-{session_id}"})
    await conn.execute(text(
        "INSERT INTO agent_pane_bindings (pane_pid, pane_proc_start, slot_id, preset_id, created_at) VALUES "
        "(1021, '1', 11, 1, CURRENT_TIMESTAMP), (1022, '1', 10, 1, CURRENT_TIMESTAMP)"
    ))
    await conn.execute(text(
        "INSERT INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path, dispatch_label, "
        "design_label, merge_policy, github_auth_mode, base_ref, max_approval_rounds, max_concurrent_dispatched, "
        "max_verification_retries, max_auto_merges_per_day, max_build_parallelism, builds_out_of_tree, "
        "continuation_enabled, max_continuation_revisions, max_continuation_failed_heads, "
        "max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled, created_at, updated_at) "
        "VALUES (1, 1, 'example', 'repo-10', '/10', 'ready', 'design', 'human', 'ambient', 'origin/main', 3, 1, 1, 0, 1, 0, "
        "0, 6, 8, 2, 32, 16, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ))
    await conn.execute(text(
        "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, issue_url, github_updated_at, "
        "issue_type, dispatch_status, attempt_phase, owner_slot_id, handoff_target_slot_id, ack_approver_member_id, "
        "active_scope_revision, approval_round_count, retry_count, diagnostic_retry_count, dispatch_nonce, "
        "created_at, updated_at) "
        "VALUES (1, 1, 7, 'title', 'https://example.invalid/7', CURRENT_TIMESTAMP, 'code', "
        "'verifying', 'implementation', 10, 11, 7, 0, 1, 0, 0, 'fixture-nonce', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ))
    await conn.execute(text(
        "INSERT INTO github_workspaces (id, scope_id, path, kind, dispatchable, enabled, leased_item_id, lease_token, "
        "leased_owner_pid, leased_owner_proc_start, push_token_expires_at, leased_at, released_at, "
        "created_at, updated_at) VALUES (1, 1, '/work/1', 'worktree', 1, 1, 1, 'fixture-lease-token', "
        "2001, '1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ))
    await conn.execute(text(
        "INSERT INTO mail_messages (id, kind, sender_member_id, recipient_member_id, subject, body_markdown, "
        "created_at) VALUES (100, 'question', 7, 8, 'Plan', 'Fixture plan', CURRENT_TIMESTAMP)"
    ))
    await conn.execute(text(
        "INSERT INTO github_approval_requests (id, work_item_id, request_kind, dispatch_nonce, approval_round, "
        "owner_member_id, leader_member_id, request_fingerprint, status, request_message_id, scope_revision_id, "
        "created_at) VALUES (1, 1, 'initial', 'fixture-nonce', 1, 7, 8, 'fixture-fingerprint', 'pending', 100, 1, "
        "CURRENT_TIMESTAMP)"
    ))
    await conn.execute(text(
        "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision, owner_slot_id, "
        "owner_member_id, phase, execution_target, summary, allowed_paths, allowed_actions, allowed_commands, "
        "prohibited_actions, tool_fallbacks, baseline_head_sha, baseline_tree_sha, originating_escalation_reason, "
        "expected_workspace_id, expected_lease_token_hash, max_failed_heads, failed_head_count, status, "
        "delivery_attempt_count, approval_request_id, created_at) "
        "VALUES (1, 1, 'fixture-nonce', 0, 10, 7, 'implementation', '/work/1', 'fixture summary', '[]', '[]', '[]', "
        "'[]', '{}', :head, :tree, 'fixture', 1, 'fixture-hash', 2, 0, 'active', 0, 1, CURRENT_TIMESTAMP)"
    ), {"head": "a" * 40, "tree": "b" * 40})
    await conn.commit()


_V37_QUIESCENCE_SQL = (
    "SELECT "
    "(SELECT COUNT(*) FROM agent_team_presets WHERE autonomy_enabled != 0) + "
    "(SELECT COUNT(*) FROM github_work_items WHERE dispatch_status IN "
    "('dispatched', 'verifying', 'review', 'retry_requested')) + "
    "(SELECT COUNT(*) FROM github_workspaces WHERE leased_item_id IS NOT NULL OR lease_token IS NOT NULL OR leased_owner_pid IS NOT NULL OR leased_owner_proc_start IS NOT NULL OR push_token_expires_at IS NOT NULL OR (leased_at IS NOT NULL AND released_at IS NULL)) + "
    "(SELECT COUNT(*) FROM github_approval_requests WHERE status = 'pending') + "
    "(SELECT COUNT(*) FROM github_attempt_scope_revisions WHERE status NOT IN ('completed', 'cancelled'))"
)


async def _v37_quiesce_and_verify(conn):
    """Execute the documented pre-downgrade quiescence procedure."""
    await conn.execute(text("UPDATE agent_team_presets SET autonomy_enabled = 0"))
    await conn.execute(text(
        "UPDATE github_work_items SET dispatch_status = 'completed', attempt_phase = 'completed'"
    ))
    await conn.execute(text(
        "UPDATE github_workspaces SET leased_item_id = NULL, lease_token = NULL, "
        "leased_owner_pid = NULL, leased_owner_proc_start = NULL, push_token_expires_at = NULL, "
        "leased_at = NULL, released_at = CURRENT_TIMESTAMP"
    ))
    await conn.execute(text("UPDATE github_approval_requests SET status = 'approved'"))
    await conn.execute(text("UPDATE github_attempt_scope_revisions SET status = 'completed'"))
    await conn.commit()
    remaining = (await conn.execute(text(_V37_QUIESCENCE_SQL))).scalar_one()
    # Close the read snapshot, then verify no writer transaction remains open.
    await conn.rollback()
    assert remaining == 0
    assert not conn.in_transaction()


async def _v37_authority_references(conn):
    async def rows(sql):
        return [dict(row) for row in (await conn.execute(text(sql))).mappings().all()]

    columns = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_presets)"))).all()}
    explicit = None
    if "leader_slot_id" in columns:
        explicit = {row[0]: row[1] for row in (await conn.execute(text(
            "SELECT id, leader_slot_id FROM agent_team_presets ORDER BY id"
        ))).all()}
    return {
        "presets": await rows("SELECT id, name, autonomy_enabled FROM agent_team_presets ORDER BY id"),
        "slots": await rows("SELECT id, preset_id, position, enabled FROM agent_team_slots ORDER BY id"),
        "members": await rows("SELECT id, identity_key, display_name, participant_kind, team_preset_id, team_slot_id "
                              "FROM mail_team_members ORDER BY id"),
        "sessions": await rows("SELECT id, member_id, provider, source, session_key, mailbox_status, team_preset_id, team_slot_id, bound_pane_pid, bound_pane_proc_start, capability_token_hash "
                               "FROM mail_agent_sessions ORDER BY id"),
        "pane_bindings": await rows("SELECT pane_pid, pane_proc_start, slot_id, preset_id FROM agent_pane_bindings ORDER BY pane_pid"),
        "items": await rows("SELECT id, scope_id, dispatch_status, attempt_phase, owner_slot_id, "
                            "handoff_target_slot_id, ack_approver_member_id, active_scope_revision, "
                            "approval_round_count, dispatch_nonce FROM github_work_items ORDER BY id"),
        "workspaces": await rows("SELECT id, scope_id, leased_item_id, lease_token, leased_owner_pid, leased_owner_proc_start, "
                                 "push_token_expires_at, leased_at, released_at FROM github_workspaces ORDER BY id"),
        "approval_requests": await rows(
            "SELECT id, work_item_id, request_kind, approval_round, owner_member_id, leader_member_id, "
            "request_fingerprint, status, request_message_id, scope_revision_id, dispatch_nonce "
            "FROM github_approval_requests ORDER BY id"),
        "revisions": await rows(
            "SELECT id, work_item_id, revision, owner_slot_id, owner_member_id, phase, execution_target, "
            "baseline_head_sha, baseline_tree_sha, expected_workspace_id, expected_lease_token_hash, status, "
            "dispatch_nonce, approval_request_id FROM github_attempt_scope_revisions ORDER BY id"),
        "legacy": await rows(
            "SELECT p.id, (SELECT s.id FROM agent_team_slots s WHERE s.preset_id = p.id AND s.enabled = 1 "
            " ORDER BY s.position, s.id LIMIT 1) AS legacy_id FROM agent_team_presets p ORDER BY p.id"),
        "explicit": explicit,
    }


@pytest.mark.asyncio
async def test_v37_downgrade_rehearsal_quiesces_and_validates_representable_restored_copy(tmp_path):
    """V37: documented rehearsal on a restored disposable backup, representable case.

    Architecture contract line 328: pause automation, quiesce attempts,
    approvals, revisions and leases, stop relevant writers, back up, then
    validate the downgrade on a restored copy against every authority
    reference. The user database is never used or downgraded.
    """
    import shutil

    upgraded_path = tmp_path / "upgraded.db"
    backup_path = tmp_path / "upgraded.backup.db"
    restored_path = tmp_path / "restored.db"

    engine = create_async_engine(f"sqlite+aiosqlite:///{upgraded_path}")
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _v37_seed_authority_records(conn, divergent=False)
        # Pause automation, quiesce all work, and verify the quiescence
        # predicates before the backup is taken.
        await _v37_quiesce_and_verify(conn)
        recorded = await _v37_authority_references(conn)
    # Stop relevant writers before the backup.
    await engine.dispose()
    source_digest = hashlib.sha256(upgraded_path.read_bytes()).hexdigest()

    shutil.copy(upgraded_path, backup_path)
    shutil.copy(backup_path, restored_path)

    restored_engine = create_async_engine(f"sqlite+aiosqlite:///{restored_path}")
    try:
        async with restored_engine.connect() as conn:
            before = await _v37_authority_references(conn)
            # Pre-mutation gate: the assignment must match the legacy resolver.
            assert before["explicit"] == {1: 10}
            assert before["legacy"][0]["legacy_id"] == 10
            refused = [
                preset_id for preset_id, explicit in before["explicit"].items()
                if next(row["legacy_id"] for row in before["legacy"] if row["id"] == preset_id) != explicit
            ]
            assert refused == []
            # The rehearsal proceeds only for representable assignments.
            await conn.execute(text("ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"))
            await conn.commit()
            after = await _v37_authority_references(conn)
        for key in ("presets", "slots", "members", "sessions", "pane_bindings", "items", "workspaces",
                    "approval_requests", "revisions", "legacy"):
            assert after[key] == recorded[key], key
    finally:
        await restored_engine.dispose()

    # The upgraded source database keeps its hash and its explicit column.
    assert hashlib.sha256(upgraded_path.read_bytes()).hexdigest() == source_digest


@pytest.mark.asyncio
async def test_v37_rehearsal_refuses_divergent_and_unrepresentable_before_downgrade_mutation(tmp_path):
    """V37: the rehearsal stops before any downgrade mutation when refused."""
    import shutil

    upgraded_path = tmp_path / "upgraded-divergent.db"
    backup_path = tmp_path / "upgraded-divergent.backup.db"
    restored_path = tmp_path / "restored-divergent.db"

    engine = create_async_engine(f"sqlite+aiosqlite:///{upgraded_path}")
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _v37_seed_authority_records(conn, divergent=True)
        await _v37_quiesce_and_verify(conn)
    await engine.dispose()

    shutil.copy(upgraded_path, backup_path)
    shutil.copy(backup_path, restored_path)

    restored_engine = create_async_engine(f"sqlite+aiosqlite:///{restored_path}")
    try:
        async with restored_engine.connect() as conn:
            before = await _v37_authority_references(conn)
            refused = [
                preset_id for preset_id, explicit in before["explicit"].items()
                if next(row["legacy_id"] for row in before["legacy"] if row["id"] == preset_id) != explicit
            ]
            assert refused == [2, 3]
            if not refused:
                # The rehearsal mutates only after a clean refusal check.
                await conn.execute(text("ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"))
                await conn.commit()
            # Refusal stopped the rehearsal before the downgrade mutation.
            columns = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_presets)"))).all()}
            assert "leader_slot_id" in columns
            unchanged = await _v37_authority_references(conn)
            assert unchanged == before
    finally:
        await restored_engine.dispose()


@pytest.mark.asyncio
async def test_v17_migration_preserves_authority_identities_and_resolves_consumers():
    """V17: real migration preserves every authority identity for real consumers.

    Covers tied positions, a disabled first slot with an enabled successor,
    all-disabled and empty rosters, missing and foreign assignments, repeated
    startup, and a real Python consumer read after migration.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.agent_team_service import agent_team_service

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"))
            await conn.execute(text(
                "INSERT INTO agent_team_presets (id, name, created_at, updated_at, autonomy_enabled) VALUES "
                "(1, 'tied', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
                "(2, 'disabled-first', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
                "(3, 'all-disabled', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
                "(4, 'empty', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            ))
            await conn.execute(text(
                "INSERT INTO agent_team_slots (id, preset_id, position, display_name, provider, repo_id, "
                "repo_path, repo_name, launch_mode, enabled, created_at, updated_at) VALUES "
                "(10, 1, 0, 'tied-a', 'codex-cli', 'a', '/a', 'a', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(11, 1, 0, 'tied-b', 'codex-cli', 'b', '/b', 'b', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(20, 2, 0, 'disabled-first', 'codex-cli', 'c', '/c', 'c', 'plain', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(21, 2, 1, 'enabled-successor', 'codex-cli', 'd', '/d', 'd', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(30, 3, 0, 'off', 'codex-cli', 'e', '/e', 'e', 'plain', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            # Full authority records attached to the tied team.
            await conn.execute(text(
                "INSERT INTO mail_team_members (id, identity_key, repo_id, repo_path, repo_name, display_name, "
                "participant_kind, team_preset_id, team_slot_id, created_at, updated_at) VALUES "
                "(7, 'slot:7', 'a', '/a', 'a', 'owner-member', 'team_slot', 1, 11, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(8, 'slot:8', 'a', '/a', 'a', 'leader-member', 'team_slot', 1, 10, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO mail_agent_sessions (id, member_id, provider, source, session_key, wake_enabled, "
                "mailbox_status, last_seen_at, team_preset_id, team_slot_id, bound_pane_pid, bound_pane_proc_start, capability_token_hash, created_at) VALUES "
                "(21, 7, 'codex-cli', 'mcp', 'mcp:21', 1, 'connected', CURRENT_TIMESTAMP, 1, 11, 1001, '1', "
                "'test-cap-owner', CURRENT_TIMESTAMP), "
                "(22, 8, 'codex-cli', 'mcp', 'mcp:22', 1, 'connected', CURRENT_TIMESTAMP, 1, 10, 1002, '1', "
                "'test-cap-leader', CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO agent_pane_bindings (pane_pid, pane_proc_start, slot_id, preset_id, created_at) VALUES "
                "(1001, '1', 11, 1, CURRENT_TIMESTAMP), (1002, '1', 10, 1, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path, dispatch_label, "
                "design_label, merge_policy, github_auth_mode, base_ref, max_approval_rounds, "
                "max_concurrent_dispatched, max_verification_retries, max_auto_merges_per_day, "
                "max_build_parallelism, builds_out_of_tree, continuation_enabled, max_continuation_revisions, "
                "max_continuation_failed_heads, max_failed_heads_per_revision, max_scope_paths, "
                "max_scope_commands, enabled, created_at, updated_at) "
                "VALUES (1, 1, 'example', 'a', '/a', 'ready', 'design', 'human', 'ambient', 'origin/main', "
                "3, 1, 1, 0, 1, 0, 0, 6, 8, 2, 32, 16, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, issue_url, "
                "github_updated_at, issue_type, dispatch_status, attempt_phase, owner_slot_id, "
                "handoff_target_slot_id, ack_approver_member_id, active_scope_revision, approval_round_count, "
                "retry_count, diagnostic_retry_count, created_at, updated_at) "
                "VALUES (1, 1, 7, 'title', 'https://example.invalid/7', CURRENT_TIMESTAMP, 'code', "
                "'verifying', 'implementation', 10, 11, 7, 0, 1, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_workspaces (id, scope_id, path, kind, dispatchable, enabled, leased_item_id, "
                "lease_token, created_at, updated_at) VALUES "
                "(1, 1, '/work/1', 'worktree', 1, 1, 1, 'active-lease', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(2, 1, '/work/2', 'worktree', 1, 1, NULL, 'residual-lease', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_approval_requests (id, work_item_id, request_kind, dispatch_nonce, "
                "approval_round, owner_member_id, leader_member_id, request_fingerprint, status, created_at) VALUES "
                "(1, 1, 'initial', 'v17-nonce', 1, 7, 8, 'v17-pending', 'pending', CURRENT_TIMESTAMP), "
                "(2, 1, 'initial', 'v17-nonce-2', 1, 7, 8, 'v17-approved', 'approved', CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision, "
                "owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths, allowed_actions, "
                "allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha, baseline_tree_sha, "
                "originating_escalation_reason, expected_workspace_id, expected_lease_token_hash, max_failed_heads, "
                "failed_head_count, status, delivery_attempt_count, created_at) "
                "VALUES (1, 1, 'v17-nonce', 0, 10, 7, 'implementation', '/work/1', 'v17 revision', '[]', '[]', "
                "'[]', '[]', '{}', :head, :tree, 'fixture', 1, 'v17-hash', 2, 0, 'active', 0, CURRENT_TIMESTAMP)"
            ), {"head": "a" * 40, "tree": "b" * 40})
            await conn.commit()

            before = await _v37_authority_references(conn)
            assert before["explicit"] is None

            await _run_sqlite_compat_migrations(conn)
            after = await _v37_authority_references(conn)

            # Every authority identity survives the real migration unchanged.
            for key in ("presets", "slots", "members", "sessions", "pane_bindings", "items", "workspaces",
                        "approval_requests", "revisions"):
                assert after[key] == before[key], key

            # Assignments: tied picks the lower id, a disabled first slot defers to
            # its enabled successor, all-disabled and empty rosters stay unassigned.
            assert after["explicit"] == {1: 10, 2: 21, 3: None, 4: None}
            assert [row["legacy_id"] for row in after["legacy"]] == [10, 21, None, None]

            # Repeated startup preserves explicit and invalid assignments without
            # overwriting them through the legacy resolver.
            await conn.execute(text("UPDATE agent_team_presets SET leader_slot_id = 11 WHERE id = 1"))
            await conn.execute(text("UPDATE agent_team_presets SET leader_slot_id = 999999 WHERE id = 4"))
            await conn.commit()
            await _run_sqlite_compat_migrations(conn)
            again = await _v37_authority_references(conn)
            assert again["explicit"] == {1: 11, 2: 21, 3: None, 4: 999999}
            for key in ("members", "sessions", "pane_bindings", "items", "workspaces", "approval_requests", "revisions"):
                assert again[key] == before[key], key

        # Real Python consumer: the service read surfaces the explicit assignment.
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            preset_one = await agent_team_service.get_preset(session, 1)
            assert preset_one.leader_slot_id == 11
            preset_four = await agent_team_service.get_preset(session, 4)
            assert preset_four.leader_slot_id == 999999
    finally:
        await engine.dispose()
