#!/usr/bin/env python3
"""Record one check on an unchanged, clean Git commit. This grants no authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def source(cwd: Path) -> dict:
    return {
        "head": git(cwd, "rev-parse", "HEAD"),
        "tree": git(cwd, "rev-parse", "HEAD^{tree}"),
        "status": git(cwd, "status", "--porcelain=v1", "--untracked-files=all"),
        "diff_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "-C", str(cwd), "diff", "--binary", "HEAD"]
        )).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Give a command after --")
    cwd = args.cwd.resolve(strict=True)
    root = Path(git(cwd, "rev-parse", "--show-toplevel"))
    output = args.output_dir.resolve()
    if output == root or root in output.parents:
        parser.error("Store evidence outside the checked Git worktree")
    before = source(cwd)
    if before["status"]:
        parser.error("Commit the source first. Dirty checks are not verification evidence")
    output.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
    log = output / (name + ".log")
    receipt = output / (name + ".json")
    record = {"version": 1, "command": command, "cwd": str(cwd),
              "source_before": before, "started_at": now(), "log": str(log),
              "exit_code": None, "eligible": False}
    # Logs can contain private values. The caller must review them before publication.
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        try:
            result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
            record["exit_code"] = result.returncode
        except OSError as error:
            record["error"] = type(error).__name__
            record["exit_code"] = 127
        except KeyboardInterrupt:
            record["error"] = "interrupted"
            record["exit_code"] = 130
    record["ended_at"] = now()
    try:
        after = source(cwd)
        record["source_after"] = after
        record["eligible"] = before == after and not after["status"]
    except (OSError, subprocess.CalledProcessError):
        record["error"] = "source_observation_failed"
    record["log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"receipt": str(receipt), "head": before["head"],
                      "exit_code": record["exit_code"], "eligible": record["eligible"]}))
    if not record["eligible"]:
        return 125
    code = record["exit_code"]
    return code if 0 <= code <= 255 else 1


if __name__ == "__main__":
    sys.exit(main())
