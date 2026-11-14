"""#861: productctl writes the GitHub credential safely. Synthetic values only, in a fully isolated harness.

The REAL productctl source is executed as a black box with its /opt and work paths replaced by a temporary
directory. 'sudo -u <user>' is simulated by running the command, unchanged, as the current user with HOME set to a
temporary home, so the real child writer runs. Nothing here runs sudo, gh, systemctl or a network call, and no real
credential, path or port is touched. These tests do not claim that a CodeQL alert is resolved.
"""
from __future__ import annotations

import io
import os
import stat
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "product-factory" / "productctl"
TOKEN = "synthetic-token-for-tests-only"
OLD_TOKEN = "synthetic-old-token-for-tests-only"
REAL_RUN = subprocess.run
USERS = ("deckproduct", "deckproductctl")


class Sandbox:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp, self.monkeypatch = tmp_path, monkeypatch
        self.base = tmp_path / "opt"
        self.env = self.base / "controller" / "backend" / ".env"
        self.state = self.base / "state"
        self.homes = {name: tmp_path / "homes" / name for name in USERS}
        self.calls, self.chowns, self.replaces, self.fchowns = [], [], [], []
        self.fail_replace = False
        self.fail_setup_git_for = None
        for directory in (self.env.parent, self.state, *self.homes.values()):
            directory.mkdir(parents=True)
        self.env.write_text(f"OPERATOR_TOKEN=synthetic-operator\nGITHUB_TOKEN={OLD_TOKEN}\nOTHER=kept\n")
        self.env.chmod(0o640)
        (self.state / "preparation.json").write_text('{"pin": "synthetic"}\n')

    def fake_run(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if command[:4] == ["sudo", "-H", "-u", "juan"]:
            return subprocess.CompletedProcess(command, 0, stdout=TOKEN + "\n", stderr="")
        if command[0] == "systemctl":
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        assert command[:3] == ["sudo", "-H", "-u"], command
        user, rest = command[3], list(command[4:])
        if rest[:2] == ["/usr/bin/gh", "auth"]:  # gh auth setup-git: recorded, never run
            if self.fail_setup_git_for == user:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if rest[0] == "/usr/bin/python3":  # the child writer: run for real, as the current user, in that home
            run_env = {**os.environ, "HOME": str(self.homes[user])}
            return REAL_RUN([sys.executable, *rest[1:]], input=kwargs.get("input"), env=run_env,
                            capture_output=True, text=True, check=kwargs.get("check", False), cwd=str(self.tmp))
        raise AssertionError(f"unexpected command {command}")

    def run(self, *argv):
        text = SCRIPT.read_text()
        text = text.replace("/opt/albiex-synth-city-product", str(self.base))
        text = text.replace("/home/deckproductctl/work", str(self.tmp / "work")).replace("127.0.0.1:8011", "127.0.0.1:1")
        mp = self.monkeypatch
        mp.setattr(sys, "argv", ["productctl", *(argv or ("configure-ambient-github", "--confirm"))])
        mp.setattr(os, "geteuid", lambda: 0)
        import pwd
        mp.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_dir=str(self.homes[name]), pw_uid=os.getuid(), pw_gid=os.getgid()))
        mp.setattr(subprocess, "run", self.fake_run)
        real_chown, real_replace, real_fchown = os.chown, os.replace, os.fchown
        mp.setattr(os, "chown", lambda path, *a, **k: self.chowns.append(str(path)))

        def replace(src, dst, *a, **k):
            if self.fail_replace:
                raise OSError("synthetic failure at the replace step")
            self.replaces.append((str(src), str(dst), stat.S_IMODE(os.stat(src).st_mode), Path(src).read_text()))
            return real_replace(src, dst, *a, **k)

        def fchown(fd, uid, gid):
            self.fchowns.append((uid, gid))
            return real_fchown(fd, uid, gid)

        mp.setattr(os, "replace", replace)
        mp.setattr(os, "fchown", fchown)
        output = io.StringIO()
        error = None
        with redirect_stdout(output):
            try:
                exec(compile(text, str(SCRIPT), "exec"), {"__name__": "__main__", "__file__": str(SCRIPT)})
            except SystemExit as exc:
                error = exc
            except Exception as exc:  # the command failed
                error = exc
        return output.getvalue(), error

    def hosts(self, user):
        return self.homes[user] / ".config" / "gh" / "hosts.yml"


@pytest.fixture
def sb(tmp_path, monkeypatch):
    return Sandbox(tmp_path, monkeypatch)


def mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_the_controller_env_gets_the_token_line_and_keeps_everything_else(sb):
    out, error = sb.run()
    assert error is None
    lines = sb.env.read_text().splitlines()
    assert f"GITHUB_TOKEN={TOKEN}" in lines and "OPERATOR_TOKEN=synthetic-operator" in lines and "OTHER=kept" in lines
    assert not any(OLD_TOKEN in line for line in lines)
    assert mode(sb.env) == 0o600 and (os.stat(sb.env).st_uid, os.stat(sb.env).st_gid) == (os.getuid(), os.getgid())
    assert TOKEN not in out


def test_the_controller_env_is_replaced_from_a_secure_temporary_file_that_keeps_owner_and_group(sb):
    before = (os.stat(sb.env).st_uid, os.stat(sb.env).st_gid)
    sb.run()
    assert len(sb.replaces) == 1
    source, target, temp_mode, temp_text = sb.replaces[0]
    assert target == str(sb.env) and Path(source).parent == sb.env.parent and Path(source) != sb.env
    assert temp_mode == 0o600  # the secret was written into a file nobody else could open
    assert TOKEN in temp_text
    assert (before[0], before[1]) in sb.fchowns  # owner and group set on the temporary file before it replaced the original
    assert [p.name for p in sb.env.parent.iterdir()] == [".env"]  # no temporary file left behind


def test_a_failure_while_replacing_the_env_leaves_the_original_untouched(sb):
    original = sb.env.read_bytes()
    sb.fail_replace = True
    out, error = sb.run()
    assert error is not None
    assert sb.env.read_bytes() == original and mode(sb.env) == 0o640  # byte for byte, mode and all
    assert [p.name for p in sb.env.parent.iterdir()] == [".env"]
    assert TOKEN not in out and TOKEN not in str(error)


def test_a_symlinked_env_is_refused(sb):
    target = sb.tmp / "elsewhere.txt"
    target.write_text("untouched\n")
    sb.env.unlink()
    sb.env.symlink_to(target)
    out, error = sb.run()
    assert error is not None and target.read_text() == "untouched\n"


@pytest.mark.parametrize("user", USERS)
def test_hosts_yml_keeps_its_exact_format_and_is_private_from_creation(sb, user):
    out, error = sb.run()
    assert error is None
    file = sb.hosts(user)
    assert file.read_text() == f"github.com:\n    user: juanrubio\n    git_protocol: https\n    oauth_token: {TOKEN}\n"
    assert mode(file) == 0o600 and mode(file.parent) == 0o700 and mode(file.parent.parent) == 0o700  # .config too: created by the user's own umask
    assert (os.stat(file).st_uid, os.stat(file).st_gid) == (os.getuid(), os.getgid())
    assert not [p for p in file.parent.iterdir() if p.name != "hosts.yml"]  # no temporary file left behind


def test_the_token_reaches_the_child_writer_only_on_stdin(sb):
    sb.run()
    writer_calls = [(c, k) for c, k in sb.calls if c[:3] == ["sudo", "-H", "-u"] and c[4:5] == ["/usr/bin/python3"]]
    assert len(writer_calls) == 2
    for command, kwargs in writer_calls:
        assert TOKEN not in " ".join(command) and TOKEN not in str(kwargs.get("env", "")) and TOKEN in kwargs["input"]
    assert TOKEN not in " ".join(" ".join(c) for c, _ in sb.calls if c[:4] != ["sudo", "-H", "-u", "juan"])


def test_root_does_nothing_inside_the_agent_homes_itself(sb):
    sb.run()
    assert not [path for path in sb.chowns if str(sb.tmp / "homes") in path]  # no chown of agent paths as root


@pytest.mark.parametrize("user", USERS)
def test_an_existing_world_readable_hosts_yml_never_receives_the_secret_bytes(sb, user):
    folder = sb.homes[user] / ".config" / "gh"
    folder.mkdir(parents=True, mode=0o755)
    old = folder / "hosts.yml"
    old.write_text("github.com:\n    oauth_token: synthetic-previous\n")
    old.chmod(0o644)
    alias = sb.tmp / f"old-inode-{user}"
    os.link(old, alias)  # the previous inode stays reachable, so we can see whether it ever got the new secret
    sb.run()
    assert alias.read_text() == "github.com:\n    oauth_token: synthetic-previous\n"  # the old 0644 file never held the token
    assert TOKEN in old.read_text() and mode(old) == 0o600 and mode(folder) == 0o700
    assert os.stat(old).st_ino != os.stat(alias).st_ino


@pytest.mark.parametrize("user", USERS)
def test_a_symlinked_gh_directory_is_not_followed(sb, user):
    target = sb.tmp / f"planted-{user}"
    target.mkdir()
    config = sb.homes[user] / ".config"
    config.mkdir()
    (config / "gh").symlink_to(target)
    out, error = sb.run()
    assert error is not None  # refused
    assert list(target.iterdir()) == [] and mode(target) == mode(target)  # nothing was written into the planted target
    assert TOKEN not in out and TOKEN not in str(error)


@pytest.mark.parametrize("user", USERS)
def test_a_symlinked_hosts_yml_is_replaced_not_followed(sb, user):
    folder = sb.homes[user] / ".config" / "gh"
    folder.mkdir(parents=True)
    victim = sb.tmp / f"victim-{user}.txt"
    victim.write_text("do not touch\n")
    (folder / "hosts.yml").symlink_to(victim)
    sb.run()
    assert victim.read_text() == "do not touch\n"  # the link target never received the secret
    assert not (folder / "hosts.yml").is_symlink() and TOKEN in (folder / "hosts.yml").read_text()


def test_a_failed_git_setup_leaves_only_complete_files_and_no_temporary_files(sb):
    sb.fail_setup_git_for = "deckproductctl"
    out, error = sb.run()
    assert error is not None
    for user in USERS:
        folder = sb.hosts(user).parent
        assert not [p for p in folder.iterdir() if p.name != "hosts.yml"]
        if sb.hosts(user).exists():
            assert sb.hosts(user).read_text().endswith(f"oauth_token: {TOKEN}\n")
    assert [p.name for p in sb.env.parent.iterdir()] == [".env"]
    assert TOKEN not in out and TOKEN not in str(error)
