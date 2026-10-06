"""V37 shared executable restored-copy procedure cases.

Every procedure-level ADMIT or REFUSE claim runs through
``tests.factory.restored_copy_procedure.run_restored_copy_procedure``. The
earlier rehearsal tests remain supporting unit evidence only. Synthetic
quiescence in these fixtures is not a real work-completion claim. V14 remains
NOT_PERFORMED.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base
from tests.factory.restored_copy_procedure import (
    DISPOSABLE_MARKER_NAME,
    PROCEDURE_STEPS,
    run_restored_copy_procedure,
)
from tests.test_sqlite_compat_migrations import (
    _v37_quiesce_and_verify,
    _v37_seed_authority_records,
)


async def _prepare(tmp_path: Path, *, name: str, divergent: bool, quiesce: bool):
    (tmp_path / DISPOSABLE_MARKER_NAME).write_text("disposable test target")
    source = tmp_path / name
    engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _v37_seed_authority_records(conn, divergent=divergent)
        if quiesce:
            await _v37_quiesce_and_verify(conn)
    await engine.dispose()
    return source


@pytest.mark.asyncio
async def test_shared_procedure_admits_representable_with_nine_step_log(tmp_path):
    """The representable case returns ADMIT through the shared procedure."""
    source = await _prepare(tmp_path, name="admit.db", divergent=False, quiesce=True)
    record = run_restored_copy_procedure(
        source_path=source, work_root=tmp_path,
        pause_state={"automation_paused": True})

    assert record["outcome"] == "ADMIT"
    assert record["refusal_code"] is None
    # Root2025: all nine literal documented steps, in order, none omitted.
    assert [entry["step"] for entry in record["step_log"]] == list(PROCEDURE_STEPS)
    assert all(entry["state"] == "ADMIT" for entry in record["step_log"])
    # AC4: the comparison record covers every reference-scope entry.
    assert set(record["comparison_record"]) == {
        "explicit_assignments", "slots", "members", "sessions", "pane_bindings",
        "items", "messages", "presets", "workspaces", "scope_policy",
        "approval_requests", "revisions"}
    # Synthetic-quiescence and separate-release limits stay explicit.
    assert "not a real" in record["limits"]["synthetic_quiescence"]
    assert record["limits"]["v14"] == "NOT_PERFORMED"
    assert record["limits"]["separate_release_required"] is True


@pytest.mark.asyncio
async def test_shared_procedure_refuses_divergent_assignments_before_any_mutation(tmp_path):
    """The divergent and unrepresentable case returns REFUSE unchanged."""
    source = await _prepare(tmp_path, name="refuse.db", divergent=True, quiesce=True)
    from tests.factory.restored_copy_procedure import _digest_set
    digest_before = _digest_set(source)
    record = run_restored_copy_procedure(
        source_path=source, work_root=tmp_path,
        pause_state={"automation_paused": True})

    assert record["outcome"] == "REFUSE"
    assert record["refusal_code"] == "assignment_unrepresentable"
    assert [entry["step"] for entry in record["step_log"]] == list(PROCEDURE_STEPS)
    refusal = next(entry for entry in record["step_log"] if entry["state"] == "REFUSE")
    assert refusal["step"] == PROCEDURE_STEPS[5]
    assert "2" in refusal["detail"] and "3" in refusal["detail"]
    assert all(entry["state"] == "NOT_REACHED"
               for entry in record["step_log"][6:]), "no step after refusal runs"
    # Refusal evidence shows unchanged digests and rows before any mutation.
    unchanged = record["unchanged_evidence"]
    assert unchanged["source_digest"] == digest_before
    assert unchanged["reference_scope"] == unchanged["pre_mutation_reference_scope"]
    assert _digest_set(source) == digest_before
    restored = tmp_path / "procedure-restored.db"
    columns = {row[1] for row in sqlite3.connect(restored).execute(
        "PRAGMA table_info(agent_team_presets)").fetchall()}
    assert "leader_slot_id" in columns, "the explicit-authority version is kept"


@pytest.mark.asyncio
async def test_shared_procedure_refuses_unverified_pause_without_backup(tmp_path):
    """S1: an unverified pause stops the procedure before any backup."""
    source = await _prepare(tmp_path, name="pause.db", divergent=False, quiesce=True)
    record = run_restored_copy_procedure(
        source_path=source, work_root=tmp_path,
        pause_state={"automation_paused": False})

    assert record["outcome"] == "REFUSE"
    assert record["refusal_code"] == "pause_unverified"
    assert not (tmp_path / "procedure-backup.db").exists()
    assert record["step_log"][0]["state"] == "REFUSE"


@pytest.mark.asyncio
async def test_shared_procedure_refuses_residual_authority_before_backup(tmp_path):
    """S2/AC5: quiescence covers residual authority fields, not only leases."""
    source = await _prepare(tmp_path, name="residual.db", divergent=False, quiesce=False)
    from tests.factory.restored_copy_procedure import _digest_set
    digest_before = _digest_set(source)
    record = run_restored_copy_procedure(
        source_path=source, work_root=tmp_path,
        pause_state={"automation_paused": True})

    assert record["outcome"] == "REFUSE"
    assert record["refusal_code"] == "quiescence_residual"
    detail = record["step_log"][1]["detail"]
    for label in ("residual workspace authority", "pending approval",
                  "nonterminal revision", "nonterminal attempt"):
        assert label in detail
    assert record["step_log"][2]["state"] == "NOT_REACHED", "no backup after refusal"
    assert record["unchanged_evidence"]["source_digest"] == digest_before
    assert _digest_set(source) == digest_before


@pytest.mark.asyncio
async def test_shared_procedure_refuses_non_disposable_target_at_interface(tmp_path):
    """S9/AC6: any non-disposable target is refused at the procedure interface."""
    # The target sits next to the checked-in tests, which may live under a
    # temp directory. Without the explicit disposable marker the procedure
    # must refuse regardless of path heuristics.
    repo_target = Path(__file__).resolve().parent / "v37-production-target.db"
    repo_target.write_bytes(b"not a disposable copy")
    try:
        record = run_restored_copy_procedure(
            source_path=repo_target, work_root=repo_target.parent,
            pause_state={"automation_paused": True})
    finally:
        repo_target.unlink()

    assert record["outcome"] == "REFUSE"
    assert record["refusal_code"] == "production_target_refused"
    assert record["step_log"][8]["step"] == PROCEDURE_STEPS[8]
    assert record["step_log"][8]["state"] == "REFUSE"
    assert record["limits"]["real_restore_or_downgrade"] == "NOT_PERFORMED"


def test_shared_procedure_covers_wal_side_files_at_boundaries(tmp_path):
    """C-6: side files are digested at boundaries; a WAL change cannot hide
    behind a released lock and an unchanged main-file digest."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.database import Base
    from tests.factory.restored_copy_procedure import _digest_set

    async def run():
        (tmp_path / DISPOSABLE_MARKER_NAME).write_text("disposable test target")
        source = tmp_path / "wal.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _v37_seed_authority_records(conn, divergent=False)
            await _v37_quiesce_and_verify(conn)
        await engine.dispose()
        digests = _digest_set(source)
        # The helper tracks main and any side files as one boundary record.
        assert set(digests) == {"main"} or set(digests) == {"main", "-wal", "-shm"}
        record = run_restored_copy_procedure(
            source_path=source, work_root=tmp_path,
            pause_state={"automation_paused": True})
        assert record["outcome"] == "ADMIT"
        assert record["unchanged_evidence"]["source_digest"] == digests

    asyncio.run(run())


def test_shared_procedure_refuses_writer_after_stop_claim(tmp_path):
    """C-6: a separate connection writing after the stop claim is refused at
    the final boundary. A released lock and a main-file digest do not
    establish stopped writers; WAL-aware boundary digests do."""
    import asyncio
    import sqlite3 as _sqlite3

    from sqlalchemy.ext.asyncio import create_async_engine

    import tests.factory.restored_copy_procedure as procedure_module
    from app.database import Base

    async def run():
        (tmp_path / DISPOSABLE_MARKER_NAME).write_text("disposable test target")
        source = tmp_path / "latewriter.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _v37_seed_authority_records(conn, divergent=False)
            await _v37_quiesce_and_verify(conn)
        await engine.dispose()

        original_digest_set = procedure_module._digest_set
        calls = {"source_reads": 0}

        def intercepting_digest_set(path):
            if path == source:
                calls["source_reads"] += 1
                if calls["source_reads"] == 3:
                    # The third source digest is the final boundary check. A
                    # separate disposable connection wrote after the stop
                    # claim; the boundary must see the change and refuse.
                    writer = _sqlite3.connect(source)
                    writer.execute(
                        "UPDATE agent_team_presets SET name = 'late-writer' WHERE id = 1")
                    writer.commit()
                    writer.close()
            return original_digest_set(path)

        procedure_module._digest_set = intercepting_digest_set
        try:
            record = procedure_module.run_restored_copy_procedure(
                source_path=source, work_root=tmp_path,
                pause_state={"automation_paused": True})
        finally:
            procedure_module._digest_set = original_digest_set

        assert calls["source_reads"] >= 3
        assert record["outcome"] == "REFUSE"
        assert record["refusal_code"] == "writer_after_stop"
        unchanged = record["unchanged_evidence"]
        assert unchanged["source_digest_after_stop_claim"] != unchanged["source_digest_final"]

    asyncio.run(run())


def test_shared_procedure_refuses_six_restored_copy_mutations(tmp_path):
    """C5/R4: injected restored-copy mutations of required authority
    references each refuse. Only the removed assignment column is
    normalized."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    import tests.factory.restored_copy_procedure as procedure_module
    from app.database import Base

    mutations = {
        "session_pid": "UPDATE mail_agent_sessions SET pid = 5555 WHERE id = 21",
        "slot_position": "UPDATE agent_team_slots SET position = position + 5 WHERE id = 10",
        "preset_autonomy": "UPDATE agent_team_presets SET autonomy_enabled = 1 - autonomy_enabled WHERE id = 1",
        "ack_evidence": "UPDATE github_work_items SET ack_approver_member_id = NULL WHERE id = 1",
        "ack_evidence_link": "UPDATE github_work_items SET ack_evidence_message_id = 999 WHERE id = 1",
        "ack_round": "UPDATE github_work_items SET ack_approval_round = 9 WHERE id = 1",
        "ack_epoch": "UPDATE github_work_items SET ack_enforcement_epoch = 9 WHERE id = 1",
        "decision_link": "UPDATE github_approval_requests SET decision_message_id = 999 WHERE id = 1",
        "deleted_request_message": "DELETE FROM mail_messages WHERE id = 100",
    }

    async def run():
        (tmp_path / DISPOSABLE_MARKER_NAME).write_text("disposable test target")
        source = tmp_path / "mutations.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _v37_seed_authority_records(conn, divergent=False)
            await _v37_quiesce_and_verify(conn)
        await engine.dispose()

        for name, sql in mutations.items():
            original_capture = procedure_module.capture_reference_scope
            calls = {"n": 0}

            def intercepting_capture(conn, _sql=sql, _original=original_capture):
                calls["n"] += 1
                if calls["n"] == 3:
                    # The third capture is the post-downgrade comparison on
                    # the restored copy (the first is the pre-mutation
                    # baseline, the second is the assignment record). Inject
                    # the mutation into that copy before the comparison.
                    conn.execute(_sql)
                    conn.commit()
                return _original(conn)

            procedure_module.capture_reference_scope = intercepting_capture
            try:
                record = procedure_module.run_restored_copy_procedure(
                    source_path=source, work_root=tmp_path,
                    pause_state={"automation_paused": True})
            finally:
                procedure_module.capture_reference_scope = original_capture
            assert record["outcome"] == "REFUSE", (name, record["outcome"])
            assert record["refusal_code"] == "restored_copy_diverged", (name, record["refusal_code"])

    asyncio.run(run())


def test_shared_procedure_backup_contains_committed_wal_state(tmp_path):
    """C6/R5: a committed WAL-mode change before the procedure run is folded
    into the protected state and present in the admitted backup."""
    import asyncio
    import sqlite3 as _sqlite3

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.database import Base

    async def run():
        (tmp_path / DISPOSABLE_MARKER_NAME).write_text("disposable test target")
        source = tmp_path / "walstate.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{source}")
        async with engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.run_sync(Base.metadata.create_all)
        async with engine.connect() as conn:
            await _v37_seed_authority_records(conn, divergent=False)
            await _v37_quiesce_and_verify(conn)
        await engine.dispose()

        # A separate WAL-mode connection commits before the procedure run.
        writer = _sqlite3.connect(source)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE github_work_items SET approval_round_count = 7 WHERE id = 1")
        writer.commit()
        writer.close()

        record = run_restored_copy_procedure(
            source_path=source, work_root=tmp_path,
            pause_state={"automation_paused": True})
        assert record["outcome"] == "ADMIT"
        # The comparison record is the backup content: the committed WAL
        # state is inside the protected logical state.
        items = record["comparison_record"]["items"]
        assert items and items[0]["approval_round_count"] == 7
        restored = tmp_path / "procedure-restored.db"
        check = _sqlite3.connect(restored)
        value = check.execute(
            "SELECT approval_round_count FROM github_work_items WHERE id = 1").fetchone()[0]
        check.close()
        assert value == 7

    asyncio.run(run())
