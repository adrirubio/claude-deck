"""Database setup with SQLAlchemy async."""
import hashlib
import json

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


async def _sqlite_create_approval_tables(conn) -> None:
    from app.models.database import GithubApprovalRequest, GithubAttemptScopeRevision

    def create_tables(sync_conn) -> None:
        GithubApprovalRequest.__table__.create(sync_conn, checkfirst=True)
        GithubAttemptScopeRevision.__table__.create(sync_conn, checkfirst=True)
        for table in (
            GithubApprovalRequest.__table__,
            GithubAttemptScopeRevision.__table__,
        ):
            for index in table.indexes:
                index.create(sync_conn, checkfirst=True)

    await conn.run_sync(create_tables)


async def _sqlite_ensure_unique_partial_index(
    conn,
    *,
    table_name: str,
    index_name: str,
    columns: tuple[str, ...],
    predicate: str,
    duplicate_preflight: str,
) -> None:
    index_rows = (
        await conn.execute(text(f"PRAGMA index_list({_sqlite_ident(table_name)})"))
    ).all()
    index_row = next((row for row in index_rows if row[1] == index_name), None)
    index_columns: tuple[str, ...] = ()
    index_sql = None
    if index_row is not None:
        index_columns = tuple(
            row[2]
            for row in (
                await conn.execute(
                    text(f"PRAGMA index_info({_sqlite_ident(index_name)})")
                )
            ).all()
        )
        index_sql = (
            await conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND name = :index_name"
                ),
                {"index_name": index_name},
            )
        ).scalar_one_or_none()
    normalized_sql = "".join(str(index_sql or "").lower().split())
    normalized_predicate = "".join(predicate.lower().split())
    valid = (
        index_row is not None
        and index_row[2] == 1
        and index_row[4] == 1
        and index_columns == columns
        and f"where{normalized_predicate}" in normalized_sql
    )
    if valid:
        return
    duplicate = (await conn.execute(text(duplicate_preflight))).first()
    if duplicate is not None:
        raise RuntimeError(
            f"cannot repair {index_name}: duplicate constrained rows exist"
        )
    if index_row is not None:
        await conn.execute(text(f"DROP INDEX {_sqlite_ident(index_name)}"))
    column_sql = ", ".join(_sqlite_ident(column) for column in columns)
    await conn.execute(
        text(
            f"CREATE UNIQUE INDEX {_sqlite_ident(index_name)} "
            f"ON {_sqlite_ident(table_name)} ({column_sql}) WHERE {predicate}"
        )
    )


def _canonical_payload_fingerprint(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _historical_approval_payload(payload: dict, body_markdown: str) -> dict:
    summary = payload.get("summary")
    if not isinstance(summary, str):
        summary = body_markdown
    plan_metadata = payload.get("plan_metadata")
    if not isinstance(plan_metadata, dict):
        plan_metadata = {}
    return {
        "plan_metadata": plan_metadata,
        "summary": summary.strip(),
    }


async def _sqlite_reconcile_historical_approvals(conn) -> bool:
    required_columns = {
        "github_work_items": {
            "id",
            "scope_id",
            "owner_slot_id",
            "dispatch_nonce",
            "approval_round_count",
            "status_note",
        },
        "team_github_scopes": {"id", "preset_id"},
        "agent_team_slots": {"id", "preset_id", "position", "enabled"},
        "mail_team_members": {"id", "team_slot_id", "updated_at"},
        "mail_messages": {
            "id",
            "kind",
            "sender_member_id",
            "recipient_member_id",
            "thread_root_id",
            "payload",
            "request_status",
            "body_markdown",
        },
    }
    for table_name, columns in required_columns.items():
        if not columns <= await _sqlite_columns(conn, table_name):
            return False

    items = (
        await conn.execute(
            text(
                """
                SELECT item.id,
                       item.dispatch_nonce,
                       item.approval_round_count,
                       owner.id AS owner_member_id,
                       leader.id AS leader_member_id
                FROM github_work_items AS item
                JOIN team_github_scopes AS scope ON scope.id = item.scope_id
                JOIN mail_team_members AS owner
                  ON owner.id = (
                      SELECT candidate.id
                      FROM mail_team_members AS candidate
                      WHERE candidate.team_slot_id = item.owner_slot_id
                      ORDER BY candidate.updated_at DESC, candidate.id DESC
                      LIMIT 1
                  )
                JOIN agent_team_slots AS leader_slot
                  ON leader_slot.id = (
                      SELECT candidate.id
                      FROM agent_team_slots AS candidate
                      WHERE candidate.preset_id = scope.preset_id
                        AND candidate.enabled = 1
                      ORDER BY candidate.position, candidate.id
                      LIMIT 1
                  )
                JOIN mail_team_members AS leader
                  ON leader.id = (
                      SELECT candidate.id
                      FROM mail_team_members AS candidate
                      WHERE candidate.team_slot_id = leader_slot.id
                      ORDER BY candidate.updated_at DESC, candidate.id DESC
                      LIMIT 1
                  )
                WHERE item.dispatch_nonce IS NOT NULL
                  AND item.approval_round_count >= 1
                """
            )
        )
    ).mappings().all()

    for item in items:
        existing = (
            await conn.execute(
                text(
                    """
                    SELECT id
                    FROM github_approval_requests
                    WHERE work_item_id = :work_item_id
                      AND status = 'pending'
                    LIMIT 1
                    """
                ),
                {"work_item_id": item["id"]},
            )
        ).first()
        if existing is not None:
            continue
        roots = (
            await conn.execute(
                text(
                    """
                    SELECT id, payload, body_markdown
                    FROM mail_messages
                    WHERE kind = 'context_request'
                      AND thread_root_id IS NULL
                      AND sender_member_id = :owner_member_id
                      AND recipient_member_id = :leader_member_id
                      AND request_status = 'pending'
                    ORDER BY id
                    """
                ),
                {
                    "owner_member_id": item["owner_member_id"],
                    "leader_member_id": item["leader_member_id"],
                },
            )
        ).mappings().all()
        matches: list[tuple[int, dict]] = []
        for root in roots:
            payload = root["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            if (
                payload.get("work_item_id") == item["id"]
                and payload.get("dispatch_nonce") == item["dispatch_nonce"]
                and payload.get("approval_round") == item["approval_round_count"]
            ):
                matches.append((root["id"], payload))

        if len(matches) == 1:
            request_message_id, payload = matches[0]
            root = next(root for root in roots if root["id"] == request_message_id)
            await conn.execute(
                text(
                    """
                    INSERT INTO github_approval_requests (
                        work_item_id,
                        request_kind,
                        dispatch_nonce,
                        approval_round,
                        owner_member_id,
                        leader_member_id,
                        request_message_id,
                        request_fingerprint,
                        status,
                        created_at
                    ) VALUES (
                        :work_item_id,
                        'initial_plan',
                        :dispatch_nonce,
                        :approval_round,
                        :owner_member_id,
                        :leader_member_id,
                        :request_message_id,
                        :request_fingerprint,
                        'pending',
                        CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "work_item_id": item["id"],
                    "dispatch_nonce": item["dispatch_nonce"],
                    "approval_round": item["approval_round_count"],
                    "owner_member_id": item["owner_member_id"],
                    "leader_member_id": item["leader_member_id"],
                    "request_message_id": request_message_id,
                    "request_fingerprint": _canonical_payload_fingerprint(
                        _historical_approval_payload(payload, root["body_markdown"])
                    ),
                },
            )
        elif len(matches) > 1:
            await conn.execute(
                text(
                    "UPDATE mail_messages SET request_status = 'superseded' "
                    "WHERE id IN (" + ", ".join(str(match[0]) for match in matches) + ")"
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE github_work_items
                    SET status_note = :status_note
                    WHERE id = :work_item_id
                    """
                ),
                {
                    "work_item_id": item["id"],
                    "status_note": (
                        "Multiple current approval requests were found during migration; "
                        "submit one fresh approval request."
                    ),
                },
            )

    return True


_APPROVAL_RECONCILIATION_MIGRATION = "pr1_historical_approval_reconciliation"


async def _sqlite_approval_reconciliation_pending(conn) -> bool:
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS deck_compat_migrations ("
            "name VARCHAR PRIMARY KEY, applied_at DATETIME NOT NULL)"
        )
    )
    return (
        await conn.execute(
            text(
                "SELECT 1 FROM deck_compat_migrations WHERE name = :name"
            ),
            {"name": _APPROVAL_RECONCILIATION_MIGRATION},
        )
    ).first() is None


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


async def _sqlite_agent_team_slots_has_unique_preset_repo_index(conn) -> bool:
    result = await conn.execute(text("PRAGMA index_list(agent_team_slots)"))
    for row in result.fetchall():
        index_name = row[1]
        is_unique = bool(row[2])
        if not is_unique:
            continue
        info = await conn.execute(text(f"PRAGMA index_info({_sqlite_ident(index_name)})"))
        if [index_row[2] for index_row in info.fetchall()] == ["preset_id", "repo_id"]:
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


async def _sqlite_rebuild_agent_team_slots(conn, columns: set[str]) -> None:
    """Replace the legacy same-repo-unique slots table without losing slot ids."""
    await conn.commit()
    await conn.execute(text("PRAGMA foreign_keys=OFF"))
    await conn.commit()

    bootstrap_expr = "bootstrap_prompt" if "bootstrap_prompt" in columns else "NULL"
    launch_mode_expr = "COALESCE(NULLIF(launch_mode, ''), 'plain')" if "launch_mode" in columns else "'plain'"
    launch_options_expr = "launch_options" if "launch_options" in columns else "NULL"
    enabled_expr = "COALESCE(enabled, 1)" if "enabled" in columns else "1"

    await conn.execute(text("DROP TABLE IF EXISTS agent_team_slots_new"))
    await conn.execute(
        text(
            """
            CREATE TABLE agent_team_slots_new (
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
                bootstrap_prompt VARCHAR,
                launch_mode VARCHAR NOT NULL,
                launch_options JSON,
                enabled BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(preset_id) REFERENCES agent_team_presets (id) ON DELETE CASCADE
            )
            """
        )
    )
    await conn.execute(
        text(
            f"""
            INSERT INTO agent_team_slots_new (
                id,
                preset_id,
                position,
                display_name,
                provider,
                repo_id,
                repo_path,
                repo_name,
                role,
                charter,
                bootstrap_prompt,
                launch_mode,
                launch_options,
                enabled,
                created_at,
                updated_at
            )
            SELECT
                id,
                preset_id,
                position,
                display_name,
                provider,
                repo_id,
                repo_path,
                repo_name,
                role,
                charter,
                {bootstrap_expr},
                {launch_mode_expr},
                {launch_options_expr},
                {enabled_expr},
                created_at,
                updated_at
            FROM agent_team_slots
            """
        )
    )
    await conn.execute(text("DROP TABLE agent_team_slots"))
    await conn.execute(text("ALTER TABLE agent_team_slots_new RENAME TO agent_team_slots"))
    await conn.execute(
        text("CREATE INDEX ix_agent_team_slots_preset_id ON agent_team_slots (preset_id)")
    )
    await conn.execute(text("CREATE INDEX ix_agent_team_slots_repo_id ON agent_team_slots (repo_id)"))
    await conn.commit()
    await conn.execute(text("PRAGMA foreign_keys=ON"))
    await conn.commit()


async def _run_sqlite_compat_migrations(conn) -> None:
    reconcile_historical_approvals = (
        await _sqlite_approval_reconciliation_pending(conn)
    )
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
    if session_columns and "capability_token_hash" not in session_columns:
        await conn.execute(
            text("ALTER TABLE mail_agent_sessions ADD COLUMN capability_token_hash TEXT")
        )
    if session_columns and "bound_pane_pid" not in session_columns:
        await conn.execute(
            text("ALTER TABLE mail_agent_sessions ADD COLUMN bound_pane_pid INTEGER")
        )
    if session_columns and "bound_pane_proc_start" not in session_columns:
        await conn.execute(
            text("ALTER TABLE mail_agent_sessions ADD COLUMN bound_pane_proc_start TEXT")
        )

    result = await conn.execute(text("PRAGMA table_info(agent_team_slots)"))
    slot_columns = {row[1] for row in result.fetchall()}
    if slot_columns and await _sqlite_agent_team_slots_has_unique_preset_repo_index(conn):
        await _sqlite_rebuild_agent_team_slots(conn, slot_columns)
        slot_columns = await _sqlite_columns(conn, "agent_team_slots")
    if slot_columns and "bootstrap_prompt" not in slot_columns:
        await conn.execute(
            text("ALTER TABLE agent_team_slots ADD COLUMN bootstrap_prompt VARCHAR")
        )
    if slot_columns and "ui_color" not in slot_columns:
        await conn.execute(text("ALTER TABLE agent_team_slots ADD COLUMN ui_color VARCHAR"))
    if slot_columns and "area_labels" not in slot_columns:
        await conn.execute(text("ALTER TABLE agent_team_slots ADD COLUMN area_labels JSON"))
    if slot_columns and "expertise" not in slot_columns:
        await conn.execute(text("ALTER TABLE agent_team_slots ADD COLUMN expertise VARCHAR"))

    result = await conn.execute(text("PRAGMA table_info(agent_team_presets)"))
    preset_columns = {row[1] for row in result.fetchall()}
    if preset_columns and "autonomy_enabled" not in preset_columns:
        await conn.execute(
            text("ALTER TABLE agent_team_presets ADD COLUMN autonomy_enabled BOOLEAN DEFAULT 0 NOT NULL")
        )

    result = await conn.execute(text("PRAGMA table_info(team_github_scopes)"))
    scope_columns = {row[1] for row in result.fetchall()}
    if scope_columns and "max_concurrent_dispatched" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN max_concurrent_dispatched INTEGER DEFAULT 3 NOT NULL")
        )
    if scope_columns and "max_verification_retries" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN max_verification_retries INTEGER DEFAULT 2 NOT NULL")
        )
    if scope_columns and "max_auto_merges_per_day" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN max_auto_merges_per_day INTEGER DEFAULT 5 NOT NULL")
        )
    if scope_columns and "base_ref" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN base_ref VARCHAR DEFAULT 'origin/HEAD' NOT NULL")
        )
    if scope_columns and "builds_out_of_tree" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN builds_out_of_tree BOOLEAN DEFAULT 0 NOT NULL")
        )
    if scope_columns and "build_dir_template" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN build_dir_template VARCHAR DEFAULT 'build'")
        )
    if scope_columns and "build_command_hint" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN build_command_hint VARCHAR")
        )
    if scope_columns and "max_build_parallelism" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN max_build_parallelism INTEGER DEFAULT 4 NOT NULL")
        )
    if scope_columns and "github_auth_mode" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN github_auth_mode VARCHAR DEFAULT 'unknown' NOT NULL")
        )
    if scope_columns and "github_app_installation_id" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN github_app_installation_id INTEGER")
        )
    if scope_columns and "continuation_enabled" not in scope_columns:
        await conn.execute(
            text(
                "ALTER TABLE team_github_scopes ADD COLUMN "
                "continuation_enabled BOOLEAN DEFAULT 0 NOT NULL"
            )
        )
    if scope_columns and "max_continuation_revisions" not in scope_columns:
        await conn.execute(
            text(
                "ALTER TABLE team_github_scopes ADD COLUMN "
                "max_continuation_revisions INTEGER DEFAULT 6 NOT NULL"
            )
        )
    if scope_columns and "max_continuation_failed_heads" not in scope_columns:
        await conn.execute(
            text(
                "ALTER TABLE team_github_scopes ADD COLUMN "
                "max_continuation_failed_heads INTEGER DEFAULT 8 NOT NULL"
            )
        )
    if scope_columns and "max_failed_heads_per_revision" not in scope_columns:
        await conn.execute(
            text(
                "ALTER TABLE team_github_scopes ADD COLUMN "
                "max_failed_heads_per_revision INTEGER DEFAULT 2 NOT NULL"
            )
        )
    if scope_columns and "max_scope_paths" not in scope_columns:
        await conn.execute(
            text(
                "ALTER TABLE team_github_scopes ADD COLUMN "
                "max_scope_paths INTEGER DEFAULT 32 NOT NULL"
            )
        )
    if scope_columns and "max_scope_commands" not in scope_columns:
        await conn.execute(
            text(
                "ALTER TABLE team_github_scopes ADD COLUMN "
                "max_scope_commands INTEGER DEFAULT 16 NOT NULL"
            )
        )

    result = await conn.execute(text("PRAGMA table_info(github_work_items)"))
    work_item_columns = {row[1] for row in result.fetchall()}
    if work_item_columns and "status_note" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN status_note VARCHAR"))
    if work_item_columns and "auto_merged_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN auto_merged_at DATETIME"))
    if work_item_columns and "last_verified_sha" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN last_verified_sha VARCHAR"))
    if work_item_columns and "dispatched_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatched_at DATETIME"))
    if work_item_columns and "ack_received_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_received_at DATETIME"))
    if work_item_columns and "last_nudge_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN last_nudge_at DATETIME"))
    if work_item_columns and "retry_requested_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN retry_requested_at DATETIME"))
    if work_item_columns and "brief_delivery_nudge_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_delivery_nudge_at DATETIME"))
    if work_item_columns and "brief_delivery_nudge_count" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_delivery_nudge_count INTEGER"))
    if work_item_columns and "brief_message_id" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_message_id INTEGER"))
    if work_item_columns and "ack_approver_member_id" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approver_member_id INTEGER"))
    if work_item_columns and "ack_evidence_message_id" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_evidence_message_id INTEGER"))
    if work_item_columns and "dispatch_nonce" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatch_nonce VARCHAR"))
    if work_item_columns and "ack_enforcement_epoch" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_enforcement_epoch INTEGER"))
    if work_item_columns and "ack_approval_round" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approval_round INTEGER"))
    if work_item_columns and "dispatch_head_ref" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatch_head_ref VARCHAR"))
    if work_item_columns and "dispatch_base_ref" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatch_base_ref VARCHAR"))
    if work_item_columns and "active_scope_revision" not in work_item_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_work_items ADD COLUMN "
                "active_scope_revision INTEGER DEFAULT 0 NOT NULL"
            )
        )
    if work_item_columns and "attempt_phase" not in work_item_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_work_items ADD COLUMN "
                "attempt_phase VARCHAR DEFAULT 'implementation' NOT NULL"
            )
        )
    if work_item_columns and "diagnostic_retry_count" not in work_item_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_work_items ADD COLUMN "
                "diagnostic_retry_count INTEGER DEFAULT 0 NOT NULL"
            )
        )
    if work_item_columns and "diagnostic_last_verified_sha" not in work_item_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_work_items ADD COLUMN "
                "diagnostic_last_verified_sha VARCHAR"
            )
        )
    if work_item_columns and "continuation_nudged_at" not in work_item_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_work_items ADD COLUMN continuation_nudged_at DATETIME"
            )
        )
    if work_item_columns and "continuation_activated_at" not in work_item_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_work_items ADD COLUMN "
                "continuation_activated_at DATETIME"
            )
        )

    workspace_columns = await _sqlite_columns(conn, "github_workspaces")
    if workspace_columns and "lease_token" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN lease_token VARCHAR"))
    if workspace_columns and "push_token_expires_at" not in workspace_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_workspaces "
                "ADD COLUMN push_token_expires_at DATETIME"
            )
        )
    if workspace_columns and "leased_owner_pid" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN leased_owner_pid INTEGER"))
    if workspace_columns and "leased_owner_proc_start" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN leased_owner_proc_start VARCHAR"))
    if workspace_columns and "lease_last_owner_contact_at" not in workspace_columns:
        await conn.execute(
            text("ALTER TABLE github_workspaces ADD COLUMN lease_last_owner_contact_at DATETIME")
        )
    if workspace_columns and "lease_release_reminded_at" not in workspace_columns:
        await conn.execute(
            text("ALTER TABLE github_workspaces ADD COLUMN lease_release_reminded_at DATETIME")
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
    if message_columns and "approval_round" not in message_columns:
        await conn.execute(text("ALTER TABLE mail_messages ADD COLUMN approval_round INTEGER"))
    if message_columns and "decision" not in message_columns:
        await conn.execute(text("ALTER TABLE mail_messages ADD COLUMN decision VARCHAR"))
    if message_columns and "delivery_key" not in message_columns:
        await conn.execute(text("ALTER TABLE mail_messages ADD COLUMN delivery_key VARCHAR"))
    if message_columns:
        await _sqlite_ensure_unique_partial_index(
            conn,
            table_name="mail_messages",
            index_name="ix_mail_messages_delivery_key",
            columns=("delivery_key",),
            predicate="delivery_key IS NOT NULL",
            duplicate_preflight=(
                "SELECT delivery_key FROM mail_messages "
                "WHERE delivery_key IS NOT NULL GROUP BY delivery_key "
                "HAVING COUNT(*) > 1 LIMIT 1"
            ),
        )

    await _sqlite_create_approval_tables(conn)
    revision_columns = await _sqlite_columns(conn, "github_attempt_scope_revisions")
    if revision_columns and "submitted_head_sha" not in revision_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_attempt_scope_revisions "
                "ADD COLUMN submitted_head_sha VARCHAR"
            )
        )
    if revision_columns and "submitted_at" not in revision_columns:
        await conn.execute(
            text(
                "ALTER TABLE github_attempt_scope_revisions "
                "ADD COLUMN submitted_at DATETIME"
            )
        )
    await _sqlite_ensure_unique_partial_index(
        conn,
        table_name="github_approval_requests",
        index_name="uix_github_approval_requests_pending_work_item",
        columns=("work_item_id",),
        predicate="status = 'pending'",
        duplicate_preflight=(
            "SELECT work_item_id FROM github_approval_requests "
            "WHERE status = 'pending' GROUP BY work_item_id "
            "HAVING COUNT(*) > 1 LIMIT 1"
        ),
    )
    if reconcile_historical_approvals:
        reconciliation_complete = await _sqlite_reconcile_historical_approvals(conn)
        if reconciliation_complete:
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO deck_compat_migrations "
                    "(name, applied_at) VALUES (:name, CURRENT_TIMESTAMP)"
                ),
                {"name": _APPROVAL_RECONCILIATION_MIGRATION},
            )
    if {"pr_number", "retry_requested_at"} <= work_item_columns:
        await conn.execute(
            text(
                "UPDATE github_work_items SET retry_requested_at = NULL "
                "WHERE pr_number IS NOT NULL AND retry_requested_at IS NOT NULL"
            )
        )
    await conn.commit()


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if settings.database_url.startswith("sqlite"):
        async with engine.connect() as conn:
            await _run_sqlite_compat_migrations(conn)
