"""Bounded retry of an idempotent step that hit SQLite's busy or locked condition."""
import asyncio
import logging

from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

# SQLITE_BUSY and SQLITE_LOCKED. Their extended codes (busy snapshot, busy recovery, locked shared cache) keep
# these primary codes in the low byte.
_BUSY_PRIMARY_CODES = frozenset({5, 6})


class SqliteBusyExhausted(Exception):
    """The step was still busy after every attempt."""


def is_sqlite_busy(exc) -> bool:
    """True for a SQLAlchemy error that SQLite raised because the database was busy or locked."""
    if not isinstance(exc, OperationalError):
        return False
    code = getattr(exc.orig, "sqlite_errorcode", None)
    if isinstance(code, int):
        return (code & 0xFF) in _BUSY_PRIMARY_CODES
    return "database is locked" in str(exc.orig).lower()


async def retry_when_busy(db, step, *, route, attempts=3, delay=0.05, reload=()):
    """Run ``step`` again while SQLite reports busy or locked, then raise SqliteBusyExhausted.

    Only for a step that is safe to repeat. Before each retry the failed transaction is rolled back and the
    rows in ``reload`` are read again (a rollback expires them). A failure that is not a lock is never retried.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await step()
        except OperationalError as exc:
            if not is_sqlite_busy(exc):
                raise
            await db.rollback()
            for row in reload:
                await db.refresh(row)
            logger.warning("sqlite_busy route=%s attempt=%s/%s", route, attempt, attempts)
            if attempt == attempts:
                raise SqliteBusyExhausted(route) from exc
            await asyncio.sleep(delay * attempt)
