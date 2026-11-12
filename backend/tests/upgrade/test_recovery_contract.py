"""T-G2: follow the published complete-backup recovery, including browser state."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from .provider_upgrade_harness import BACKEND, OLD, NEW, entries, run_startup
from .reference_startup_harness import run_fixture_code
from .v31_fixture import V31_SOURCE_SHA, SemanticSnapshot, build_v31_install, copy_database_set

ROOT = BACKEND.parent


def digests(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()}


def database_bytes(database):
    return {suffix: hashlib.sha256(Path(str(database) + suffix).read_bytes()).hexdigest()
            for suffix in ('', '-wal', '-shm') if Path(str(database) + suffix).exists()}


def code(install, old=False):
    for name in ('app', 'mcp_shim'):
        shutil.rmtree(install.app_dir / name)
    if old:
        archive = subprocess.check_output(['git', 'archive', V31_SOURCE_SHA, 'backend/app', 'backend/mcp_shim'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(install.source, filter='data')
    else:
        for name in ('app', 'mcp_shim'):
            shutil.copytree(BACKEND / name, install.app_dir / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))


def start(install, environment):
    result = run_startup(install, environment=environment)
    assert result.returncode == 0, result.stderr[-5000:]


def browser(install, state):
    request = install.root / 'browser-request.json'
    request.write_text(json.dumps(state))
    result = subprocess.run(['node', str(Path(__file__).with_name('browser_recovery.mjs')), str(request),
                             str(ROOT / 'frontend/src/lib/browserStorageMigration.ts')],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr[-2500:]
    report = json.loads(result.stdout)
    assert set(report['first'].values()) == set(report['second'].values()) == {'complete'}
    return report['state']


def old_readers(install, partial=False):
    # Boot the actual pinned old app first, then read through its API and service.
    result = subprocess.run([sys.executable, '-c', r'''
import asyncio, hashlib, json, os, re
from pathlib import Path
import httpx
from fastapi import FastAPI
from app.api.v1.router import router
from app.config import settings
from app.database import engine
assert settings.app_version == '3.1.0'
async def read():
    app=FastAPI();app.include_router(router,prefix='/api/v1')
    source=Path.cwd().parent/'frontend/src'
    operator_source=(source/'features/agent-teams/operatorAuth.ts').read_text()
    provider_source=(source/'contexts/ProviderContext.tsx').read_text()
    operator_key=re.search(r"OPERATOR_TOKEN_KEY = '([^']+)'",operator_source).group(1)
    provider_key=re.search(r"STORAGE_KEY = '([^']+)'",provider_source).group(1)
    state=json.loads((Path.home().parent/'browser-storage.json').read_text())
    partial=os.environ.get('RECOVERY_PARTIAL')=='1'
    if partial:
        # Supply the unchanged server credential so an auth error cannot pass
        # as evidence of the broken stored file reference.
        token='synthetic-upgrade-operator'
    else:
        token=state['sessionStorage'][operator_key]
        assert state['localStorage'][provider_key]=='pi-cli'
    headers={'X-Deck-Operator-Token':token}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture',headers=headers) as client:
        teams=await client.get('/api/v1/agent-teams/presets')
        assert teams.status_code==200,teams.text
        names={team['name'] for team in teams.json()['presets']}
        assert 'Pre-upgrade team' in names and 'WAL-only team' in names
        assert ('Post-upgrade discard me' in names)==partial
        response=await client.get('/api/v1/backup/list');assert response.status_code==200,response.text
        backup=next(row for row in response.json()['backups'] if row['name']=='pre-upgrade-restorable')
        base='/api/v1/backup/'+str(backup['id'])
        download=await client.get(base+'/download')
        if partial:
            assert download.status_code==404,download.text
            await engine.dispose()
            return
        assert download.status_code==200,download.text
        manifest=json.loads((Path.home().parent/'manifest.json').read_text())
        assert hashlib.sha256(download.content).hexdigest()==manifest['backup_reader_checks']['download_sha256']
        validation=await client.post(base+'/validate');assert validation.status_code==200 and validation.json()['valid']
    await engine.dispose()
asyncio.run(read())
'''], cwd=install.app_dir, env={
        'HOME': str(install.home), 'PATH': '/usr/local/bin:/usr/bin:/bin',
        'PYTHONPATH': str(install.root / 'no-network') + ':' + str(install.app_dir),
        'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8',
        'PROVIDER_TEST_ROOT': str(install.root), 'OPERATOR_TOKEN': 'synthetic-upgrade-operator',
        'RECOVERY_PARTIAL': '1' if partial else '0',
    }, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr[-4000:]


@pytest.mark.parametrize('dotenv', [False, True], ids=['explicit-environment', 'unchanged-dotenv'])
def test_t_g2_complete_restore_and_partial_rename_back_contract(tmp_path, dotenv):
    guide = (ROOT / 'docs/guide/migration-v4.md').read_text()
    for phrase in ('Stop Claude Deck v3.1 completely', 'While it is stopped',
                   'database file set', 'whole `~/.claude-registry`', 'provider) configuration',
                   'browser state', 'discard', 'Going back'):
        # The guide says "accept losing" instead of "discard"; the test does that literally.
        assert phrase in guide or (phrase == 'discard' and 'accept losing anything created after the upgrade' in guide)
    install = build_v31_install(tmp_path / 'install')
    backup = install.root / 'complete-pre-upgrade'
    saved_db = copy_database_set(install.database, backup / 'database')
    assert Path(str(saved_db) + '-wal').stat().st_size > 0
    shutil.copytree(install.home, backup / 'home')
    saved_browser = json.loads(json.dumps(install.browser_state))
    (backup / 'browser-storage.json').write_text(json.dumps(saved_browser))
    old_home_digest = digests(install.home)
    configured = {'DATABASE_URL': 'sqlite+aiosqlite:///' + str(install.database),
                  'BRIDGE_ATTACHMENT_DIR': str(install.home / '.claude-registry/bridge-attachments')}
    env = {} if dotenv else configured
    settings_bytes = ''.join(key + '=' + value + '\n' for key, value in configured.items()).encode()
    if dotenv:
        (install.app_dir / '.env').write_bytes(settings_bytes)
    sandbox = install.root / 'no-network'; sandbox.mkdir()
    (sandbox / 'sitecustomize.py').write_text(
        "import socket\ndef reject(*a,**k): raise AssertionError('Recovery fixture forbids network')\n"
        "socket.socket.connect=reject\nsocket.socket.connect_ex=reject\n")
    code(install)
    start(install, env)
    upgraded_browser = browser(install, saved_browser)
    assert upgraded_browser != saved_browser
    for provider in install.manifest['installed_providers']:
        assert OLD not in entries(install, provider) and NEW in entries(install, provider)
    new_db = install.app_dir / 'synth_city.db'
    assert new_db.is_file() and not install.database.exists()
    first = (digests(install.home), database_bytes(new_db), SemanticSnapshot.capture(new_db).__dict__)
    start(install, env)
    second = (digests(install.home), database_bytes(new_db), SemanticSnapshot.capture(new_db).__dict__)
    assert second == first, 'Second ordinary start changed a completed resource/config/reference byte'
    assert browser(install, upgraded_browser) == upgraded_browser
    assert not install.database.exists() and not (install.home / '.claude-registry').exists()
    if dotenv:
        assert (install.app_dir / '.env').read_bytes() == settings_bytes
    run_fixture_code(install, r'''
import asyncio
from pathlib import Path
import httpx
from fastapi import FastAPI
from app.api.v1.router import router
from app.database import init_db,engine
async def write():
    await init_db()
    app=FastAPI();app.include_router(router,prefix='/api/v1')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture',
            headers={'X-Synth-City-Operator-Token':'synthetic-upgrade-operator'}) as client:
        response=await client.post('/api/v1/agent-teams/presets',json={'name':'Post-upgrade discard me',
            'slots':[{'display_name':'Post-upgrade','provider':'codex-cli','repo_path':str(Path.home()/'project')}]})
        assert response.status_code==200,response.text
    await engine.dispose()
asyncio.run(write())
''', environment=env)
    (install.home / '.albiex-synth-city/post-upgrade-user-file').write_text('discard this new file')
    upgraded_browser['localStorage']['albiex-synth-city:selected-provider'] = 'codex-cli'
    (install.root / 'browser-storage.json').write_text(json.dumps(upgraded_browser))
    post = install.root / 'post-upgrade'
    post_db = copy_database_set(new_db, post / 'database')
    shutil.copytree(install.home, post / 'home')
    # A files-only rename-back keeps migrated references, provider names and browser keys.
    new_home = install.home / '.albiex-synth-city'
    new_home.rename(install.home / '.claude-registry')
    for suffix in ('', '-wal', '-shm'):
        source = Path(str(new_db) + suffix)
        if source.exists(): source.rename(Path(str(install.database) + suffix))
    with pytest.raises(FileNotFoundError, match='albiex-synth-city'):
        SemanticSnapshot.capture(install.database)
    assert upgraded_browser != saved_browser
    assert any(OLD not in entries(install, provider) for provider in install.manifest['installed_providers'])
    code(install, old=True)
    start(install, env)
    old_readers(install, partial=True)
    # D3: discard post-upgrade resources, restore the complete quiescent set and old source.
    def restore_complete():
        for database in (install.database, new_db):
            for suffix in ('', '-wal', '-shm'):
                Path(str(database) + suffix).unlink(missing_ok=True)
        copy_database_set(saved_db, install.app_dir)
        shutil.rmtree(install.home)
        shutil.copytree(backup / 'home', install.home)
        shutil.copy2(backup / 'browser-storage.json', install.root / 'browser-storage.json')
        for path in install.app_dir.glob('.albiex-synth-city-*'):
            if path.is_file(): path.unlink()

    def verify_complete():
        assert database_bytes(install.database) == database_bytes(saved_db), 'database set was not restored'
        actual = digests(install.home)
        data = lambda values: {key: value for key, value in values.items() if key.startswith('.claude-registry/')}
        config = lambda values: {key: value for key, value in values.items() if not key.startswith('.claude-registry/')}
        assert data(actual) == data(old_home_digest), 'home data was not restored'
        assert config(actual) == config(old_home_digest), 'provider configuration was not restored'
        state = json.loads((install.root / 'browser-storage.json').read_text())
        for area in ('sessionStorage', 'localStorage'):
            assert state[area] == saved_browser[area], area + ' was not restored'

    # Remove each resource from an otherwise complete restore, and require the
    # independent pre-upgrade snapshot oracle to reject that exact omission.
    for missing in ('database', 'home', 'provider', 'sessionStorage', 'localStorage'):
        restore_complete()
        if missing == 'database':
            for suffix in ('', '-wal', '-shm'):
                source = Path(str(post_db) + suffix)
                target = Path(str(install.database) + suffix)
                target.unlink(missing_ok=True)
                if source.exists(): shutil.copy2(source, target)
        elif missing == 'home':
            shutil.rmtree(install.home / '.claude-registry')
            shutil.copytree(post / 'home/.albiex-synth-city', install.home / '.claude-registry')
        elif missing == 'provider':
            shutil.copy2(post / 'home/.codex/config.toml', install.home / '.codex/config.toml')
        else:
            state = dict(saved_browser); state[missing] = upgraded_browser[missing]
            (install.root / 'browser-storage.json').write_text(json.dumps(state))
        with pytest.raises(AssertionError, match=missing):
            verify_complete()
    restore_complete()
    verify_complete()
    restored = SemanticSnapshot.capture(install.database)
    assert restored.__dict__ == install.before.__dict__
    assert json.loads((install.root / 'browser-storage.json').read_text()) == install.browser_state
    assert all(OLD in entries(install, provider) and NEW not in entries(install, provider)
               for provider in install.manifest['installed_providers'])
    code(install, old=True)
    start(install, env)
    old_readers(install)
