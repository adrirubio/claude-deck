"""Isolated reference fixtures; the pinned v3.1 fixture remains unchanged."""
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
import shutil
import subprocess
import sys


OLD = '.claude-registry'
NEW = '.albiex-synth-city'


def reference(home, *, resources=('backups', 'attachments'), move=None, suffix='a'):
    record = {'version': 1, 'kind': 'references', 'id': str(uuid.uuid4()),
              'move_journal_id': move or str(uuid.uuid4()), 'stage': 'files_landed',
              'resources': {}, 'diagnostics': {'excluded': [], 'unmapped': []}}
    for resource in resources:
        folder = 'backups' if resource == 'backups' else 'bridge-attachments'
        source, target = home / OLD / folder, home / NEW / folder
        record['resources'][resource] = {'source_root': str(source), 'target_root': str(target),
            'mappings': [{'source': str(source / (suffix + '.bin')),
                          'target': str(target / (suffix + '.allocated.bin'))}]}
        landed = target / (suffix + '.allocated.bin')
        landed.parent.mkdir(parents=True, exist_ok=True)
        landed.write_bytes((resource + suffix).encode())
    publish(home, record)
    return record


def journal(home, record):
    return home / ('.albiex-synth-city-upgrade.' + record['id'] + '.references.json')


def publish(home, record):
    home.mkdir(parents=True, exist_ok=True)
    journal(home, record).write_text(json.dumps(record))


def digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode('ascii')).hexdigest()


def create_database(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        db.executescript('''
            CREATE TABLE backups (id INTEGER PRIMARY KEY, file_path TEXT NOT NULL);
            CREATE TABLE bridge_session_attachments (id INTEGER PRIMARY KEY,
                storage_path TEXT NOT NULL, agent_path TEXT NOT NULL,
                prompt_text TEXT NOT NULL, expires_at DATETIME);
            CREATE TABLE upgrade_reference_stamps (
                reference_record_id TEXT NOT NULL, resource TEXT NOT NULL,
                move_journal_id TEXT NOT NULL, record_digest TEXT NOT NULL,
                completed_at DATETIME NOT NULL,
                PRIMARY KEY (reference_record_id, resource));
            CREATE TABLE history (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
        ''')
        for record in records:
            for resource, entry in record['resources'].items():
                for row in entry['mappings']:
                    if resource == 'backups':
                        db.execute('INSERT INTO backups(file_path) VALUES (?)', (row['source'],))
                    else:
                        db.execute('INSERT INTO bridge_session_attachments '
                            '(storage_path,agent_path,prompt_text,expires_at) VALUES (?,?,?,?)',
                            (row['source'], row['source'], 'Inspect "' + row['source'] + '"', None))
                    db.execute('INSERT INTO history(body) VALUES (?)', (row['source'],))
    return path


def rows(path, table):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]


def run_reference(path, records, home, **kwargs):
    from app.upgrade_references import complete_reference_upgrade
    return complete_reference_upgrade(path, records, home=home,
        agent_path=lambda storage: str(storage), **kwargs)


def run_fixture_code(install, code, *, environment=None):
    backend = Path(__file__).resolve().parents[2]
    for name in ('app', 'mcp_shim'):
        shutil.rmtree(install.app_dir / name)
        shutil.copytree(backend / name, install.app_dir / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    env = {'HOME': str(install.home), 'PATH': '/usr/local/bin:/usr/bin:/bin',
           'PYTHONPATH': str(install.app_dir) + ':' + str(backend),
           'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8',
           'OPERATOR_TOKEN': 'synthetic-upgrade-operator'}
    env.update(environment or {})
    result = subprocess.run([sys.executable, '-c', code], cwd=install.app_dir,
        env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-5000:]
    return result
