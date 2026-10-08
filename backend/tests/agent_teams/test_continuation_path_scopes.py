"""Explicit directory scopes preserve the meaning of exact file approvals."""
import pytest

from app.services.accepted_source_imports import verified_import_snapshots
from app.services.github_approval_service import GithubApprovalError, github_approval_service
from app.services.github_client import GithubTreeEntry
from app.services.github_verification_service import GithubVerificationService


def test_directory_scope_canonicalization_keeps_the_trailing_slash():
    assert github_approval_service._canonical_paths(
        ["docs/", "README.md", "docs/", "assets/images/"]
    ) == ["README.md", "assets/images/", "docs/"]


@pytest.mark.parametrize("path", ["/", "./", "../", "docs//", "docs/../", "docs/./", "docs/**", "/docs/", "docs\\images/"])
def test_directory_scope_refuses_noncanonical_paths(path):
    with pytest.raises(GithubApprovalError, match="allowed_paths_invalid"):
        github_approval_service._canonical_paths([path])


@pytest.mark.parametrize(
    ("path", "scope", "allowed"),
    [
        ("docs/index.md", "docs/", True),
        ("docs/guide/install.md", "docs/", True),
        ("docs/.vitepress/config.ts", "docs/", True),
        ("new-directory/new.md", "new-directory/", True),
        ("docs-old/index.md", "docs/", False),
        ("docs", "docs/", False),
        ("README.md", "docs/", False),
        ("docs/index.md", "docs", False),
        ("docs/index.md", "docs/index.md", True),
        ("docs/index.md/child", "docs/index.md", False),
    ],
)
def test_exact_files_and_explicit_subtrees_have_distinct_authority(path, scope, allowed):
    assert github_approval_service.path_is_allowed(path, [scope]) is allowed


def test_directory_scope_covers_additions_deletions_and_mode_changes():
    def entry(path, mode="100644", sha="a"):
        return GithubTreeEntry(path=path, mode=mode, object_type="blob", sha=sha * 40)

    baseline = {e.path: e for e in [entry("docs/old.md"), entry("docs/mode.md")]}
    current = {e.path: e for e in [entry("docs/new/nested.md"), entry("docs/mode.md", "100755")]}
    changed = GithubVerificationService._changed_tree_paths(baseline, current)
    assert changed == {"docs/old.md", "docs/new/nested.md", "docs/mode.md"}
    assert all(github_approval_service.path_is_allowed(p, ["docs/"]) for p in changed)


def test_import_records_cannot_relabel_files_already_in_an_approved_directory():
    path = "docs/index.md"
    baseline = {path: GithubTreeEntry(path, "100644", "blob", "a" * 40)}
    accepted = {path: GithubTreeEntry(path, "100644", "blob", "b" * 40)}
    with pytest.raises(ValueError, match="source_import_content_mismatch"):
        verified_import_snapshots(baseline, accepted, accepted, ["docs/"], [path])
    assert path in verified_import_snapshots(baseline, accepted, accepted, ["docs"], [path])
