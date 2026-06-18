"""Database setup with SQLAlchemy async."""
from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)


# For SQLite: enable WAL so readers don't block writers (and vice versa).
# Without this, writes can stall
# concurrent chart/page reads and can surface "database is locked" under
# load. WAL is a one-time pragma that persists in the DB header.
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """Dependency for getting async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _sqlite_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _sqlite_columns(conn, table_name: str) -> set[str]:
    result = await conn.execute(text(f"PRAGMA table_info({_sqlite_ident(table_name)})"))
    return {row[1] for row in result.fetchall()}


async def _sqlite_has_unique_repo_id_index(conn) -> bool:
    result = await conn.execute(text("PRAGMA index_list(mail_team_members)"))
    for row in result.fetchall():
        index_name = row[1]
        is_unique = bool(row[2])
        if not is_unique:
            continue
        info = await conn.execute(text(f"PRAGMA index_info({_sqlite_ident(index_name)})"))
        if [index_row[2] for index_row in info.fetchall()] == ["repo_id"]:
            return True
    return False


async def _sqlite_rebuild_mail_team_members(conn, columns: set[str]) -> None:
    """Replace the legacy repo-unique table without losing referencing rows."""
    await conn.commit()
    await conn.execute(text("PRAGMA foreign_keys=OFF"))
    await conn.commit()

    identity_expr = (
        "COALESCE(NULLIF(identity_key, ''), 'repo:' || repo_id)"
        if "identity_key" in columns
        else "'repo:' || repo_id"
    )
    participant_kind_expr = (
        "COALESCE(NULLIF(participant_kind, ''), 'repo')"
        if "participant_kind" in columns
        else "'repo'"
    )
    team_preset_expr = "team_preset_id" if "team_preset_id" in columns else "NULL"
    team_slot_expr = "team_slot_id" if "team_slot_id" in columns else "NULL"
    last_inbox_expr = (
        "last_inbox_checked_at" if "last_inbox_checked_at" in columns else "NULL"
    )

    await conn.execute(text("DROP TABLE IF EXISTS mail_team_members_new"))
    await conn.execute(
        text(
            """
            CREATE TABLE mail_team_members_new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                identity_key VARCHAR NOT NULL,
                repo_id VARCHAR NOT NULL,
                repo_path VARCHAR NOT NULL,
                repo_name VARCHAR NOT NULL,
                display_name VARCHAR NOT NULL,
                participant_kind VARCHAR NOT NULL,
                team_preset_id INTEGER,
                team_slot_id INTEGER,
                role VARCHAR,
                charter VARCHAR,
                last_inbox_checked_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(team_preset_id) REFERENCES agent_team_presets (id) ON DELETE SET NULL,
                FOREIGN KEY(team_slot_id) REFERENCES agent_team_slots (id) ON DELETE SET NULL
            )
            """
        )
    )
    await conn.execute(
        text(
            f"""
            INSERT INTO mail_team_members_new (
                id,
                identity_key,
                repo_id,
                repo_path,
                repo_name,
                display_name,
                participant_kind,
                team_preset_id,
                team_slot_id,
                role,
                charter,
                last_inbox_checked_at,
                created_at,
                updated_at
            )
            SELECT
                id,
                {identity_expr},
                repo_id,
                repo_path,
                repo_name,
                display_name,
                {participant_kind_expr},
                {team_preset_expr},
                {team_slot_expr},
                role,
                charter,
                {last_inbox_expr},
                created_at,
                updated_at
            FROM mail_team_members
            """
        )
    )
    await conn.execute(text("DROP TABLE mail_team_members"))
    await conn.execute(text("ALTER TABLE mail_team_members_new RENAME TO mail_team_members"))
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX ix_mail_team_members_identity_key "
            "ON mail_team_members (identity_key)"
        )
    )
    await conn.execute(text("CREATE INDEX ix_mail_team_members_repo_id ON mail_team_members (repo_id)"))
    await conn.execute(
        text("CREATE INDEX ix_mail_team_members_team_preset_id ON mail_team_members (team_preset_id)")
    )
    await conn.execute(
        text("CREATE INDEX ix_mail_team_members_team_slot_id ON mail_team_members (team_slot_id)")
    )
    await conn.commit()
    await conn.execute(text("PRAGMA foreign_keys=ON"))
    await conn.commit()


async def _run_sqlite_compat_migrations(conn) -> None:
    columns = await _sqlite_columns(conn, "mail_team_members")
    if columns:
        if await _sqlite_has_unique_repo_id_index(conn):
            await _sqlite_rebuild_mail_team_members(conn, columns)
            columns = await _sqlite_columns(conn, "mail_team_members")
        if "identity_key" not in columns:
            await conn.execute(text("ALTER TABLE mail_team_members ADD COLUMN identity_key VARCHAR"))
        if "participant_kind" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE mail_team_members "
                    "ADD COLUMN participant_kind VARCHAR DEFAULT 'repo'"
                )
            )
        if "team_preset_id" not in columns:
            await conn.execute(text("ALTER TABLE mail_team_members ADD COLUMN team_preset_id INTEGER"))
        if "team_slot_id" not in columns:
            await conn.execute(text("ALTER TABLE mail_team_members ADD COLUMN team_slot_id INTEGER"))
        if "last_inbox_checked_at" not in columns:
            await conn.execute(
                text("ALTER TABLE mail_team_members ADD COLUMN last_inbox_checked_at DATETIME")
            )
        await conn.execute(
            text(
                "UPDATE mail_team_members "
                "SET identity_key = 'repo:' || repo_id "
                "WHERE identity_key IS NULL OR identity_key = ''"
            )
        )
        await conn.execute(
            text(
                "UPDATE mail_team_members "
                "SET participant_kind = 'repo' "
                "WHERE participant_kind IS NULL OR participant_kind = ''"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_mail_team_members_identity_key "
                "ON mail_team_members (identity_key)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_mail_team_members_repo_id "
                "ON mail_team_members (repo_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_mail_team_members_team_preset_id "
                "ON mail_team_members (team_preset_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_mail_team_members_team_slot_id "
                "ON mail_team_members (team_slot_id)"
            )
        )

    result = await conn.execute(text("PRAGMA table_info(mail_agent_sessions)"))
    session_columns = {row[1] for row in result.fetchall()}
    if session_columns and "team_preset_id" not in session_columns:
        await conn.execute(
            text("ALTER TABLE mail_agent_sessions ADD COLUMN team_preset_id INTEGER")
        )
    if session_columns and "team_slot_id" not in session_columns:
        await conn.execute(text("ALTER TABLE mail_agent_sessions ADD COLUMN team_slot_id INTEGER"))

    result = await conn.execute(text("PRAGMA table_info(agent_team_slots)"))
    slot_columns = {row[1] for row in result.fetchall()}
    if slot_columns and "bootstrap_prompt" not in slot_columns:
        await conn.execute(
            text("ALTER TABLE agent_team_slots ADD COLUMN bootstrap_prompt VARCHAR")
        )

    result = await conn.execute(text("PRAGMA table_info(agent_team_launch_items)"))
    launch_item_columns = {row[1] for row in result.fetchall()}
    if launch_item_columns and "message" not in launch_item_columns:
        await conn.execute(
            text("ALTER TABLE agent_team_launch_items ADD COLUMN message VARCHAR")
        )
    if launch_item_columns and "block_code" not in launch_item_columns:
        await conn.execute(
            text("ALTER TABLE agent_team_launch_items ADD COLUMN block_code VARCHAR")
        )

    result = await conn.execute(text("PRAGMA table_info(mail_messages)"))
    message_columns = {row[1] for row in result.fetchall()}
    if message_columns and "sender_actor_id" not in message_columns:
        await conn.execute(text("ALTER TABLE mail_messages ADD COLUMN sender_actor_id INTEGER"))
    await conn.commit()


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if settings.database_url.startswith("sqlite"):
        async with engine.connect() as conn:
            await _run_sqlite_compat_migrations(conn)
