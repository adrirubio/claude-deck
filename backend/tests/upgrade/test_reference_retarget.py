"""T-D7/T-D8 ownership, exact allocations, atomic stamps and live references."""
import sqlite3
from datetime import datetime, timedelta

import pytest

from .reference_startup_harness import (
    OLD, create_database, digest, journal, publish, reference, rows, run_reference,
)


def test_t_d7_shared_partition_union_follows_exact_collision_allocations(tmp_path):
    home = tmp_path / 'home'
    first = reference(home)
    second = reference(home, move=first['move_journal_id'], suffix='b')
    path = create_database(tmp_path / 'synth_city.db', [first, second])
    history = rows(path, 'history')
    run_reference(path, [first, second], home)
    assert [r['file_path'] for r in rows(path, 'backups')] == [
        r['resources']['backups']['mappings'][0]['target'] for r in (first, second)]
    for actual, record in zip(rows(path, 'bridge_session_attachments'), (first, second)):
        target = record['resources']['attachments']['mappings'][0]['target']
        assert (actual['storage_path'], actual['agent_path'], actual['prompt_text']) == (
            target, target, 'Inspect "' + target + '"')
    stamps = rows(path, 'upgrade_reference_stamps')
    assert len(stamps) == 4
    assert {(s['reference_record_id'], s['resource'], s['move_journal_id'], s['record_digest'])
            for s in stamps} == {(r['id'], resource, r['move_journal_id'], digest(r))
                                   for r in (first, second) for resource in r['resources']}
    assert rows(path, 'history') == history
    assert not journal(home, first).exists() and not journal(home, second).exists()


def test_t_d8_unmapped_and_custom_values_are_not_guessed(tmp_path, caplog):
    home = tmp_path / 'home'
    record = reference(home)
    excluded = home / OLD / 'backups' / 'custom'
    record['diagnostics']['excluded'] = [str(excluded)]
    publish(home, record)
    path = create_database(tmp_path / 'db', [record])
    values = [str(home / OLD / 'backups/missing.zip'), str(excluded / 'keep.zip'),
              str(home / (OLD + '-other') / 'backups/a.zip'), str(tmp_path / 'custom.zip')]
    with sqlite3.connect(path) as db:
        db.executemany('INSERT INTO backups(file_path) VALUES (?)', [(v,) for v in values])
    run_reference(path, [record], home)
    assert [row['file_path'] for row in rows(path, 'backups')][1:] == values
    assert 'ambiguous' in caplog.text.lower()
    assert all(value not in caplog.text for value in values)


def test_t_d8_expired_storage_only_and_exact_prompt_boundaries(tmp_path):
    home = tmp_path / 'home'
    record = reference(home, resources=('attachments',))
    path = create_database(tmp_path / 'db', [record])
    old, new = (record['resources']['attachments']['mappings'][0][k] for k in ('source', 'target'))
    prompt = f'Inspect "{old}" and `{old}`; keep {old}.other and prefix{old}'
    with sqlite3.connect(path) as db:
        db.execute('UPDATE bridge_session_attachments SET prompt_text=?', (prompt,))
        db.execute('INSERT INTO bridge_session_attachments '
            '(storage_path,agent_path,prompt_text,expires_at) VALUES (?,?,?,?)',
            (old, old, 'Expired ' + old, (datetime.utcnow() - timedelta(days=1)).isoformat()))
    from app.upgrade_references import complete_reference_upgrade
    complete_reference_upgrade(path, [record], home=home,
        agent_path=lambda storage: '/agent-view/' + storage.name)
    live, expired = rows(path, 'bridge_session_attachments')
    assert live['storage_path'] == new and live['agent_path'] == '/agent-view/a.allocated.bin'
    assert live['prompt_text'] == prompt.replace('"' + old + '"', '"' + live['agent_path'] + '"').replace(
        '`' + old + '`', '`' + live['agent_path'] + '`')
    assert (expired['storage_path'], expired['agent_path'], expired['prompt_text']) == (new, old, 'Expired ' + old)


@pytest.mark.parametrize('mismatch', ['digest', 'move'])
def test_stamp_identity_mismatch_retains_all_records_without_rewrite(tmp_path, mismatch):
    home = tmp_path / 'home'
    record = reference(home)
    path = create_database(tmp_path / 'db', [record])
    before = rows(path, 'backups'), rows(path, 'bridge_session_attachments')
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO upgrade_reference_stamps VALUES (?,?,?,?,?)',
                   (record['id'], 'backups', record['move_journal_id'] if mismatch == 'digest'
                    else '00000000-0000-0000-0000-000000000000',
                    '0' * 64 if mismatch == 'digest' else digest(record), '2026-01-01'))
    with pytest.raises(RuntimeError, match='identity|digest'):
        run_reference(path, [record], home)
    assert (rows(path, 'backups'), rows(path, 'bridge_session_attachments')) == before
    assert journal(home, record).exists()


@pytest.mark.parametrize('template', [
    'No verifiable attachment path here', 'prefix{path}', '{path}.other',
    'Inspect {path}; also {path}#unresolved',
])
def test_t_d8_unresolved_live_prompt_rolls_back_resource_and_keeps_shared_records(tmp_path, template):
    home = tmp_path / 'home'
    first = reference(home)
    second = reference(home, move=first['move_journal_id'], suffix='b')
    path = create_database(tmp_path / 'db', [first, second])
    old = second['resources']['attachments']['mappings'][0]['source']
    prompt = template.replace('{path}', old)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE bridge_session_attachments SET prompt_text=? WHERE id=2', (prompt,))
    before = rows(path, 'bridge_session_attachments')
    history = rows(path, 'history')
    with pytest.raises(RuntimeError, match='prompt') as failure:
        run_reference(path, [first, second], home)
    assert old not in str(failure.value) and prompt not in str(failure.value)
    assert rows(path, 'bridge_session_attachments') == before
    assert not [s for s in rows(path, 'upgrade_reference_stamps') if s['resource'] == 'attachments']
    assert len(rows(path, 'upgrade_reference_stamps')) == 2  # prior backup transaction may commit
    assert rows(path, 'history') == history
    assert all(journal(home, record).exists() for record in (first, second))
