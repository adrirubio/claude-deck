#!/usr/bin/env python3
"""Validate a review finding list. The list is a claim, not an approval."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


def validate(value: dict, head: str | None) -> list[str]:
    errors = []
    if not isinstance(value, dict) or value.get("version") != 1:
        return ["Use a version 1 object."]
    rows = value.get("findings")
    if not isinstance(rows, list) or not rows:
        return ["Supply a nonempty findings list."]
    ids = set()
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append(f"Row {number}: use an object.")
            continue
        ident = row.get("id")
        label = ident if isinstance(ident, str) else str(number)
        if not isinstance(ident, str) or not ident.strip() or ident in ids:
            errors.append(f"{label}: use a unique finding ID.")
        else:
            ids.add(ident)
        for field in ("location", "requirement", "decisive_check"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"{label}: supply {field}.")
        state = row.get("state")
        if state not in {"open", "claimed_fixed", "verified"}:
            errors.append(f"{label}: invalid state.")
        if state in {"claimed_fixed", "verified"}:
            fixed = row.get("fixed_head")
            if not isinstance(fixed, str) or re.fullmatch(r"[0-9a-f]{40}", fixed) is None:
                errors.append(f"{label}: supply a full fixed_head SHA.")
            if head and fixed != head:
                errors.append(f"{label}: fixed_head differs from the review head.")
        if state == "verified":
            evidence = row.get("evidence")
            if not isinstance(evidence, dict):
                errors.append(f"{label}: supply closure evidence.")
                continue
            for field in ("reviewer", "after"):
                if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                    errors.append(f"{label}: supply evidence.{field}.")
            if evidence.get("kind") == "regression":
                if not isinstance(evidence.get("before"), str) or not evidence["before"].strip():
                    errors.append(f"{label}: link the failing check before the fix.")
            elif evidence.get("kind") == "inspection":
                if not isinstance(evidence.get("reason"), str) or not evidence["reason"].strip():
                    errors.append(f"{label}: explain why a regression check does not apply.")
            else:
                errors.append(f"{label}: use regression or inspection evidence.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--head", help="Full SHA of the complete review candidate")
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args()
    try:
        value = json.loads(args.file.read_text())
        errors = validate(value, args.head)
    except (OSError, ValueError) as error:
        print(type(error).__name__, file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    counts = {state: sum(row["state"] == state for row in value["findings"])
              for state in ("open", "claimed_fixed", "verified")}
    print(json.dumps({"counts": counts, "complete": counts["verified"] == len(value["findings"])}))
    return int(args.require_verified and bool(counts["open"] or counts["claimed_fixed"]))


if __name__ == "__main__":
    sys.exit(main())
