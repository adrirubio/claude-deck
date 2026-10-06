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
    PROCEDURE_STEPS,
    run_restored_copy_procedure,
)
from tests.test_sqlite_compat_migrations import (
    _v37_quiesce_and_verify,
    _v37_seed_authority_records,
)


async def _prepare(tmp_path: Path, *, name: str, divergent: bool, quiesce: bool):
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
        "explicit_assignments", "members", "sessions", "pane_bindings",
        "items", "workspaces", "approval_requests", "revisions"}
    # Synthetic-quiescence and separate-release limits stay explicit.
    assert "not a real" in record["limits"]["synthetic_quiescence"]
    assert record["limits"]["v14"] == "NOT_PERFORMED"
    assert record["limits"]["separate_release_required"] is True


@pytest.mark.asyncio
async def test_shared_procedure_refuses_divergent_assignments_before_any_mutation(tmp_path):
    """The divergent and unrepresentable case returns REFUSE unchanged."""
    source = await _prepare(tmp_path, name="refuse.db", divergent=True, quiesce=True)
    digest_before = hashlib.sha256(source.read_bytes()).hexdigest()
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
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest_before
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
    digest_before = hashlib.sha256(source.read_bytes()).hexdigest()
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
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest_before


@pytest.mark.asyncio
async def test_shared_procedure_refuses_non_disposable_target_at_interface(tmp_path):
    """S9/AC6: any non-disposable target is refused at the procedure interface."""
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
