"""The e2e instance must not reset a reused connection at the poll interval (#916).

The shared read store polls every 5 seconds, and uvicorn closes an idle
keep-alive connection after 5 seconds by default. Playwright's route.fetch
reuses connections and does not retry a reset, so the isolated e2e instance
keeps idle connections open longer than any poll interval. It can also write
its backend log to a file, which CI uploads when a journey fails.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "e2e-instance.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "e2e.yml"
READS = ROOT / "frontend" / "src" / "features" / "factory" / "reads.ts"


def poll_interval_seconds() -> float:
    match = re.search(r"^const POLL_MS = (\d+);", READS.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "POLL_MS is not defined in the shared read store"
    return int(match.group(1)) / 1000


def keep_alive_seconds() -> int:
    text = SCRIPT.read_text(encoding="utf-8")
    flags = re.findall(r"--timeout-keep-alive (\d+)", text)
    assert len(flags) == 1, "the e2e instance must set --timeout-keep-alive exactly once"
    return int(flags[0])


def test_idle_connections_outlive_the_poll_interval():
    assert keep_alive_seconds() > poll_interval_seconds() * 2


def test_the_server_gets_the_keep_alive_flag_in_both_launch_modes():
    text = SCRIPT.read_text(encoding="utf-8")
    # Both the logged and the plain start expand the same argument list.
    assert text.count('"${SERVER_ARGS[@]}"') == 2
    assert re.search(r"SERVER_ARGS=\(.*--timeout-keep-alive 75 .*\)", text)


def test_the_script_is_valid_bash():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_a_backend_log_is_written_to_the_named_file_at_info_level():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'BACKEND_LOG="${E2E_BACKEND_LOG:-}"' in text
    assert '>> "$BACKEND_LOG" 2>&1 &' in text
    assert re.search(r'\[\[ -n "\$BACKEND_LOG" \]\] && LOG_LEVEL=info', text)


def test_the_workflow_sets_and_uploads_the_backend_log():
    text = WORKFLOW.read_text(encoding="utf-8")
    # Three jobs run the instance and each keeps its log when it fails.
    assert text.count("E2E_BACKEND_LOG: ${{ github.workspace }}/frontend/e2e-logs/backend.log") == 3
    assert text.count("frontend/e2e-logs/") >= 3
    assert "frontend/e2e-logs/backend.log" in text


def test_the_flicker_loop_repeats_the_route_fetch_journey_twenty_times():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "e2e-flicker-loop:" in text
    assert '--grep "Overview re-watches" --repeat-each=20' in text
    # Twenty plain passes: a flaky or skipped result does not count.
    assert "s.expected !== 20 || s.unexpected || s.flaky || s.skipped" in text
