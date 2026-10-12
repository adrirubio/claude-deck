#!/usr/bin/env python3
"""Seed the Deck E2E database with deterministic, synthetic state.

The ORM creates the schema (``init_db``). Rows are then written with stdlib
``sqlite3``: SQLAlchemy defaults are Python-side, so every NOT NULL column is
filled explicitly, and ``insert()`` refuses a row that omits one.

All timestamps are fixed offsets from ``SEED_NOW``. All names, repositories,
SHAs and tokens are synthetic. ``frontend/e2e/support/time.ts`` reads the
same ``E2E_SEED_NOW`` value.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

def _seed_now() -> datetime:
    """The seed clock: E2E_SEED_NOW, or the start of the current UTC hour.

    playwright.config.ts sets E2E_SEED_NOW once per run, so the instance and
    the journeys share one value. Offsets from it are identical on every run,
    and the data stays inside Deck's recent windows (for example Audit's 7 days).
    """
    value = os.environ.get("E2E_SEED_NOW")
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)


SEED_NOW = _seed_now()  # naive UTC, as Deck stores it


def at(**delta: float) -> str:
    """A naive UTC timestamp at SEED_NOW minus the given offset."""
    return (SEED_NOW - timedelta(**delta)).isoformat(sep=" ")


def sha(label: str) -> str:
    """A synthetic, stable 40-character Git SHA."""
    return hashlib.sha1(label.encode()).hexdigest()


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class Seeder:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._columns: dict[str, list[tuple[str, bool, bool]]] = {}

    def columns(self, table: str) -> list[tuple[str, bool, bool]]:
        """(name, not_null, primary_key) for each column of ``table``."""
        if table not in self._columns:
            rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            if not rows:
                raise SystemExit(f"seed: unknown table {table}")
            self._columns[table] = [(r[1], bool(r[3]), bool(r[5])) for r in rows]
        return self._columns[table]

    def insert(self, table: str, **values: Any) -> int:
        known = {name for name, _, _ in self.columns(table)}
        unknown = set(values) - known
        if unknown:
            raise SystemExit(f"seed: {table} has no column {sorted(unknown)}")
        missing = [
            name for name, not_null, pk in self.columns(table)
            if not_null and name not in values and not (pk and name == "id")
        ]
        if missing:
            raise SystemExit(f"seed: {table} row omits NOT NULL {missing}")
        encoded = {
            k: json.dumps(v) if isinstance(v, (dict, list)) else v
            for k, v in values.items()
        }
        cols = ", ".join(encoded)
        marks = ", ".join("?" for _ in encoded)
        cur = self.conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(encoded.values())
        )
        return int(cur.lastrowid)


async def create_schema() -> None:
    from app.database import init_db

    await init_db()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()

    db_path: Path = args.database.resolve()
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    asyncio.run(create_schema())

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        from scenarios import seed_all  # noqa: E402  (scripts/e2e on sys.path)

        with conn:
            seed_all(Seeder(conn), root=args.root.resolve())
    finally:
        conn.close()
    print(f"seed: wrote {db_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
