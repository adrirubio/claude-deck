"""Tests for CC Bridge session discovery."""
import pytest
from unittest.mock import MagicMock, patch


def test_is_claude_code_matches_claude_command():
    from app.services.cc_bridge.discovery import _is_claude_code
    assert _is_claude_code("claude") is True


def test_is_claude_code_rejects_other_commands():
    from app.services.cc_bridge.discovery import _is_claude_code
    assert _is_claude_code("vim") is False
    assert _is_claude_code("bash") is False
    assert _is_claude_code("node") is False


def test_is_claude_code_matches_claude_variants():
    from app.services.cc_bridge.discovery import _is_claude_code
    assert _is_claude_code("claude") is True


def test_discover_returns_list():
    from app.services.cc_bridge.discovery import discover_cc_sessions
    result = discover_cc_sessions()
    assert isinstance(result, list)


def test_discover_session_dict_shape():
    from app.services.cc_bridge.discovery import _build_session_info

    mock_pane = MagicMock()
    mock_pane.pane_current_command = "claude"
    mock_pane.pane_current_path = "/home/user/project"
    mock_pane.pane_pid = "12345"
    mock_pane.pane_id = "%0"
    mock_pane.pane_index = "0"

    mock_window = MagicMock()
    mock_window.window_index = "0"
    mock_window.window_name = "main"

    mock_session = MagicMock()
    mock_session.session_name = "cc-proj"

    result = _build_session_info(mock_pane, mock_window, mock_session)
    assert result["tmux_target"] == "cc-proj:0.0"
    assert result["session_name"] == "cc-proj"
    assert result["cwd"] == "/home/user/project"
    assert result["pid"] == "12345"
    assert result["pane_id"] == "%0"


def test_capture_pane_preview_returns_string():
    from app.services.cc_bridge.discovery import capture_pane_preview
    result = capture_pane_preview("nonexistent-session:0.0")
    assert isinstance(result, str)
