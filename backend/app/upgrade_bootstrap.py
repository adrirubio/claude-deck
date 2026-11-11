"""One-time, pre-engine conversion of the shipped SQLite database file set.

Old-name literals in this module identify conversion inputs only. No database
connection, SQL migration or stored-reference rewrite lives here. The old
application must already be stopped before this protocol runs. Home resources
extend the same locked file protocol; their reference mappings are retained for C6.

The link/unlink discipline never replaces an existing target. File fsync and
directory fsync are separate barriers (Linux link(2) and fsync(2)); journal
retirement is the last barrier before the caller may construct its engine.
"""
from contextlib import contextmanager, ExitStack
import ctypes
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
OLD_HOME = '.claude-registry'
NEW_HOME = '.albiex-synth-city'
HOME_JOURNAL_PREFIX = '.albiex-synth-city-upgrade.'


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

    def rmdir(self, path: Path):
        path.rmdir()

    def replace(self, source: Path, target: Path):
        # Only our already-validated JSON records are atomically replaced.
        os.replace(source, target)

    def rename_directory(self, source: Path, target: Path):
        # Unlike os.rename, Linux renameat2(RENAME_NOREPLACE) cannot replace
        # even an empty directory created by another process after preflight.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise OSError(errno.ENOSYS, 'no no-replace directory rename')
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):
            code = ctypes.get_errno()
            raise OSError(code, 'no-replace directory rename failed')

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
    # The durable writer must never publish intent that its bounded recovery
    # reader cannot consume, especially before a unit directory rename.
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(encoded) > 1024 * 1024:
        raise RuntimeError(f'Upgrade record exceeds the bounded recovery size: {path}')
    _mkdir_synced(path.parent, ops)
    temporary = path.with_name(path.name + '.write-' + str(uuid.uuid4()) + '.tmp')
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        with os.fdopen(descriptor, 'wb') as output:
            output.write(encoded)
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


def _land_file(row: dict, journal: Path, value: dict, ops: FileOps, *, event_prefix=''):
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
    ops.checkpoint(event_prefix + 'landed:' + row['suffix'], target)


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


def _database_choice(configured_url: str, cwd: Path | None):
    try:
        url = make_url(configured_url)
        configured = _configured_file(url, cwd)
    except (ArgumentError, ValueError, TypeError):
        # Do not log/format an operator URL; it may contain credentials.
        raise RuntimeError('Database upgrade cannot resolve the configured database URL') from None
    return url, configured


@contextmanager
def _resource_locks(home: Path, cwd: Path, configured: Path | None, ops: FileOps):
    """One order for both entries: HOME first, then sorted unique DB anchors.

    The HOME anchor is the parent of both product directories. The same anchor
    protects the binding family while additional DB locks protect their sets.
    """
    _mkdir_synced(home, ops)
    with _migration_lock(home):
        binding = home / NEW_HOME / BINDING_NAME
        bindings = _bindings(binding)
        parents = {cwd} if configured is not None else set()
        entry = bindings['resources'].get('database')
        if entry and configured == Path(entry['old_path']):
            parents.add(Path(entry['old_path']).parent)
        with ExitStack() as stack:
            for parent in sorted(parents - {home}, key=str):
                stack.enter_context(_migration_lock(parent))
            if _bindings(binding) != bindings:
                raise RuntimeError('Upgrade bindings changed while taking locks; restart')
            yield binding, bindings


def _resolve_database_locked(configured_url, url, configured, explicit,
                             cwd, binding, bindings, ops):
    if configured is None:
        return configured_url
    eligible = not explicit or configured == cwd / OLD_NAME
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


def prepare_database_url(configured_url: str, *, explicit: bool,
                         test_instance: bool = False, cwd: Path | None = None,
                         home: Path | None = None, ops: FileOps | None = None) -> str:
    """C4-compatible DB-only wrapper over the shared locked protocol.

    Non-file choices remain complete no-ops here. Product startup calls
    prepare_resource_locations so independent HOME resources still migrate.
    """
    if test_instance:
        return configured_url
    url, configured = _database_choice(configured_url, cwd)
    if configured is None:
        return configured_url
    cwd, home = (cwd or Path.cwd()).resolve(), (home or Path.home()).resolve()
    binding = home / NEW_HOME / BINDING_NAME
    if explicit and configured != cwd / OLD_NAME and not _exists(binding):
        return configured_url
    ops = ops or FileOps()
    try:
        with _resource_locks(home, cwd, configured, ops) as (binding, bindings):
            return _resolve_database_locked(configured_url, url, configured, explicit,
                                             cwd, binding, bindings, ops)
    except OSError as error:
        raise RuntimeError(f'Database upgrade filesystem failure ({error.errno}): {cwd / OLD_NAME} -> {cwd / NEW_NAME}') from None
    except RuntimeError as error:
        raise RuntimeError(f'{error}; database paths: {cwd / OLD_NAME} -> {cwd / NEW_NAME}') from None


def _home_record(home, identity, *, references=False):
    suffix = '.references.json' if references else '.json'
    return home / (HOME_JOURNAL_PREFIX + identity + suffix)


def _absolute(value):
    return (isinstance(value, str) and Path(value).is_absolute()
            and str(Path(value)) == value and os.path.normpath(value) == value)


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _require_journal(condition):
    if not condition:
        raise ValueError('invalid journal')


def _validate_reference(path, value, home):
    """C6 v1 contract. Validate ownership/map structure, never file contents.

    C5 never updates or retires these records, including after a DB has opened.
    C6 must add its transaction/stamp/durability protocol before retiring one.
    """
    try:
        _require_journal(set(value) == {'version', 'kind', 'id', 'move_journal_id', 'stage', 'resources', 'diagnostics'})
        _require_journal(type(value['version']) is int and value['version'] == 1)
        _require_journal(value['kind'] == 'references' and value['stage'] == 'files_landed')
        _require_journal(_uuid(value['id']) and _uuid(value['move_journal_id']))
        _require_journal(path == _home_record(home, value['id'], references=True))
        _require_journal(isinstance(value['resources'], dict) and set(value['resources']) <= {'backups', 'attachments'})
        sources, targets = set(), set()
        for resource, entry in value['resources'].items():
            folder = 'backups' if resource == 'backups' else 'bridge-attachments'
            old, new = home / OLD_HOME / folder, home / NEW_HOME / folder
            _require_journal(set(entry) == {'source_root', 'target_root', 'mappings'})
            _require_journal(entry['source_root'] == str(old) and entry['target_root'] == str(new))
            _require_journal(isinstance(entry['mappings'], list))
            for row in entry['mappings']:
                _require_journal(isinstance(row, dict) and set(row) == {'source', 'target'})
                source, target = Path(row['source']), Path(row['target'])
                _require_journal(_absolute(row['source']) and _absolute(row['target']))
                _require_journal(source != old and source.is_relative_to(old))
                _require_journal(target != new and target.is_relative_to(new))
                _require_journal(source not in sources and target not in targets)
                sources.add(source)
                targets.add(target)
        diagnostics = value['diagnostics']
        _require_journal(isinstance(diagnostics, dict) and set(diagnostics) == {'excluded', 'unmapped'})
        _require_journal(all(isinstance(items, list) and all(_absolute(item) for item in items)
                   and len(items) == len(set(items)) for items in diagnostics.values()))
    except (AssertionError, KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError(f'Upgrade reference journal is invalid: {path}') from None


def read_reference_journals(*, home: Path | None = None) -> list[dict]:
    """Read-only C6 handoff: exact allocations and diagnostics, no file I/O replay."""
    home = (home or Path.home()).resolve()
    records = []
    for path in sorted(home.glob(HOME_JOURNAL_PREFIX + '*.references.json')):
        value = _read_json(path)
        _validate_reference(path, value, home)
        records.append(value)
    return records


def _check_directories(path: Path):
    # Inspect lexical components before resolve() could erase a symlink.
    for directory in reversed((path, *path.parents)):
        if _exists(directory) and (directory.is_symlink() or not directory.is_dir()):
            raise RuntimeError(f'Upgrade directory conflict (symlink or non-directory): {directory}')


def _home_binding(bindings, home):
    entry = bindings['resources'].get('attachments')
    if entry is None:
        return None
    if (not isinstance(entry, dict) or set(entry) != {'old_path', 'new_path', 'journal_id', 'state'}
            or entry.get('old_path') != str(home / OLD_HOME / 'bridge-attachments')
            or entry.get('new_path') != str(home / NEW_HOME / 'bridge-attachments')
            or not _uuid(entry.get('journal_id')) or entry.get('state') not in ('active', 'retiring')):
        raise RuntimeError('Upgrade attachment binding record is invalid')
    return entry


def _attachment_choice(configured, explicit, home, cwd, bindings):
    old, new = home / OLD_HOME / 'bridge-attachments', home / NEW_HOME / 'bridge-attachments'
    value = str(configured)
    if value == '~' or value.startswith('~/'):
        value = str(home) + value[1:]
    location = Path(value).expanduser()
    location = (location if location.is_absolute() else cwd / location).resolve()
    entry = _home_binding(bindings, home)
    if entry and entry['state'] == 'active' and explicit and location == Path(entry['old_path']):
        _check_directories(new)
        if not new.is_dir():
            raise RuntimeError(f'Upgrade attachment binding target is missing: {old} -> {new}')
        return new, False, False, False
    eligible = not explicit or location == old
    bind = bool(eligible and explicit)
    return (new if eligible else location), eligible, bind, bool(entry and not bind)


def _check_resume_containment(value, attachment, attachment_eligible, configured,
                              database_explicit, home, cwd, bindings):
    """A saved allocation never authorizes moving newly configured custom data."""
    old, new = home / OLD_HOME, home / NEW_HOME
    protected = []
    if not attachment_eligible and attachment != new / 'bridge-attachments':
        if old.is_relative_to(attachment) or attachment == old / 'backups':
            raise RuntimeError(f'Upgrade containment conflict with custom attachments: {attachment}')
        protected.append((attachment, True))
    entry = bindings['resources'].get('database')
    bound = entry and entry['state'] == 'active' and configured == Path(entry['old_path'])
    if configured is not None and database_explicit and configured != cwd / OLD_NAME and not bound:
        protected.extend((Path(str(configured) + suffix), False) for suffix in SUFFIXES)
    for row in value['files']:
        if any(_protected(Path(row[key]), protected) for key in ('source', 'target')):
            raise RuntimeError(f'Upgrade containment conflict with newly custom data: {row["source"]} -> {row["target"]}')
    for row in value['directories']:
        source = Path(row['source'])
        if _protected(source, protected) or _protected(new / source.relative_to(old), protected):
            raise RuntimeError(f'Upgrade containment conflict with newly custom directory: {source}')


def _protected(path, exclusions):
    return any(path == excluded or (directory and path.is_relative_to(excluded))
               for excluded, directory in exclusions)


def _inspect_home(old, exclusions):
    files, directories = [], []
    if not _exists(old):
        return files, directories
    def walk(directory):
        _check_directories(directory)
        metadata = directory.lstat()
        directories.append({'source': str(directory), 'mode': stat.S_IMODE(metadata.st_mode),
                            'uid': metadata.st_uid, 'gid': metadata.st_gid,
                            'dev': metadata.st_dev, 'ino': metadata.st_ino})
        for path in sorted(directory.iterdir()):
            if _protected(path, exclusions):
                continue
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                walk(path)
            elif stat.S_ISREG(mode):
                files.append(path)
            else:
                raise RuntimeError(f'Upgrade refuses a non-regular or symlink home file: {path}')
    walk(old)
    return files, directories


def _preflight_database(configured, explicit, cwd, binding, bindings):
    """Validate the C4 set without moving it; HOME must not hide DB conflicts."""
    if configured is None:
        return
    entry = bindings['resources'].get('database')
    if entry and entry['state'] == 'active' and explicit and configured == Path(entry['old_path']):
        old, new = Path(entry['old_path']), Path(entry['new_path'])
        if not new.is_file() or new.is_symlink():
            raise RuntimeError(f'Database upgrade binding target is missing: {old} -> {new}')
        journals = _journals(old.parent)
        if journals:
            value = _read_json(journals[0])
            if value.get('id') != entry['journal_id']:
                raise RuntimeError('Database upgrade binding and journal disagree')
            _validate_journal(journals[0], value, old, new)
        return
    if explicit and configured != cwd / OLD_NAME:
        return
    old, new = cwd / OLD_NAME, cwd / NEW_NAME
    journals = _journals(cwd)
    if journals:
        _validate_journal(journals[0], _read_json(journals[0]), old, new)
        return
    sources = [Path(str(old) + suffix) for suffix in SUFFIXES if _exists(Path(str(old) + suffix))]
    targets = [Path(str(new) + suffix) for suffix in SUFFIXES if _exists(Path(str(new) + suffix))]
    for path in sources + targets:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError(f'Database upgrade refuses a non-regular file: {path}')
    if sources and (old not in sources or (old.stat().st_size == 0 and any(p.stat().st_size for p in sources if p != old))):
        raise RuntimeError(f'Database upgrade source set has no usable main file: {old} -> {new}')
    if sources and any(path.stat().st_size for path in targets):
        raise RuntimeError(f'Database upgrade conflict: {old} -> {new}; preserve both complete file sets')
    if not sources and targets and (new not in targets or (new.stat().st_size == 0 and any(p.stat().st_size for p in targets if p != new))):
        raise RuntimeError(f'Database upgrade target set has no usable main file: {old} -> {new}')


def _home_preflight(home, cwd, configured, attachment, attachment_eligible, records, bindings):
    old, new = home / OLD_HOME, home / NEW_HOME
    _check_directories(old)
    _check_directories(new)
    exclusions = []
    completed = {resource for record in records for resource in record['resources']}
    resources = {}
    for resource, folder in [('backups', 'backups'), ('attachments', 'bridge-attachments')]:
        if resource in completed:
            exclusions.append((old / folder, True))
        elif resource == 'backups' or attachment_eligible:
            resources[resource] = {'source_root': str(old / folder), 'target_root': str(new / folder)}
    if not attachment_eligible:
        if attachment == old / 'backups' or old.is_relative_to(attachment):
            raise RuntimeError(f'Upgrade containment overlap conflict: attachments {attachment}, home {old}')
        if attachment.is_relative_to(old):
            exclusions.append((attachment, True))
        # A consumed old literal is never opened as a fallback location.
        if _home_binding(bindings, home) and attachment == new / 'bridge-attachments':
            exclusions.append((old / 'bridge-attachments', True))
    database_locations = set()
    if configured is not None:
        database_locations.add(configured)
        database_locations.update((cwd / OLD_NAME, cwd / NEW_NAME))
        entry = bindings['resources'].get('database')
        if entry:
            database_locations.update((Path(entry['old_path']), Path(entry['new_path'])))
    for database in database_locations:
        for suffix in SUFFIXES:
            path = Path(str(database) + suffix)
            if path.is_relative_to(old):
                exclusions.append((path, False))
    if cwd.is_relative_to(old):
        exclusions.append((cwd / LOCK_NAME, False))
    source_files, directories = _inspect_home(old, exclusions)
    # A target directory can be custom storage too. Never merge into it.
    if not attachment_eligible and attachment.is_relative_to(new):
        for source in source_files:
            target = new / source.relative_to(old)
            if target == attachment or target.is_relative_to(attachment):
                raise RuntimeError(f'Upgrade containment conflict: {source} -> custom {attachment}')
    return resources, exclusions, source_files, directories


def _allocate_home_plan(home, resources, exclusions, sources, directories, bind_attachment):
    old, new = home / OLD_HOME, home / NEW_HOME
    identity = str(uuid.uuid4())
    rows, allocated = [], set()
    for index, source in enumerate(sources):
        target = new / source.relative_to(old)
        _check_directories(target.parent)
        if _exists(target):
            if not stat.S_ISREG(target.lstat().st_mode):
                raise RuntimeError(f'Upgrade allocation conflict: {source} -> {target}')
            for attempt in range(128):
                suffix = source.suffix if len(source.suffix.encode()) <= 16 else ''
                target = target.with_name(f'.synth-city-{identity}-{index}-{attempt}{suffix}')
                if not _exists(target) and target not in allocated:
                    break
            else:
                raise RuntimeError(f'Upgrade allocation incomplete: {source}')
        allocated.add(target)
        resource = next((key for key, roots in resources.items()
                         if source.is_relative_to(Path(roots['source_root']))), 'home')
        snapshot = _snapshot(source)
        rows.append(snapshot | {'suffix': str(index), 'resource': resource,
            'source': str(source), 'target': str(target),
            'temporary': str(target.parent / f'.synth-city-upgrade-{identity}-{index}.tmp'),
            'copy_state': 'none', 'target_identity': {'dev': snapshot['dev'], 'ino': snapshot['ino']}})
    return {'version': 1, 'kind': 'home', 'id': identity, 'source': str(old), 'target': str(new),
            'stage': 'planned', 'strategy': 'unit' if _exists(old) and not _exists(new) and not exclusions else 'files',
            'files': rows, 'directories': directories, 'resources': resources,
            'diagnostics': {'excluded': sorted({str(p) for p, _ in exclusions}), 'unmapped': []},
            'exclusions': [{'path': str(p), 'directory': directory} for p, directory in exclusions],
            'bind_attachment': bind_attachment, 'reference_id': str(uuid.uuid4())}


def _validate_home_journal(path, value, home):
    """Validate the full typed extension before any mutation or source unlink."""
    old, new = home / OLD_HOME, home / NEW_HOME
    try:
        _require_journal(set(value) == {'version', 'kind', 'id', 'source', 'target', 'stage', 'strategy',
                              'files', 'directories', 'resources', 'diagnostics', 'exclusions',
                              'bind_attachment', 'reference_id'})
        _require_journal(type(value['version']) is int and value['version'] == 1 and value['kind'] == 'home')
        _require_journal(_uuid(value['id']) and _uuid(value['reference_id']))
        _require_journal(path == _home_record(home, value['id']))
        _require_journal(value['source'] == str(old) and value['target'] == str(new))
        _require_journal(value['strategy'] in ('unit', 'files'))
        _require_journal(value['stage'] in ('planned', 'landing', 'targets_durable', 'removing_sources', 'landed'))
        _require_journal(type(value['bind_attachment']) is bool)
        _require_journal(isinstance(value['files'], list) and isinstance(value['directories'], list))
        _require_journal(isinstance(value['exclusions'], list))
        exclusions = []
        for excluded in value['exclusions']:
            _require_journal(set(excluded) == {'path', 'directory'} and _absolute(excluded['path']))
            _require_journal(type(excluded['directory']) is bool)
            _require_journal(Path(excluded['path']).is_relative_to(old))
            exclusions.append((Path(excluded['path']), excluded['directory']))
        sources, targets = set(), set()
        snapshot_keys = {'sha256', 'size', 'dev', 'ino', 'mode', 'uid', 'gid', 'atime_ns', 'mtime_ns'}
        for index, row in enumerate(value['files']):
            _require_journal(isinstance(row, dict) and set(row) == snapshot_keys | {'suffix', 'resource', 'source', 'target', 'temporary', 'copy_state', 'target_identity'})
            _require_journal(row['suffix'] == str(index) and row['resource'] in ('home', *value['resources']))
            _require_journal(_valid_snapshot(row) and _absolute(row['source']) and _absolute(row['target']))
            source, target = Path(row['source']), Path(row['target'])
            _require_journal(source != old and source.is_relative_to(old) and not _protected(source, exclusions))
            _require_journal(target != new and target.is_relative_to(new))
            _require_journal(target.parent == new / source.relative_to(old).parent)
            _require_journal(source not in sources and target not in targets)
            resource = next((key for key, roots in value['resources'].items()
                             if source.is_relative_to(Path(roots['source_root']))), 'home')
            _require_journal(row['resource'] == resource)
            sources.add(source)
            targets.add(target)
            _require_journal(row['temporary'] == str(target.parent / f'.synth-city-upgrade-{value["id"]}-{index}.tmp'))
            _require_journal(row['copy_state'] in ('none', 'writing', 'verified'))
            _require_journal(set(row['target_identity']) == {'dev', 'ino'})
            _require_journal(all(type(n) is int and n >= 0 for n in row['target_identity'].values()))
            if row['copy_state'] != 'verified':
                _require_journal(row['target_identity'] == {'dev': row['dev'], 'ino': row['ino']})
        for directory in value['directories']:
            _require_journal(set(directory) == {'source', 'mode', 'uid', 'gid', 'dev', 'ino'})
            _require_journal(_absolute(directory['source']) and Path(directory['source']).is_relative_to(old))
            _require_journal(all(type(directory[k]) is int and directory[k] >= 0 for k in ('mode', 'uid', 'gid', 'dev', 'ino')))
            _require_journal(directory['mode'] <= 0o7777)
        reference = _reference_from_plan(value)
        _validate_reference(_home_record(home, reference['id'], references=True), reference, home)
        if value['strategy'] == 'unit':
            _require_journal(not exclusions)
            root = next(d for d in value['directories'] if d['source'] == str(old))
            present = old if _exists(old) else new
            metadata = present.lstat()
            _require_journal(stat.S_ISDIR(metadata.st_mode) and (metadata.st_dev, metadata.st_ino) == (root['dev'], root['ino']))
    except (AssertionError, KeyError, TypeError, ValueError, AttributeError, StopIteration, FileNotFoundError):
        raise RuntimeError(f'Upgrade home journal is invalid or mismatched: {path}') from None
    for row in value['files']:
        source, target, temporary = (Path(row[k]) for k in ('source', 'target', 'temporary'))
        _check_directories(source.parent)
        _check_directories(target.parent)
        if _exists(source) and not _same(source, row):
            raise RuntimeError(f'Upgrade home source disagrees with journal: {source}')
        if not _exists(source) and not _exists(target):
            raise RuntimeError(f'Upgrade home file missing: {source} -> {target}')
        if _exists(target) and not _same(target, _target_metadata(row)):
            raise RuntimeError(f'Upgrade home target disagrees with journal: {target}')
        if _exists(temporary):
            if not stat.S_ISREG(temporary.lstat().st_mode) or row['copy_state'] == 'none' or not _exists(source):
                raise RuntimeError(f'Upgrade home temporary is unexplained: {temporary}')
            if row['copy_state'] == 'verified' and not _same(temporary, _target_metadata(row)):
                raise RuntimeError(f'Upgrade home verified copy disagrees with journal: {temporary}')
    for row in value['directories']:
        source = Path(row['source'])
        directory = source if _exists(source) else new / source.relative_to(old)
        if _exists(source) or value['strategy'] == 'unit':
            metadata = directory.lstat()
            if (not stat.S_ISDIR(metadata.st_mode)
                    or (metadata.st_dev, metadata.st_ino, stat.S_IMODE(metadata.st_mode), metadata.st_uid, metadata.st_gid)
                    != (row['dev'], row['ino'], row['mode'], row['uid'], row['gid'])):
                raise RuntimeError(f'Upgrade home directory disagrees with journal: {directory}')
    actual, _ = _inspect_home(old, exclusions)
    if any(source not in sources for source in actual):
        raise RuntimeError(f'Upgrade home has unjournalled source files: {old}')


def _reference_from_plan(value):
    return {'version': 1, 'kind': 'references', 'id': value['reference_id'],
            'move_journal_id': value['id'], 'stage': 'files_landed',
            'resources': {key: roots | {'mappings': [
                {'source': row['source'], 'target': row['target']}
                for row in value['files'] if row['resource'] == key]}
                for key, roots in value['resources'].items()},
            'diagnostics': value['diagnostics']}


def _home_directories(value, ops):
    old, new = Path(value['source']), Path(value['target'])
    for row in sorted(value['directories'], key=lambda row: len(Path(row['source']).parts)):
        target = new / Path(row['source']).relative_to(old)
        _check_directories(target)
        if not _exists(target):
            _mkdir_synced(target.parent, ops)
            target.mkdir(mode=row['mode'])
            os.chown(target, row['uid'], row['gid'], follow_symlinks=False)
            os.chmod(target, row['mode'], follow_symlinks=False)
            ops.sync_dir(target)
            ops.sync_dir(target.parent)
    for roots in value['resources'].values():
        _check_directories(Path(roots['target_root']))
        _mkdir_synced(Path(roots['target_root']), ops)


def _resume_home(journal, value, home, binding, bindings, ops):
    _validate_home_journal(journal, value, home)
    old, new = Path(value['source']), Path(value['target'])
    if value['strategy'] == 'unit' and _exists(old):
        # Persist source inodes/names before atomically changing their parent.
        for row in value['files']:
            ops.sync_file(Path(row['source']))
        for directory in reversed(value['directories']):
            ops.sync_dir(Path(directory['source']))
        try:
            ops.rename_directory(old, new)
        except OSError as error:
            if error.errno not in (errno.EXDEV, errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
                raise
            value['strategy'] = 'files'
            _write_json(journal, value, ops)
        else:
            ops.checkpoint('home_unit_renamed', new)
            ops.sync_dir(home)
    value['stage'] = 'landing'
    _write_json(journal, value, ops)
    _home_directories(value, ops)
    for row in value['files']:
        _land_file(row, journal, value, ops, event_prefix='home_')
        _write_json(journal, value, ops)
    _validate_home_journal(journal, value, home)
    for row in value['files']:
        _verify_landed(row)
    ops.sync_dir(new)
    ops.sync_dir(home)
    value['stage'] = 'targets_durable'
    _write_json(journal, value, ops)
    ops.checkpoint('home_targets_durable', new)
    value['stage'] = 'removing_sources'
    _write_json(journal, value, ops)
    for row in value['files']:
        source = Path(row['source'])
        if _exists(source):
            if not _same(source, row):
                raise RuntimeError(f'Upgrade home source changed before removal: {source}')
            ops.unlink(source)
            ops.sync_dir(source.parent)
        ops.checkpoint('home_source_removed:' + row['suffix'], source)
    for directory in reversed(value['directories']):
        source = Path(directory['source'])
        protected_parent = any(Path(row['path']).is_relative_to(source) for row in value['exclusions'])
        if _exists(source) and not protected_parent and not any(source.iterdir()):
            ops.rmdir(source)
            ops.sync_dir(source.parent)
    if value['bind_attachment']:
        bindings['resources']['attachments'] = {
            'old_path': str(home / OLD_HOME / 'bridge-attachments'),
            'new_path': str(home / NEW_HOME / 'bridge-attachments'),
            'journal_id': value['id'], 'state': 'active'}
        _write_json(binding, bindings, ops)
        ops.checkpoint('home_binding_durable', binding)
    reference = _reference_from_plan(value)
    reference_path = _home_record(home, reference['id'], references=True)
    if _exists(reference_path):
        current = _read_json(reference_path)
        _validate_reference(reference_path, current, home)
        if current != reference:
            raise RuntimeError(f'Upgrade reference journal disagrees with file journal: {reference_path}')
    else:
        _write_json(reference_path, reference, ops, initial=True)
    ops.checkpoint('home_reference_durable', reference_path)
    value['stage'] = 'landed'
    _write_json(journal, value, ops)
    ops.unlink(journal)
    ops.checkpoint('home_file_journal_unlinked', journal)
    ops.sync_dir(home)
    ops.checkpoint('home_file_journal_retired', journal)


def prepare_resource_locations(configured_url: str, configured_attachment_dir: str, *,
                               database_explicit: bool, attachment_explicit: bool,
                               test_instance: bool = False, cwd: Path | None = None,
                               home: Path | None = None, ops: FileOps | None = None) -> tuple[str, str]:
    """Product's single pre-engine entry. No SQL or C6 reference writes occur."""
    if test_instance:
        return configured_url, configured_attachment_dir
    cwd, home = (cwd or Path.cwd()).resolve(), (home or Path.home()).resolve()
    ops = ops or FileOps()
    url, configured = _database_choice(configured_url, cwd)
    try:
        with _resource_locks(home, cwd, configured, ops) as (binding, bindings):
            records = read_reference_journals(home=home)
            attachment, eligible, bind_attachment, retire_attachment = _attachment_choice(
                configured_attachment_dir, attachment_explicit, home, cwd, bindings)
            _preflight_database(configured, database_explicit, cwd, binding, bindings)
            candidates = [p for p in sorted(home.glob(HOME_JOURNAL_PREFIX + '*.json'))
                          if not p.name.endswith('.references.json')]
            if len(candidates) > 1:
                raise RuntimeError(f'Upgrade has multiple home file journals: {home}')
            if candidates:
                journal = candidates[0]
                value = _read_json(journal)
                _validate_home_journal(journal, value, home)
                _check_resume_containment(value, attachment, eligible, configured,
                    database_explicit, home, cwd, bindings)
            else:
                resources, exclusions, sources, directories = _home_preflight(
                    home, cwd, configured, attachment, eligible, records, bindings)
                value = _allocate_home_plan(home, resources, exclusions, sources, directories, bind_attachment)
                journal = _home_record(home, value['id'])
                # No old data and no explicit conversion key: fresh/already
                # moved installs create no unnecessary reference records.
                needed = bool(sources or (directories and not records) or bind_attachment)
                if needed:
                    _validate_home_journal(journal, value, home)
                    _write_json(journal, value, ops, initial=True)
                    ops.checkpoint('home_journal_durable', journal)
                else:
                    value = None
            # Nested DB sets land first; excluding their old/new file names
            # keeps their stable CWD and lock anchor outside directory moves.
            nested_db = configured is not None and configured.is_relative_to(home / OLD_HOME)
            if nested_db:
                database_url = _resolve_database_locked(configured_url, url, configured,
                    database_explicit, cwd, binding, bindings, ops)
            if value is not None:
                _resume_home(journal, value, home, binding, bindings, ops)
            if not nested_db:
                database_url = _resolve_database_locked(configured_url, url, configured,
                    database_explicit, cwd, binding, bindings, ops)
            if retire_attachment:
                bindings['resources']['attachments']['state'] = 'retiring'
                _write_json(binding, bindings, ops)
                del bindings['resources']['attachments']
                _write_json(binding, bindings, ops)
            return database_url, str(attachment)
    except OSError as error:
        raise RuntimeError(f'Upgrade filesystem failure ({error.errno}): {home / OLD_HOME} -> {home / NEW_HOME}') from None
