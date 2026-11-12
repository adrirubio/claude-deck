"""Bounded structured-reference rewrite after the immutable file phase.

The SQLite commit and its identity-bound stamps are one transaction per
move/resource. A completed native WAL checkpoint is a separate durability
barrier. Only that barrier permits retirement of the immutable v1 records.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

from app.upgrade_bootstrap import (
    FileOps, HOME_JOURNAL_PREFIX, reference_phase_lock, retire_reference_record,
)


logger = logging.getLogger(__name__)


class ReferenceOps(FileOps):
    """Native SQLite/POSIX boundary, injectable without runtime fail switches."""

    def open_database(self, path: Path):
        # The file phase has already selected and landed this exact database.
        # mode=rw prevents a typo/missing file from creating an empty database.
        db = sqlite3.connect('file:' + quote(str(path), safe='/') + '?mode=rw',
                             uri=True, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def execute(self, db, sql, parameters=()):
        return db.execute(sql, parameters)


@dataclass
class ReferenceState:
    home: Path
    database: Path | None
    records: list[dict]
    ops: ReferenceOps


@contextmanager
def reference_startup(configured_url: str, *, test_instance=False,
                      home: Path | None = None, cwd: Path | None = None,
                      ops: ReferenceOps | None = None):
    """Take startup ownership before the first engine connection is opened."""
    ops = ops or ReferenceOps()
    if test_instance:
        home = home or Path.home()
        # Test instances must never move/replay operator data or create locks.
        # They also cannot silently treat pending recovery as complete. Inspect
        # names only; do not read payloads or suppress an unreadable directory.
        try:
            with os.scandir(home) as entries:
                pending = any(entry.name.startswith(HOME_JOURNAL_PREFIX)
                              and entry.name.endswith('.json') for entry in entries)
        except FileNotFoundError:
            pending = False
        except OSError:
            raise RuntimeError('Test instance cannot safely inspect pending upgrade recovery records') from None
        if pending:
            raise RuntimeError('Test instance cannot start with pending upgrade recovery records')
        yield ReferenceState(home, None, [], ops)
        return
    try:
        with reference_phase_lock(configured_url, home=home, cwd=cwd, ops=ops) as (home, path, records):
            if records and path is None:
                raise RuntimeError('Upgrade references require verified file-backed SQLite durability; '
                                   'pending journals retained')
            yield ReferenceState(home, path, records, ops)
    except OSError as error:
        raise RuntimeError(f'Upgrade reference filesystem failure ({error.errno}); '
                           'recovery records retained where not durably retired') from None


def _digest(record):
    value = json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _stamp(db, record, resource, ops):
    row = ops.execute(db, 'SELECT move_journal_id, record_digest FROM upgrade_reference_stamps '
        'WHERE reference_record_id=? AND resource=?', (record['id'], resource)).fetchone()
    if row is not None and (row[0] != record['move_journal_id'] or row[1] != _digest(record)):
        raise RuntimeError('Upgrade reference stamp identity/digest mismatch; journal retained')
    return row is not None


def _owned_target(value, source_root, mapping, excluded, known_sources, resource, identity):
    path = Path(value).expanduser()
    if not path.is_absolute():
        return None
    path = path.resolve()
    if not path.is_relative_to(source_root):
        return None
    if any(path.is_relative_to(entry) for entry in excluded):
        return None
    target = mapping.get(str(path))
    if target is None and str(path) not in known_sources:
        # IDs identify the affected structured record without disclosing any
        # stored prompt, operator path, URL, or credential in startup logs.
        logger.warning('Upgrade reference ambiguous: resource=%s row_id=%s; value unchanged', resource, identity)
    return target


def _retarget_prompt(prompt, old, new):
    if old == new:
        return prompt
    # The stored agent path is the structured token in this one prompt field.
    # Sentence punctuation and image:path are supported custom templates. A
    # period followed by filename characters still belongs to a longer name.
    edge = r'''[\s"'`)\]}>;,!?=:]'''
    pattern = (r'''(?<![^\s"'`(\[<{=:;,!?])''' + re.escape(old)
               + rf'(?=$|{edge}|\.+(?=$|{edge}))')
    matched = {match.span() for match in re.finditer(pattern, prompt)} if old else set()
    for match in re.finditer(re.escape(old), prompt) if old else ():
        if match.span() in matched:
            continue
        before = prompt[match.start() - 1:match.start()] if match.start() else ''
        after = prompt[match.end():match.end() + 1]
        # Preserve known filename/path continuations and prefix lookalikes.
        # Any other unmatched occurrence is ambiguous, even if another token
        # was matched: rolling back is safer than retiring a partial rewrite.
        if any(char and (char.isalnum() or char in '/\\._-~') for char in (before, after)):
            continue
        raise RuntimeError('Upgrade live attachment prompt path cannot be verified; journals retained')
    if not matched:
        raise RuntimeError('Upgrade live attachment prompt path cannot be verified; journals retained')
    return re.sub(pattern, lambda _: new, prompt)


def _live(expires, now):
    if expires is None:
        return True
    expiry = datetime.fromisoformat(expires)
    if expiry.tzinfo is not None:
        expiry = expiry.astimezone(UTC).replace(tzinfo=None)
    return expiry > now


def _retarget_resource(db, records, all_records, resource, ops, agent_path, now):
    entries = [record['resources'][resource] for record in records]
    source_root = Path(entries[0]['source_root'])
    mapping = {row['source']: row['target'] for entry in entries for row in entry['mappings']}
    excluded = [Path(path) for record in all_records for path in record['diagnostics']['excluded']]
    known_sources = {row['source'] for record in all_records
        for entry in record['resources'].values() for row in entry['mappings']}
    if resource == 'backups':
        for row in ops.execute(db, 'SELECT id, file_path FROM backups').fetchall():
            target = _owned_target(row[1], source_root, mapping, excluded, known_sources, resource, row[0])
            if target is not None:
                ops.execute(db, 'UPDATE backups SET file_path=? WHERE id=?', (target, row[0]))
    else:
        for row in ops.execute(db, 'SELECT id, storage_path, agent_path, prompt_text, expires_at '
                               'FROM bridge_session_attachments').fetchall():
            target = _owned_target(row[1], source_root, mapping, excluded, known_sources, resource, row[0])
            if target is None:
                continue
            if _live(row[4], now):
                display = agent_path(Path(target))
                prompt = _retarget_prompt(row[3], row[2], display)
                ops.execute(db, 'UPDATE bridge_session_attachments SET storage_path=?,agent_path=?,'
                               'prompt_text=? WHERE id=?', (target, display, prompt, row[0]))
            else:
                ops.execute(db, 'UPDATE bridge_session_attachments SET storage_path=? WHERE id=?', (target, row[0]))


def _barrier(db, ops):
    # Changing synchronous after a NORMAL commit does not itself flush that
    # commit. The completed checkpoint syncs WAL before backfill and the main
    # database afterwards. Reject busy/incomplete/non-WAL no-op results.
    ops.execute(db, 'PRAGMA synchronous=FULL')
    if ops.execute(db, 'PRAGMA synchronous').fetchone()[0] != 2:
        raise RuntimeError('Upgrade reference durability mode cannot be verified')
    if ops.execute(db, 'PRAGMA journal_mode').fetchone()[0] != 'wal':
        raise RuntimeError('Upgrade reference WAL durability cannot be verified')
    result = ops.execute(db, 'PRAGMA wal_checkpoint(FULL)').fetchone()
    if (result is None or len(result) != 3 or result[0] != 0 or result[1] < 0
            or result[1] != result[2]):
        raise RuntimeError('Upgrade reference durability checkpoint is incomplete; journals retained')


def complete_reference_upgrade(database: Path | None, records: list[dict], *, home: Path,
                               ops: ReferenceOps | None = None, agent_path=None, now=None):
    """Called under reference_startup, after create_all/compat, before services.

    Stamps are per immutable record, not a digest of the surviving subset: a
    power cut can restore only some already-retired records. Existing stamps
    skip rewrites but never skip the checkpoint barrier or identity checks.
    """
    if not records:
        return
    if database is None:
        raise RuntimeError('Upgrade references require verified file-backed SQLite durability')
    ops = ops or ReferenceOps()
    if agent_path is None:
        from app.services.agent_bridge.attachments import agent_bridge_attachment_service
        agent_path = agent_bridge_attachment_service._agent_path
    now = now or datetime.now(UTC).replace(tzinfo=None)
    db = None
    try:
        db = ops.open_database(database)
        if ops.execute(db, 'PRAGMA journal_mode').fetchone()[0] != 'wal':
            raise RuntimeError('Upgrade references require verified WAL durability; journals retained')
        ops.execute(db, 'PRAGMA wal_autocheckpoint=0')
        ops.execute(db, 'PRAGMA synchronous=NORMAL')
        ops.execute(db, 'PRAGMA foreign_keys=ON')
        # Validate every surviving identity before the first resource changes.
        for record in records:
            for resource in record['resources']:
                _stamp(db, record, resource, ops)
        for move in sorted({record['move_journal_id'] for record in records}):
            for resource in ('backups', 'attachments'):
                group = [record for record in records if record['move_journal_id'] == move
                         and resource in record['resources']]
                if not group:
                    continue
                ops.execute(db, 'BEGIN IMMEDIATE')
                try:
                    stamped = [_stamp(db, record, resource, ops) for record in group]
                    if not all(stamped):
                        _retarget_resource(db, group, records, resource, ops, agent_path, now)
                        ops.checkpoint('reference_rows_updated:' + resource, database)
                        for record, exists in zip(group, stamped):
                            if not exists:
                                ops.execute(db, 'INSERT INTO upgrade_reference_stamps '
                                    '(reference_record_id,resource,move_journal_id,record_digest,completed_at) '
                                    'VALUES (?,?,?,?,?)', (record['id'], resource, move, _digest(record), now.isoformat()))
                        ops.checkpoint('reference_stamps_written:' + resource, database)
                    ops.execute(db, 'COMMIT')
                except Exception:
                    db.rollback()
                    raise
                ops.checkpoint('reference_committed:' + resource, database)
        _barrier(db, ops)
        ops.checkpoint('reference_barrier_verified', database)
        for index, record in enumerate(records):
            if not all(_stamp(db, record, resource, ops) for resource in record['resources']):
                raise RuntimeError('Upgrade reference resource completion is incomplete')
            path = retire_reference_record(home, record, ops)
            ops.checkpoint('reference_record_unlinked:' + str(index), path)
            ops.sync_dir(home)
            ops.checkpoint('reference_record_retired:' + str(index), path)
    except sqlite3.Error as error:
        # SQLite errors can contain data values. Only publish a stable code.
        code = getattr(error, 'sqlite_errorname', 'SQLITE_ERROR')
        raise RuntimeError(f'Upgrade reference database failure ({code}); journals retained') from None
    finally:
        if db is not None:
            db.close()
