"""Trust changes use synthetic native homes and repository metadata."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit


def trust_fixture(monkeypatch, tmp_path):
    from app.services import team_workspace_trust as trust
    home = tmp_path / "native-home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(trust, "native_user", lambda: trust.NativeUser(home, os.getuid(), {}))
    return trust, home, repo


@pytest.mark.parametrize("provider", ["claude-code", "codex-cli"])
def test_trust_preserves_other_entries_and_is_idempotent(monkeypatch, tmp_path, provider):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    if provider == "claude-code":
        path = home / ".claude.json"
        original = {"otherSetting": "preserved", "projects": {
            "/other/repo": {"hasTrustDialogAccepted": False, "allowedTools": ["Read"]},
            str(repo): {"allowedTools": ["Edit"]}}}
        path.write_text(json.dumps(original))
    else:
        path = home / ".codex" / "config.toml"
        path.parent.mkdir()
        path.write_text('# Keep this comment\nmodel = "example"\n[projects."/other/repo"]\ntrust_level = "untrusted"\n')
    path.chmod(0o640)
    assert trust.prepare_workspace_trust(provider, str(repo)) is True
    if provider == "claude-code":
        saved = json.loads(path.read_text())
        assert saved["otherSetting"] == original["otherSetting"]
        assert saved["projects"]["/other/repo"] == original["projects"]["/other/repo"]
        assert saved["projects"][str(repo)] == {"allowedTools": ["Edit"], "hasTrustDialogAccepted": True}
    else:
        saved = tomlkit.parse(path.read_text())
        assert saved["model"] == "example"
        assert saved["projects"]["/other/repo"]["trust_level"] == "untrusted"
        assert saved["projects"][str(repo)]["trust_level"] == "trusted"
        assert "# Keep this comment" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o640
    before = path.read_bytes()
    assert trust.prepare_workspace_trust(provider, str(repo)) is False
    assert path.read_bytes() == before


def test_claude_trust_uses_primary_checkout(monkeypatch, tmp_path):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    primary = tmp_path / "primary"
    primary.mkdir()
    def git(args, **kwargs):
        assert args[:3] == ["git", "-C", str(repo)]
        return SimpleNamespace(returncode=0, stdout=f"worktree {primary}\0HEAD abc\0branch refs/heads/main\0\0worktree {repo}\0HEAD abc\0\0", stderr="")
    monkeypatch.setattr(trust.subprocess, "run", git)
    assert trust.prepare_workspace_trust("claude-code", str(repo)) is True
    assert json.loads((home / ".claude.json").read_text())["projects"] == {
        str(primary): {"hasTrustDialogAccepted": True}}


@pytest.mark.parametrize("provider,contents", [("claude-code", "{"), ("codex-cli", "[broken")])
def test_invalid_trust_file_is_not_replaced(monkeypatch, tmp_path, provider, contents):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    path = home / ".claude.json" if provider == "claude-code" else home / ".codex" / "config.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(contents)
    with pytest.raises(ValueError, match="Workspace trust"):
        trust.prepare_workspace_trust(provider, str(repo))
    assert path.read_text() == contents


def test_atomic_trust_failure_preserves_original(monkeypatch, tmp_path):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    path = home / ".claude.json"
    path.write_text('{"projects": {}}')
    def refuse(*args):
        raise PermissionError("fixture")
    monkeypatch.setattr(trust.os, "replace", refuse)
    with pytest.raises(ValueError, match="Workspace trust"):
        trust.prepare_workspace_trust("claude-code", str(repo))
    assert path.read_text() == '{"projects": {}}'
    assert list(home.iterdir()) == [path]


def test_native_user_uses_tmux_owner_and_environment(monkeypatch, tmp_path):
    from app.services import team_workspace_trust as trust
    proc = tmp_path / "proc"
    (proc / "123").mkdir(parents=True)
    monkeypatch.setattr(trust, "_PROC", proc)
    home = tmp_path / "native"
    home.mkdir()
    def tmux(args, **kwargs):
        assert args[0] == "tmux"
        if args[1] == "display-message":
            return SimpleNamespace(returncode=0, stdout="123\n", stderr="")
        return SimpleNamespace(returncode=0, stdout=f"HOME={home}\nCODEX_HOME={home}/codex\n", stderr="")
    monkeypatch.setattr(trust.subprocess, "run", tmux)
    native = trust.native_user()
    assert native.home == home
    assert native.uid == (proc / "123").stat().st_uid
    assert native.environment["CODEX_HOME"] == str(home / "codex")


@pytest.mark.parametrize("provider", ["claude-code", "codex-cli"])
def test_trust_refuses_symlink_configuration(monkeypatch, tmp_path, provider):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("{}" if provider == "claude-code" else "")
    path = home / ".claude.json" if provider == "claude-code" else home / ".codex" / "config.toml"
    path.parent.mkdir(exist_ok=True)
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="Workspace trust"):
        trust.prepare_workspace_trust(provider, str(repo))
    assert path.is_symlink()
    assert outside.read_text() == ("{}" if provider == "claude-code" else "")


def test_empty_existing_claude_configuration_is_not_replaced(monkeypatch, tmp_path):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    path = home / ".claude.json"
    path.touch()
    with pytest.raises(ValueError, match="Workspace trust"):
        trust.prepare_workspace_trust("claude-code", str(repo))
    assert path.read_bytes() == b""


def test_trust_failure_does_not_expose_configuration(monkeypatch, tmp_path):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    path = home / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text('fixture_private_value = "secret"\n[broken')
    with pytest.raises(ValueError) as error:
        trust.prepare_workspace_trust("codex-cli", str(repo))
    assert "secret" not in str(error.value)
    assert str(home) not in str(error.value)


def test_new_native_config_directory_keeps_native_owner(monkeypatch, tmp_path):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    native_uid = os.getuid() + 1
    monkeypatch.setattr(trust, "native_user", lambda: trust.NativeUser(home, native_uid, {}))
    changed = []
    monkeypatch.setattr(trust.os, "chown", lambda path, uid, gid: changed.append((Path(path), uid)))
    monkeypatch.setattr(trust.os, "fchown", lambda *args: None)
    assert trust.prepare_workspace_trust("codex-cli", str(repo)) is True
    assert (home / ".codex", native_uid) in changed


def test_claude_primary_checkout_keeps_special_path_characters(monkeypatch, tmp_path):
    trust, home, repo = trust_fixture(monkeypatch, tmp_path)
    primary = tmp_path / "primary with spaces é"
    primary.mkdir()
    def git(args, **kwargs):
        assert args[-1] == "-z"
        return SimpleNamespace(returncode=0, stdout=f"worktree {primary}\0HEAD abc\0\0worktree {repo}\0HEAD abc\0\0", stderr="")
    monkeypatch.setattr(trust.subprocess, "run", git)
    assert trust.prepare_workspace_trust("claude-code", str(repo)) is True
    assert list(json.loads((home / ".claude.json").read_text())["projects"]) == [str(primary)]
