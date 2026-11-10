"""Names-only startup diagnostic; legacy values are never read or translated."""
import logging
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def warn_legacy_environment() -> None:
    """Warn once per process using environment keys, never their values."""
    names = sorted(name for name in os.environ if name.startswith("CLAUDE_DECK_"))
    if names:
        replacements = "; ".join(f"{name} -> SYNTH_CITY_{name[len('CLAUDE_DECK_'):]}" for name in names)
        logging.getLogger(__name__).warning(
            "Albiex Synth City ignores old environment names; rename them: %s", replacements
        )
