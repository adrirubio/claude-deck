"""Observed issue-label priority. Ordering grants no dispatch authority."""
from __future__ import annotations

import re
from collections.abc import Iterable

_PRIORITY = re.compile(r"priority:([1-9][0-9]{0,3})\Z", re.ASCII)


def priority_from_labels(labels: Iterable[str]) -> int | None:
    """The smallest strict priority:1..9999 label wins; other labels are ignored."""
    values = [int(match[1]) for label in labels if isinstance(label, str)
              and (match := _PRIORITY.fullmatch(label))]
    return min(values, default=None)


def effective_priority(value: object) -> int | None:
    """Damaged or legacy values cannot acquire explicit priority."""
    return value if type(value) is int and 1 <= value <= 9999 else None


def dispatch_order_key(item) -> tuple[bool, int, int, int]:
    priority = effective_priority(item.dispatch_priority)
    return priority is None, priority or 0, item.issue_number, item.id
