"""Pre-open durability model: discard unsynced namespace state, not just a process kill.

The production protocol never mutates a synchronised file inode in place: its
journals/bindings are replaced atomically, and copied data is immutable after
fsync. Durable inode objects can therefore be retained as hard links while
directory snapshots decide which names survive a simulated power cut. This
models file/directory fsync separately; it is no claim about C6 SQL/WAL barriers.
"""
import os
from pathlib import Path
import shutil


class Interrupted(BaseException):
    """A process terminates without the protocol's ordinary error recovery."""


class DurableFilesystem:
    def __init__(self, root: Path, base, cut=None):
        self.root = root
        self.base = base
        self.cut = cut
        self.events = []
        self.objects = root.parent / (root.name + '-durable-inodes')
        self.objects.mkdir()
        self.durable_contents = set()
        self.directories = {}
        for path in sorted(root.rglob('*')):
            if path.is_file():
                self.durable_contents.add(self._remember(path))
        for path in [root, *sorted(p for p in root.rglob('*') if p.is_dir())]:
            self._directory(path)

    def _remember(self, path):
        value = path.stat()
        identity = f'{value.st_dev}-{value.st_ino}'
        stored = self.objects / identity
        if not stored.exists():
            os.link(path, stored)
        return identity

    def _directory(self, path):
        self.directories[path.relative_to(self.root)] = {
            p.name: ('directory', None) if p.is_dir() else ('file', self._remember(p))
            for p in path.iterdir()
        }

    def sync_file(self, path):
        self.base.sync_file(path)
        self.durable_contents.add(self._remember(path))

    def sync_dir(self, path):
        self.base.sync_dir(path)
        if path.is_relative_to(self.root):
            self._directory(path)

    def checkpoint(self, stage, path):
        self.events.append(stage)
        if stage == self.cut:
            raise Interrupted(stage)

    def __getattr__(self, name):
        return getattr(self.base, name)

    def power_cut(self):
        """Reconstruct only namespace entries whose parent directory was synced."""
        shutil.rmtree(self.root)
        self.root.mkdir()

        def restore(relative):
            directory = self.root / relative
            for name, (kind, identity) in self.directories.get(relative, {}).items():
                target = directory / name
                if kind == 'directory':
                    target.mkdir()
                    restore(relative / name)
                else:
                    os.link(self.objects / identity, target)
                    if identity not in self.durable_contents:
                        # A durable name does not make its unsynced bytes
                        # durable. Choose total content loss as the allowed
                        # failure outcome, including journal/copy temporaries.
                        target.write_bytes(b'')

        restore(Path('.'))
