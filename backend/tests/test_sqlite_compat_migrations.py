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
