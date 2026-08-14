"""SQLite compatibility migration regressions."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import (
    _run_sqlite_compat_migrations,
    _sqlite_agent_team_slots_has_unique_preset_repo_index,
    _sqlite_columns,
    _sqlite_rebuild_agent_team_slots,
)


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
            message_columns = {"approval_round", "decision"}
            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)
                assert work_item_columns <= await _sqlite_columns(
                    conn, "github_work_items"
                )
                assert message_columns <= await _sqlite_columns(conn, "mail_messages")
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
