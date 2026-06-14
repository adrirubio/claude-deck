"""Tests for repo identity derivation."""
import subprocess

from app.utils.repo_utils import derive_repo_identity


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_non_git_dir_uses_normalized_path(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    ident = derive_repo_identity(str(d))
    assert ident["repo_name"] == "plain"
    assert ident["repo_root"] == str(d.resolve())
    assert len(ident["repo_id"]) == 16


def test_same_dir_is_stable(tmp_path):
    d = tmp_path / "stable"
    d.mkdir()
    assert derive_repo_identity(str(d)) == derive_repo_identity(str(d))


def test_worktrees_share_repo_id(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(["init", "-b", "master"], main)
    (main / "f.txt").write_text("x")
    _git(["add", "."], main)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"], main)
    wt = tmp_path / "wt"
    _git(["worktree", "add", "-b", "feature", str(wt)], main)

    a = derive_repo_identity(str(main))
    b = derive_repo_identity(str(wt))
    assert a["repo_id"] == b["repo_id"]
    assert a["repo_name"] == "main"


def test_missing_dir_does_not_crash(tmp_path):
    ident = derive_repo_identity(str(tmp_path / "nope"))
    assert ident["repo_id"]
