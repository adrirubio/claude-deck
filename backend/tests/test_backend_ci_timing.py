"""The hosted backend job reports its own timings and keeps them after a failure (#866).

The job prints the slowest tests and writes a JUnit file with the time of every
test case. A later change to make the suite faster needs those numbers from the
real runner, so the report must not disappear and the file must be uploaded even
when the suite fails. These tests read the workflow, then run pytest with the
same reporting flags on a tiny failing suite to prove the file and the log
section exist after a failure.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "backend-tests.yml"


def _backend_steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["backend"]["steps"]


def _suite_step() -> dict:
    steps = [step for step in _backend_steps() if "pytest tests " in step.get("run", "")]
    assert len(steps) == 1, "the backend job must have one step that runs the suite"
    return steps[0]


def _reporting_flags() -> list[str]:
    return [token for token in shlex.split(_suite_step()["run"])
            if token.startswith(("--durations", "--junitxml"))]


def _junit_name() -> str:
    names = [flag.split("=", 1)[1] for flag in _reporting_flags() if flag.startswith("--junitxml=")]
    assert len(names) == 1, "the suite must write exactly one JUnit file"
    return names[0]


def test_the_suite_prints_the_slowest_tests_and_writes_a_junit_file():
    flags = _reporting_flags()
    assert any(flag.startswith("--durations=") for flag in flags)
    assert any(flag.startswith("--durations-min=") for flag in flags)
    assert _junit_name().endswith(".xml")


def test_the_junit_file_is_uploaded_even_when_the_suite_fails():
    suite = _suite_step()
    uploads = [step for step in _backend_steps()
               if str(step.get("uses", "")).startswith("actions/upload-artifact@")
               and "timings" in step.get("with", {}).get("name", "")]
    assert len(uploads) == 1, "one step must upload the timings"
    upload = uploads[0]
    # The suite runs in the working directory the workflow names; the upload path is from the repository root.
    suite_dir = suite["working-directory"]
    assert upload["with"]["path"] == f"{suite_dir}/{_junit_name()}"
    assert "always()" in upload["if"], "without always() a failed suite would keep no timings"
    steps = _backend_steps()
    assert steps.index(upload) > steps.index(suite)


def test_a_failing_run_still_writes_per_case_times_and_the_slowest_section(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "import time\n"
        "def test_slow_pass():\n    time.sleep(1.1)\n"
        "def test_fast_fail():\n    assert False\n",
        encoding="utf-8",
    )
    report = tmp_path / "timings.xml"
    flags = [f"--junitxml={report}" if flag.startswith("--junitxml=") else flag for flag in _reporting_flags()]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_sample.py", "-q", "-p", "no:cacheprovider", *flags],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert report.is_file(), "a failed run must still leave the JUnit file"
    cases = ET.parse(report).getroot().iter("testcase")
    times = {case.get("name"): float(case.get("time")) for case in cases}
    assert set(times) == {"test_slow_pass", "test_fast_fail"}
    assert times["test_slow_pass"] >= 1.0
    assert "slowest" in result.stdout and "test_slow_pass" in result.stdout
