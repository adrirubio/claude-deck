"""Build an old installation without importing the candidate's application.

The source archive is test input, not a second working checkout. Every fixture
is created offline from the immutable v3.1.0 commit already present in Git.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path


V31_SOURCE_SHA = "a68a02cb768eb8fa9afa90df81871dbccc464a09"
_PATH_FIELDS = {"file_path", "storage_path", "agent_path", "prompt_text"}
_RETARGET_FIELDS = {
    "backups": {"file_path"},
    "bridge_session_attachments": {"storage_path", "agent_path", "prompt_text"},
}


def copy_database_set(database: Path, destination: Path) -> Path:
    """Copy a quiescent SQLite file set without opening or checkpointing it."""
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / database.name
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(database) + suffix)
        if source.exists():
            shutil.copyfile(source, Path(str(target) + suffix))
    return target


def _ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _value(value):
    return {"bytes_hex": value.hex()} if isinstance(value, bytes) else value


@dataclass
class SemanticSnapshot:
    """Exact pre-existing records, owned-file digests and persisted paths.

    Compare meaning rather than SQLite bytes: new tables/rows/columns are
    allowed, but every old primary key and old field must survive. Only exact,
    explicitly supplied values of the four path fields can be retargeted.
    """

    records: dict[str, dict[str, dict]]
    files: dict[str, str]
    paths: dict[str, dict[str, str]]

    @classmethod
    def capture(cls, database: Path) -> SemanticSnapshot:
        records, files, paths = {}, {}, {}
        # Even a reader can change SQLite sidecars. Inspect a copy so repeated
        # assertions cannot accidentally checkpoint the WAL being tested.
        with tempfile.TemporaryDirectory(prefix="upgrade-snapshot-") as temporary:
            copied = copy_database_set(database, Path(temporary))
            with sqlite3.connect(copied) as db:
                db.row_factory = sqlite3.Row
                tables = db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
                for (table,) in tables:
                    columns = db.execute(f"PRAGMA table_info({_ident(table)})").fetchall()
                    primary = [column[1] for column in sorted(columns, key=lambda col: col[5]) if column[5]]
                    if not primary:
                        raise AssertionError(f"Snapshot requires a stable primary key: {table}")
                    rows = {}
                    for raw in db.execute(f"SELECT * FROM {_ident(table)}"):
                        row = {key: _value(raw[key]) for key in raw.keys()}
                        identity = json.dumps([row[key] for key in primary], separators=(",", ":"))
                        rows[identity] = row
                        stored = {field: row[field] for field in _PATH_FIELDS
                                  if isinstance(row.get(field), str)}
                        if stored:
                            paths[f"{table}:{identity}"] = stored
                        owned = (row.get("file_path") if table == "backups" else
                                 row.get("storage_path") if table == "bridge_session_attachments" else None)
                        if owned:
                            files[owned] = hashlib.sha256(Path(owned).read_bytes()).hexdigest()
                    records[table] = rows
        return cls(records=records, files=files, paths=paths)

    def assert_preserved(self, after: SemanticSnapshot, *, path_map: dict[str, str] | None = None) -> None:
        mapping = path_map or {}
        for table, rows in self.records.items():
            assert table in after.records, f"Lost pre-existing table: {table}"
            for identity, row in rows.items():
                actual = after.records[table].get(identity)
                assert actual is not None, f"Lost pre-existing record: {table}:{identity}"
                for field, value in row.items():
                    expected = (mapping.get(value, value)
                                if field in _RETARGET_FIELDS.get(table, ()) and isinstance(value, str) else value)
                    assert field in actual and actual[field] == expected, f"Changed pre-existing field: {table}:{identity}:{field}"
        for path, digest in self.files.items():
            assert after.files.get(mapping.get(path, path)) == digest, "Lost or changed owned file"


@dataclass
class V31Install:
    root: Path
    home: Path
    source: Path
    app_dir: Path
    database: Path
    browser_state: dict
    manifest: dict
    before: SemanticSnapshot


def build_v31_install(root: Path) -> V31Install:
    """Run pinned v3.1 APIs/installers, then export the quiescent WAL set."""
    repository = Path(__file__).resolve().parents[3]
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / "v3.1.0-source"
    source.mkdir()
    try:
        pinned = subprocess.check_output(
            ["git", "rev-parse", "v3.1.0^{commit}"], cwd=repository, text=True, stderr=subprocess.PIPE
        ).strip()
        if pinned != V31_SOURCE_SHA:
            raise AssertionError("v3.1.0 does not match the reviewed source pin")
        archive = subprocess.check_output(
            ["git", "archive", V31_SOURCE_SHA, "backend/app", "backend/mcp_shim", "backend/pyproject.toml",
             "integrations/pi-agent-mail", "frontend/src/contexts/ProviderContext.tsx",
             "frontend/src/features/agent-teams/operatorAuth.ts"],
            cwd=repository, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError:
        raise AssertionError("The v3.1.0 Git source is required; use a full-history checkout (CI fetch-depth: 0)") from None
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(source, filter="data")
    home = root / "home"
    home.mkdir()
    app_dir = source / "backend"
    # Construct a fresh child environment. Do not inherit credentials, custom
    # provider homes, database settings, .env paths, or live-instance addresses.
    environment = {
        "HOME": str(home), "PATH": str(root / "no-external-binaries"),
        "PYTHONPATH": str(app_dir), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
        "OPERATOR_TOKEN": "synthetic-upgrade-operator",
    }
    runner = Path(__file__).with_name("v31_seed.py")
    result = subprocess.run(
        [sys.executable, str(runner), str(root), V31_SOURCE_SHA], cwd=app_dir,
        env=environment, capture_output=True, text=True, timeout=90,
    )
    if result.returncode:
        # Only this credential-free child can supply these diagnostics.
        raise AssertionError(f"Pinned v3.1 seeder failed:\n{result.stderr[-6000:]}")
    manifest = json.loads((root / "manifest.json").read_text())
    browser_state = json.loads((root / "browser-storage.json").read_text())
    database = app_dir / "claude_registry.db"
    before = SemanticSnapshot.capture(database)
    (root / "semantic-snapshot.json").write_text(json.dumps(before.__dict__, indent=2, sort_keys=True))
    return V31Install(root, home, source, app_dir, database, browser_state, manifest, before)
