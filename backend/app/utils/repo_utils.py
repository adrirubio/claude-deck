"""Derive a stable repository identity from a working directory."""
import hashlib
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


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
