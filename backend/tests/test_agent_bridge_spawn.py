"""Tests for provider-aware tmux spawning."""
import json
from types import SimpleNamespace


def test_claude_worktree_uses_generated_session_name_when_blank(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="worktree"),
    )

    assert result["session_name"] == "repo-abcd"
    assert calls[0][:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    assert "--worktree repo-abcd" in calls[0][7]
    assert spawn.get_spawned_sessions()["repo-abcd"]["worktree_name"] == "repo-abcd"


def test_claude_resume_resolves_directory_from_transcript_cwd(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.cc_bridge import spawn as claude_spawn
    from app.services.providers.base import SpawnCommandOptions

    project_dir = tmp_path / "claude-deck"
    project_dir.mkdir()
    project_folder = "-tmp-claude-deck"
    session_id = "session-123"
    transcript_dir = tmp_path / ".claude" / "projects" / project_folder
    transcript_dir.mkdir(parents=True)
    transcript = transcript_dir / f"{session_id}.jsonl"
    transcript.write_text(json.dumps({"cwd": str(project_dir)}) + "\n", encoding="utf-8")

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(claude_spawn.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "claude-deck-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(
            directory="",
            mode="resume",
            session_id=session_id,
            project_folder=project_folder,
        ),
    )

    assert result["session_name"] == "claude-deck-abcd"
    assert calls[0][:7] == ["tmux", "new-session", "-d", "-s", "claude-deck-abcd", "-c", str(project_dir)]
    assert "--resume session-123" in calls[0][7]
