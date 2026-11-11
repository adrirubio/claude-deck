"""C4: T-D2/D4 and DB-only binding contracts, before any database open."""
import errno
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import stat

import pytest
from sqlalchemy.engine import make_url

from .v31_fixture import SemanticSnapshot, copy_database_set
from .database_move_faults import DurableFilesystem, Interrupted


SUFFIXES = ('-wal', '-shm', '-journal', '')
JOURNALS = '.albiex-synth-city-db-upgrade.*.json'
BINDING = '.albiex-synth-city/upgrade-location-bindings.json'


def migration():
    assert importlib.util.find_spec('app.upgrade_bootstrap'), 'C4 pre-open database conversion is missing'
    return importlib.import_module('app.upgrade_bootstrap')


def start(root, *, url='sqlite+aiosqlite:///./synth_city.db', explicit=False,
          test_instance=False, ops=None, home=None):
    return migration().prepare_database_url(url, explicit=explicit, test_instance=test_instance,
        cwd=root, home=home or root / 'home', ops=ops)


def database_files(root):
    return {p.name: p.read_bytes() for name in ('claude_registry.db', 'synth_city.db')
            for suffix in SUFFIXES if (p := root / (name + suffix)).is_file()}


def seed_bytes(root, name='claude_registry.db'):
    root.mkdir(parents=True, exist_ok=True)
    for suffix in SUFFIXES:
        (root / (name + suffix)).write_bytes(('historical-content' + suffix).encode())


def test_t_d2_same_inode_wal_and_semantics_survive_before_first_open(v31_install, tmp_path):
    old = copy_database_set(v31_install.database, tmp_path)
    expected = {s: (Path(str(old) + s).read_bytes(), Path(str(old) + s).stat())
                for s in SUFFIXES if Path(str(old) + s).exists()}
    actual = Path(make_url(start(tmp_path)).database)
    assert actual == tmp_path / 'synth_city.db'
    assert not list(tmp_path.glob(JOURNALS))
    for suffix, (data, original) in expected.items():
        target = Path(str(actual) + suffix)
        assert target.read_bytes() == data
        assert target.stat().st_ino == original.st_ino
        assert stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE(original.st_mode)
        assert (target.stat().st_uid, target.stat().st_gid) == (original.st_uid, original.st_gid)
        assert target.stat().st_mtime_ns == original.st_mtime_ns
        assert not Path(str(old) + suffix).exists()
    v31_install.before.assert_preserved(SemanticSnapshot.capture(actual))
    with sqlite3.connect(actual) as db:
        assert db.execute("SELECT count(*) FROM agent_team_presets WHERE name='WAL-only team'").fetchone()[0] == 1
    # Legitimate first-open changes never get checked against immutable pre-open digests.
    after_open = database_files(tmp_path)
    start(tmp_path)
    assert database_files(tmp_path) == after_open


def test_t_d2_cross_device_uses_journalled_digests_and_preserves_metadata(tmp_path):
    seed_bytes(tmp_path)
    (tmp_path / 'claude_registry.db').chmod(0o640)
    before = database_files(tmp_path)
    metadata = {name: (tmp_path / name).stat() for name in before}
    module = migration()
    copied = []

    class CrossDevice(module.FileOps):
        def link(self, source, target):
            if source.name.startswith('claude_registry.db'):
                raise OSError(errno.EXDEV, 'cross-device injection')
            return super().link(source, target)

        def copy(self, source, temporary, metadata):
            journal = json.loads(next(tmp_path.glob(JOURNALS)).read_text())
            row = next(f for f in journal['files'] if f['source'] == str(source))
            assert row['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
            copied.append(source.name)
            return super().copy(source, temporary, metadata)

    start(tmp_path, ops=CrossDevice())
    assert set(copied) == set(before)
    assert database_files(tmp_path) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in before.items()}
    for name, original in metadata.items():
        target = tmp_path / name.replace('claude_registry.db', 'synth_city.db')
        actual = target.stat()
        assert (stat.S_IMODE(actual.st_mode), actual.st_uid, actual.st_gid, actual.st_mtime_ns) == (
            stat.S_IMODE(original.st_mode), original.st_uid, original.st_gid, original.st_mtime_ns)
    assert not list(tmp_path.glob(JOURNALS))
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('main,sidecar', [(False, '-wal'), (True, '-wal'), (False, '-shm'),
    (True, '-shm'), (False, '-journal'), (True, '-journal'), (True, '')])
def test_t_d4_unexplained_target_content_stops_without_deletion(tmp_path, main, sidecar):
    seed_bytes(tmp_path)
    if main:
        (tmp_path / 'synth_city.db').touch()
    (tmp_path / ('synth_city.db' + sidecar)).write_bytes(b'unrelated-target-state')
    before = database_files(tmp_path)
    with pytest.raises(RuntimeError) as error:
        start(tmp_path)
    assert str(tmp_path / 'claude_registry.db') in str(error.value)
    assert str(tmp_path / 'synth_city.db') in str(error.value)
    assert database_files(tmp_path) == before


def test_t_d4_zero_target_is_removed_only_after_durable_intent(tmp_path):
    seed_bytes(tmp_path)
    (tmp_path / 'synth_city.db').touch()
    module = migration()
    removed = []

    class Observe(module.FileOps):
        def unlink(self, path):
            if path.name == 'synth_city.db':
                journal = json.loads(next(tmp_path.glob(JOURNALS)).read_text())
                assert str(path) in journal['empty_targets']
                removed.append(path)
            return super().unlink(path)

    start(tmp_path, ops=Observe())
    assert removed == [tmp_path / 'synth_city.db']
    assert (tmp_path / 'synth_city.db').read_bytes() == b'historical-content'


@pytest.mark.parametrize('payload', ['not JSON', '{"version":999}', '{"version":1,"id":"wrong"}'])
def test_t_d4_invalid_journal_never_authorizes_a_move(tmp_path, payload):
    seed_bytes(tmp_path)
    path = tmp_path / '.albiex-synth-city-db-upgrade.00000000-0000-0000-0000-000000000000.json'
    path.write_text(payload)
    before = database_files(tmp_path)
    with pytest.raises(RuntimeError):
        start(tmp_path)
    assert database_files(tmp_path) == before
    assert path.read_text() == payload


def test_t_d4_absent_sets_create_no_database_and_already_upgraded_is_noop(tmp_path):
    new = tmp_path / 'synth_city.db'
    assert Path(make_url(start(tmp_path)).database) == new
    assert database_files(tmp_path) == {}
    new.write_bytes(b'previously-upgraded-content')
    before = database_files(tmp_path)
    start(tmp_path)
    assert database_files(tmp_path) == before
    assert not list(tmp_path.glob(JOURNALS))


@pytest.mark.parametrize('custom', ['sqlite+aiosqlite:///:memory:', 'postgresql+asyncpg://host/name',
    'sqlite+aiosqlite:///elsewhere/claude_registry.db'])
def test_custom_database_and_test_instance_do_not_move_or_create_metadata(tmp_path, custom):
    seed_bytes(tmp_path)
    before = database_files(tmp_path)
    assert start(tmp_path, url=custom, explicit=True) == custom
    start(tmp_path, test_instance=True)
    assert database_files(tmp_path) == before
    assert not list(tmp_path.glob('.albiex-synth-city*'))
    assert not (tmp_path / 'home').exists()


def test_db_binding_preserves_explicit_old_default_then_retires_for_intentional_change(tmp_path):
    seed_bytes(tmp_path)
    configured = 'sqlite+aiosqlite:///./claude_registry.db'
    effective = start(tmp_path, url=configured, explicit=True)
    binding = tmp_path / 'home' / BINDING
    record = json.loads(binding.read_text())
    entry = record['resources']['database']
    assert record['version'] == 1
    assert entry['old_path'] == str(tmp_path / 'claude_registry.db')
    assert entry['new_path'] == str(tmp_path / 'synth_city.db')
    assert entry['journal_id']
    before = database_files(tmp_path)
    assert start(tmp_path, url=configured, explicit=True) == effective
    assert database_files(tmp_path) == before
    # Other resources belong to C5 and must survive DB retirement.
    record['resources']['backups'] = {'old_path': 'synthetic-old', 'new_path': 'synthetic-new',
                                     'journal_id': 'synthetic-c5-id', 'state': 'active'}
    binding.write_text(json.dumps(record))
    chosen = 'sqlite+aiosqlite:///chosen.db'
    assert start(tmp_path, url=chosen, explicit=True) == chosen
    retired = json.loads(binding.read_text())['resources']
    assert 'database' not in retired
    assert retired['backups'] == record['resources']['backups']


def test_missing_bound_database_never_recreates_old_location(tmp_path):
    seed_bytes(tmp_path)
    configured = 'sqlite+aiosqlite:///./claude_registry.db'
    start(tmp_path, url=configured, explicit=True)
    (tmp_path / 'synth_city.db').unlink()
    binding = tmp_path / 'home' / BINDING
    before = binding.read_bytes()
    with pytest.raises(RuntimeError):
        start(tmp_path, url=configured, explicit=True)
    assert not (tmp_path / 'claude_registry.db').exists()
    assert binding.read_bytes() == before


@pytest.mark.parametrize('custom', ['sqlite+aiosqlite:///:memory:',
    'sqlite+aiosqlite:///file:temporary?mode=memory&uri=true',
    'postgresql+asyncpg://synthetic.invalid/database'])
@pytest.mark.parametrize('existing', [False, True])
def test_non_file_urls_are_full_noops_even_with_existing_binding(tmp_path, custom, existing):
    seed_bytes(tmp_path)
    home = tmp_path / 'home'
    if existing:
        binding = home / BINDING
        binding.parent.mkdir(parents=True)
        # Even unreadable/invalid metadata is irrelevant to a non-file URL.
        binding.write_bytes(b'synthetic invalid binding: must never be read')
    before = {str(p.relative_to(tmp_path)): p.read_bytes()
              for p in tmp_path.rglob('*') if p.is_file()}
    assert start(tmp_path, url=custom, explicit=True) == custom
    assert {str(p.relative_to(tmp_path)): p.read_bytes()
            for p in tmp_path.rglob('*') if p.is_file()} == before
    assert not (tmp_path / '.albiex-synth-city-db-upgrade.lock').exists()
    assert home.exists() == existing


def test_unset_retires_only_database_binding_and_uses_new_default(tmp_path):
    seed_bytes(tmp_path)
    start(tmp_path, url='sqlite+aiosqlite:///./claude_registry.db', explicit=True)
    before = database_files(tmp_path)
    binding = tmp_path / 'home' / BINDING
    start(tmp_path)
    assert json.loads(binding.read_text())['resources'] == {}
    assert database_files(tmp_path) == before


PRE_OPEN_CUTS = ['journal_durable', 'landed:-wal', 'landed:-shm', 'landed:-journal', 'landed:',
    'target_set_durable', 'source_removed:-wal', 'source_removed:-shm',
    'source_removed:-journal', 'source_removed:', 'journal_unlinked', 'journal_retired']


@pytest.mark.parametrize('cut', PRE_OPEN_CUTS)
def test_t_d5_power_cut_drops_unsynced_namespace_then_restarts_exactly_once(tmp_path, cut):
    root = tmp_path / 'case'
    seed_bytes(root)
    expected = database_files(root)
    model = DurableFilesystem(root, migration().FileOps(), cut)
    with pytest.raises(Interrupted, match='.'):
        start(root, ops=model)
    assert cut in model.events
    model.power_cut()
    start(root)
    result = database_files(root)
    assert result == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in expected.items()}
    assert not list(root.glob(JOURNALS))
    start(root)
    assert database_files(root) == result


@pytest.mark.parametrize('cross_device', [False, True])
def test_t_d5_returned_success_is_durable_before_first_connection(tmp_path, cross_device):
    root = tmp_path / 'case'
    seed_bytes(root)
    original = database_files(root)
    module = migration()

    class Storage(module.FileOps):
        def link(self, source, target):
            if cross_device and source.name.startswith('claude_registry.db'):
                raise OSError(errno.EXDEV, 'cross-device injection')
            return super().link(source, target)

    model = DurableFilesystem(root, Storage())
    start(root, ops=model)
    # Once the bootstrap returns, SQL may mutate the target immediately.
    # Recovery must not require running an old immutable-file journal again.
    model.power_cut()
    assert database_files(root) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in original.items()}
    assert not list(root.glob(JOURNALS))


@pytest.mark.parametrize('operation', ['sync_file', 'sync_dir', 'copy', 'link', 'unlink'])
def test_t_d5_failed_file_operations_preserve_every_byte_and_restart(tmp_path, operation):
    seed_bytes(tmp_path)
    expected = database_files(tmp_path)
    module = migration()
    fired = []

    class FailOnce(module.FileOps):
        def link(self, source, target):
            if operation == 'copy' and source.name.startswith('claude_registry.db'):
                raise OSError(errno.EXDEV, 'force copy path')
            return super().link(source, target)

    original = getattr(FailOnce, operation)

    def fail(self, *args, **kwargs):
        # Keep journal installation operational so failures exercise move stages too.
        path = args[0]
        if not fired and (operation in ('sync_file', 'sync_dir') or path.name.startswith('claude_registry.db')):
            fired.append(True)
            raise OSError(errno.EIO, 'injected storage failure')
        return original(self, *args, **kwargs)

    setattr(FailOnce, operation, fail)
    with pytest.raises((OSError, RuntimeError)):
        start(tmp_path, ops=FailOnce())
    assert fired
    # A journalled partial move can split the names, never lose any source bytes.
    for name, data in expected.items():
        candidates = [tmp_path / name, tmp_path / name.replace('claude_registry.db', 'synth_city.db')]
        assert any(p.exists() and p.read_bytes() == data for p in candidates)
    start(tmp_path)
    assert database_files(tmp_path) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in expected.items()}


COPY_CUTS = ['copy_written:-wal', 'copy_synced:-wal', 'copy_verified:-wal',
             'landed:', 'target_set_durable', 'source_removed:-wal', 'binding_durable']


@pytest.mark.parametrize('cut', COPY_CUTS)
def test_t_d5_cross_device_power_cut_resumes_both_populated_set_from_journal(tmp_path, cut):
    root = tmp_path / 'case'
    seed_bytes(root)
    original = database_files(root)
    module = migration()

    class CrossDevice(module.FileOps):
        def link(self, source, target):
            if source.name.startswith('claude_registry.db'):
                raise OSError(errno.EXDEV, 'cross-device injection')
            return super().link(source, target)

    model = DurableFilesystem(root, CrossDevice(), cut)
    configured = 'sqlite+aiosqlite:///./claude_registry.db'
    with pytest.raises(Interrupted):
        start(root, url=configured, explicit=True, ops=model)
    model.power_cut()
    start(root, url=configured, explicit=True, ops=CrossDevice())
    expected = {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in original.items()}
    assert database_files(root) == expected
    binding = root / 'home' / BINDING
    assert json.loads(binding.read_text())['resources']['database']['new_path'] == str(root / 'synth_city.db')
    metadata = binding.read_bytes()
    start(root, url=configured, explicit=True)
    assert database_files(root) == expected
    assert binding.read_bytes() == metadata
    assert not list(root.glob(JOURNALS))


@pytest.mark.parametrize('corruption', ['digest', 'paths', 'identity', 'metadata', 'duplicate',
    'order', 'copy_identity', 'empty_metadata', 'version_type'])
def test_t_d4_mismatched_or_multiple_journals_preserve_all_evidence(tmp_path, corruption):
    seed_bytes(tmp_path)
    module = migration()

    class Stop(module.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'journal_durable':
                raise Interrupted()

    with pytest.raises(Interrupted):
        start(tmp_path, ops=Stop())
    journal = next(tmp_path.glob(JOURNALS))
    value = json.loads(journal.read_text())
    if corruption == 'digest':
        value['files'][0]['sha256'] = '0' * 64
    elif corruption == 'paths':
        value['files'][0]['source'] = str(tmp_path / 'unrelated.db')
    elif corruption == 'identity':
        value['id'] = '11111111-1111-1111-1111-111111111111'
    elif corruption == 'metadata':
        value['existing_targets'] = {str(tmp_path / 'synth_city.db'): {'size': 1}}
    elif corruption == 'order':
        value['files'].reverse()
    elif corruption == 'copy_identity':
        value['files'][0]['target_identity']['ino'] += 1
    elif corruption == 'empty_metadata':
        value['empty_targets'] = [str(tmp_path / 'synth_city.db')]
        value['empty_states'] = {str(tmp_path / 'synth_city.db'): {'size': 0}}
    elif corruption == 'version_type':
        value['version'] = True
    else:
        (tmp_path / '.albiex-synth-city-db-upgrade.11111111-1111-1111-1111-111111111111.json').write_text(json.dumps(value))
    journal.write_text(json.dumps(value))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with pytest.raises(RuntimeError) as error:
        start(tmp_path)
    assert str(tmp_path / 'claude_registry.db') in str(error.value)
    assert str(tmp_path / 'synth_city.db') in str(error.value)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('name', ['claude_registry.db-wal', 'synth_city.db-wal'])
def test_t_d4_orphan_sidecars_stop_and_preserve_bytes(tmp_path, name):
    (tmp_path / name).write_bytes(b'orphan-WAL-state')
    before = database_files(tmp_path)
    with pytest.raises(RuntimeError) as error:
        start(tmp_path)
    assert 'claude_registry.db' in str(error.value) and 'synth_city.db' in str(error.value)
    assert database_files(tmp_path) == before


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm', '-journal'])
def test_t_d4_symlink_targets_never_followed_or_replaced(tmp_path, suffix):
    seed_bytes(tmp_path)
    elsewhere = tmp_path / 'unrelated'
    elsewhere.write_bytes(b'unrelated bytes')
    target = tmp_path / ('synth_city.db' + suffix)
    target.symlink_to(elsewhere)
    before = database_files(tmp_path)
    with pytest.raises(RuntimeError):
        start(tmp_path)
    assert target.is_symlink() and elsewhere.read_bytes() == b'unrelated bytes'
    assert database_files(tmp_path) == before


def test_dormant_binding_survives_memory_then_absolute_old_path_after_cwd_change(tmp_path):
    seed_bytes(tmp_path)
    configured = 'sqlite+aiosqlite:///' + str(tmp_path / 'claude_registry.db')
    effective = start(tmp_path, url=configured, explicit=True)
    binding = tmp_path / 'home' / BINDING
    original = binding.read_bytes()
    start(tmp_path, url='sqlite+aiosqlite:///:memory:', explicit=True)
    assert binding.read_bytes() == original
    other = tmp_path / 'elsewhere'
    other.mkdir()
    assert start(other, url=configured, explicit=True, home=tmp_path / 'home') == effective
    assert not (tmp_path / 'claude_registry.db').exists()
    assert binding.read_bytes() == original


def test_t_d5_no_replace_operation_preserves_a_target_that_appears_during_landing(tmp_path):
    seed_bytes(tmp_path)
    original = database_files(tmp_path)
    module = migration()
    collided = []

    class Collision(module.FileOps):
        def link(self, source, target):
            if source.name == 'claude_registry.db-wal' and not collided:
                target.write_bytes(b'unrelated concurrent target')
                collided.append(target)
            return super().link(source, target)

    with pytest.raises(RuntimeError):
        start(tmp_path, ops=Collision())
    assert collided[0].read_bytes() == b'unrelated concurrent target'
    for name, data in original.items():
        assert (tmp_path / name).read_bytes() == data


@pytest.mark.parametrize('failure', ['digest', 'short_write', 'mode'])
def test_t_d5_rejected_copy_keeps_all_sources_then_recovers_automatically(tmp_path, failure):
    seed_bytes(tmp_path)
    original = database_files(tmp_path)
    module = migration()

    class BadCopy(module.FileOps):
        def link(self, source, target):
            if source.name.startswith('claude_registry.db'):
                raise OSError(errno.EXDEV, 'cross-device injection')
            return super().link(source, target)

        def copy(self, source, temporary, metadata):
            super().copy(source, temporary, metadata)
            if failure == 'mode':
                temporary.chmod(metadata['mode'] ^ 0o100)
            else:
                data = temporary.read_bytes()
                temporary.write_bytes((bytes([data[0] ^ 1]) + data[1:]) if failure == 'digest' else data[:2])

    with pytest.raises(RuntimeError) as error:
        start(tmp_path, ops=BadCopy())
    assert str(tmp_path / 'claude_registry.db') in str(error.value)
    assert str(tmp_path / 'synth_city.db') in str(error.value)
    assert database_files(tmp_path) == original
    start(tmp_path)
    assert database_files(tmp_path) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in original.items()}


def test_t_d5_copy_file_sync_failure_discards_unverified_copy_and_keeps_sources(tmp_path):
    seed_bytes(tmp_path)
    original = database_files(tmp_path)
    module = migration()
    failed = []

    class FailCopySync(module.FileOps):
        def link(self, source, target):
            if source.name.startswith('claude_registry.db'):
                raise OSError(errno.EXDEV, 'cross-device injection')
            return super().link(source, target)

        def sync_file(self, path):
            if path.name.startswith('.synth_city.db') and path.name.endswith('.tmp'):
                failed.append(path)
                raise OSError(errno.EIO, 'copy fsync failure')
            return super().sync_file(path)

    with pytest.raises(RuntimeError):
        start(tmp_path, ops=FailCopySync())
    assert failed and not failed[0].exists()
    assert database_files(tmp_path) == original
    start(tmp_path)
    assert database_files(tmp_path) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in original.items()}


@pytest.mark.parametrize('boundary', ['landed:-wal', 'target_set_durable', 'source_removed:-wal'])
def test_t_d5_directory_sync_failure_after_landing_or_unlink_still_resumes(tmp_path, boundary):
    seed_bytes(tmp_path)
    original = database_files(tmp_path)
    module = migration()
    armed, failed = [], []

    class FailSync(module.FileOps):
        def checkpoint(self, stage, path):
            if stage == boundary:
                armed.append(True)

        def sync_dir(self, path):
            if armed and not failed:
                failed.append(True)
                raise OSError(errno.EIO, 'directory sync failure after movement')
            return super().sync_dir(path)

    with pytest.raises(RuntimeError):
        start(tmp_path, ops=FailSync())
    assert failed
    for name, data in original.items():
        assert any(p.exists() and p.read_bytes() == data for p in
            (tmp_path / name, tmp_path / name.replace('claude_registry.db', 'synth_city.db')))
    start(tmp_path)
    assert database_files(tmp_path) == {k.replace('claude_registry.db', 'synth_city.db'): v for k, v in original.items()}


@pytest.mark.parametrize('missing', SUFFIXES)
@pytest.mark.parametrize('existing_binding', [False, True])
def test_adoption_recovery_refuses_each_missing_recorded_target_before_open(tmp_path, missing, existing_binding):
    seed_bytes(tmp_path, name='synth_city.db')
    module = migration()

    class Stop(module.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'journal_durable':
                raise Interrupted()

    configured = 'sqlite+aiosqlite:///./claude_registry.db'
    binding = tmp_path / 'home' / BINDING
    if existing_binding:
        binding.parent.mkdir(parents=True)
        binding.write_text(json.dumps({'version': 1, 'resources': {'backups': {'owned_by': 'future-c5'}}}))
    with pytest.raises(Interrupted):
        start(tmp_path, url=configured, explicit=True, ops=Stop())
    journal = next(tmp_path.glob(JOURNALS))
    Path(str(tmp_path / 'synth_city.db') + missing).rename(tmp_path / 'quarantined-target')
    before = {str(path.relative_to(tmp_path)): path.read_bytes()
              for path in tmp_path.rglob('*') if path.is_file()}
    opened = []
    with pytest.raises(RuntimeError) as error:
        effective = start(tmp_path, url=configured, explicit=True)
        # This boundary must be unreachable, especially for the missing main:
        # SQLite would otherwise silently create an empty database here.
        opened.append(True)
        connection = sqlite3.connect(make_url(effective).database)
        connection.close()
    assert not opened
    assert str(tmp_path / 'claude_registry.db') in str(error.value)
    assert str(tmp_path / 'synth_city.db') in str(error.value)
    assert journal.exists() and binding.exists() == existing_binding
    assert {str(path.relative_to(tmp_path)): path.read_bytes()
            for path in tmp_path.rglob('*') if path.is_file()} == before


def test_valid_adoption_journal_recovers_and_preserves_shared_binding_state(tmp_path):
    seed_bytes(tmp_path, name='synth_city.db')
    module = migration()
    binding = tmp_path / 'home' / BINDING
    binding.parent.mkdir(parents=True)
    unrelated = {'backups': {'owned_by': 'future-c5'}}
    binding.write_text(json.dumps({'version': 1, 'resources': unrelated}))

    class Stop(module.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'journal_durable':
                raise Interrupted()

    configured = 'sqlite+aiosqlite:///./claude_registry.db'
    before = database_files(tmp_path)
    with pytest.raises(Interrupted):
        start(tmp_path, url=configured, explicit=True, ops=Stop())
    effective = start(tmp_path, url=configured, explicit=True)
    assert Path(make_url(effective).database) == tmp_path / 'synth_city.db'
    assert database_files(tmp_path) == before
    record = json.loads(binding.read_text())
    assert record['resources']['backups'] == unrelated['backups']
    assert record['resources']['database']['state'] == 'active'
    assert not list(tmp_path.glob(JOURNALS))


@pytest.mark.parametrize('name', ['case#fragment', 'case?fragment', 'case%23fragment', 'plain-control'])
def test_generated_sqlite_uri_opens_preserved_database_with_special_path_characters(tmp_path, monkeypatch, name):
    from sqlalchemy import create_engine

    root = tmp_path / name
    root.mkdir()
    monkeypatch.chdir(root)
    original = create_engine('sqlite:///./claude_registry.db')
    with original.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE preserved(value TEXT)')
        connection.exec_driver_sql("INSERT INTO preserved VALUES ('historical-row')")
    original.dispose()
    configured = 'sqlite+aiosqlite:///file:./claude_registry.db?uri=true&mode=rw&cache=private'
    result = start(root, url=configured, explicit=True, home=tmp_path / 'home')
    parsed = make_url(result)
    assert parsed.drivername == 'sqlite+aiosqlite'
    assert parsed.query == make_url(configured).query
    engine = create_engine(parsed.set(drivername='sqlite'))
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql('SELECT value FROM preserved').fetchall() == [('historical-row',)]
            assert Path(connection.exec_driver_sql('PRAGMA database_list').fetchone()[2]) == root / 'synth_city.db'
            connection.exec_driver_sql("INSERT INTO preserved VALUES ('legitimate-first-open-write')")
    finally:
        engine.dispose()
    assert not (root / 'claude_registry.db').exists()
    assert start(root, url=configured, explicit=True, home=tmp_path / 'home') == result


@pytest.mark.parametrize('query', ['', '?uri=false'])
def test_uri_disabled_file_prefix_is_a_literal_custom_filename(tmp_path, monkeypatch, query):
    from sqlalchemy import create_engine

    monkeypatch.chdir(tmp_path)
    engine = create_engine('sqlite:///file:claude_registry.db' + query)
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE custom_data(value TEXT)')
        connection.exec_driver_sql("INSERT INTO custom_data VALUES ('preserve-custom')")
    engine.dispose()
    seed_bytes(tmp_path)
    original = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    configured = 'sqlite+aiosqlite:///file:claude_registry.db' + query
    assert start(tmp_path, url=configured, explicit=True) == configured
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == original
    assert not (tmp_path / 'home').exists()


def test_mode_memory_without_uri_is_a_real_disk_database(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    monkeypatch.chdir(tmp_path)
    engine = create_engine('sqlite:///./claude_registry.db?mode=memory')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE preserved(value TEXT)')
    engine.dispose()
    result = start(tmp_path, url='sqlite+aiosqlite:///./claude_registry.db?mode=memory', explicit=True)
    assert Path(make_url(result).database) == tmp_path / 'synth_city.db'
    assert not (tmp_path / 'claude_registry.db').exists()
    assert make_url(result).query['mode'] == 'memory'


@pytest.mark.parametrize('version', [True, 1.0, 1])
def test_binding_version_requires_integer_one_and_preserves_invalid_evidence(tmp_path, version):
    configured = 'sqlite+aiosqlite:///./claude_registry.db'
    seed_bytes(tmp_path)
    module = migration()

    class Stop(module.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'binding_durable':
                raise Interrupted()

    if type(version) is int:
        effective = start(tmp_path, url=configured, explicit=True)
    else:
        with pytest.raises(Interrupted):
            start(tmp_path, url=configured, explicit=True, ops=Stop())
        assert list(tmp_path.glob(JOURNALS)), 'negative case must preserve real recovery evidence'
    binding = tmp_path / 'home' / BINDING
    value = json.loads(binding.read_text())
    value['version'] = version
    binding.write_text(json.dumps(value))
    before = {str(path.relative_to(tmp_path)): path.read_bytes()
              for path in tmp_path.rglob('*') if path.is_file()}
    if type(version) is int:
        assert start(tmp_path, url=configured, explicit=True) == effective
    else:
        with pytest.raises(RuntimeError):
            start(tmp_path, url=configured, explicit=True)
    assert {str(path.relative_to(tmp_path)): path.read_bytes()
            for path in tmp_path.rglob('*') if path.is_file()} == before


@pytest.mark.parametrize('kind', ['file', 'directory'])
def test_production_sync_boundary_calls_fsync_on_the_right_descriptor(tmp_path, monkeypatch, kind):
    import os

    module = migration()
    path = tmp_path / 'regular-file'
    path.write_bytes(b'preserved')
    expected = (path if kind == 'file' else tmp_path).stat()
    called = []
    real_sync = os.fsync

    def observe(descriptor):
        actual = os.fstat(descriptor)
        called.append((actual.st_dev, actual.st_ino, stat.S_ISDIR(actual.st_mode)))
        return real_sync(descriptor)

    monkeypatch.setattr(module.os, 'fsync', observe)
    ops = module.FileOps()
    (ops.sync_file if kind == 'file' else ops.sync_dir)(path if kind == 'file' else tmp_path)
    assert called == [(expected.st_dev, expected.st_ino, kind == 'directory')]


@pytest.mark.parametrize('kind', ['file', 'directory'])
def test_production_sync_failure_propagates_and_closes_descriptor(tmp_path, monkeypatch, kind):
    import os

    module = migration()
    path = tmp_path / 'regular-file'
    path.write_bytes(b'preserved')
    descriptors = []

    def fail(descriptor):
        descriptors.append(descriptor)
        raise OSError(errno.EIO, 'injected actual fsync failure')

    monkeypatch.setattr(module.os, 'fsync', fail)
    ops = module.FileOps()
    with pytest.raises(OSError) as error:
        (ops.sync_file if kind == 'file' else ops.sync_dir)(path if kind == 'file' else tmp_path)
    assert error.value.errno == errno.EIO
    assert len(descriptors) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF
    assert path.read_bytes() == b'preserved'


@pytest.mark.parametrize('authority', ['', 'localhost'])
def test_absolute_file_uri_resolves_the_same_default_database(tmp_path, monkeypatch, authority):
    from sqlalchemy import create_engine

    monkeypatch.chdir(tmp_path)
    engine = create_engine('sqlite:///./claude_registry.db')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE preserved(value TEXT)')
    engine.dispose()
    uri = (tmp_path / 'claude_registry.db').as_uri()
    if authority:
        uri = uri.replace('file:///', 'file://localhost/', 1)
    configured = 'sqlite+aiosqlite:///' + uri + '?uri=true'
    result = start(tmp_path, url=configured, explicit=True)
    assert not (tmp_path / 'claude_registry.db').exists()
    engine = create_engine(make_url(result).set(drivername='sqlite'))
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='preserved'").fetchall() == [('preserved',)]
            assert Path(connection.exec_driver_sql('PRAGMA database_list').fetchone()[2]) == tmp_path / 'synth_city.db'
    finally:
        engine.dispose()


@pytest.mark.parametrize('mode', ['ro', 'memory'])
def test_uri_enabled_without_file_scheme_keeps_the_dialects_literal_filename(tmp_path, monkeypatch, mode):
    from sqlalchemy import create_engine

    monkeypatch.chdir(tmp_path)
    configured = 'sqlite+aiosqlite:///./claude_registry.db?uri=true&mode=' + mode
    engine = create_engine(make_url(configured).set(drivername='sqlite'))
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE custom_data(value TEXT)')
    engine.dispose()
    assert (tmp_path / ('claude_registry.db?mode=' + mode)).exists()
    # A real converted resource already has a binding. Choosing this other
    # disk file must retire it; it is neither the old default nor memory.
    seed_bytes(tmp_path)
    start(tmp_path, url='sqlite+aiosqlite:///./claude_registry.db', explicit=True)
    before = database_files(tmp_path)
    assert start(tmp_path, url=configured, explicit=True) == configured
    assert database_files(tmp_path) == before
    assert 'database' not in json.loads((tmp_path / 'home' / BINDING).read_text())['resources']


@pytest.mark.parametrize('query', ['', '?mode=memory', '?uri=false'])
def test_plain_sqlite_url_in_question_mark_cwd_still_opens_the_moved_file(tmp_path, monkeypatch, query):
    from sqlalchemy import create_engine

    root = tmp_path / 'case?fragment'
    root.mkdir()
    monkeypatch.chdir(root)
    engine = create_engine('sqlite:///./claude_registry.db' + query)
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE preserved(value TEXT)')
    engine.dispose()
    configured = 'sqlite+aiosqlite:///./claude_registry.db' + query
    result = start(root, url=configured, explicit=True)
    assert make_url(result).query == make_url(configured).query
    engine = create_engine(make_url(result).set(drivername='sqlite'))
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='preserved'").fetchall() == [('preserved',)]
            assert Path(connection.exec_driver_sql('PRAGMA database_list').fetchone()[2]) == root / 'synth_city.db'
    finally:
        engine.dispose()


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('mode', ['memory', 'ro'])
def test_uri_fragment_ignored_native_options_stay_ignored_after_move(tmp_path, monkeypatch, bound, mode):
    from sqlalchemy import create_engine

    monkeypatch.chdir(tmp_path)
    configured = ('sqlite+aiosqlite:///file:./claude_registry.db#label?uri=true&mode=' + mode
                  + '&timeout=7&check_same_thread=false&cached_statements=17')
    parsed = make_url(configured)
    before_python_options = parsed.get_dialect()().create_connect_args(parsed)[1]
    engine = create_engine(parsed.set(drivername='sqlite'))
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE preserved(value TEXT)')
        connection.exec_driver_sql("INSERT INTO preserved VALUES ('historical-row')")
        assert Path(connection.exec_driver_sql('PRAGMA database_list').fetchone()[2]) == tmp_path / 'claude_registry.db'
    engine.dispose()
    if bound:
        start(tmp_path, url='sqlite+aiosqlite:///./claude_registry.db', explicit=True)
    result = start(tmp_path, url=configured, explicit=True)
    effective = make_url(result)
    assert effective.drivername == parsed.drivername
    assert effective.get_dialect()().create_connect_args(effective)[1] == before_python_options
    engine = create_engine(effective.set(drivername='sqlite'))
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql('SELECT value FROM preserved').fetchall() == [('historical-row',)]
            assert Path(connection.exec_driver_sql('PRAGMA database_list').fetchone()[2]) == tmp_path / 'synth_city.db'
            connection.exec_driver_sql("INSERT INTO preserved VALUES ('still-writable')")
    finally:
        engine.dispose()
    assert not (tmp_path / 'claude_registry.db').exists()
    assert start(tmp_path, url=configured, explicit=True) == result


@pytest.mark.parametrize('existing_metadata', [False, True])
def test_uri_fragment_terminated_memory_mode_is_a_complete_noop(tmp_path, monkeypatch, existing_metadata):
    from sqlalchemy import create_engine

    monkeypatch.chdir(tmp_path)
    configured = 'sqlite+aiosqlite:///file:./claude_registry.db?uri=true&mode=memory#label'
    engine = create_engine(make_url(configured).set(drivername='sqlite'))
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE transient(value TEXT)')
        assert connection.exec_driver_sql('PRAGMA database_list').fetchone()[2] == ''
    engine.dispose()
    seed_bytes(tmp_path)
    binding = tmp_path / 'home' / BINDING
    if existing_metadata:
        binding.parent.mkdir(parents=True)
        binding.write_bytes(b'malformed metadata must not be read for a memory URL')
    before = {str(path.relative_to(tmp_path)): path.read_bytes()
              for path in tmp_path.rglob('*') if path.is_file()}
    assert start(tmp_path, url=configured, explicit=True) == configured
    assert {str(path.relative_to(tmp_path)): path.read_bytes()
            for path in tmp_path.rglob('*') if path.is_file()} == before
    assert not (tmp_path / migration().LOCK_NAME).exists()


@pytest.mark.parametrize(('spelling', 'filename'), [
    ('\tclaude_registry.db', '\tclaude_registry.db'),
    ('\nclaude_registry.db', '\nclaude_registry.db'),
    ('\rclaude_registry.db', '\rclaude_registry.db'),
    ('%09claude_registry.db', '\tclaude_registry.db'),
    ('%0Aclaude_registry.db', '\nclaude_registry.db'),
    ('%0Dclaude_registry.db', '\rclaude_registry.db'),
    ('custom-claude_registry.db', 'custom-claude_registry.db'),
], ids=['literal-TAB', 'literal-LF', 'literal-CR', 'escaped-TAB', 'escaped-LF', 'escaped-CR', 'ordinary'])
def test_literal_uri_control_characters_preserve_custom_filename_and_unrelated_default(tmp_path, monkeypatch, spelling, filename):
    from sqlalchemy import create_engine

    monkeypatch.chdir(tmp_path)
    configured = 'sqlite+aiosqlite:///file:./' + spelling + '?uri=true&cache=private'
    engine = create_engine(make_url(configured).set(drivername='sqlite'))
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE custom_data(value TEXT)')
        assert Path(connection.exec_driver_sql('PRAGMA database_list').fetchone()[2]) == tmp_path / filename
    engine.dispose()
    seed_bytes(tmp_path)
    before = {str(path.relative_to(tmp_path)): path.read_bytes()
              for path in tmp_path.rglob('*') if path.is_file()}
    assert start(tmp_path, url=configured, explicit=True) == configured
    assert {str(path.relative_to(tmp_path)): path.read_bytes()
            for path in tmp_path.rglob('*') if path.is_file()} == before
    assert not (tmp_path / 'home').exists()
