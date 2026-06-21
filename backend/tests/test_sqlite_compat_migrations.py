"""SQLite compatibility migration regressions."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import (
    _sqlite_agent_team_slots_has_unique_preset_repo_index,
    _sqlite_columns,
    _sqlite_rebuild_agent_team_slots,
)


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
