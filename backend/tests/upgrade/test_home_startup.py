"""C5 import isolation, real supported starts, explicit settings and lock order."""
import json
import errno
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

import pytest

from .database_startup_harness import run_entrypoint
from .test_home_move import OLD, NEW, files, put
from .v31_fixture import build_v31_install


BACKEND = Path(__file__).resolve().parents[2]


def environment(home):
    return {'HOME': str(home), 'PATH': '/usr/local/bin:/usr/bin:/bin',
            'PYTHONPATH': str(BACKEND), 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}


def test_conftest_isolates_home_before_import_and_restores_and_cleans_at_exit(tmp_path):
    home = tmp_path / 'operator-home'
    put(home / OLD / 'backups/keep.zip', b'operator-backup')
    put(home / OLD / 'bridge-attachments/keep.png', b'operator-attachment')
    binding = put(home / NEW / 'upgrade-location-bindings.json',
                  b'{"version":1,"resources":{}}')
    before = files(home)
    report = tmp_path / 'exit-report.json'
    script = '''
import atexit, json, os
from pathlib import Path
original=Path.home()
disposable=None
def after_cleanup():
    Path(REPORT).write_text(json.dumps({'restored':Path.home()==original,
        'removed':disposable is not None and not disposable.exists()}))
atexit.register(after_cleanup)
import tests.conftest
disposable=Path.home()
assert disposable != original, 'conftest inherited operator HOME'
assert disposable.is_dir()
import app.database
'''.replace('REPORT', repr(str(report)))
    process = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
        env=environment(home), capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert files(home) == before
    assert binding.read_bytes() == before[str(binding.relative_to(home))]
    assert json.loads(report.read_text()) == {'restored': True, 'removed': True}


@pytest.mark.parametrize('mode', ['uvicorn', 'dev', 'factory'])
def test_supported_entrypoints_complete_home_moves_before_first_connection(tmp_path, mode):
    install = build_v31_install(tmp_path / 'install')
    run_entrypoint(install, mode, home_audit=True)


@pytest.mark.parametrize('dotenv', [False, True])
def test_t_d6_explicit_attachment_env_and_dotenv_remain_identical_across_two_starts(tmp_path, dotenv):
    install = build_v31_install(tmp_path / 'install')
    old = str(install.home / OLD / 'bridge-attachments')
    for mode in ['uvicorn', 'factory']:
        run_entrypoint(install, mode, configured='sqlite+aiosqlite:///./claude_registry.db',
            configured_attachment=old, dotenv=dotenv, home_audit=True)
        assert not (install.home / OLD).exists()
        assert (install.home / NEW / 'bridge-attachments').is_dir()


def test_pre_engine_preallocation_order_and_custom_agent_root_is_display_only(tmp_path):
    home = tmp_path / 'home'
    source = put(home / OLD / 'backups/a.zip', b'backup')
    put(home / OLD / 'bridge-attachments/a.png', b'image')
    script = '''
from pathlib import Path
from unittest.mock import patch
import sqlalchemy.ext.asyncio as sql
from app.config import settings
home=Path.home()
original=sql.create_async_engine
def observed(*args, **kwargs):
    assert (home/'.albiex-synth-city/backups/a.zip').read_bytes()==b'backup'
    assert (home/'.albiex-synth-city/bridge-attachments/a.png').read_bytes()==b'image'
    assert not (home/'.claude-registry').exists(), 'engine can allocate before HOME move'
    assert settings.bridge_attachment_agent_root=='/synthetic/display-only'
    assert settings.bridge_attachment_dir==str(home/'.albiex-synth-city/bridge-attachments')
    return original(*args, **kwargs)
with patch.object(sql, 'create_async_engine', observed):
    import app.database
'''
    env = environment(home) | {'DATABASE_URL': 'sqlite+aiosqlite:///:memory:',
                             'BRIDGE_ATTACHMENT_AGENT_ROOT': '/synthetic/display-only'}
    process = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr
    assert not source.exists()


def test_explicit_database_first_start_migrates_home_from_unwritable_cwd(tmp_path):
    home, cwd = tmp_path / 'home', tmp_path / 'readonly-backend'
    cwd.mkdir()
    source = put(home / OLD / 'backups/a.zip', b'backup')
    database = tmp_path / 'data/custom.db'
    database.parent.mkdir()
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE custom_probe (value TEXT)')
        db.execute("INSERT INTO custom_probe VALUES ('custom-database')")
    identity = database.stat().st_ino
    script = '''
import asyncio, errno, os
from pathlib import Path
cwd = Path.cwd()
# The probe proves the real filesystem permission boundary, before startup.
try:
    descriptor = os.open(cwd/'write-probe', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
except PermissionError as error:
    assert error.errno == errno.EACCES
else:
    os.close(descriptor)
    raise AssertionError('permission regression requires an unwritable cwd')
database = Path(os.environ['CUSTOM_DATABASE'])
original = database.read_bytes()
from app.database import engine, init_db
from app.config import settings
from app.upgrade_references import reference_startup
assert 'database_url' in settings.model_fields_set
with reference_startup(settings.database_url) as state:
    assert state.database == Path(os.environ['CUSTOM_DATABASE'])
    assert state.records, 'HOME move must publish reference recovery evidence'
assert engine.url.database == os.environ['CUSTOM_DATABASE']
assert database.read_bytes() == original, 'file phase changed an explicit database'
async def start():
    await init_db()
    await engine.dispose()
asyncio.run(start())
assert not (cwd/'.albiex-synth-city-db-upgrade.lock').exists()
'''
    cwd.chmod(0o555)
    try:
        process = subprocess.run([sys.executable, '-c', script], cwd=cwd,
            env=environment(home) | {'DATABASE_URL': 'sqlite+aiosqlite:///' + str(database),
                                     'CUSTOM_DATABASE': str(database)},
            capture_output=True, text=True, timeout=15)
    finally:
        cwd.chmod(0o755)
    assert process.returncode == 0, process.stderr
    assert not source.exists()
    assert (home / NEW / 'backups/a.zip').read_bytes() == b'backup'
    assert database.stat().st_ino == identity
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT value FROM custom_probe').fetchall() == [('custom-database',)]
    assert (home / '.albiex-synth-city-db-upgrade.lock').is_file()
    assert (database.parent / '.albiex-synth-city-db-upgrade.lock').is_file()
    assert not list(cwd.iterdir())


@pytest.mark.parametrize('anchor', ['home', 'default-database', 'custom-database'])
def test_lock_creation_failure_names_the_lock_and_operation(tmp_path, anchor):
    from app import upgrade_bootstrap as upgrade
    home, cwd, data = (tmp_path / name for name in ('home', 'backend', 'data'))
    source = put(home / OLD / 'backups/a.zip', b'backup')
    cwd.mkdir()
    data.mkdir()
    parent = {'home': home, 'default-database': cwd, 'custom-database': data}[anchor]
    denied = parent / upgrade.LOCK_NAME
    before = files(home), files(cwd), files(data)
    parent.chmod(0o555)
    try:
        # A root run must not turn this permission regression into a false pass.
        assert not os.access(parent, os.W_OK), 'permission regression requires an unwritable lock parent'
        with pytest.raises(RuntimeError) as failure:
            if anchor == 'custom-database':
                with upgrade.reference_phase_lock('sqlite+aiosqlite:///' + str(data / 'custom.db'),
                                                   home=home, cwd=cwd):
                    pytest.fail('startup continued without the database lock')
            else:
                upgrade.prepare_resource_locations('sqlite+aiosqlite:///./synth_city.db',
                    '~/.albiex-synth-city/bridge-attachments', database_explicit=False,
                    attachment_explicit=False, home=home, cwd=cwd)
    finally:
        parent.chmod(0o755)
    assert str(denied) in str(failure.value)
    assert 'open lock' in str(failure.value).lower()
    assert source.read_bytes() == b'backup'
    assert (files(home), files(cwd), files(data)) == before


def test_lock_acquisition_failure_names_the_lock_and_operation(tmp_path, monkeypatch):
    from app import upgrade_bootstrap as upgrade

    def fail_acquire(descriptor, operation):
        raise OSError(errno.EIO, 'synthetic lock acquisition failure')

    monkeypatch.setattr(upgrade.fcntl, 'flock', fail_acquire)
    with pytest.raises(RuntimeError) as failure:
        with upgrade._migration_lock(tmp_path):
            pytest.fail('startup continued without acquiring the lock')
    assert str(tmp_path / upgrade.LOCK_NAME) in str(failure.value)
    assert 'acquire lock' in str(failure.value).lower()


@pytest.mark.parametrize('boundary', ['home_journal_durable', 'home_landed:0'])
@pytest.mark.parametrize('database', ['file', 'memory'])
def test_two_actual_starts_share_home_then_database_lock_order(tmp_path, boundary, database):
    home, cwd = tmp_path / 'home', tmp_path / 'backend'
    cwd.mkdir()
    put(cwd / 'claude_registry.db', b'old-db')
    put(home / OLD / 'backups/a.zip', b'backup')
    (home / NEW).mkdir()
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    script = '''
from pathlib import Path
import sys,time
from app.upgrade_bootstrap import FileOps,prepare_resource_locations
home,cwd,ready,release=map(Path,sys.argv[1:5])
class Owner(FileOps):
    def checkpoint(self,stage,path):
        if stage==sys.argv[5]:
            ready.write_text('held')
            deadline=time.monotonic()+20
            while not release.exists():
                assert time.monotonic()<deadline,'release timeout'
                time.sleep(.02)
prepare_resource_locations(sys.argv[6],
    '~/.albiex-synth-city/bridge-attachments',database_explicit=False,
    attachment_explicit=False,home=home,cwd=cwd,ops=Owner())
'''
    url = 'sqlite+aiosqlite:///:memory:' if database == 'memory' else 'sqlite+aiosqlite:///./synth_city.db'
    command = [sys.executable, '-c', script, str(home), str(cwd), str(ready), str(release), boundary, url]
    owner = subprocess.Popen(command, cwd=cwd, env=environment(home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists(), owner.communicate(timeout=2)[1] if owner.poll() is not None else 'owner did not hold lock'
        before = files(home), files(cwd)
        contender = subprocess.run(command, cwd=cwd, env=environment(home), capture_output=True, text=True, timeout=5)
        assert contender.returncode != 0
        assert 'upgrade in progress' in contender.stderr.lower()
        assert (files(home), files(cwd)) == before
        assert (home / '.albiex-synth-city-db-upgrade.lock').is_file()
        assert not (home / OLD / '.albiex-synth-city-db-upgrade.lock').exists()
    finally:
        release.write_text('resume')
        if owner.poll() is None:
            try:
                owner.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                owner.kill()
                owner.communicate(timeout=5)
    assert owner.returncode == 0


def test_new_file_allocators_and_installer_use_only_new_home(tmp_path, monkeypatch):
    from app.services import backup_service, agent_mail_install_service
    from app.config import Settings
    monkeypatch.setenv('HOME', str(tmp_path))
    assert Settings().bridge_attachment_dir == '~/.albiex-synth-city/bridge-attachments'
    assert backup_service.get_backup_storage_dir() == tmp_path / NEW / 'backups'
    # This function is async and provider-mutating: inspect only its allocation
    # expression, never run an installer against the user's provider config.
    import inspect
    allocation = inspect.getsource(agent_mail_install_service._backup_before_mutation)
    assert '".albiex-synth-city" / "backups"' in allocation
    assert '".claude-registry" / "backups"' not in allocation
    installer = (BACKEND.parent / 'scripts/install.sh').read_text()
    assert 'mkdir -p ~/.albiex-synth-city/backups' in installer
    assert 'mkdir -p ~/.claude-registry/backups' not in installer


@pytest.mark.parametrize('kind', ['references', 'home'])
def test_journal_validation_is_enforced_with_python_optimization(tmp_path, kind):
    home = tmp_path / 'home'
    home.mkdir()
    identity, reference_id = str(uuid.uuid4()), str(uuid.uuid4())
    roots = {'backups': {'source_root': str(home / OLD / 'backups'),
                         'target_root': str(home / NEW / 'backups')}}
    if kind == 'references':
        value = {'version': True, 'kind': kind, 'id': identity,
                 'move_journal_id': reference_id, 'stage': 'files_landed',
                 'resources': {}, 'diagnostics': {'excluded': [], 'unmapped': []}}
        path = home / ('.albiex-synth-city-upgrade.' + identity + '.references.json')
    else:
        value = {'version': True, 'kind': kind, 'id': identity,
                 'source': str(home / OLD), 'target': str(home / NEW), 'stage': 'planned',
                 'strategy': 'files', 'files': [], 'directories': [], 'resources': roots,
                 'diagnostics': {'excluded': [], 'unmapped': []}, 'exclusions': [],
                 'bind_attachment': False, 'reference_id': reference_id}
        path = home / ('.albiex-synth-city-upgrade.' + identity + '.json')
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    script = '''
from pathlib import Path
from app.upgrade_bootstrap import prepare_resource_locations
try:
    prepare_resource_locations('sqlite+aiosqlite:///:memory:',
        '~/.albiex-synth-city/bridge-attachments',database_explicit=True,
        attachment_explicit=False)
except RuntimeError:
    pass
else:
    raise SystemExit('optimized Python accepted malformed journal')
'''
    result = subprocess.run([sys.executable, '-O', '-c', script], cwd=tmp_path,
        env=environment(home), capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert path.read_bytes() == before
