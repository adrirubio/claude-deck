"""Run the shipped entry-point forms with throwaway data and guarded boundaries."""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen


BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent


def executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


def run_entrypoint(install, mode, configured=None, dotenv=False, *,
                   configured_attachment=None, home_audit=False):
    # This is code replacement inside a fresh fixture's throwaway installation,
    # not a worktree, installed factory, or modification of the shared baseline.
    for package in ('app', 'mcp_shim'):
        shutil.rmtree(install.app_dir / package)
        shutil.copytree(BACKEND / package, install.app_dir / package,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    bin_dir = install.root / 'bin'
    bin_dir.mkdir(exist_ok=True)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    assert port != 8011
    trace = install.root / 'sqlite-open.jsonl'
    guard = install.root / 'guard'
    guard.mkdir(exist_ok=True)
    old = str(install.database)
    new = str(install.app_dir / 'synth_city.db')
    home_checks = ''
    if home_audit:
        home_checks = f'''
            assert not pathlib.Path({str(install.home / '.claude-registry')!r}).exists(), 'HOME move incomplete before first connection'
            assert pathlib.Path({str(install.home / '.albiex-synth-city/backups')!r}).is_dir(), 'backup root not landed'
            assert pathlib.Path({str(install.home / '.albiex-synth-city/bridge-attachments')!r}).is_dir(), 'attachment root not landed'
            from app.config import settings
            assert settings.bridge_attachment_dir == {str(install.home / '.albiex-synth-city/bridge-attachments')!r}, 'attachment binding not effective'
'''
    (guard / 'sitecustomize.py').write_text(f'''
import json, os, pathlib, sys
old = pathlib.Path({old!r})
new = pathlib.Path({new!r})
def guard(event, args):
    if event == 'sqlite3.connect':
        path = str(args[0])
        if path.endswith(('claude_registry.db', 'synth_city.db')):
            assert pathlib.Path(path).resolve() == new, 'first connection selected the old database'
            assert new.is_file(), 'first connection would create an empty database before movement'
            assert not list(new.parent.glob('.albiex-synth-city-db-upgrade.*.json')), 'DB journal still open'
            assert not old.exists(), 'source DB is still present at first open'
{home_checks}
            with open({str(trace)!r}, 'a') as stream:
                stream.write(json.dumps({{'path': path}}) + '\\n')
    elif event == 'socket.connect':
        address = args[1]
        if isinstance(address, tuple):
            assert address[0] in ('127.0.0.1', '::1') and address[1] == {port}, 'external network refused'
    elif event == 'os.kill':
        assert os.getpgid(args[0]) == os.getpgrp(), 'signal outside fixture group refused'
    elif event == 'os.killpg':
        assert args[0] == os.getpgrp(), 'signal outside fixture group refused'
sys.addaudithook(guard)
''')
    for name in ('tmux', 'gh', 'pgrep', 'lsof'):
        executable(bin_dir / name, '#!/bin/sh\nexit 1\n')
    executable(bin_dir / 'npm', '#!/bin/sh\nexec /bin/sleep 120\n')
    # Only transport ports and the Python executable are mapped. The real
    # uvicorn loader/import/lifespan and SQLite boundary run unchanged.
    executable(bin_dir / 'uvicorn', f'''#!{sys.executable}
import os, sys
args = sys.argv[1:]
if '--port' in args: args[args.index('--port') + 1] = {str(port)!r}
os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', *args])
''')
    executable(bin_dir / 'curl', f'''#!{sys.executable}
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:{port}/health', timeout=1).read()
except Exception:
    sys.exit(1)
''')
    environment = {
        'HOME': str(install.home), 'PATH': str(bin_dir) + ':/usr/local/bin:/usr/bin:/bin',
        'PYTHONPATH': str(guard) + ':' + str(install.app_dir),
        'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8',
        'OPERATOR_TOKEN': 'synthetic-upgrade-operator',
    }
    env_file = install.app_dir / '.env'
    if configured:
        if dotenv:
            if not env_file.exists():
                env_file.write_text('DATABASE_URL=' + configured + '\n')
        else:
            environment['DATABASE_URL'] = configured
    if configured_attachment:
        if dotenv:
            current = env_file.read_text() if env_file.exists() else ''
            line = 'BRIDGE_ATTACHMENT_DIR=' + configured_attachment + '\n'
            if line not in current:
                env_file.write_text(current + line)
        else:
            environment['BRIDGE_ATTACHMENT_DIR'] = configured_attachment
    operator_bytes = env_file.read_bytes() if env_file.exists() else None
    if mode == 'uvicorn':
        command = [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)]
    elif mode == 'factory':
        text = (REPOSITORY / 'scripts/product-factory/claude-deck-product.service').read_text()
        args = shlex.split(next(line.split('=', 1)[1] for line in text.splitlines() if line.startswith('ExecStart=')))
        assert args[1:4] == ['-m', 'uvicorn', 'app.main:app']
        assert args[args.index('--port') + 1] == '8011'
        command = [sys.executable, *args[1:]]
        command[command.index('--port') + 1] = str(port)
    elif mode == 'dev':
        scripts = install.source / 'scripts'
        scripts.mkdir(exist_ok=True)
        shutil.copy2(REPOSITORY / 'scripts/dev.sh', scripts / 'dev.sh')
        (install.app_dir / 'venv/bin').mkdir(parents=True)
        (install.app_dir / 'venv/bin/activate').write_text(':\n')
        (install.source / 'frontend/node_modules').mkdir(parents=True)
        command = ['bash', str(scripts / 'dev.sh'), 'start', '--host', '127.0.0.1']
    else:
        raise AssertionError(mode)
    output = install.root / (mode + '.log')
    with output.open('w') as stream:
        process = subprocess.Popen(command, cwd=install.app_dir, env=environment,
            stdout=stream, stderr=stream, start_new_session=True)
        try:
            deadline = time.monotonic() + 30
            result = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError('entry point exited before serving fixture data:\n' + output.read_text()[-3500:])
                try:
                    req = Request(f'http://127.0.0.1:{port}/api/v1/agent-teams/presets',
                        headers={'X-Synth-City-Operator-Token': 'synthetic-upgrade-operator'})
                    with urlopen(req, timeout=1) as response:
                        result = json.load(response)
                    break
                except OSError:
                    time.sleep(0.1)
            assert result is not None, output.read_text()[-3500:]
            assert trace.exists(), 'no first-connection ordering evidence'
            assert all(row['path'] == new for row in map(json.loads, trace.read_text().splitlines()))
            assert any(row['name'] == 'WAL-only team' for row in result['presets'])
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    assert (env_file.read_bytes() if env_file.exists() else None) == operator_bytes
    return result
