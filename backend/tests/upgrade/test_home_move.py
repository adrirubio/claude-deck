"""C5: file/location T-D6 and allocation-only T-D7, without reference writes."""
import errno
import hashlib
import json
from pathlib import Path
import stat

import pytest
from sqlalchemy.engine import make_url

from app import upgrade_bootstrap as migration
from .database_move_faults import DurableFilesystem, Interrupted


OLD = '.claude-registry'
NEW = '.albiex-synth-city'
BINDING = 'upgrade-location-bindings.json'


@pytest.fixture
def roots(tmp_path, monkeypatch):
    home, cwd = tmp_path / 'home', tmp_path / 'backend'
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv('HOME', str(home))
    return home, cwd


def put(path, content=b'old-file'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and not p.name.endswith('.lock')}


def start(roots, *, database=None, attachments=None, test_instance=False, ops=None):
    home, cwd = roots
    return migration.prepare_resource_locations(
        database or 'sqlite+aiosqlite:///./synth_city.db',
        attachments or '~/.albiex-synth-city/bridge-attachments',
        database_explicit=database is not None, attachment_explicit=attachments is not None,
        cwd=cwd, home=home, test_instance=test_instance, ops=ops)


def references(home):
    return migration.read_reference_journals(home=home)


def mappings(home, resource):
    return {row['source']: row['target'] for record in references(home)
            for row in record['resources'].get(resource, {}).get('mappings', [])}


@pytest.mark.parametrize('database', ['default', 'custom', 'memory', 'postgres'])
@pytest.mark.parametrize('attachments', ['default', 'custom'])
def test_t_d6_each_resource_is_eligible_independently(roots, database, attachments):
    home, cwd = roots
    old_db = put(cwd / 'claude_registry.db', b'original-database')
    backup = put(home / OLD / 'backups/export.zip', b'backup')
    attachment = put(home / OLD / 'bridge-attachments/session/image.png', b'image')
    custom_attachment = put(home / 'custom-attachments/image.png', b'custom-image')
    custom_db = put(cwd / 'custom.db', b'custom-database')
    choices = {'default': None, 'custom': 'sqlite+aiosqlite:///' + str(custom_db),
               'memory': 'sqlite+aiosqlite:///:memory:', 'postgres': 'postgresql+asyncpg://host/name'}
    db_url, attachment_root = start(roots, database=choices[database],
        attachments=str(custom_attachment.parent) if attachments == 'custom' else None)
    assert (home / NEW / 'backups/export.zip').read_bytes() == b'backup'
    assert not backup.exists()
    assert mappings(home, 'backups')[str(backup)] == str(home / NEW / 'backups/export.zip')
    if database == 'default':
        assert not old_db.exists()
        assert Path(make_url(db_url).database).read_bytes() == b'original-database'
    else:
        assert old_db.read_bytes() == b'original-database'
        assert db_url == choices[database]
    assert custom_db.read_bytes() == b'custom-database'
    assert custom_attachment.read_bytes() == b'custom-image'
    if attachments == 'default':
        assert not attachment.exists()
        assert Path(attachment_root) == home / NEW / 'bridge-attachments'
        assert mappings(home, 'attachments')[str(attachment)] == str(home / NEW / 'bridge-attachments/session/image.png')
    else:
        assert attachment_root == str(custom_attachment.parent)
        assert not mappings(home, 'attachments')


def test_only_old_home_uses_no_replace_unit_rename_and_keeps_inode_metadata(roots):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip')
    put(home / OLD / 'misc/state', b'other-owned-state')
    (home / OLD / 'empty').mkdir()
    source.chmod(0o640)
    before, directory = source.stat(), (home / OLD).stat()
    start(roots, database='sqlite+aiosqlite:///:memory:')
    target = home / NEW / 'backups/a.zip'
    assert target.stat().st_ino == before.st_ino
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert (target.stat().st_uid, target.stat().st_gid, target.stat().st_mtime_ns) == (before.st_uid, before.st_gid, before.st_mtime_ns)
    assert (home / NEW).stat().st_ino == directory.st_ino
    assert (home / NEW / 'empty').is_dir()
    assert (home / NEW / 'misc/state').read_bytes() == b'other-owned-state'
    assert not (home / OLD).exists()


@pytest.mark.parametrize('nested', ['sibling', 'inside-backups', 'database'])
def test_t_d6_containment_preserves_custom_locations_and_reports_exclusions(roots, nested):
    home, cwd = roots
    backup = put(home / OLD / 'backups/a.zip', b'backup')
    put(home / OLD / 'bridge-attachments/a.png', b'image')
    if nested == 'database':
        protected = put(home / OLD / 'custom.db', b'custom-db')
        put(Path(str(protected) + '-wal'), b'custom-wal')
        kwargs = {'database': 'sqlite+aiosqlite:///' + str(protected)}
    else:
        protected = put(home / OLD / ('backups/uploads/a.png' if nested == 'inside-backups' else 'my-attachments/a.png'), b'custom-image')
        kwargs = {'attachments': str(protected.parent)}
    original = {str(p): p.read_bytes() for p in protected.parent.glob(protected.name + '*')}
    start(roots, **kwargs)
    assert {name: Path(name).read_bytes() for name in original} == original
    assert protected.exists()
    assert (home / OLD).exists()
    assert (home / NEW / 'backups/a.zip').read_bytes() == b'backup'
    assert not backup.exists()
    diagnostics = [record['diagnostics'] for record in references(home)]
    assert any(str(protected if nested == 'database' else protected.parent) in record['excluded'] for record in diagnostics)
    assert all(str(protected) not in mapping for mapping in (mappings(home, 'backups'), mappings(home, 'attachments')))


@pytest.mark.parametrize('overlap', ['same-root', 'attachment-contains-home'])
def test_t_d6_unclassifiable_overlap_stops_before_any_database_or_home_move(roots, overlap):
    home, cwd = roots
    put(cwd / 'claude_registry.db', b'old-db')
    put(home / OLD / 'backups/a.zip', b'backup')
    before = files(home), files(cwd)
    location = home / OLD / 'backups' if overlap == 'same-root' else home
    with pytest.raises(RuntimeError, match='(?i)overlap|containment|conflict'):
        start(roots, attachments=str(location))
    assert all((home / name).read_bytes() == data for name, data in before[0].items())
    assert files(cwd) == before[1]


def test_t_d6_explicit_old_attachment_binding_survives_two_starts_and_retires_independently(roots):
    home, cwd = roots
    old = home / OLD / 'bridge-attachments'
    put(old / 'a.png', b'image')
    put(cwd / 'claude_registry.db', b'db')
    db_url = 'sqlite+aiosqlite:///./claude_registry.db'
    first = start(roots, database=db_url, attachments=str(old))
    binding = home / NEW / BINDING
    original = binding.read_bytes()
    entry = json.loads(original)['resources']['attachments']
    assert entry['state'] == 'active' and entry['old_path'] == str(old)
    assert entry['new_path'] == first[1] and entry['journal_id']
    checkpoint = files(home)
    assert start(roots, database=db_url, attachments=str(old)) == first
    assert binding.read_bytes() == original
    assert files(home) == checkpoint
    assert first[1] == str(home / NEW / 'bridge-attachments')
    assert not old.exists()
    custom = home / 'intentional-new-root'
    custom.mkdir()
    assert start(roots, database=db_url, attachments=str(custom))[1] == str(custom)
    value = json.loads(binding.read_text())['resources']
    assert 'attachments' not in value
    assert 'database' in value


def test_t_d6_unset_attachment_value_retires_only_its_binding(roots):
    home, cwd = roots
    old = home / OLD / 'bridge-attachments'
    put(old / 'a.png')
    start(roots, attachments=str(old))
    start(roots)
    assert 'attachments' not in json.loads((home / NEW / BINDING).read_text())['resources']


def test_missing_bound_attachment_root_stops_without_recreating_old_or_mutating_evidence(roots):
    home, cwd = roots
    old = home / OLD / 'bridge-attachments'
    start(roots, attachments=str(old))
    binding = home / NEW / BINDING
    evidence = binding.read_bytes()
    (home / NEW / 'bridge-attachments').rmdir()
    with pytest.raises(RuntimeError, match='(?i)binding.*missing|missing.*binding'):
        start(roots, attachments=str(old))
    assert binding.read_bytes() == evidence
    assert not old.exists()


def test_t_d6_same_basename_elsewhere_is_custom(roots):
    home, cwd = roots
    custom = put(home / 'elsewhere/bridge-attachments/a.png')
    db = put(cwd / 'elsewhere/claude_registry.db', b'custom-db')
    root = custom.parent
    actual = start(roots, database='sqlite+aiosqlite:///' + str(db), attachments=str(root))
    assert actual == ('sqlite+aiosqlite:///' + str(db), str(root))
    assert custom.read_bytes() == b'old-file'
    assert db.read_bytes() == b'custom-db'


def test_t_d6_test_instance_disables_every_move_and_metadata_access(roots):
    home, cwd = roots
    put(cwd / 'claude_registry.db')
    put(home / OLD / 'backups/a.zip')
    before = files(home), files(cwd)
    actual = start(roots, database='synthetic-invalid-url', attachments='~/.claude-registry/bridge-attachments', test_instance=True)
    assert actual == ('synthetic-invalid-url', '~/.claude-registry/bridge-attachments')
    assert (files(home), files(cwd)) == before


def test_t_d7_colliding_backup_and_attachment_names_are_lossless_and_exactly_mapped(roots):
    home, cwd = roots
    expected = {}
    for resource, relative in [('backups', 'export.zip'), ('bridge-attachments', 'session/image.png')]:
        source = put(home / OLD / resource / relative, b'incoming-' + resource.encode())
        target = put(home / NEW / resource / relative, b'existing-' + resource.encode())
        expected[resource] = (source, target, target.read_bytes(), hashlib.sha256(source.read_bytes()).hexdigest())
    start(roots)
    for resource, (source, target, original, digest) in expected.items():
        mapping = mappings(home, 'attachments' if resource == 'bridge-attachments' else resource)
        allocated = Path(mapping[str(source)])
        assert allocated != target
        assert allocated.is_relative_to(home / NEW / resource)
        assert hashlib.sha256(allocated.read_bytes()).hexdigest() == digest
        assert target.read_bytes() == original
        assert not source.exists()
    checkpoint = files(home)
    start(roots)
    assert files(home) == checkpoint


def test_t_d7_unmappable_destination_stops_loudly_and_leaves_incoming_file(roots):
    home, cwd = roots
    source = put(home / OLD / 'backups/session/a.zip', b'incoming')
    blocking = put(home / NEW / 'backups/session', b'not-a-directory')
    with pytest.raises(RuntimeError, match='(?i)conflict|incomplete|allocat') as raised:
        start(roots)
    assert str(source) in str(raised.value) or str(blocking) in str(raised.value)
    assert source.read_bytes() == b'incoming'
    assert blocking.read_bytes() == b'not-a-directory'


@pytest.mark.parametrize('which', ['source-link', 'target-link', 'source-fifo'])
def test_special_paths_stop_without_following_or_replacing_them(roots, which):
    home, cwd = roots
    external = put(home / 'outside', b'private-outside')
    source = put(home / OLD / 'backups/a.zip')
    if which == 'source-fifo':
        source.unlink()
        import os
        os.mkfifo(source)
    elif which == 'source-link':
        source.unlink()
        source.symlink_to(external)
    else:
        target = home / NEW / 'backups/a.zip'
        target.parent.mkdir(parents=True)
        target.symlink_to(external)
    with pytest.raises(RuntimeError, match='(?i)regular|symlink|special|conflict'):
        start(roots)
    assert external.read_bytes() == b'private-outside'


def test_reference_contract_survives_open_and_never_rechecks_mutable_file_digests(roots):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip')
    start(roots)
    records = references(home)
    assert records
    reference = records[0]
    assert type(reference['version']) is int and reference['version'] == 1
    assert reference['kind'] == 'references'
    assert reference['stage'] == 'files_landed'
    assert reference['move_journal_id']
    assert reference['resources']['backups']['source_root'] == str(home / OLD / 'backups')
    assert reference['resources']['backups']['target_root'] == str(home / NEW / 'backups')
    # C6 consumes only ownership mappings. A post-open file is not immutable.
    Path(mappings(home, 'backups')[str(source)]).write_bytes(b'legitimate-post-open-mutation')
    start(roots)
    assert references(home) == records
    assert not [p for p in home.glob('.albiex-synth-city-upgrade.*.json') if json.loads(p.read_text()).get('kind') != 'references']


HOME_CUTS = ['home_journal_durable', 'home_landed:0', 'home_targets_durable',
             'home_source_removed:0', 'home_reference_durable',
             'home_file_journal_unlinked', 'home_file_journal_retired']


@pytest.mark.parametrize('cut', HOME_CUTS)
@pytest.mark.parametrize('cross_device', [False, True])
def test_home_power_cut_resumes_durable_allocation_and_reference_handoff(tmp_path, monkeypatch, cut, cross_device):
    root = tmp_path / 'disk'
    home, cwd = root / 'home', root / 'backend'
    home.mkdir(parents=True)
    cwd.mkdir()
    monkeypatch.setenv('HOME', str(home))
    source = put(home / OLD / 'backups/a.zip', b'new-backup')
    target = put(home / NEW / 'backups/a.zip', b'existing-backup')
    class CrossDevice(migration.FileOps):
        def link(self, source, target):
            if cross_device and source.name == 'a.zip':
                raise OSError(errno.EXDEV, 'simulated cross-device boundary')
            return super().link(source, target)
    durable = DurableFilesystem(root, CrossDevice(), cut=cut)
    with pytest.raises(Interrupted):
        start((home, cwd), ops=durable)
    durable.power_cut()
    start((home, cwd), ops=CrossDevice())
    assert target.read_bytes() == b'existing-backup'
    assert Path(mappings(home, 'backups')[str(source)]).read_bytes() == b'new-backup'
    assert not source.exists()
    before = files(home)
    start((home, cwd))
    assert files(home) == before


@pytest.mark.parametrize('operation', ['link', 'sync_file', 'sync_dir', 'copy', 'unlink'])
def test_home_failed_file_operation_preserves_all_bytes_and_can_resume(roots, operation):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip', b'incoming')
    put(home / NEW / 'backups/a.zip', b'existing')
    class Failure(migration.FileOps):
        tripped = False
        def __getattribute__(self, name):
            original = super().__getattribute__(name)
            if name == 'link':
                def linking(source, target):
                    if operation == 'copy' and source.name == 'a.zip':
                        raise OSError(errno.EXDEV, 'force copy')
                    return original(source, target)
                if operation != 'link':
                    return linking
            if name == operation:
                def failing(*args, **kwargs):
                    if not self.tripped:
                        self.tripped = True
                        raise OSError(errno.ENOSPC, 'injected failure')
                    return original(*args, **kwargs)
                return failing
            return original
    with pytest.raises(RuntimeError):
        start(roots, ops=Failure())
    assert source.read_bytes() == b'incoming'
    assert (home / NEW / 'backups/a.zip').read_bytes() == b'existing'
    start(roots)
    assert Path(mappings(home, 'backups')[str(source)]).read_bytes() == b'incoming'


def test_target_arriving_after_allocation_is_never_overwritten_or_counted_as_landed(roots):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip', b'incoming')
    (home / NEW).mkdir()
    arrived = []
    class Race(migration.FileOps):
        def link(self, source, target):
            if source.name == 'a.zip':
                target.write_bytes(b'arrived-after-allocation')
                arrived.append(target)
            return super().link(source, target)
    with pytest.raises(RuntimeError):
        start(roots, ops=Race())
    assert source.read_bytes() == b'incoming'
    assert arrived and arrived[0].read_bytes() == b'arrived-after-allocation'
    with pytest.raises(RuntimeError, match='(?i)incomplete|file.phase|in progress'):
        references(home)


@pytest.mark.parametrize('corruption', ['bool-version', 'outside-root', 'duplicate-target', 'unknown-stage'])
def test_malformed_retained_reference_record_stops_without_mutating_evidence(roots, corruption):
    home, cwd = roots
    put(home / OLD / 'backups/a.zip')
    start(roots)
    record_path = next(p for p in home.glob('.albiex-synth-city-upgrade.*.json')
                       if json.loads(p.read_text()).get('kind') == 'references')
    value = json.loads(record_path.read_text())
    if corruption == 'bool-version':
        value['version'] = True
    elif corruption == 'outside-root':
        value['resources']['backups']['mappings'][0]['target'] = str(home / 'outside')
    elif corruption == 'duplicate-target':
        value['resources']['backups']['mappings'].append(value['resources']['backups']['mappings'][0].copy())
    else:
        value['stage'] = 'references_done'
    record_path.write_text(json.dumps(value))
    before = files(home), files(cwd)
    with pytest.raises(RuntimeError, match='(?i)reference|journal'):
        start(roots)
    assert (files(home), files(cwd)) == before


def test_existing_c4_binding_uses_mutated_database_without_re_move_or_digest_check(roots, monkeypatch):
    import sqlite3
    home, cwd = roots
    old = cwd / 'claude_registry.db'
    with sqlite3.connect(old) as db:
        db.execute('CREATE TABLE preserved(value TEXT)')
        db.execute("INSERT INTO preserved VALUES('before')")
    configured = 'sqlite+aiosqlite:///' + str(old)
    converted = migration.prepare_database_url(configured, explicit=True, home=home, cwd=cwd)
    target = Path(make_url(converted).database)
    with sqlite3.connect(target) as db:
        db.execute("INSERT INTO preserved VALUES('after legitimate open')")
    put(home / OLD / 'backups/a.zip', b'backup')
    original = migration._snapshot
    def no_post_open_digest(path):
        assert path != target, 'C5 digested an already-open C4 database'
        return original(path)
    monkeypatch.setattr(migration, '_snapshot', no_post_open_digest)
    actual, _ = start(roots, database=configured)
    assert actual == converted
    assert not old.exists()
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT value FROM preserved ORDER BY rowid').fetchall() == [('before',), ('after legitimate open',)]


@pytest.mark.parametrize('cut', ['home_journal_durable', 'home_unit_renamed', 'home_targets_durable', 'home_reference_durable'])
def test_unit_directory_rename_power_cut_preserves_complete_durable_tree(tmp_path, monkeypatch, cut):
    root = tmp_path / 'disk'
    home, cwd = root / 'home', root / 'backend'
    home.mkdir(parents=True)
    cwd.mkdir()
    monkeypatch.setenv('HOME', str(home))
    source = put(home / OLD / 'backups/a.zip', b'backup')
    put(home / OLD / 'bridge-attachments/a.png', b'image')
    durable = DurableFilesystem(root, migration.FileOps(), cut=cut)
    with pytest.raises(Interrupted):
        start((home, cwd), database='sqlite+aiosqlite:///:memory:', ops=durable)
    durable.power_cut()
    start((home, cwd), database='sqlite+aiosqlite:///:memory:')
    assert Path(mappings(home, 'backups')[str(source)]).read_bytes() == b'backup'
    assert (home / NEW / 'bridge-attachments/a.png').read_bytes() == b'image'
    assert not (home / OLD).exists()


@pytest.mark.parametrize('resource', ['attachments', 'database'])
def test_resume_rechecks_new_custom_containment_before_moving_a_previously_planned_file(roots, resource):
    home, cwd = roots
    protected = put(home / OLD / 'backups/uploads/custom.data', b'newly-custom')
    put(home / OLD / 'backups/a.zip', b'backup')
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_journal_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    before = files(home), files(cwd)
    kwargs = {'attachments': str(protected.parent)} if resource == 'attachments' else {
        'database': 'sqlite+aiosqlite:///' + str(protected)}
    with pytest.raises(RuntimeError, match='(?i)containment|conflict|custom'):
        start(roots, **kwargs)
    assert (files(home), files(cwd)) == before
    assert protected.read_bytes() == b'newly-custom'


def test_unit_rename_never_replaces_even_an_empty_target_directory(roots):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip', b'incoming')
    identity = []
    class Race(migration.FileOps):
        def rename_directory(self, source, target):
            target.mkdir(mode=0o700)
            identity.append(target.stat().st_ino)
            return super().rename_directory(source, target)
    with pytest.raises(RuntimeError):
        start(roots, database='sqlite+aiosqlite:///:memory:', ops=Race())
    assert source.read_bytes() == b'incoming'
    assert (home / NEW).stat().st_ino == identity[0]


def test_unit_rename_requires_durable_intent_and_mapping_before_namespace_mutation(roots):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip')
    class Observe(migration.FileOps):
        def rename_directory(self, old, new):
            journal = next(home.glob('.albiex-synth-city-upgrade.*.json'))
            value = json.loads(journal.read_text())
            assert value['files'][0]['source'] == str(source)
            assert value['files'][0]['target'] == str(home / NEW / 'backups/a.zip')
            return super().rename_directory(old, new)
    start(roots, database='sqlite+aiosqlite:///:memory:', ops=Observe())


def test_custom_database_parent_remains_available_before_first_database_creation(roots):
    home, cwd = roots
    put(home / OLD / 'backups/a.zip')
    custom = home / OLD / 'not-yet-created.db'
    actual, _ = start(roots, database='sqlite+aiosqlite:///' + str(custom))
    assert actual == 'sqlite+aiosqlite:///' + str(custom)
    assert custom.parent.is_dir()
    assert not custom.exists()


def test_durable_writer_refuses_records_its_recovery_reader_cannot_read(roots):
    home, cwd = roots
    record = home / 'synthetic-oversized-journal.json'
    with pytest.raises(RuntimeError, match='(?i)large|bound|size'):
        migration._write_json(record, {'synthetic': 'x' * (1024 * 1024)}, migration.FileOps(), initial=True)
    assert not record.exists()


@pytest.mark.parametrize('strategy', ['unit', 'files'])
def test_resume_preserves_new_missing_database_parent_before_any_resource_mutation(roots, strategy):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip', b'backup')
    if strategy == 'files':
        (home / NEW).mkdir()
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_journal_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    before = files(home), files(cwd)
    configured = 'sqlite+aiosqlite:///' + str(home / OLD / 'not-created-yet.db')
    with pytest.raises(RuntimeError, match='(?i)containment|custom|parent'):
        start(roots, database=configured)
    assert (files(home), files(cwd)) == before
    assert source.read_bytes() == b'backup'
    assert (home / OLD).is_dir()


@pytest.mark.parametrize('strategy', ['unit', 'files'])
def test_resume_preserves_empty_new_unrecorded_custom_attachment_directory(roots, strategy):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip', b'backup')
    if strategy == 'files':
        (home / NEW).mkdir()
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_journal_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    custom = home / OLD / 'new-empty-custom-root'
    custom.mkdir()
    identity = custom.stat().st_ino
    before = files(home), files(cwd)
    if strategy == 'unit':
        with pytest.raises(RuntimeError, match='(?i)containment|custom|parent'):
            start(roots, attachments=str(custom))
        assert (files(home), files(cwd)) == before
        assert source.read_bytes() == b'backup'
    else:
        assert start(roots, attachments=str(custom))[1] == str(custom)
        assert (home / NEW / 'backups/a.zip').read_bytes() == b'backup'
    assert custom.is_dir() and custom.stat().st_ino == identity
    assert not list(custom.iterdir())


class SizeProbeOps(migration.FileOps):
    """Real namespace/copy/validation; omit fsync only in large volume probes.

    The separate DurableFilesystem and descriptor fsync tests cover barriers.
    """
    def sync_file(self, path):
        pass

    def sync_dir(self, path):
        pass


def generated_plan(roots):
    home, cwd = roots
    resources = {key: {'source_root': str(home / OLD / folder),
                       'target_root': str(home / NEW / folder)}
                 for key, folder in [('backups', 'backups'), ('attachments', 'bridge-attachments')]}
    sources, directories = migration._inspect_home(home / OLD, [])
    return migration._allocate_home_plan(home, resources, [], sources, directories, False)


def json_size(value):
    return len(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def make_boundary_tree(roots):
    home, cwd = roots
    for index in range(1900):
        put(home / OLD / 'backups' / f'{index:04d}', b'x')
    plan = generated_plan(roots)
    # Find a real generated prefix without thousands of repeated inspections.
    lo, hi = 1, len(plan['files'])
    while lo < hi:
        middle = (lo + hi + 1) // 2
        if json_size(plan | {'files': plan['files'][:middle]}) <= 1024 * 1024 - 600:
            lo = middle
        else:
            hi = middle - 1
    for row in plan['files'][lo:]:
        Path(row['source']).unlink()
    plan = generated_plan(roots)
    for path in sorted((home / OLD / 'backups').iterdir())[:8]:
        extra = min(230, max(0, (1024 * 1024 - 2 - json_size(plan)) // 2))
        path.rename(path.with_name(path.name + 'x' * extra))
        plan = generated_plan(roots)
    assert 1024 * 1024 - 8 < json_size(plan) <= 1024 * 1024
    assert json_size(plan | {'stage': 'targets_durable'}) > 1024 * 1024
    return {row['source'] for row in plan['files']}


@pytest.mark.parametrize('strategy', ['unit', 'files', 'exdev'])
def test_generated_boundary_plan_reserves_every_transition_and_restarts(roots, strategy):
    home, cwd = roots
    expected = make_boundary_tree(roots)
    if strategy == 'files':
        (home / NEW).mkdir()
    class CopyBoundary(SizeProbeOps):
        def rename_directory(self, source, target):
            if strategy == 'exdev':
                raise OSError(errno.EXDEV, 'force directory fallback')
            return super().rename_directory(source, target)

        def link(self, source, target):
            if strategy == 'exdev' and source.is_relative_to(home / OLD):
                raise OSError(errno.EXDEV, 'force verified file copy')
            return super().link(source, target)

        def checkpoint(self, stage, path):
            if stage == 'home_targets_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, database='sqlite+aiosqlite:///:memory:', ops=CopyBoundary())
    start(roots, database='sqlite+aiosqlite:///:memory:', ops=SizeProbeOps())
    assert set(mappings(home, 'backups')) == expected
    assert all(Path(target).read_bytes() == b'x' for target in mappings(home, 'backups').values())
    assert not (home / OLD).exists()


@pytest.mark.parametrize('strategy', ['unit', 'files', 'exdev'])
def test_larger_than_reader_bound_collection_migrates_without_volume_ceiling(roots, strategy):
    home, cwd = roots
    for index in range(1900):
        put(home / OLD / 'backups' / f'{index:04d}', b'x')
    assert json_size(generated_plan(roots)) > 1024 * 1024
    if strategy == 'files':
        (home / NEW).mkdir()
    class CopyVolume(SizeProbeOps):
        def rename_directory(self, source, target):
            if strategy == 'exdev':
                raise OSError(errno.EXDEV, 'force directory fallback')
            return super().rename_directory(source, target)

        def link(self, source, target):
            if strategy == 'exdev' and source.is_relative_to(home / OLD):
                raise OSError(errno.EXDEV, 'force verified file copy')
            return super().link(source, target)
    start(roots, database='sqlite+aiosqlite:///:memory:', ops=CopyVolume())
    assert len(mappings(home, 'backups')) == 1900
    assert all(Path(target).read_bytes() == b'x' for target in mappings(home, 'backups').values())
    assert not (home / OLD).exists()
    before = files(home)
    start(roots, database='sqlite+aiosqlite:///:memory:')
    assert files(home) == before


def test_public_reference_reader_refuses_any_unclosed_file_phase(roots):
    home, cwd = roots
    put(home / OLD / 'backups/a.zip')
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_reference_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    with pytest.raises(RuntimeError, match='(?i)incomplete|file.phase|in progress'):
        references(home)


@pytest.mark.parametrize('conflict', ['source', 'target', 'diagnostics'])
def test_public_reference_reader_rejects_cross_record_ownership_conflicts(roots, conflict):
    import uuid
    home, cwd = roots
    put(home / OLD / 'backups/a.zip')
    start(roots)
    record = references(home)[0]
    second = json.loads(json.dumps(record))
    second['id'] = str(uuid.uuid4())
    row = second['resources']['backups']['mappings'][0]
    if conflict == 'source':
        row['target'] += '-another'
    elif conflict == 'target':
        row['source'] += '-another'
    else:
        second['resources']['backups']['mappings'] = []
        second['diagnostics']['excluded'] = [record['resources']['backups']['mappings'][0]['source']]
    path = migration._home_record(home, second['id'], references=True)
    path.write_text(json.dumps(second))
    before = files(home)
    with pytest.raises(RuntimeError, match='(?i)reference|ownership|partition'):
        references(home)
    assert files(home) == before


def partition_fixture(roots, monkeypatch):
    # Exercise the production paging algorithm at a smaller packing target;
    # the recovery reader's 1 MiB safety bound is never changed.
    monkeypatch.setattr(migration, 'HOME_PART_BYTES', 1024, raising=False)
    home, cwd = roots
    expected = {}
    for index in range(16):
        source = put(home / OLD / 'backups' / f'{index:04d}.zip', bytes([index]))
        put(home / NEW / 'backups' / source.name, b'existing')
        expected[str(source)] = bytes([index])
    return expected


@pytest.mark.parametrize('cut', ['home_reference_published:0', 'home_reference_published:1',
                               'home_references_complete', 'home_file_journal_unlinked'])
def test_partition_publication_power_cut_never_exposes_partial_set_and_resumes_same_ids(tmp_path, monkeypatch, cut):
    root = tmp_path / 'disk'
    home, cwd = root / 'home', root / 'backend'
    home.mkdir(parents=True)
    cwd.mkdir()
    roots = (home, cwd)
    expected = partition_fixture(roots, monkeypatch)
    durable = DurableFilesystem(root, migration.FileOps(), cut=cut)
    with pytest.raises(Interrupted):
        start(roots, ops=durable)
    surviving = {p.name: p.read_bytes() for p in home.glob('*.references.json')}
    if cut != 'home_file_journal_unlinked':
        with pytest.raises(RuntimeError, match='(?i)incomplete|file.phase|in progress'):
            references(home)
    durable.power_cut()
    start(roots)
    records = references(home)
    assert len(records) > 2 and len({r['move_journal_id'] for r in records}) == 1
    assert {p.name: p.read_bytes() for p in home.glob('*.references.json') if p.name in surviving} == surviving
    assert {source: Path(target).read_bytes() for source, target in mappings(home, 'backups').items()} == expected
    before = files(home)
    for target in mappings(home, 'backups').values():
        Path(target).write_bytes(b'post-open change')
    retained = {p.name: p.read_bytes() for p in home.glob('*.references.json')}
    start(roots)
    assert {p.name: p.read_bytes() for p in home.glob('*.references.json')} == retained
    assert len(before) >= len(retained)


@pytest.mark.parametrize('corruption', ['missing', 'duplicate', 'foreign', 'digest'])
def test_partition_descriptor_corruption_refuses_before_movement(roots, monkeypatch, corruption):
    home, cwd = roots
    expected = partition_fixture(roots, monkeypatch)
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_journal_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    pages = sorted(home.glob('*.part'))
    assert len(pages) > 1, 'real fixture must use bounded manifest pages'
    if corruption == 'missing':
        pages[0].unlink()
    elif corruption == 'duplicate':
        pages[-1].write_bytes(pages[0].read_bytes())
    elif corruption == 'foreign':
        value = json.loads(pages[0].read_text())
        value['id'] = '00000000-0000-4000-8000-000000000000'
        pages[0].write_text(json.dumps(value))
    else:
        value = json.loads(pages[0].read_text())
        value['content'] = ' ' + value['content']
        pages[0].write_text(json.dumps(value))
    before = files(home)
    with pytest.raises(RuntimeError, match='(?i)journal|manifest|partition'):
        start(roots)
    assert files(home) == before
    assert all(Path(source).read_bytes() == data for source, data in expected.items())


@pytest.mark.parametrize('boundary', ['linked-first', 'linked-last', 'sync-first', 'sync-last'])
def test_reference_publication_sync_failure_keeps_manifest_and_resume_ids(roots, monkeypatch, boundary):
    home, cwd = roots
    expected = partition_fixture(roots, monkeypatch)
    class Failure(migration.FileOps):
        publications = 0
        expected_count = None
        pending_failure = False
        def checkpoint(self, stage, path):
            if stage == 'home_journal_durable':
                loader = getattr(migration, '_load_home_plan', None)
                self.expected_count = len(loader(path, home).reference_records) if loader else 1
            if stage == 'home_reference_linked':
                self.publications += 1
                selected = self.publications == (1 if boundary.endswith('first') else self.expected_count)
                if selected and boundary.startswith('linked'):
                    raise Interrupted()
                self.pending_failure = selected

        def sync_dir(self, path):
            if self.pending_failure and boundary.startswith('sync'):
                self.pending_failure = False
                raise OSError(errno.EIO, 'reference directory durability failure')
            return super().sync_dir(path)
    with pytest.raises((Interrupted, RuntimeError)):
        start(roots, ops=Failure())
    assert list(home.glob('*.json'))
    with pytest.raises(RuntimeError, match='(?i)incomplete|file.phase|in progress'):
        references(home)
    original = {p.name: p.read_bytes() for p in home.glob('*.references.json')}
    start(roots)
    assert all((home / name).read_bytes() == data for name, data in original.items())
    assert {source: Path(target).read_bytes() for source, target in mappings(home, 'backups').items()} == expected


@pytest.mark.parametrize('caller', ['startup', 'reader'])
def test_absent_file_journal_is_directory_durable_before_open_or_ready_handoff(roots, monkeypatch, caller):
    home, cwd = roots
    put(home / OLD / 'backups/a.zip')
    start(roots)
    synced = []
    original = migration.FileOps.sync_dir
    def observe(self, path):
        synced.append(path)
        return original(self, path)
    monkeypatch.setattr(migration.FileOps, 'sync_dir', observe)
    if caller == 'startup':
        start(roots, database='sqlite+aiosqlite:///:memory:')
    else:
        references(home)
    assert home in synced, 'a prior process may have unlinked the root before its directory barrier'


@pytest.mark.parametrize('cut', ['copy_written:0', 'copy_synced:0', 'copy_verified:0', 'home_landed:0'])
def test_partitioned_copy_progress_power_cut_resumes_without_changing_reference_ids(tmp_path, monkeypatch, cut):
    root = tmp_path / 'disk'
    home, cwd = root / 'home', root / 'backend'
    home.mkdir(parents=True)
    cwd.mkdir()
    expected = partition_fixture((home, cwd), monkeypatch)
    class CrossDevice(migration.FileOps):
        def link(self, source, target):
            if source.is_relative_to(home / OLD):
                raise OSError(errno.EXDEV, 'force copied identities')
            return super().link(source, target)
    durable = DurableFilesystem(root, CrossDevice(), cut=cut)
    with pytest.raises(Interrupted):
        start((home, cwd), ops=durable)
    journal = migration._home_journals(home)[0]
    ids = {r['id'] for r in migration._load_home_plan(journal, home).reference_records}
    durable.power_cut()
    start((home, cwd), ops=CrossDevice())
    assert {r['id'] for r in references(home)} == ids
    assert {source: Path(target).read_bytes() for source, target in mappings(home, 'backups').items()} == expected


@pytest.mark.parametrize('position', ['first', 'last'])
def test_partition_reference_link_before_directory_sync_power_cut_restores_manifest_closure(tmp_path, monkeypatch, position):
    root = tmp_path / 'disk'
    home, cwd = root / 'home', root / 'backend'
    home.mkdir(parents=True)
    cwd.mkdir()
    expected = partition_fixture((home, cwd), monkeypatch)
    class Cut(DurableFilesystem):
        publications = 0
        def checkpoint(self, stage, path):
            super().checkpoint(stage, path)
            if stage == 'home_journal_durable':
                value = migration._load_home_plan(path, home)
                self.expected_ids = {r['id'] for r in value.reference_records}
            if stage == 'home_reference_linked':
                self.publications += 1
                if self.publications == (1 if position == 'first' else len(self.expected_ids)):
                    self.interrupted = True
                    raise Interrupted()
    durable = Cut(root, migration.FileOps())
    with pytest.raises(Interrupted):
        start((home, cwd), ops=durable)
    durable.power_cut()
    with pytest.raises(RuntimeError, match='(?i)incomplete|file.phase|in progress'):
        references(home)
    start((home, cwd))
    assert {r['id'] for r in references(home)} == durable.expected_ids
    assert {source: Path(target).read_bytes() for source, target in mappings(home, 'backups').items()} == expected


@pytest.mark.parametrize('corruption', ['missing', 'foreign', 'extra-mapping'])
def test_internal_pending_reference_recovery_completes_missing_and_refuses_contradictions(roots, monkeypatch, corruption):
    import uuid
    home, cwd = roots
    expected = partition_fixture(roots, monkeypatch)
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_reference_published:0':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    journal = migration._home_journals(home)[0]
    ids = {r['id'] for r in migration._load_home_plan(journal, home).reference_records}
    published = next(home.glob('*.references.json'))
    if corruption == 'missing':
        published.unlink()
        start(roots)
        assert {r['id'] for r in references(home)} == ids
        assert {source: Path(target).read_bytes() for source, target in mappings(home, 'backups').items()} == expected
    else:
        value = json.loads(published.read_text())
        if corruption == 'foreign':
            value['id'] = str(uuid.uuid4())
            published = migration._home_record(home, value['id'], references=True)
            value['resources']['backups']['mappings'] = []
        else:
            row = value['resources']['backups']['mappings'][0].copy()
            value['resources']['backups']['mappings'].append({key: item + '-extra' for key, item in row.items()})
        published.write_text(json.dumps(value))
        before = files(home)
        with pytest.raises(RuntimeError, match='(?i)reference|partition|manifest'):
            start(roots)
        assert files(home) == before


def test_legacy_sub_bound_journal_stranded_after_unit_rename_recovers_with_bounded_pages(roots):
    home, cwd = roots
    expected = make_boundary_tree(roots)
    value = generated_plan(roots)
    value['stage'] = 'landing'
    journal = migration._home_record(home, value['id'])
    migration._write_json(journal, value, migration.FileOps(), initial=True)
    migration.FileOps().rename_directory(home / OLD, home / NEW)
    migration.FileOps().sync_dir(home)
    assert journal.stat().st_size <= 1024 * 1024
    assert json_size(value | {'stage': 'targets_durable'}) > 1024 * 1024
    start(roots, database='sqlite+aiosqlite:///:memory:', ops=SizeProbeOps())
    assert set(mappings(home, 'backups')) == expected
    assert not journal.exists()


def test_legacy_conversion_preserves_already_published_complete_v1_record_bytes(roots):
    home, cwd = roots
    for index in range(200):
        put(home / OLD / 'backups' / f'{index:04d}', b'x')
    value = generated_plan(roots)
    assert json_size(value) > 64 * 1024
    journal = migration._home_record(home, value['id'])
    ops = migration.FileOps()
    migration._write_json(journal, value, ops, initial=True)
    ops.rename_directory(home / OLD, home / NEW)
    ops.sync_dir(home)
    reference = migration._reference_from_plan(value)
    path = migration._home_record(home, reference['id'], references=True)
    migration._write_json(path, reference, ops, initial=True)
    original = path.read_bytes()
    start(roots, database='sqlite+aiosqlite:///:memory:')
    assert path.read_bytes() == original
    assert references(home) == [reference]
    assert not journal.exists()


@pytest.mark.parametrize('strategy', ['unit', 'files'])
def test_directory_only_plan_also_scales_past_the_reader_bound(roots, strategy):
    home, cwd = roots
    old = home / OLD
    old.mkdir()
    for index in range(4200):
        (old / (f'{index:04d}' + 'x' * 160)).mkdir()
    assert json_size(generated_plan(roots)) > 1024 * 1024
    if strategy == 'files':
        (home / NEW).mkdir()
    start(roots, database='sqlite+aiosqlite:///:memory:', ops=SizeProbeOps())
    assert not old.exists()
    assert len([p for p in (home / NEW).iterdir() if p.name.endswith('x' * 160)]) == 4200
    assert references(home)


def test_partition_manifest_requires_exact_planned_mapping_coverage_before_movement(roots, monkeypatch):
    home, cwd = roots
    partition_fixture(roots, monkeypatch)
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_journal_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    journal = migration._home_journals(home)[0]
    manifest = json.loads(journal.read_text())
    paths = [migration._plan_part(home, manifest['id'], manifest['plan_id'], index)
             for index in range(manifest['page_count'])]
    pages = [json.loads(path.read_text()) for path in paths]
    payload = json.loads(''.join(page['content'] for page in pages))
    payload['references'][0]['resources']['backups']['mappings'].pop()
    encoded = migration._encoded(payload)
    for index, (path, page) in enumerate(zip(paths, pages)):
        page['content'] = encoded[index * migration.HOME_PART_BYTES:(index + 1) * migration.HOME_PART_BYTES].decode('ascii')
        path.write_text(json.dumps(page))
    manifest['sha256'] = hashlib.sha256(encoded).hexdigest()
    journal.write_text(json.dumps(manifest))
    before = files(home)
    with pytest.raises(RuntimeError, match='(?i)exactly cover|partition|manifest'):
        start(roots)
    assert files(home) == before


def test_power_cut_model_cannot_commit_a_finally_block_after_interruption(roots, tmp_path):
    home, cwd = roots
    durable = DurableFilesystem(home, migration.FileOps(), cut='hard-cut')
    with pytest.raises(Interrupted):
        durable.checkpoint('hard-cut', home)
    with pytest.raises(Interrupted):
        durable.sync_dir(home)


@pytest.mark.parametrize('resource', ['database', 'attachments'])
def test_files_resume_preserves_existing_ancestor_of_new_missing_custom_parent(roots, resource):
    home, cwd = roots
    source = put(home / OLD / 'backups/a.zip')
    (home / NEW).mkdir()
    class Pause(migration.FileOps):
        def checkpoint(self, stage, path):
            if stage == 'home_journal_durable':
                raise Interrupted()
    with pytest.raises(Interrupted):
        start(roots, ops=Pause())
    custom = home / OLD / 'absent-parent/also-absent'
    kwargs = {'database': 'sqlite+aiosqlite:///' + str(custom / 'db.sqlite')} if resource == 'database' else {'attachments': str(custom)}
    before = files(home)
    with pytest.raises(RuntimeError, match='(?i)containment|parent|custom'):
        start(roots, **kwargs)
    assert files(home) == before
    assert source.exists() and (home / OLD).is_dir()
