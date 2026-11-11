"""Power-cut model with real SQLite WAL and separately durable namespace.

An unverified NORMAL commit is allowed to disappear, unlike a process kill.
The durability oracle observes actual SQL results, never a production stage
name. Cleanup after the cut cannot advance the frozen durable images.
"""
from pathlib import Path


class PowerCut(BaseException):
    pass


class ReferencePowerLoss:
    def __init__(self, database, home, cut=None, *, durable_commit_prefix=0):
        self.database, self.home, self.cut = database, home, cut
        self.events, self.sql = [], []
        self.mode, self.sync, self.cut_seen = None, None, False
        self.barriers = 0
        self.commits = 0
        self.durable_commit_prefix = durable_commit_prefix
        self.database_image = self.capture_database()
        self.namespace = self.capture_namespace()

    def capture_database(self):
        return {suffix: Path(str(self.database) + suffix).read_bytes()
                for suffix in ('', '-wal', '-shm') if Path(str(self.database) + suffix).exists()}

    def capture_namespace(self):
        return {path.name: path.read_bytes()
                for path in self.home.glob('.albiex-synth-city-upgrade.*.references.json')}

    def event(self, name):
        if self.cut_seen:
            raise AssertionError('I/O after modeled power cut')
        self.events.append(name)
        if name == self.cut or (isinstance(self.cut, int) and len(self.events) - 1 == self.cut):
            self.cut_seen = True
            raise PowerCut(name)

    def operations(self):
        from app.upgrade_references import ReferenceOps
        model = self

        class Observed(ReferenceOps):
            def execute(self, db, sql, parameters=()):
                model.event('sql.before:' + sql)
                cursor = super().execute(db, sql, parameters)
                normalized = sql.upper()
                if normalized == 'COMMIT':
                    assert not db.in_transaction
                    model.commits += 1
                    if model.commits == model.durable_commit_prefix:
                        # NORMAL permits OS writeback to preserve an earlier
                        # complete WAL prefix while losing later commits. This
                        # is an allowed power-loss outcome, never evidence that
                        # the implementation verified a durability barrier.
                        model.database_image = model.capture_database()
                if normalized.startswith('PRAGMA') and cursor.description:
                    # Fetch the actual native result before returning it to the
                    # implementation. No declared "barrier passed" seam is used.
                    result = cursor.fetchall()
                    model.sql.append((sql, result))
                    if normalized == 'PRAGMA JOURNAL_MODE':
                        model.mode = result[0][0]
                    elif normalized == 'PRAGMA SYNCHRONOUS':
                        model.sync = result[0][0]
                    elif normalized.startswith('PRAGMA WAL_CHECKPOINT'):
                        if (model.mode == 'wal' and model.sync == 2 and len(result) == 1
                                and len(result[0]) == 3 and result[0][0] == 0
                                and result[0][1] >= 0 and result[0][1] == result[0][2]):
                            model.database_image = model.capture_database()
                            model.barriers += 1

                    class Result:
                        def fetchone(self):
                            return result[0] if result else None

                    cursor = Result()
                model.event('sql.after:' + sql)
                return cursor

            def sync_dir(self, path):
                model.event('directory.before')
                super().sync_dir(path)
                if path == model.home:
                    model.namespace = model.capture_namespace()
                model.event('directory.after')

            def unlink(self, path):
                model.event('unlink.before:' + path.name)
                super().unlink(path)
                model.event('unlink.after:' + path.name)

            def checkpoint(self, stage, path):
                model.event(stage)

        return Observed()

    def restore(self):
        assert self.cut_seen
        # The real connection may have closed/checkpointed after the cut. Those
        # bytes are volatile in this model and cannot redefine durable state.
        for suffix in ('', '-wal', '-shm'):
            path = Path(str(self.database) + suffix)
            path.unlink(missing_ok=True)
            if suffix in self.database_image:
                path.write_bytes(self.database_image[suffix])
        for path in self.home.glob('.albiex-synth-city-upgrade.*.references.json'):
            path.unlink()
        for name, data in self.namespace.items():
            (self.home / name).write_bytes(data)
