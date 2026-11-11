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
    assert not references(home)


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
