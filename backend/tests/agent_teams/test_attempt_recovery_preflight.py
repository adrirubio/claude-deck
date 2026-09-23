import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PREFLIGHT = REPO_ROOT / "scripts" / "attempt-recovery-preflight.sh"


def _session(
    session_id: int,
    *,
    slot_id: int,
    source: str,
    status: str,
    last_seen_at: str,
    tmux_target: str | None = None,
) -> dict[str, object]:
    return {
        "id": session_id,
        "provider": "codex-cli",
        "source": source,
        "session_key": f"{source}:{session_id}",
        "team_preset_id": 2,
        "team_slot_id": slot_id,
        "mailbox_status": status,
        "tmux_target": tmux_target,
        "last_seen_at": last_seen_at,
    }


def _bridge_session(slot_id: int, target: str) -> dict[str, object]:
    return {
        "pane_id": f"%{slot_id}",
        "tmux_target": target,
        "team_preset_id": 2,
        "team_slot_id": slot_id,
        "mail_wake_state": "wakeable",
        "mail_wake_enabled": True,
        "mail_wake_target": target,
    }


def _bridge_sessions() -> dict[str, object]:
    return {
        "sessions": [
            _bridge_session(4, "leader:0.0"),
            _bridge_session(6, "specialist:0.0"),
        ]
    }


def _fixtures(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    now = datetime.now(UTC)
    fresh = (now - timedelta(seconds=30)).replace(tzinfo=None).isoformat()
    stale = (now - timedelta(days=30)).replace(tzinfo=None).isoformat()
    team = {
        "members": [
            {
                "display_name": "Leader",
                "sessions": [
                    _session(
                        1,
                        slot_id=4,
                        source="mcp",
                        status="connected",
                        last_seen_at=stale,
                    ),
                    _session(
                        2,
                        slot_id=4,
                        source="mcp",
                        status="connected",
                        last_seen_at=fresh,
                    ),
                    _session(
                        3,
                        slot_id=4,
                        source="hook",
                        status="connected",
                        last_seen_at=fresh,
                    ),
                    _session(
                        4,
                        slot_id=4,
                        source="observed",
                        status="observed",
                        last_seen_at=fresh,
                        tmux_target="leader:0.0",
                    ),
                ],
            },
            {
                "display_name": "Specialist",
                "sessions": [
                    _session(
                        5,
                        slot_id=6,
                        source="mcp",
                        status="connected",
                        last_seen_at=fresh,
                    ),
                    _session(
                        6,
                        slot_id=6,
                        source="hook",
                        status="connected",
                        last_seen_at=fresh,
                    ),
                    _session(
                        7,
                        slot_id=6,
                        source="observed",
                        status="observed",
                        last_seen_at=fresh,
                        tmux_target="specialist:0.0",
                    ),
                ],
            },
        ]
    }
    fixtures = {
        "health.json": {"status": "running", "version": "2.0.1"},
        "preset.json": {
            "id": 2,
            "autonomy_enabled": False,
            "slots": [
                {"id": 4, "display_name": "Leader", "role": "Leader", "enabled": True},
                {
                    "id": 6,
                    "display_name": "Specialist",
                    "role": "Specialist",
                    "enabled": True,
                },
            ],
        },
        "scopes.json": {
            "scopes": [
                {
                    "id": 1,
                    "continuation_enabled": False,
                    "max_continuation_revisions": 6,
                    "max_continuation_failed_heads": 8,
                    "max_failed_heads_per_revision": 2,
                    "max_scope_paths": 32,
                    "max_scope_commands": 16,
                }
            ]
        },
        "items.json": {
            "items": [
                {
                    "id": 23,
                    "scope_id": 1,
                    "issue_number": 821,
                    "pr_number": 875,
                    "dispatch_status": "escalated",
                    "attempt_phase": "implementation",
                    "active_scope_revision": 0,
                    "owner_slot_id": 6,
                    "workspace_path": "/tmp/preserved-workspace",
                    "pending_approval_request_id": None,
                    "continuation_block_code": "continuation_disabled",
                    "retry_block_code": "pr_preserved",
                }
            ]
        },
        "team.json": team,
        "bridge-sessions.json": _bridge_sessions(),
    }
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir(parents=True)
    for filename, payload in fixtures.items():
        (fixture_dir / filename).write_text(json.dumps(payload))
    return fixture_dir, team


def _run_preflight(
    tmp_path: Path,
    team: dict[str, object],
    bridge_sessions: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    fixture_dir, _ = _fixtures(tmp_path)
    (fixture_dir / "team.json").write_text(json.dumps(team))
    if bridge_sessions is not None:
        (fixture_dir / "bridge-sessions.json").write_text(json.dumps(bridge_sessions))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    curl = fake_bin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
url=${!#}
case "$url" in
  */agent-mail/team*) file=team.json ;;
  */agent-bridge/sessions*) file=bridge-sessions.json ;;
  */github-work-items*) file=items.json ;;
  */github-scopes*) file=scopes.json ;;
  */presets/2) file=preset.json ;;
  */health) file=health.json ;;
  *) exit 22 ;;
esac
cat "$PREFLIGHT_FIXTURE_DIR/$file"
"""
    )
    curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PREFLIGHT_FIXTURE_DIR"] = str(fixture_dir)
    return subprocess.run(
        [str(PREFLIGHT), "http://127.0.0.1:8000", "2", "1", "23"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_counts_one_physical_agent_not_mcp_and_hook_rows(tmp_path: Path) -> None:
    _, team = _fixtures(tmp_path / "source")

    result = _run_preflight(tmp_path / "run", team)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sessions"] == {
        "owner": {
            "slot_id": 6,
            "authenticated_mcp": 1,
            "observed_panes": 1,
            "wake_state": "wakeable",
            "wake_target": "specialist:0.0",
        },
        "leader": {
            "slot_id": 4,
            "authenticated_mcp": 1,
            "observed_panes": 1,
            "wake_state": "wakeable",
            "wake_target": "leader:0.0",
        },
    }


@pytest.mark.parametrize("wake_state", ["opted_out", "unbound", "ambiguous"])
def test_preflight_refuses_non_wakeable_owner_pane(tmp_path: Path, wake_state: str) -> None:
    _, team = _fixtures(tmp_path / "source")
    bridge_sessions = _bridge_sessions()
    bridge_sessions["sessions"][1]["mail_wake_state"] = wake_state

    result = _run_preflight(tmp_path / "run", team, bridge_sessions)

    assert result.returncode == 1
    assert result.stderr.strip() == "owner slot Agent Bridge pane is not exactly wakeable"


def test_preflight_refuses_disabled_wake_participation(tmp_path: Path) -> None:
    _, team = _fixtures(tmp_path / "source")
    bridge_sessions = _bridge_sessions()
    bridge_sessions["sessions"][1]["mail_wake_enabled"] = False

    result = _run_preflight(tmp_path / "run", team, bridge_sessions)

    assert result.returncode == 1
    assert result.stderr.strip() == "owner slot Agent Bridge pane is not exactly wakeable"


def test_preflight_refuses_inexact_wake_target(tmp_path: Path) -> None:
    _, team = _fixtures(tmp_path / "source")
    bridge_sessions = _bridge_sessions()
    bridge_sessions["sessions"][1]["mail_wake_target"] = "specialist:1.0"

    result = _run_preflight(tmp_path / "run", team, bridge_sessions)

    assert result.returncode == 1
    assert result.stderr.strip() == "owner slot Agent Bridge pane is not exactly wakeable"


def test_preflight_refuses_duplicate_bridge_pane_rows(tmp_path: Path) -> None:
    _, team = _fixtures(tmp_path / "source")
    bridge_sessions = _bridge_sessions()
    bridge_sessions["sessions"].append(dict(bridge_sessions["sessions"][1]))

    result = _run_preflight(tmp_path / "run", team, bridge_sessions)

    assert result.returncode == 1
    assert result.stderr.strip() == "owner slot must have exactly one matching Agent Bridge pane"


def test_preflight_refuses_bridge_pane_from_another_slot(tmp_path: Path) -> None:
    _, team = _fixtures(tmp_path / "source")
    bridge_sessions = _bridge_sessions()
    bridge_sessions["sessions"][1]["team_slot_id"] = 4

    result = _run_preflight(tmp_path / "run", team, bridge_sessions)

    assert result.returncode == 1
    assert result.stderr.strip() == "owner slot must have exactly one matching Agent Bridge pane"


def test_preflight_refuses_duplicate_observed_owner_panes(tmp_path: Path) -> None:
    _, team = _fixtures(tmp_path / "source")
    owner = next(member for member in team["members"] if member["display_name"] == "Specialist")
    duplicate = dict(owner["sessions"][-1])
    duplicate.update({"id": 8, "session_key": "observed:8", "tmux_target": "specialist:1.0"})
    owner["sessions"].append(duplicate)

    result = _run_preflight(tmp_path / "run", team)

    assert result.returncode == 1
    assert result.stderr.strip() == "owner slot must have exactly one observed tmux pane"


def test_preflight_refuses_hook_without_fresh_authenticated_mcp(tmp_path: Path) -> None:
    _, team = _fixtures(tmp_path / "source")
    leader = next(member for member in team["members"] if member["display_name"] == "Leader")
    leader["sessions"] = [
        session
        for session in leader["sessions"]
        if session["source"] != "mcp" or session["id"] == 1
    ]

    result = _run_preflight(tmp_path / "run", team)

    assert result.returncode == 1
    assert result.stderr.strip() == "Leader slot has no fresh authenticated MCP session"
