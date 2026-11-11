"""T-D5 reference/barrier power loss and the pre-service startup boundary."""
import sqlite3

import pytest

from .reference_power_loss import PowerCut, ReferencePowerLoss
from .reference_startup_harness import create_database, journal, reference, rows, run_reference
from .reference_startup_harness import run_fixture_code
from .v31_fixture import build_v31_install, SemanticSnapshot
import json
from pathlib import Path
import subprocess
import sys
import time
from .database_startup_harness import run_entrypoint


@pytest.mark.parametrize('collision,agent_root', [(False, ''), (True, ''), (True, '/synthetic/agent-view')])
def test_t_d1_pinned_v31_references_preserve_records_and_use_current_readers(tmp_path, collision, agent_root):
    install = build_v31_install(tmp_path / 'install')
    if collision:
        for source in install.before.files:
            old = Path(source)
            target = install.home / '.albiex-synth-city' / old.relative_to(install.home / '.claude-registry')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'pre-existing target must survive')
    run_fixture_code(install, r'''
import asyncio, hashlib, json, socket, subprocess
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app.database import engine, init_db, AsyncSessionLocal
from app.config import settings
from app.upgrade_bootstrap import read_reference_journals
from tests.upgrade.v31_fixture import SemanticSnapshot
from app.services.agent_bridge.attachments import AgentBridgeAttachmentService
from app.models.schemas import BridgeAttachmentPasteRequest
from app.models.database import BridgeSessionAttachment
from app.api.v1.router import router

def reject(*args, **kwargs):
    raise AssertionError('external transport refused')
socket.socket.connect = reject
subprocess.Popen = reject
root=Path.home().parent
records=read_reference_journals()
mapping={row['source']:row['target'] for record in records
    for resource in record['resources'].values() for row in resource['mappings']}
before=json.loads((root/'semantic-snapshot.json').read_text())
for old in before['records']['bridge_session_attachments'].values():
    if old['storage_path'] in mapping and old['original_filename']=='live.png':
        target=mapping[old['storage_path']]
        display=AgentBridgeAttachmentService()._agent_path(Path(target))
        mapping[old['prompt_text']]=old['prompt_text'].replace(old['agent_path'],display)

async def check():
    await init_db()
    # Capture before ordinary expired-row cleanup or deliberate user deletion.
    after=SemanticSnapshot.capture(Path.cwd()/'synth_city.db')
    (root/'reference-after.json').write_text(json.dumps(after.__dict__))
    (root/'reference-path-map.json').write_text(json.dumps(mapping))
    assert not read_reference_journals(), 'reference journals were not durably completed'
    app=FastAPI()
    app.include_router(router,prefix='/api/v1')
    headers={'X-Synth-City-Operator-Token':'synthetic-upgrade-operator'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
            base_url='http://fixture',headers=headers) as client:
        response=await client.get('/api/v1/backup/list')
        assert response.status_code==200,response.text
        backup=next(b for b in response.json()['backups'] if b['name']=='pre-upgrade-restorable')
        base='/api/v1/backup/'+str(backup['id'])
        download=await client.get(base+'/download')
        assert download.status_code==200,download.text
        manifest=json.loads((root/'manifest.json').read_text())
        assert hashlib.sha256(download.content).hexdigest()==manifest['backup_reader_checks']['download_sha256']
        validation=await client.post(base+'/validate')
        assert validation.status_code==200 and validation.json()['valid'],validation.text
        contents=await client.get(base+'/contents')
        assert contents.status_code==200 and contents.json()['files']
        file=Path.home()/'.claude/settings.json'
        original=file.read_bytes()
        file.write_text('{"env":{"UPGRADE_FIXTURE_SETTING":"changed by C6 test"}}')
        restored=await client.post(base+'/restore',json={'install_dependencies':False})
        assert restored.status_code==200 and restored.json()['success'],restored.text
        assert file.read_bytes()==original,'restore did not restore actual settings bytes'
    service=AgentBridgeAttachmentService()
    target='upgrade-fixture:0.0'
    async with AsyncSessionLocal() as db:
        listed=await service.list_attachments(db,target=target)
        assert len(listed)==2
        live=next(a for a in listed if a.original_filename=='live.png')
        expired=next(a for a in listed if a.original_filename=='expired.png')
        live_path=Path((await db.get(BridgeSessionAttachment,live.id)).storage_path)
        expired_path=Path((await db.get(BridgeSessionAttachment,expired.id)).storage_path)
        assert live_path.is_file() and expired_path.is_file()
        assert '.albiex-synth-city/bridge-attachments/' in str(live_path)
        sent=[]
        with patch.object(service,'_require_live_session',return_value={'tmux_target':target}), \
                patch.object(service,'_send_tmux_prompt',side_effect=lambda *a,**k:sent.append((a,k))):
            await service.paste_attachment(db,target=target,attachment_id=live.id,
                request=BridgeAttachmentPasteRequest(submit=False))
        assert sent and live.agent_path in sent[0][0][1]
        assert '.claude-registry/bridge-attachments/' not in sent[0][0][1]
        assert await service.cleanup_expired(db)==1
        assert not expired_path.exists(),'expiry did not unlink the landed file'
        await service.delete_attachment(db,target=target,attachment_id=live.id)
        assert not live_path.exists(),'delete did not unlink the landed file'
        assert await service.list_attachments(db,target=target)==[]
    await engine.dispose()
asyncio.run(check())
''', environment={'BRIDGE_ATTACHMENT_AGENT_ROOT': agent_root})
    after = SemanticSnapshot(**json.loads((install.root / 'reference-after.json').read_text()))
    mapping = json.loads((install.root / 'reference-path-map.json').read_text())
    # The frozen snapshot's single value map cannot express an expired row
    # whose storage_path changes while its identical agent_path stays old.
    # Check every original field with the same frozen assertion, separating
    # only that row's storage field from its byte-identical remaining fields.
    for table, records in install.before.records.items():
        for identity, row in records.items():
            if table == 'bridge_session_attachments' and row['original_filename'] == 'expired.png':
                SemanticSnapshot({table: {identity: {'storage_path': row['storage_path']}}}, {}, {}).assert_preserved(
                    after, path_map=mapping)
                SemanticSnapshot({table: {identity: {key: value for key, value in row.items()
                    if key != 'storage_path'}}}, {}, {}).assert_preserved(after)
            elif table == 'bridge_session_attachments':
                # A custom display root can make storage and agent paths diverge
                # even though the old fixture stored the same string in both.
                expected_agent = (str(Path(agent_root) /
                    Path(mapping[row['storage_path']]).relative_to(
                        install.home / '.albiex-synth-city/bridge-attachments'))
                    if agent_root else mapping[row['storage_path']])
                assert after.records[table][identity]['agent_path'] == expected_agent
                SemanticSnapshot({table: {identity: {key: value for key, value in row.items()
                    if key != 'agent_path'}}}, {}, {}).assert_preserved(after, path_map=mapping)
            else:
                SemanticSnapshot({table: {identity: row}}, {}, {}).assert_preserved(after, path_map=mapping)
    SemanticSnapshot({}, install.before.files, {}).assert_preserved(after, path_map=mapping)
    if collision:
        for source in install.before.files:
            old = Path(source)
            original_target = install.home / '.albiex-synth-city' / old.relative_to(install.home / '.claude-registry')
            assert original_target.read_bytes() == b'pre-existing target must survive'


@pytest.mark.parametrize('cut', ['reference_rows_updated:backups', 'reference_stamps_written:backups',
    'reference_committed:backups', 'reference_barrier_verified', 'reference_record_unlinked:0',
    'reference_record_retired:0'])
def test_t_d5_power_cut_drops_unflushed_sql_and_replays_without_losing_journal(tmp_path, cut):
    home = tmp_path / 'home'
    record = reference(home)
    path = create_database(tmp_path / 'db', [record])
    model = ReferencePowerLoss(path, home, cut)
    with pytest.raises(PowerCut):
        run_reference(path, [record], home, ops=model.operations())
    model.restore()
    if not model.barriers:
        assert rows(path, 'backups')[0]['file_path'].endswith('/a.bin')
        assert rows(path, 'upgrade_reference_stamps') == []
        assert journal(home, record).exists()
    else:
        assert len(rows(path, 'upgrade_reference_stamps')) == 2
    # Ordinary locked startup reads whatever namespace actually survived.
    from app.upgrade_bootstrap import read_reference_journals
    remaining = read_reference_journals(home=home)
    run_reference(path, remaining, home)
    assert rows(path, 'backups')[0]['file_path'].endswith('/a.allocated.bin')
    assert len(rows(path, 'upgrade_reference_stamps')) == 2
    assert not journal(home, record).exists()
    run_reference(path, [], home)


@pytest.mark.parametrize('url', ['sqlite+aiosqlite:///:memory:', 'postgresql://unused/db'])
def test_pending_journals_fail_closed_on_unsupported_backend(tmp_path, url):
    home = tmp_path / 'home'
    record = reference(home)
    from app.upgrade_references import reference_startup
    with pytest.raises(RuntimeError, match='durab|file-backed'):
        with reference_startup(url, home=home, cwd=tmp_path):
            pytest.fail('unsupported pending phase reached ordinary services')
    assert journal(home, record).exists()
    journal(home, record).unlink()
    with reference_startup(url, home=home, cwd=tmp_path) as state:
        assert state.records == []


def test_t_d5_every_native_sql_and_retirement_boundary_with_shared_partitions(tmp_path):
    def case(root):
        home = root / 'home'
        first = reference(home)
        second = reference(home, move=first['move_journal_id'], suffix='b')
        third = reference(home, resources=('backups',), suffix='c')
        records = [first, second, third]
        path = create_database(root / 'db', records)
        return home, records, path

    home, records, path = case(tmp_path / 'discovery')
    discovery = ReferencePowerLoss(path, home)
    run_reference(path, records, home, ops=discovery.operations())
    assert discovery.barriers == 1
    assert any('wal_checkpoint(FULL)' in name for name in discovery.events)
    assert len([name for name in discovery.events if name.startswith('unlink.after:')]) == 3
    for cut in range(len(discovery.events)):
        home, records, path = case(tmp_path / str(cut))
        landed = {p: p.read_bytes() for p in home.rglob('*.allocated.bin')}
        history = rows(path, 'history')
        model = ReferencePowerLoss(path, home, cut)
        with pytest.raises(PowerCut):
            run_reference(path, records, home, ops=model.operations())
        model.restore()
        from app.upgrade_bootstrap import read_reference_journals
        remaining = read_reference_journals(home=home)
        if not model.barriers:
            assert len(remaining) == 3, (cut, discovery.events[cut])
            assert rows(path, 'upgrade_reference_stamps') == []
        run_reference(path, remaining, home)
        assert len(rows(path, 'upgrade_reference_stamps')) == 5, (cut, discovery.events[cut])
        assert all(r['file_path'].endswith('.allocated.bin') for r in rows(path, 'backups'))
        assert all(r['storage_path'].endswith('.allocated.bin')
                   for r in rows(path, 'bridge_session_attachments'))
        assert rows(path, 'history') == history
        assert {p: p.read_bytes() for p in landed} == landed
        assert read_reference_journals(home=home) == []
        before = rows(path, 'upgrade_reference_stamps')
        run_reference(path, [], home)
        assert rows(path, 'upgrade_reference_stamps') == before


def test_t_d5_real_reader_blocks_native_checkpoint_and_records_remain(tmp_path):
    home = tmp_path / 'home'
    record = reference(home)
    path = create_database(tmp_path / 'db', [record])
    reader = sqlite3.connect(path, isolation_level=None)
    reader.execute('BEGIN')
    reader.execute('SELECT * FROM backups').fetchall()
    from app.upgrade_references import ReferenceOps

    class FastBusy(ReferenceOps):
        result = None

        def execute(self, db, sql, parameters=()):
            if sql == 'PRAGMA wal_checkpoint(FULL)':
                db.execute('PRAGMA busy_timeout=30')
                self.result = super().execute(db, sql, parameters).fetchone()

                class Result:
                    def fetchone(inner):
                        return self.result

                return Result()
            return super().execute(db, sql, parameters)

    ops = FastBusy()
    try:
        with pytest.raises(RuntimeError, match='checkpoint is incomplete'):
            run_reference(path, [record], home, ops=ops)
        assert ops.result is not None and ops.result[0] == 1
        assert journal(home, record).exists()
    finally:
        reader.close()
    run_reference(path, [record], home)
    assert not journal(home, record).exists()


@pytest.mark.parametrize('result', [(1, 3, 1), (0, -1, -1), (0, 3, 1), None])
def test_t_d5_unverifiable_checkpoint_cannot_retire_shared_record(tmp_path, result):
    home = tmp_path / 'home'
    record = reference(home)
    path = create_database(tmp_path / 'db', [record])
    from app.upgrade_references import ReferenceOps

    class Unverified(ReferenceOps):
        def execute(self, db, sql, parameters=()):
            if sql == 'PRAGMA wal_checkpoint(FULL)':
                class Result:
                    def fetchone(self):
                        return result
                return Result()
            return super().execute(db, sql, parameters)

    with pytest.raises(RuntimeError, match='checkpoint is incomplete'):
        run_reference(path, [record], home, ops=Unverified())
    assert journal(home, record).exists()


def test_t_d5_resource_update_and_all_partition_stamps_share_one_transaction(tmp_path):
    home = tmp_path / 'home'
    first = reference(home)
    second = reference(home, move=first['move_journal_id'], suffix='b')
    path = create_database(tmp_path / 'db', [first, second])
    from app.upgrade_references import ReferenceOps

    class Atomic(ReferenceOps):
        observed = []

        def checkpoint(self, stage, unused_path):
            if stage.startswith(('reference_rows_updated:', 'reference_stamps_written:')):
                resource = stage.split(':')[1]
                # A separate connection must see neither uncommitted updates
                # nor any of this move/resource's partition stamps.
                table, field = (('backups', 'file_path') if resource == 'backups'
                    else ('bridge_session_attachments', 'storage_path'))
                assert all(r[field].endswith('/a.bin') or r[field].endswith('/b.bin')
                           for r in rows(path, table))
                assert not any(s['resource'] == resource for s in rows(path, 'upgrade_reference_stamps'))
                self.observed.append(stage)

    ops = Atomic()
    run_reference(path, [first, second], home, ops=ops)
    assert len(ops.observed) == 4


def test_t_d5_stamp_write_failure_rolls_back_resource_and_retains_shared_record(tmp_path):
    home = tmp_path / 'home'
    record = reference(home)
    path = create_database(tmp_path / 'db', [record])
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER refuse_stamp BEFORE INSERT ON upgrade_reference_stamps "
                   "WHEN new.resource='attachments' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(RuntimeError, match='database failure'):
        run_reference(path, [record], home)
    assert rows(path, 'backups')[0]['file_path'].endswith('.allocated.bin')
    assert rows(path, 'bridge_session_attachments')[0]['storage_path'].endswith('/a.bin')
    assert {s['resource'] for s in rows(path, 'upgrade_reference_stamps')} == {'backups'}
    assert journal(home, record).exists()
    with sqlite3.connect(path) as db:
        db.execute('DROP TRIGGER refuse_stamp')
    run_reference(path, [record], home)
    assert not journal(home, record).exists()


def test_t_d5_stamped_replay_skips_updates_but_reverifies_native_barrier(tmp_path):
    home = tmp_path / 'home'
    record = reference(home)
    path = create_database(tmp_path / 'db', [record])
    from app.upgrade_references import ReferenceOps

    class BeforeUnlink(ReferenceOps):
        def checkpoint(self, stage, unused_path):
            if stage == 'reference_barrier_verified':
                raise OSError(5, 'synthetic interruption')

    with pytest.raises(OSError):
        run_reference(path, [record], home, ops=BeforeUnlink())
    assert journal(home, record).exists()
    before = rows(path, 'upgrade_reference_stamps')

    class Replay(ReferenceOps):
        checkpoints = 0

        def execute(self, db, sql, parameters=()):
            assert not sql.startswith(('UPDATE ', 'INSERT ')), 'stamped replay rewrote a resource'
            if sql == 'PRAGMA wal_checkpoint(FULL)':
                self.checkpoints += 1
            return super().execute(db, sql, parameters)

    ops = Replay()
    run_reference(path, [record], home, ops=ops)
    assert ops.checkpoints == 1 and rows(path, 'upgrade_reference_stamps') == before
    assert not journal(home, record).exists()


@pytest.mark.parametrize('mode', ['uvicorn', 'dev', 'factory'])
def test_t_d1_supported_start_retires_references_before_ordinary_services(tmp_path, mode):
    install = build_v31_install(tmp_path / 'install')
    run_entrypoint(install, mode, home_audit=True, reference_audit=True)


def test_reference_barrier_failure_aborts_actual_lifespan_before_cleanup_or_scheduler(tmp_path):
    install = build_v31_install(tmp_path / 'install')
    run_fixture_code(install, r'''
import asyncio
from unittest.mock import AsyncMock, patch
from app.main import app, lifespan, github_dispatch_scheduler, agent_bridge_attachment_service
from app.database import engine
from app.upgrade_references import ReferenceOps
from app.upgrade_bootstrap import read_reference_journals
original=ReferenceOps.execute
def failed(self,db,sql,parameters=()):
    if sql=='PRAGMA wal_checkpoint(FULL)':
        raise RuntimeError('synthetic barrier failure')
    return original(self,db,sql,parameters)
async def check():
    with patch.object(ReferenceOps,'execute',failed), \
            patch.object(agent_bridge_attachment_service,'cleanup_expired',new_callable=AsyncMock) as cleanup, \
            patch.object(github_dispatch_scheduler,'start',new_callable=AsyncMock) as scheduler:
        try:
            async with lifespan(app):
                raise AssertionError('ordinary lifespan was reached')
        except RuntimeError as error:
            assert str(error)=='synthetic barrier failure'
        else:
            raise AssertionError('barrier failure did not abort startup')
        cleanup.assert_not_called()
        scheduler.assert_not_called()
        assert read_reference_journals(),'failed barrier discarded recovery records'
    await engine.dispose()
asyncio.run(check())
''')


@pytest.mark.parametrize('cut', ['reference_rows_updated:backups', 'reference_committed:attachments',
                                'reference_barrier_verified', 'reference_record_unlinked:0'])
def test_t_d5_two_process_starts_share_home_and_database_locks_through_reference_phase(tmp_path, cut):
    home = tmp_path / 'home'
    record = reference(home)
    path = create_database(tmp_path / 'synth_city.db', [record])
    ready, release = tmp_path / 'ready', tmp_path / 'release'
    code = r'''
import sys,time
from pathlib import Path
from app.upgrade_references import ReferenceOps,reference_startup,complete_reference_upgrade
home,path,ready,release=map(Path,sys.argv[1:5])
class Owner(ReferenceOps):
    def checkpoint(self,stage,path):
        if stage==sys.argv[5]:
            ready.write_text('held')
            deadline=time.monotonic()+15
            while not release.exists():
                assert time.monotonic()<deadline,'release timeout'
                time.sleep(.01)
with reference_startup('sqlite+aiosqlite:///'+str(path),home=home,cwd=path.parent,ops=Owner()) as state:
    complete_reference_upgrade(state.database,state.records,home=home,ops=state.ops,agent_path=str)
'''
    backend = Path(__file__).resolve().parents[2]
    env = {'HOME': str(home), 'PATH': '/usr/local/bin:/usr/bin:/bin',
           'PYTHONPATH': str(backend), 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    args = [sys.executable, '-c', code, str(home), str(path), str(ready), str(release), cut]
    owner = subprocess.Popen(args, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists(), owner.communicate(timeout=2)[1] if owner.poll() is not None else 'owner did not hold'
        contender = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=4)
        assert contender.returncode != 0 and 'upgrade in progress' in contender.stderr.lower()
        assert (home / '.albiex-synth-city-db-upgrade.lock').exists()
        assert (tmp_path / '.albiex-synth-city-db-upgrade.lock').exists()
    finally:
        release.write_text('resume')
        try:
            _, error = owner.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            owner.kill()
            owner.communicate(timeout=3)
            raise
    assert owner.returncode == 0, error
    assert not journal(home, record).exists()
