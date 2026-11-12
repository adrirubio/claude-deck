"""T-D3 entry points and T-D5 two real starts; all resources are disposable."""
import os
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

from .database_startup_harness import run_entrypoint
from .test_database_move import database_files, seed_bytes, start
from .v31_fixture import build_v31_install


@pytest.mark.parametrize('entrypoint', ['uvicorn', 'dev', 'factory'])
def test_t_d3_all_entrypoints_serve_old_fixture_on_first_response(tmp_path, entrypoint):
    run_entrypoint(build_v31_install(tmp_path / 'install'), entrypoint)


@pytest.mark.parametrize('dotenv', [False, True])
def test_db_binding_explicit_env_and_dotenv_survive_two_starts_without_operator_edits(tmp_path, dotenv):
    install = build_v31_install(tmp_path / 'install')
    configured = 'sqlite+aiosqlite:///./claude_registry.db'
    run_entrypoint(install, 'uvicorn', configured, dotenv)
    # Code replacement is now already in place; the harness repeats normal start.
    run_entrypoint(install, 'factory', configured, dotenv)


@pytest.mark.parametrize('cut', ['journal_durable', 'landed:-wal'])
def test_t_d5_two_racing_starts_have_one_owner_and_no_half_open(tmp_path, cut):
    seed_bytes(tmp_path)
    original = database_files(tmp_path)
    ready = tmp_path / 'owner-ready'
    release = tmp_path / 'owner-release'
    script = '''
from pathlib import Path
import sys, time
from app.upgrade_bootstrap import FileOps, prepare_database_url
root=Path(sys.argv[1])
class Owner(FileOps):
    def checkpoint(self, stage, path):
        if stage == sys.argv[2]:
            (root/'owner-ready').write_text('ready')
            limit=time.monotonic()+20
            while not (root/'owner-release').exists():
                if time.monotonic()>limit: raise AssertionError('owner release timeout')
                time.sleep(.02)
prepare_database_url('sqlite+aiosqlite:///./synth_city.db', explicit=False,
    cwd=root,home=root/'home',ops=Owner())
'''
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
        'PYTHONPATH': str(Path(__file__).resolve().parents[2]), 'LANG': 'C.UTF-8'}
    owner = subprocess.Popen([sys.executable, '-c', script, str(tmp_path), cut],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists(), owner.communicate(timeout=2)[1] if owner.poll() is not None else 'owner never acquired lock'
        owned_state = database_files(tmp_path)
        result = subprocess.run([sys.executable, '-c', script.replace('ops=Owner()', 'ops=FileOps()'), str(tmp_path), cut],
            env=environment, capture_output=True, text=True, timeout=10)
        assert result.returncode != 0
        assert 'upgrade in progress' in result.stderr.lower()
        assert database_files(tmp_path) == owned_state
        release.write_text('continue')
        out, error = owner.communicate(timeout=10)
        assert owner.returncode == 0, error
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.communicate(timeout=5)
    start(tmp_path)
    assert database_files(tmp_path) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in original.items()}


@pytest.mark.parametrize('existing', [False, True])
def test_backend_test_bootstrap_cannot_retire_an_installations_binding(tmp_path, existing):
    """Only a synthetic HOME is exposed, even on the intentionally red run."""
    home = tmp_path / 'installation-home'
    metadata = home / '.albiex-synth-city'
    home.mkdir()
    database = tmp_path / 'synth_city.db'
    database.write_bytes(b'synthetic-installation-bytes')
    binding = metadata / 'upgrade-location-bindings.json'
    if existing:
        metadata.mkdir()
        binding.write_text(json.dumps({'version': 1, 'resources': {'database': {
            'old_path': str(tmp_path / 'claude_registry.db'), 'new_path': str(database),
            'journal_id': str(uuid.uuid4()), 'state': 'active',
        }}}))
    original = binding.read_bytes() if existing else None
    environment = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
        'PYTHONPATH': str(Path(__file__).resolve().parents[2])}
    result = subprocess.run([sys.executable, '-c', 'import tests.conftest; import app.database'],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert (binding.read_bytes() if binding.exists() else None) == original
    assert metadata.exists() == existing
    assert not (tmp_path / '.albiex-synth-city-db-upgrade.lock').exists()
    assert database.read_bytes() == b'synthetic-installation-bytes'


@pytest.mark.parametrize('cut', ['journal_durable', 'landed:', 'source_removed:-wal', 'journal_unlinked'])
def test_t_d5_abrupt_process_exit_releases_lock_and_resumes_without_open(tmp_path, cut):
    seed_bytes(tmp_path)
    original = database_files(tmp_path)
    script = '''
from pathlib import Path
import os, sys
from app.upgrade_bootstrap import FileOps, prepare_database_url
root = Path(sys.argv[1])
class Crash(FileOps):
    def checkpoint(self, stage, path):
        if stage == sys.argv[2]:
            os._exit(75)
prepare_database_url('sqlite+aiosqlite:///./synth_city.db', explicit=False,
    cwd=root, home=root/'home', ops=Crash())
'''
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
        'PYTHONPATH': str(Path(__file__).resolve().parents[2]), 'LANG': 'C.UTF-8'}
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), cut],
        env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 75, result.stderr
    for name, data in original.items():
        assert any(path.exists() and path.read_bytes() == data for path in
            (tmp_path / name, tmp_path / name.replace('claude_registry.db', 'synth_city.db')))
    start(tmp_path)
    final = {name.replace('claude_registry.db', 'synth_city.db'): data for name, data in original.items()}
    assert database_files(tmp_path) == final
    assert not list(tmp_path.glob('.albiex-synth-city-db-upgrade.*.json'))
    start(tmp_path)
    assert database_files(tmp_path) == final


def test_pre_engine_hook_settles_the_whole_set_before_engine_construction(tmp_path):
    seed_bytes(tmp_path)
    original = database_files(tmp_path)
    script = '''
from pathlib import Path
from unittest.mock import patch
import sqlalchemy.ext.asyncio as sql
root = Path.cwd()
original = sql.create_async_engine
calls = []
def observe(url, *args, **kwargs):
    assert not (root/'claude_registry.db').exists(), 'engine constructed before move'
    assert (root/'synth_city.db').is_file(), 'engine would create empty database'
    assert not list(root.glob('.albiex-synth-city-db-upgrade.*.json')), 'journal not retired'
    calls.append(url)
    return original(url, *args, **kwargs)
with patch.object(sql, 'create_async_engine', observe):
    import app.database
assert len(calls) == 1
'''
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
        'PYTHONPATH': str(Path(__file__).resolve().parents[2]), 'LANG': 'C.UTF-8'}
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
        env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert database_files(tmp_path) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in original.items()}


def test_t_d4_startup_conflict_prevents_every_sqlite_connection(tmp_path):
    seed_bytes(tmp_path)
    (tmp_path / 'synth_city.db-wal').write_bytes(b'unexplained-target')
    original = database_files(tmp_path)
    script = '''
import sys
def guard(event, args):
    if event == 'sqlite3.connect':
        raise AssertionError('SQLite connection attempted before conflict refusal')
sys.addaudithook(guard)
import app.database
'''
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
        'PYTHONPATH': str(Path(__file__).resolve().parents[2]), 'LANG': 'C.UTF-8'}
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
        env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'Database upgrade conflict' in result.stderr
    assert str(tmp_path / 'claude_registry.db') in result.stderr
    assert str(tmp_path / 'synth_city.db') in result.stderr
    assert 'SQLite connection attempted' not in result.stderr
    assert database_files(tmp_path) == original
