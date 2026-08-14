import io
import json
import os
import subprocess
import urllib.error

from mcp_shim import git_credential_helper


class _Response:
    def __init__(self, status=200, body=None):
        self.status = status
        self._body = json.dumps(
            body or {"username": "x-access-token", "password": "short-lived"}
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def test_get_posts_git_fields_and_prints_only_credentials(monkeypatch, capsys):
    seen = []

    def urlopen(request, timeout):
        seen.append((request, timeout))
        return _Response()

    monkeypatch.setattr(git_credential_helper.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        git_credential_helper.sys,
        "stdin",
        io.StringIO("protocol=https\nhost=github.com\npath=owner/repo.git\n\n"),
    )

    result = git_credential_helper.main(
        ["--deck-url", "http://127.0.0.1:9123", "--lease", "lease-secret", "get"]
    )

    assert result == 0
    assert capsys.readouterr().out == (
        "username=x-access-token\npassword=short-lived\n\n"
    )
    request, timeout = seen[0]
    assert request.full_url.endswith("/api/v1/agent-teams/git-credential")
    assert timeout == 30
    assert json.loads(request.data) == {
        "workspace_token": "lease-secret",
        "protocol": "https",
        "host": "github.com",
        "path": "owner/repo.git",
    }


def test_non_get_operation_is_a_noop(monkeypatch, capsys):
    monkeypatch.setattr(
        git_credential_helper.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    monkeypatch.setattr(git_credential_helper.sys, "stdin", io.StringIO(""))

    assert git_credential_helper.main(
        ["--deck-url", "http://127.0.0.1:8000", "--lease", "secret", "store"]
    ) == 0
    assert capsys.readouterr().out == ""


def test_refusal_prints_no_password_or_secret(monkeypatch, capsys):
    def refused(*_args, **_kwargs):
        raise urllib.error.URLError("backend unavailable")

    monkeypatch.setattr(git_credential_helper.urllib.request, "urlopen", refused)
    monkeypatch.setattr(
        git_credential_helper.sys,
        "stdin",
        io.StringIO("protocol=https\nhost=github.com\npath=owner/repo.git\n"),
    )

    assert git_credential_helper.main(
        [
            "--deck-url",
            "http://127.0.0.1:8000",
            "--lease",
            "do-not-print-this",
            "get",
        ]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "password" not in captured.err
    assert "do-not-print-this" not in captured.err


def test_malformed_json_refuses_without_response_echo(monkeypatch, capsys):
    monkeypatch.setattr(
        git_credential_helper.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(body={"username": "x-access-token"}),
    )
    monkeypatch.setattr(git_credential_helper.sys, "stdin", io.StringIO("path=x\n"))

    assert git_credential_helper.main(
        ["--deck-url", "http://127.0.0.1:8000", "--lease", "secret", "get"]
    ) == 1
    assert capsys.readouterr().out == ""


def test_git_use_http_path_delivers_the_repository_path(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    capture = tmp_path / "capture"
    helper = tmp_path / "capture-helper"
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "data = sys.stdin.read()\n"
        "open(os.environ['CAPTURE'], 'w').write(data)\n"
        "print('username=test')\n"
        "print('password=test')\n"
    )
    helper.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "CAPTURE": str(capture),
    }
    subprocess.run(
        ["git", "init", str(repo)], env=env, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "config",
            "credential.https://github.com.useHttpPath",
            "true",
        ],
        cwd=repo,
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "config", "credential.https://github.com.helper", ""],
        cwd=repo,
        env=env,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "--add",
            "credential.https://github.com.helper",
            f"!{helper}",
        ],
        cwd=repo,
        env=env,
        check=True,
    )

    subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        env=env,
        input="url=https://github.com/owner/repo.git\n\n",
        text=True,
        check=True,
        capture_output=True,
    )
    assert "path=owner/repo.git" in capture.read_text()

    subprocess.run(
        [
            "git",
            "config",
            "--unset-all",
            "credential.https://github.com.useHttpPath",
        ],
        cwd=repo,
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        env=env,
        input="url=https://github.com/owner/repo.git\n\n",
        text=True,
        check=True,
        capture_output=True,
    )
    assert "path=" not in capture.read_text()
