"""The CI docs-only detector: a docs-only pull request skips the expensive suites."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "docs_only.py"
spec = importlib.util.spec_from_file_location("docs_only", SCRIPT)
docs_only = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs_only)


def change(filename, status="modified", previous=None):
    row = {"filename": filename, "status": status}
    if previous:
        row["previous_filename"] = previous
    return row


@pytest.mark.parametrize("files,expected", [
    ([change("docs/plans/x/01-audit.md"), change("docs/guide/index.md")], True),
    ([change("README.md"), change("CHANGELOG.md")], True),
    ([change("docs/.vitepress/config.ts")], True),
    ([change("docs/guide/index.md"), change("backend/app/main.py")], False),
    ([change("frontend/e2e/README.md")], False),  # Markdown outside docs/ and the root can be app content
    ([change("backend/app/old.py", status="removed")], False),
    ([change("docs/moved.md", status="renamed", previous="backend/app/moved.md")], False),
    ([change("docs/new.md", status="renamed", previous="docs/old.md")], True),
    ([change(".github/workflows/e2e.yml")], False),
    ([change("README.txt")], False),
    ([], False),  # nothing proves docs-only
])
def test_docs_only_classification(files, expected):
    assert docs_only.is_docs_only(files) is expected


def test_any_failure_runs_the_suites(tmp_path, monkeypatch):
    output = tmp_path / "out"
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7, "changed_files": 1}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def broken(*_args):
        raise OSError("network down")

    monkeypatch.setattr(docs_only, "pull_request_files", broken)
    docs_only.main()
    assert output.read_text() == "run_suites=true\n"


def test_a_push_always_runs_the_suites(tmp_path, monkeypatch):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(docs_only, "pull_request_files", lambda *_args: [change("docs/a.md")])
    docs_only.main()
    assert output.read_text() == "run_suites=true\n"


def test_a_docs_only_pull_request_skips_the_suites(tmp_path, monkeypatch):
    output = tmp_path / "out"
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7, "changed_files": 2}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(docs_only, "pull_request_files",
                        lambda *_args: [change("docs/a.md"), change("README.md")])
    docs_only.main()
    assert output.read_text() == "run_suites=false\n"


def test_an_incomplete_file_list_runs_the_suites(tmp_path, monkeypatch):
    output = tmp_path / "out"
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7, "changed_files": 3}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(docs_only, "pull_request_files", lambda *_args: [change("docs/a.md")])
    docs_only.main()
    assert output.read_text() == "run_suites=true\n"
