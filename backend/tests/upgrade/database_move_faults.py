"""Pre-open durability model: discard unsynced namespace state, not just a process kill.

The production protocol never mutates a synchronised file inode in place: its
journals/bindings are replaced atomically, and copied data is immutable after
fsync. Durable inode objects can therefore be retained as hard links while
directory snapshots decide which names survive a simulated power cut. This
models file/directory fsync separately; it is no claim about C6 SQL/WAL barriers.
"""
import os
from pathlib import Path


class Interrupted(BaseException):
    """A process terminates without the protocol's ordinary error recovery."""


class DurableFilesystem:
    def __init__(self, root: Path, base, cut=None):
        self.root = root
        self.base = base
        self.cut = cut
        self.interrupted = False
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
        metadata = path.stat()
        identity = (metadata.st_dev, metadata.st_ino)
        if path == self.root:
            self.root_identity = identity
        self.directories[identity] = {
            p.name: ('directory', (p.stat().st_dev, p.stat().st_ino)) if p.is_dir() else ('file', self._remember(p))
            for p in path.iterdir()
        }

    def sync_file(self, path):
        if self.interrupted:
            raise Interrupted('power is off')
        self.base.sync_file(path)
        self.durable_contents.add(self._remember(path))

    def sync_dir(self, path):
        if self.interrupted:
            raise Interrupted('power is off')
        self.base.sync_dir(path)
        if path.is_relative_to(self.root):
            self._directory(path)

    def checkpoint(self, stage, path):
        self.events.append(stage)
        if stage == self.cut:
            self.interrupted = True
            raise Interrupted(stage)

    def rmdir(self, path):
        # Retain the actual empty directory inode, while removing its live
        # name. A power cut may restore that name if its parent was not synced.
        if any(path.iterdir()):
            raise OSError('model rmdir requires an empty directory')
        metadata = path.stat()
        os.rename(path, self.objects / f'directory-{metadata.st_dev}-{metadata.st_ino}')

    def __getattr__(self, name):
        return getattr(self.base, name)

    def power_cut(self):
        """Reconstruct only namespace entries whose parent directory was synced."""
        # Keep directory inodes as well as file inodes. Recreating directories
        # with mkdir would model a power cut as changing their identities, and
        # accidentally reused inode numbers could hide a broken rename model.
        for path in sorted((p for p in self.root.rglob('*') if p.is_dir()),
                           key=lambda p: len(p.parts), reverse=True):
            metadata = path.stat()
            for child in path.iterdir():
                child.unlink()
            os.rename(path, self.objects / f'directory-{metadata.st_dev}-{metadata.st_ino}')
        for path in self.root.iterdir():
            path.unlink()

        def restore(relative, identity):
            directory = self.root / relative
            for name, (kind, child_identity) in self.directories.get(identity, {}).items():
                target = directory / name
                if kind == 'directory':
                    stored = self.objects / f'directory-{child_identity[0]}-{child_identity[1]}'
                    os.rename(stored, target)
                    restore(relative / name, child_identity)
                else:
                    os.link(self.objects / child_identity, target)
                    if child_identity not in self.durable_contents:
                        # A durable name does not make its unsynced bytes
                        # durable. Choose total content loss as the allowed
                        # failure outcome, including journal/copy temporaries.
                        target.write_bytes(b'')

        restore(Path('.'), self.root_identity)
