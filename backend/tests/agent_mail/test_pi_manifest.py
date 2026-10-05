"""Keep the Pi tool list equal to the real standalone MCP server."""
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def sync_module():
    path = Path(__file__).resolve().parents[3] / "integrations/pi-agent-mail/sync_manifest.py"
    spec = importlib.util.spec_from_file_location("fixture_pi_manifest_sync", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_matches_real_mcp_tools_without_registration(sync_module, monkeypatch):
    def reject_http(*args, **kwargs):
        raise AssertionError("Schema inspection must not make an HTTP request")

    monkeypatch.setattr(httpx, "request", reject_http)
    monkeypatch.setenv("CLAUDE_DECK_PROVIDER", "pi-cli")
    expected = sync_module.render_manifest()
    path = Path(sync_module.__file__).with_name("manifest.ts")
    assert path.read_text() == expected
    for name in (
        "deck_get_backlog_coordination", "deck_report_backlog_assessment",
        "deck_get_operator_action_contexts", "deck_prepare_operator_action_contexts",
    ):
        assert f'"name": "{name}"' in expected
    public, private = expected.split("export const privateTools = ")
    assert "__deck_mail_close_generation" not in public
    assert '"name": "__deck_mail_close_generation"' in private


def test_check_reports_drift_without_writing(sync_module, monkeypatch, tmp_path, capsys):
    path = tmp_path / "manifest.ts"
    path.write_text("stale list\n")
    monkeypatch.setattr(sync_module, "__file__", str(tmp_path / "sync_manifest.py"))
    monkeypatch.setattr(sync_module, "render_manifest", lambda: "current list\n")
    monkeypatch.setattr(sys, "argv", ["sync_manifest.py", "--check"])
    assert sync_module.main() == 1
    assert path.read_text() == "stale list\n"
    assert "differs" in capsys.readouterr().out
    path.write_text("current list\n")
    assert sync_module.main() == 0


def test_sync_writes_current_list(sync_module, monkeypatch, tmp_path):
    monkeypatch.setattr(sync_module, "__file__", str(tmp_path / "sync_manifest.py"))
    monkeypatch.setattr(sync_module, "render_manifest", lambda: "current list\n")
    monkeypatch.setattr(sys, "argv", ["sync_manifest.py"])
    assert sync_module.main() == 0
    assert (tmp_path / "manifest.ts").read_text() == "current list\n"
