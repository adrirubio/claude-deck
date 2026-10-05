"""Derive a stable repository identity from a working directory."""
import hashlib
import logging
import os
import re
import subprocess
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_GITHUB_REPOSITORY_PATH = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def is_primary_github_checkout(cwd: str, owner: str, repo: str) -> bool:
    """Return whether cwd is the primary checkout for the requested GitHub repo.

    Git output is used only in memory. This function does not log or return a
    remote URL, filesystem path, credential, or command output.
    """
    path = os.path.realpath(os.path.expanduser(cwd or "."))

    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", path, *args],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            raise
        return result.stdout.strip() if result.returncode == 0 else None

    top_level = git("rev-parse", "--show-toplevel")
    git_dir = git("rev-parse", "--absolute-git-dir")
    common_dir = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    remote = git("remote", "get-url", "origin")
    if not top_level or not git_dir or not common_dir or not remote:
        return False
    if os.path.realpath(top_level) != path:
        return False
    if os.path.realpath(git_dir) != os.path.realpath(common_dir):
        return False

    remote_owner: str | None = None
    remote_repo: str | None = None
    if remote.startswith("git@github.com:"):
        match = _GITHUB_REPOSITORY_PATH.fullmatch(
            "/" + remote.removeprefix("git@github.com:")
        )
        if match:
            remote_owner, remote_repo = match.groups()
    else:
        parsed = urlsplit(remote)
        if (parsed.scheme in {"https", "ssh", "git"}
                and parsed.hostname == "github.com"
                and parsed.username in {None, "git"}
                and parsed.password is None
                and parsed.port is None
                and not parsed.query and not parsed.fragment):
            match = _GITHUB_REPOSITORY_PATH.fullmatch(parsed.path)
            if match:
                remote_owner, remote_repo = match.groups()
    return bool(
        remote_owner and remote_repo
        and remote_owner.casefold() == owner.strip().casefold()
        and remote_repo.casefold() == repo.strip().casefold()
    )


def derive_repo_identity(cwd: str) -> dict:
    """Return a stable repo identity for a working directory.

    Git worktrees share a common git directory, so hashing that path maps
    worktrees of the same repository to the same repo_id. Plain directories
    fall back to their normalized absolute path.
    """
    norm = os.path.realpath(os.path.expanduser(cwd or "."))
    anchor = norm
    repo_root = norm
    try:
        result = subprocess.run(
            ["git", "-C", norm, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            anchor = os.path.realpath(result.stdout.strip())
            repo_root = os.path.dirname(anchor) if anchor.endswith(f"{os.sep}.git") else anchor
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("git common-dir lookup failed for %s: %s", norm, exc)

    return {
        "repo_id": hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:16],
        "repo_root": repo_root,
        "repo_name": os.path.basename(repo_root) or repo_root,
    }
