#!/usr/bin/env python3
"""Check changed Python files for undefined names before publication."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Accepted base commit or branch")
    args = parser.parse_args()
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    base = subprocess.check_output(
        ["git", "rev-parse", "--verify", args.base + "^{commit}"], cwd=root, text=True
    ).strip()
    # Include committed, staged, and unstaged edits relative to the accepted base.
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", "-z", base], cwd=root
    ).split(b"\0")
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root
    ).split(b"\0")
    files = sorted({name.decode() for name in changed + untracked
                    if name and name.endswith(b".py") and (Path(root) / name.decode()).is_file()})
    if not files:
        print("No changed Python files.")
        return 0
    return subprocess.call([sys.executable, "-m", "ruff", "check", "--isolated",
                            "--select", "F821", "--", *files], cwd=root)


if __name__ == "__main__":
    sys.exit(main())
