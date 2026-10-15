#!/usr/bin/env python3
"""Tell CI whether a pull request changes only documentation.

Writes `run_suites=false` to $GITHUB_OUTPUT only when every changed file of a
pull request is documentation. Every other case writes `run_suites=true`: a
push, any API or parsing failure, and a file list that does not match the
pull request's changed-file count. The required jobs keep running and finish
`success` either way, because Deck accepts a required check only with that
conclusion. Standard library only: it runs before any setup step.
"""
from __future__ import annotations

import json
import os
import urllib.request

API = "https://api.github.com"
MAX_FILES = 3000  # GitHub lists at most 3000 files for a pull request


def is_documentation(path: str) -> bool:
    # Markdown elsewhere can be application content, so only docs/ and the root count.
    return path.startswith("docs/") or ("/" not in path and path.endswith(".md"))


def is_docs_only(files: list[dict]) -> bool:
    if not files:
        return False
    for row in files:
        paths = [row.get("filename"), row.get("previous_filename") or row.get("filename")]
        if not all(isinstance(path, str) and is_documentation(path) for path in paths):
            return False
    return True


def pull_request_files(repository: str, number: int, token: str) -> list[dict]:
    files: list[dict] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"{API}/repos/{repository}/pulls/{number}/files?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("Unexpected pull request files response")
        files.extend(batch)
        if len(batch) < 100 or len(files) >= MAX_FILES:
            return files
        page += 1


def decide() -> bool:
    """Return True when the suites must run."""
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return True
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
        pull = json.load(stream)["pull_request"]
    files = pull_request_files(os.environ["GITHUB_REPOSITORY"], int(pull["number"]),
                               os.environ.get("GITHUB_TOKEN", ""))
    if len(files) != pull.get("changed_files") or len(files) >= MAX_FILES:
        return True  # an incomplete list proves nothing
    return not is_docs_only(files)


def main() -> None:
    try:
        run_suites = decide()
    except Exception as exc:  # any doubt runs the suites
        print(f"Docs-only detection failed ({exc.__class__.__name__}); running the suites.")
        run_suites = True
    message = "Running the suites." if run_suites else "Docs-only change: the suites are skipped."
    print(message)
    if not run_suites and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f"{message} Every changed file is under docs/ or is root Markdown.\n")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"run_suites={'true' if run_suites else 'false'}\n")


if __name__ == "__main__":
    main()
