"""One-time, pre-engine conversion of the shipped SQLite database file set.

Old-name literals in this module identify conversion inputs only. No database
connection, SQL migration, home-content move or stored-reference rewrite lives
here. The old application must already be stopped before this protocol runs.

The link/unlink discipline never replaces an existing target. File fsync and
directory fsync are separate barriers (Linux link(2) and fsync(2)); journal
retirement is the last barrier before the caller may construct its engine.
"""
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid
from urllib.parse import quote, unquote, urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.util import asbool


OLD_NAME = 'claude_registry.db'
NEW_NAME = 'synth_city.db'
SUFFIXES = ('-wal', '-shm', '-journal', '')
LOCK_NAME = '.albiex-synth-city-db-upgrade.lock'
JOURNAL_PREFIX = '.albiex-synth-city-db-upgrade.'
BINDING_NAME = 'upgrade-location-bindings.json'


class FileOps:
    """The POSIX boundary; injectable for fault/concurrency/durability tests."""

    def sync_file(self, path: Path):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def sync_dir(self, path: Path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def link(self, source: Path, target: Path):
        os.link(source, target, follow_symlinks=False)

    def unlink(self, path: Path):
        path.unlink()

    def replace(self, source: Path, target: Path):
        # Only our already-validated JSON records are atomically replaced.
        os.replace(source, target)

    def copy(self, source: Path, temporary: Path, metadata: dict):
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            target_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(target_fd, 'wb') as output:
                with os.fdopen(source_fd, 'rb', closefd=False) as incoming:
                    shutil.copyfileobj(incoming, output, 1024 * 1024)
                output.flush()
                os.fchown(output.fileno(), metadata['uid'], metadata['gid'])
                os.fchmod(output.fileno(), metadata['mode'])
            os.utime(temporary, ns=(metadata['atime_ns'], metadata['mtime_ns']), follow_symlinks=False)
        finally:
            os.close(source_fd)

    def checkpoint(self, stage: str, path: Path):
        """No runtime failpoint or environment switch; tests override this seam."""


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _snapshot(path: Path) -> dict:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f'Database upgrade refuses a non-regular file: {path}')
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise RuntimeError(f'Database upgrade file changed during inspection: {path}')
        with os.fdopen(descriptor, 'rb', closefd=False) as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return {'sha256': digest.hexdigest(), 'size': metadata.st_size,
            'dev': metadata.st_dev, 'ino': metadata.st_ino,
            'mode': stat.S_IMODE(metadata.st_mode), 'uid': metadata.st_uid,
            'gid': metadata.st_gid, 'atime_ns': metadata.st_atime_ns,
            'mtime_ns': metadata.st_mtime_ns}


def _same(path: Path, expected: dict, identity=True) -> bool:
    actual = _snapshot(path)
    keys = ('sha256', 'size', 'mode', 'uid', 'gid') + (('dev', 'ino') if identity else ())
    return all(actual[key] == expected[key] for key in keys)


def _read_json(path: Path) -> dict:
    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > 1024 * 1024:
        raise RuntimeError(f'Database upgrade record is not a bounded regular file: {path}')
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError):
        raise RuntimeError(f'Database upgrade record is invalid: {path}') from None
    if not isinstance(value, dict):
        raise RuntimeError(f'Database upgrade record is invalid: {path}')
    return value


def _mkdir_synced(directory: Path, ops: FileOps):
    missing = []
    current = directory
    while not _exists(current):
        missing.append(current)
        current = current.parent
    if not current.is_dir() or current.is_symlink():
        raise RuntimeError(f'Database upgrade metadata directory is invalid: {current}')
    for path in reversed(missing):
        path.mkdir(mode=0o700)
        ops.sync_dir(path)
        ops.sync_dir(path.parent)


def _write_json(path: Path, value: dict, ops: FileOps, *, initial=False):
    _mkdir_synced(path.parent, ops)
    temporary = path.with_name(path.name + '.write-' + str(uuid.uuid4()) + '.tmp')
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output, sort_keys=True, separators=(',', ':'))
            output.flush()
        ops.sync_file(temporary)
        if initial:
            ops.link(temporary, path)
        else:
            if _exists(path):
                _read_json(path)
            ops.replace(temporary, path)
        ops.sync_dir(path.parent)
    finally:
        if created and _exists(temporary):
            ops.unlink(temporary)
            ops.sync_dir(path.parent)


@contextmanager
def _migration_lock(parent: Path):
    path = parent / LOCK_NAME
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f'Database upgrade lock is invalid: {path}')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f'Database upgrade in progress: {parent / OLD_NAME} -> {parent / NEW_NAME}') from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _bindings(path: Path) -> dict:
    value = _read_json(path) if _exists(path) else {'version': 1, 'resources': {}}
    if type(value.get('version')) is not int or value['version'] != 1 or not isinstance(value.get('resources'), dict):
        raise RuntimeError(f'Database upgrade binding record is invalid: {path}')
    entry = value['resources'].get('database')
    if entry is not None:
        if not isinstance(entry, dict) or set(entry) != {'old_path', 'new_path', 'journal_id', 'state'}:
            raise RuntimeError(f'Database upgrade binding record is invalid: {path}')
        try:
            old, new = Path(entry['old_path']), Path(entry['new_path'])
            valid_id = str(uuid.UUID(entry['journal_id'])) == entry['journal_id']
            valid_paths = old.is_absolute() and new.is_absolute() and old.name == OLD_NAME and new.name == NEW_NAME and old.parent == new.parent
        except (TypeError, ValueError, AttributeError):
            valid_id = valid_paths = False
        if not valid_id or not valid_paths or entry['state'] not in ('active', 'retiring'):
            raise RuntimeError(f'Database upgrade binding record is invalid: {path}')
    return value


def _retire_binding(path: Path, value: dict, ops: FileOps):
    if 'database' not in value['resources']:
        return
    value['resources']['database']['state'] = 'retiring'
    _write_json(path, value, ops)
    del value['resources']['database']
    _write_json(path, value, ops)


def _bind(path: Path, value: dict, old: Path, new: Path, journal_id: str, ops: FileOps):
    value['resources']['database'] = {'old_path': str(old), 'new_path': str(new),
                                     'journal_id': journal_id, 'state': 'active'}
    _write_json(path, value, ops)
    ops.checkpoint('binding_durable', path)


def _journal_path(parent: Path, identity: str) -> Path:
    return parent / (JOURNAL_PREFIX + identity + '.json')


def _target_metadata(row: dict) -> dict:
    return row | row['target_identity']


def _valid_snapshot(value: dict) -> bool:
    """Reject malformed journal metadata before inspecting or changing any file."""
    if not isinstance(value, dict):
        return False
    numbers = ('size', 'dev', 'ino', 'mode', 'uid', 'gid', 'atime_ns', 'mtime_ns')
    if any(type(value.get(key)) is not int or value[key] < 0 for key in numbers):
        return False
    digest = value.get('sha256')
    return (value['mode'] <= 0o7777 and isinstance(digest, str) and len(digest) == 64
            and all(character in '0123456789abcdef' for character in digest))


def _validate_journal(path: Path, value: dict, old: Path, new: Path):
    """Validate the entire immutable set before authorizing even one unlink."""
    def require(condition):
        if not condition:
            raise ValueError('invalid journal')

    try:
        require(set(value) == {'version', 'id', 'source', 'target', 'stage', 'files',
                              'empty_targets', 'empty_states', 'existing_targets'})
        identity = value['id']
        require(str(uuid.UUID(identity)) == identity)
        require(path == _journal_path(old.parent, identity))
        require(type(value['version']) is int and value['version'] == 1)
        require(value['source'] == str(old) and value['target'] == str(new))
        require(value['stage'] in ('planned', 'landing', 'targets_durable', 'removing_sources', 'landed'))
        files = value['files']
        require(isinstance(files, list) and len(files) <= len(SUFFIXES))
        require(isinstance(value['empty_targets'], list))
        require(isinstance(value['empty_states'], dict))
        require(len(value['empty_targets']) == len(set(value['empty_targets'])))
        require(set(value['empty_targets']) == set(value['empty_states']))
        require(isinstance(value['existing_targets'], dict))
        seen = []
        snapshot_keys = {'sha256', 'size', 'dev', 'ino', 'mode', 'uid', 'gid', 'atime_ns', 'mtime_ns'}
        for row in files:
            require(isinstance(row, dict))
            require(set(row) == snapshot_keys | {'suffix', 'source', 'target', 'temporary', 'copy_state', 'target_identity'})
            suffix = row['suffix']
            require(suffix in SUFFIXES and suffix not in seen)
            seen.append(suffix)
            require(row['source'] == str(old) + suffix and row['target'] == str(new) + suffix)
            require(row['temporary'] == str(new.parent / ('.' + NEW_NAME + suffix + '.upgrade-' + identity + '.tmp')))
            require(row['copy_state'] in ('none', 'writing', 'verified'))
            require(isinstance(row['target_identity'], dict) and set(row['target_identity']) == {'dev', 'ino'})
            require(_valid_snapshot(row))
            require(all(type(v) is int and v >= 0 for v in row['target_identity'].values()))
            if row['copy_state'] in ('none', 'writing'):
                require(row['target_identity'] == {'dev': row['dev'], 'ino': row['ino']})
        require(seen == [suffix for suffix in SUFFIXES if suffix in seen])
        allowed_targets = {str(new) + suffix for suffix in SUFFIXES}
        require(set(value['empty_targets']) <= allowed_targets)
        require(set(value['existing_targets']) <= allowed_targets)
        for metadata in value['empty_states'].values():
            require(_valid_snapshot(metadata) and set(metadata) == snapshot_keys and metadata['size'] == 0)
        for metadata in value['existing_targets'].values():
            require(_valid_snapshot(metadata) and set(metadata) == snapshot_keys)
        if files:
            require('' in seen and not value['existing_targets'])
        else:
            # Adoption records bind an upgraded set; they cannot authorize a
            # move or combine with disposable empty targets.
            require(not value['empty_states'] and str(new) in value['existing_targets'])
            require(value['existing_targets'][str(new)]['size'] > 0
                    or all(row['size'] == 0 for row in value['existing_targets'].values()))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError(f'Database upgrade journal is invalid or mismatched: {path}') from None

    # Adoption has no source rows to require a surviving target implicitly.
    # Its complete recorded set must still exist before any record is changed.
    for name, expected in value['existing_targets'].items():
        target = Path(name)
        if not _exists(target) or not _same(target, expected):
            raise RuntimeError(f'Database upgrade adopted target does not match its journal: {target}')

    rows = {row['suffix']: row for row in files}
    for suffix in SUFFIXES:
        source, target = Path(str(old) + suffix), Path(str(new) + suffix)
        row = rows.get(suffix)
        if _exists(source) and (row is None or not _same(source, row)):
            raise RuntimeError(f'Database upgrade source does not match its journal: {source}')
        if row is not None and not _exists(source) and not _exists(target):
            raise RuntimeError(f'Database upgrade journal cannot find its file: {source} -> {target}')
        if _exists(target):
            matched = row is not None and _same(target, _target_metadata(row))
            empty = value['empty_states'].get(str(target))
            existing = value['existing_targets'].get(str(target))
            if not matched and not (empty and _same(target, empty)) and not (existing and _same(target, existing)):
                raise RuntimeError(f'Database upgrade target does not match its journal: {target}')
        if row is not None:
            temporary = Path(row['temporary'])
            if _exists(temporary):
                if not stat.S_ISREG(temporary.lstat().st_mode):
                    raise RuntimeError(f'Database upgrade copy temporary is invalid: {temporary}')
                if row['copy_state'] == 'verified' and not _same(temporary, _target_metadata(row)):
                    raise RuntimeError(f'Database upgrade verified copy changed: {temporary}')
                if row['copy_state'] not in ('writing', 'verified') or not _exists(source):
                    raise RuntimeError(f'Database upgrade temporary is unexplained: {temporary}')


def _create_plan(old: Path, new: Path, *, adopt=False) -> dict:
    identity = str(uuid.uuid4())
    files = []
    for suffix in SUFFIXES:
        source = Path(str(old) + suffix)
        if _exists(source):
            snapshot = _snapshot(source)
            files.append(snapshot | {'suffix': suffix, 'source': str(source),
                'target': str(new) + suffix,
                'temporary': str(new.parent / ('.' + NEW_NAME + suffix + '.upgrade-' + identity + '.tmp')),
                'copy_state': 'none',
                'target_identity': {'dev': snapshot['dev'], 'ino': snapshot['ino']}})
    empty, existing = {}, {}
    for suffix in SUFFIXES:
        target = Path(str(new) + suffix)
        if _exists(target):
            snapshot = _snapshot(target)
            (existing if adopt else empty)[str(target)] = snapshot
    return {'version': 1, 'id': identity, 'source': str(old), 'target': str(new),
            'stage': 'planned', 'files': files, 'empty_targets': list(empty),
            'empty_states': empty, 'existing_targets': existing}


def _verify_landed(row: dict):
    target = Path(row['target'])
    if not _exists(target) or not _same(target, _target_metadata(row)):
        raise RuntimeError(f'Database upgrade landing verification failed: {target}')


def _land_file(row: dict, journal: Path, value: dict, ops: FileOps):
    source, target, temporary = (Path(row[key]) for key in ('source', 'target', 'temporary'))
    if not _exists(target):
        if row['copy_state'] == 'verified' and _exists(temporary):
            ops.link(temporary, target)
        else:
            try:
                ops.link(source, target)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    # EEXIST never counts as a successful no-replace operation.
                    raise
                row['copy_state'] = 'writing'
                _write_json(journal, value, ops)
                if _exists(temporary):
                    ops.unlink(temporary)
                    ops.sync_dir(temporary.parent)
                try:
                    ops.copy(source, temporary, row)
                    ops.checkpoint('copy_written:' + row['suffix'], temporary)
                    ops.sync_file(temporary)
                    ops.checkpoint('copy_synced:' + row['suffix'], temporary)
                    if not _same(temporary, row, identity=False):
                        raise RuntimeError(f'Database upgrade copy digest/metadata verification failed: {temporary}')
                    prepared = _snapshot(temporary)
                    row['target_identity'] = {'dev': prepared['dev'], 'ino': prepared['ino']}
                    row['copy_state'] = 'verified'
                    _write_json(journal, value, ops)
                    ops.checkpoint('copy_verified:' + row['suffix'], temporary)
                    ops.link(temporary, target)
                except Exception:
                    # Only a writing-stage copy belongs to this failed operation.
                    # A verified copy is recovery information and is retained.
                    if row['copy_state'] == 'writing' and _exists(temporary):
                        ops.unlink(temporary)
                        ops.sync_dir(temporary.parent)
                    raise
    _verify_landed(row)
    ops.sync_file(target)
    ops.sync_dir(target.parent)
    if _exists(temporary):
        ops.unlink(temporary)
        ops.sync_dir(temporary.parent)
    ops.checkpoint('landed:' + row['suffix'], target)


def _resume(journal: Path, value: dict, old: Path, new: Path,
            binding: Path, bindings: dict, explicit: bool, ops: FileOps):
    _validate_journal(journal, value, old, new)
    for name, expected in value['empty_states'].items():
        target = Path(name)
        if _exists(target) and _same(target, expected):
            ops.unlink(target)
            ops.sync_dir(target.parent)
    value['stage'] = 'landing'
    _write_json(journal, value, ops)
    for row in value['files']:
        _land_file(row, journal, value, ops)
        _write_json(journal, value, ops)
    _validate_journal(journal, value, old, new)
    for row in value['files']:
        _verify_landed(row)
    ops.sync_dir(new.parent)
    value['stage'] = 'targets_durable'
    _write_json(journal, value, ops)
    ops.checkpoint('target_set_durable', new)
    value['stage'] = 'removing_sources'
    _write_json(journal, value, ops)
    for row in value['files']:
        source = Path(row['source'])
        if _exists(source):
            if not _same(source, row):
                raise RuntimeError(f'Database upgrade source changed before removal: {source}')
            ops.unlink(source)
            ops.sync_dir(source.parent)
        ops.checkpoint('source_removed:' + row['suffix'], source)
    _validate_journal(journal, value, old, new)
    if explicit:
        _bind(binding, bindings, old, new, value['id'], ops)
    value['stage'] = 'landed'
    _write_json(journal, value, ops)
    # All source removals, target data and any binding are already durable.
    ops.unlink(journal)
    ops.checkpoint('journal_unlinked', journal)
    ops.sync_dir(journal.parent)
    ops.checkpoint('journal_retired', journal)


def _journals(parent: Path) -> list[Path]:
    paths = sorted(parent.glob(JOURNAL_PREFIX + '*.json'))
    if len(paths) > 1:
        raise RuntimeError(f'Database upgrade has multiple journals: {parent / OLD_NAME} -> {parent / NEW_NAME}')
    return paths


def _move_default(parent: Path, binding: Path, bindings: dict, explicit: bool, ops: FileOps):
    old, new = parent / OLD_NAME, parent / NEW_NAME
    journals = _journals(parent)
    if journals:
        value = _read_json(journals[0])
        _resume(journals[0], value, old, new, binding, bindings, explicit, ops)
        return
    sources = [Path(str(old) + suffix) for suffix in SUFFIXES if _exists(Path(str(old) + suffix))]
    targets = [Path(str(new) + suffix) for suffix in SUFFIXES if _exists(Path(str(new) + suffix))]
    # Refuse special files even when they are empty. Nothing follows a sidecar symlink.
    for path in sources + targets:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError(f'Database upgrade refuses a non-regular file: {path}')
    if sources:
        if old not in sources or (old.stat().st_size == 0 and any(p.stat().st_size for p in sources if p != old)):
            raise RuntimeError(f'Database upgrade source set has no usable main file: {old} -> {new}')
        if any(path.stat().st_size for path in targets):
            raise RuntimeError(f'Database upgrade conflict: {old} -> {new}; preserve both complete file sets')
    elif targets:
        if new not in targets or (new.stat().st_size == 0 and any(p.stat().st_size for p in targets if p != new)):
            raise RuntimeError(f'Database upgrade target set has no usable main file: {old} -> {new}')
        if not explicit:
            return
    else:
        # A fresh installation has no converted resource to bind. Its first
        # connection creates only the new filename. A later explicit-default
        # start can durably bind that existing resource without moving bytes.
        return
    value = _create_plan(old, new, adopt=not sources)
    journal = _journal_path(parent, value['id'])
    _validate_journal(journal, value, old, new)
    _write_json(journal, value, ops, initial=True)
    ops.checkpoint('journal_durable', journal)
    _resume(journal, value, old, new, binding, bindings, explicit, ops)


def _configured_file(url, cwd: Path | None):
    if url.get_backend_name() != 'sqlite' or not url.database:
        return None
    name = url.database
    # Ask the dialect for its filename, without constructing an engine or
    # opening a connection. In URI mode it appends native SQLite options; a
    # filename without file: still treats that suffix literally in SQLite.
    if asbool(url.query.get('uri', False)):
        name = url.get_dialect()().create_connect_args(url)[0][0]
        if name.startswith('file:'):
            # urlsplit removes literal TAB/LF/CR, but SQLite keeps those bytes
            # in filenames. Protect them for parsing, then decode the path.
            name = name.translate({9: '%09', 10: '%0A', 13: '%0D'})
            parsed = urlsplit(name)
            if parsed.netloc not in ('', 'localhost'):
                return None
            # SQLite stops its native query at # and percent-decodes names
            # and values without HTML-form '+' decoding. SQLAlchemy's query
            # can contain ignored fragment text, so it is not authoritative.
            native = {}
            for option in parsed.query.split('&'):
                key, _, value = option.partition('=')
                native[unquote(key).split('\0', 1)[0]] = unquote(value).split('\0', 1)[0]
            if native.get('mode') == 'memory':
                return None
            name = unquote(parsed.path)
    if name == ':memory:':
        return None
    path = Path(name).expanduser()
    return (path if path.is_absolute() else (cwd or Path.cwd()) / path).resolve()


def _new_url(url, path: Path) -> str:
    is_uri = asbool(url.query.get('uri', False))
    name = 'file:' + quote(str(path), safe='/') if is_uri else str(path)
    if is_uri and (url.database or '').startswith('file:') and '#' in url.database:
        # Retain the database fragment before the dialect appends its native
        # query. Dropping it would activate formerly ignored native options.
        # Preserve the SQLAlchemy query separately, including Python options.
        name += '#' + url.database.split('#', 1)[1]
    if not is_uri and '?' in name:
        # SQLAlchemy string URLs split an unescaped ? even without URI mode.
        # Keep the same disk filename/options using a safe relative spelling.
        # Never enable URI mode implicitly: it could activate ignored options.
        name = os.path.relpath(path, Path.cwd())
        if '?' in name:
            raise RuntimeError(f'Database upgrade cannot represent the target in a literal SQLite URL: {path}')
    return url.set(database=name).render_as_string(hide_password=False)


def prepare_database_url(configured_url: str, *, explicit: bool,
                         test_instance: bool = False, cwd: Path | None = None,
                         home: Path | None = None, ops: FileOps | None = None) -> str:
    """Resolve the DB conversion completely before the caller constructs an engine.

    Explicit old defaults are conversion keys in the binding record, never a
    fallback location. Custom choices retain their URL/driver/options verbatim.
    The new home contains metadata only; C5 owns moving its actual contents.
    """
    if test_instance:
        return configured_url
    try:
        url = make_url(configured_url)
        configured = _configured_file(url, cwd)
    except (ArgumentError, ValueError, TypeError):
        # Do not log/format an operator URL; it may contain credentials.
        raise RuntimeError('Database upgrade cannot resolve the configured database URL') from None
    # A non-file URL is no location choice to bind or retire. This must precede
    # even HOME resolution or a metadata existence check (also for test runners).
    if configured is None:
        return configured_url
    ops = ops or FileOps()
    cwd = (cwd or Path.cwd()).resolve()
    home = (home or Path.home()).resolve()
    binding = home / '.albiex-synth-city' / BINDING_NAME
    eligible = not explicit or configured == cwd / OLD_NAME
    if not eligible and not _exists(binding):
        return configured_url

    def resolve_locked(bindings):
        entry = bindings['resources'].get('database')
        if entry and entry['state'] == 'active' and explicit and configured == Path(entry['old_path']):
            old, new = Path(entry['old_path']), Path(entry['new_path'])
            if not new.is_file() or new.is_symlink():
                raise RuntimeError(f'Database upgrade binding target is missing: {old} -> {new}; preserve binding evidence')
            journals = _journals(old.parent)
            if journals:
                value = _read_json(journals[0])
                if value.get('id') != entry['journal_id']:
                    raise RuntimeError(f'Database upgrade binding and journal disagree: {old} -> {new}')
                _resume(journals[0], value, old, new, binding, bindings, True, ops)
            return _new_url(url, new)
        if entry:
            _retire_binding(binding, bindings, ops)
        if not eligible:
            return configured_url
        _move_default(cwd, binding, bindings, explicit, ops)
        return _new_url(url, cwd / NEW_NAME)

    failure_parent = cwd
    try:
        with _migration_lock(cwd):
            bindings = _bindings(binding)
            entry = bindings['resources'].get('database')
            bound_parent = Path(entry['old_path']).parent if entry and entry['state'] == 'active' and explicit and configured == Path(entry['old_path']) else cwd
            failure_parent = bound_parent
            if bound_parent != cwd:
                # A recorded absolute old default keeps resolving after a CWD
                # change. Both anchors are outside the files being moved.
                with _migration_lock(bound_parent):
                    fresh = _bindings(binding)
                    if fresh != bindings:
                        raise RuntimeError('Database upgrade binding changed while taking its lock; restart')
                    return resolve_locked(fresh)
            return resolve_locked(bindings)
    except OSError as error:
        raise RuntimeError(f'Database upgrade filesystem failure ({error.errno}): {failure_parent / OLD_NAME} -> {failure_parent / NEW_NAME}') from None
    except RuntimeError as error:
        raise RuntimeError(f'{error}; database paths: {failure_parent / OLD_NAME} -> {failure_parent / NEW_NAME}') from None
