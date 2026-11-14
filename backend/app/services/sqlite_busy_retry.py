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


async def retry_when_busy(db, step, *, route, attempts=3, delay=0.05, prepare=None):
    """Run ``step`` again while SQLite reports busy or locked, then raise SqliteBusyExhausted.

    Only for a step that is safe to repeat. A failed attempt is rolled back and waited out. Then ``prepare`` runs
    before EVERY retry (never before the first attempt), after the wait and immediately before the step: it must
    read the context again and refuse (by raising) if the step should no longer run, because anything may have
    changed while the attempt waited. A refusal raised there is not retried. A failure that is not a lock is
    never retried.
    """
    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1 and prepare is not None:
                await prepare()
            return await step()
        except OperationalError as exc:
            if not is_sqlite_busy(exc):
                raise
            await db.rollback()
            logger.warning("sqlite_busy route=%s attempt=%s/%s", route, attempt, attempts)
            if attempt == attempts:
                raise SqliteBusyExhausted(route) from exc
            await asyncio.sleep(delay * attempt)
