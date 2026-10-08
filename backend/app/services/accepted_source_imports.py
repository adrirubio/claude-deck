"""An accepted import explains exact tree differences; it grants no edit scope."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    GithubAcceptedSourceImport, GithubApprovalRequest, GithubAttemptScopeRevision,
    GithubWorkItem, GithubWorkspace, TeamGithubScope,
)
from app.services.factory_delivery_policy import (
    effective_policy, policy_context, policy_context_conditions, required_check_blockers,
)
from app.services.github_approval_service import github_approval_service
from app.services.github_client import GithubClient, GithubTreeEntry, github_client


class SourceImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    expected_dispatch_nonce: str = Field(min_length=1, max_length=200)
    expected_scope_revision: int = Field(gt=0)
    expected_baseline_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    expected_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    accepted_pull_number: int = Field(gt=0)
    accepted_source_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    accepted_merge_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    paths: list[str] = Field(min_length=1, max_length=64)

    @field_validator("paths")
    @classmethod
    def bounded_paths(cls, paths):
        for path in paths:
            parts = PurePosixPath(path).parts
            if (not path or len(path) > 500 or path.startswith("/") or "\\" in path
                    or any(ord(c) < 32 for c in path) or ".." in parts
                    or str(PurePosixPath(path)) != path):
                raise ValueError("A source import requires an exact relative file path")
        if len(set(paths)) != len(paths):
            raise ValueError("Source import paths must be distinct")
        return sorted(paths)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fields(value, names):
    result = {}
    for name in names:
        field = value.get(name) if isinstance(value, Mapping) else getattr(value, name)
        if name == "acknowledged_at" and isinstance(field, str):
            field = datetime.fromisoformat(field)
        if isinstance(field, datetime):
            field = field.isoformat()
        if name == "enabled":
            field = bool(field)
        if name in {"allowed_paths", "allowed_actions", "allowed_commands", "prohibited_actions",
                    "tool_fallbacks", "delivery_policy"} and isinstance(field, str):
            field = json.loads(field)
        result[name] = deepcopy(field)
    return result


def source_import_context(item, revision, workspace, scope):
    """Only immutable authority binds an import across normal submission/retry."""
    return digest({
        "item": fields(item, ("id", "scope_id", "dispatch_nonce", "owner_slot_id",
                             "active_scope_revision", "pr_number", "delivery_policy",
                             "delivery_policy_revision")),
        "revision": fields(revision, ("id", "work_item_id", "dispatch_nonce", "revision",
            "owner_slot_id", "owner_member_id", "phase", "execution_target", "allowed_paths",
            "allowed_actions", "allowed_commands", "prohibited_actions", "tool_fallbacks",
            "baseline_head_sha", "baseline_tree_sha", "acknowledged_at", "expected_workspace_id",
            "expected_lease_token_hash", "max_failed_heads", "approval_request_id")),
        "workspace": fields(workspace, ("id", "path", "leased_item_id", "enabled",
                                      "leased_owner_pid", "leased_owner_proc_start")),
        "scope": fields(scope, ("id", "preset_id", "repo_owner", "repo_name", "base_ref")),
    })


def file_identity(tree: Mapping[str, GithubTreeEntry], path: str):
    entry = tree.get(path)
    if entry is None:
        return None
    if entry.object_type == "tree":
        raise ValueError("source_import_file_required")
    return [entry.mode, entry.object_type, entry.sha]


def verified_import_snapshots(baseline, current, accepted, allowed_paths, paths):
    snapshots = {}
    for path in paths:
        value = file_identity(current, path)
        if (github_approval_service.path_is_allowed(path, allowed_paths)
                or file_identity(baseline, path) == value
                or file_identity(accepted, path) != value):
            raise ValueError("source_import_content_mismatch")
        snapshots[path] = value
    return snapshots


def import_record_values(item, revision, workspace, scope, *, operation_id,
                         request_sha256, accepted_pull_number, accepted_source_sha,
                         accepted_merge_sha, observed_head_sha, path_snapshots):
    item_fields = fields(item, ("id",))
    revision_fields = fields(revision, ("id",))
    scope_fields = fields(scope, ("repo_owner", "repo_name"))
    return dict(operation_id=operation_id, work_item_id=item_fields["id"],
        scope_revision_id=revision_fields["id"],
        context_sha256=source_import_context(item, revision, workspace, scope),
        request_sha256=request_sha256,
        accepted_repository=scope_fields["repo_owner"] + "/" + scope_fields["repo_name"],
        accepted_pull_number=accepted_pull_number, accepted_source_sha=accepted_source_sha,
        accepted_merge_sha=accepted_merge_sha, observed_head_sha=observed_head_sha,
        path_snapshots=path_snapshots)


def scoped_pull(value, scope, number, head):
    """Malformed or foreign responses cannot establish import authority."""
    if not isinstance(value, dict):
        return False
    base, source = value.get("base"), value.get("head")
    if not isinstance(base, dict) or not isinstance(source, dict):
        return False
    repository = base.get("repo")
    name = repository.get("full_name") if isinstance(repository, dict) else None
    return (type(value.get("number")) is int and value["number"] == number
            and source.get("sha") == head
            and base.get("ref") == scope.base_ref.removeprefix("origin/")
            and isinstance(name, str)
            and name.lower() == f"{scope.repo_owner}/{scope.repo_name}".lower())


def source_import_claim_conditions(item, revision, workspace, scope):
    """Freeze the same authority as the record before any external read."""
    context_rows = [
        (GithubWorkItem, item, ("id", "scope_id", "dispatch_nonce", "owner_slot_id",
                              "active_scope_revision", "pr_number")),
        (GithubAttemptScopeRevision, revision, ("id", "work_item_id", "dispatch_nonce", "revision",
            "owner_slot_id", "owner_member_id", "phase", "execution_target", "allowed_paths",
            "allowed_actions", "allowed_commands", "prohibited_actions", "tool_fallbacks",
            "baseline_head_sha", "baseline_tree_sha", "acknowledged_at", "expected_workspace_id",
            "expected_lease_token_hash", "max_failed_heads", "approval_request_id")),
        (GithubWorkspace, workspace, ("id", "path", "leased_item_id", "enabled",
                                      "leased_owner_pid", "leased_owner_proc_start")),
        (TeamGithubScope, scope, ("id", "preset_id", "repo_owner", "repo_name", "base_ref")),
    ]
    result = []
    for model, row, names in context_rows:
        predicates = [getattr(model, key) == (getattr(row, key) if key == "acknowledged_at" else value)
                      for key, value in fields(row, names).items()]
        if model is GithubWorkspace:
            predicates.append(GithubWorkspace.lease_token == workspace.lease_token)
        if model is GithubWorkItem:
            result.extend(predicates)
        else:
            result.append(exists(select(model.id).where(*predicates)))
    result.extend(policy_context_conditions(policy_context(item)))
    return result


async def matching_imported_paths(db: AsyncSession, item, revision, workspace, scope,
                                 current, changed_paths, current_head_sha, *, client, token):
    identity = source_import_context(item, revision, workspace, scope)
    records = (await db.scalars(select(GithubAcceptedSourceImport).where(
        GithubAcceptedSourceImport.work_item_id == item.id,
        GithubAcceptedSourceImport.scope_revision_id == revision.id,
        GithubAcceptedSourceImport.context_sha256 == identity,
    ).limit(65))).all()
    if len(records) > 64:
        raise ValueError("source_import_read_limit")
    matched = set()
    checked = {}
    for record in records:
        if record.context_sha256 != identity:
            continue
        paths = {p for p in changed_paths if p in record.path_snapshots
                 and file_identity(current, p) == record.path_snapshots[p]}
        if not paths:
            continue
        key = record.accepted_merge_sha
        if key not in checked:
            checked[key] = await client.is_commit_ancestor(
                scope.repo_owner, scope.repo_name, key, current_head_sha, token=token)
        if not checked[key]:
            continue
        matched.update(paths)
    return matched


async def register_source_import(db: AsyncSession, item: GithubWorkItem,
                                 scope: TeamGithubScope, request: SourceImportRequest,
                                 *, client: GithubClient | None = None):
    client = client or github_client
    revision = await db.scalar(select(GithubAttemptScopeRevision).where(
        GithubAttemptScopeRevision.work_item_id == item.id,
        GithubAttemptScopeRevision.dispatch_nonce == request.expected_dispatch_nonce,
        GithubAttemptScopeRevision.revision == request.expected_scope_revision,
    ))
    workspace = await db.scalar(select(GithubWorkspace).where(
        GithubWorkspace.leased_item_id == item.id))
    if (item.dispatch_status != "dispatched" or item.dispatch_nonce != request.expected_dispatch_nonce
            or item.active_scope_revision != request.expected_scope_revision or revision is None
            or revision.status != "active" or revision.phase != "implementation"
            or revision.owner_slot_id != item.owner_slot_id or not revision.acknowledged_at
            or revision.baseline_head_sha != request.expected_baseline_head
            or workspace is None or not workspace.enabled
            or workspace.id != revision.expected_workspace_id or not workspace.lease_token
            or not github_approval_service.lease_token_matches(
                workspace.lease_token, revision.expected_lease_token_hash)):
        raise ValueError("source_import_context_changed")
    approval = await db.get(GithubApprovalRequest, revision.approval_request_id) if revision.approval_request_id else None
    if (approval is None or approval.status != "approved"
            or approval.request_kind != "continuation" or approval.scope_revision_id != revision.id
            or approval.work_item_id != item.id or approval.dispatch_nonce != item.dispatch_nonce
            or approval.owner_member_id != revision.owner_member_id):
        raise ValueError("source_import_approval_required")
    context_hash = source_import_context(item, revision, workspace, scope)
    request_hash = digest(request.model_dump())
    old = await db.scalar(select(GithubAcceptedSourceImport).where(
        GithubAcceptedSourceImport.operation_id == request.operation_id))
    if old:
        if (old.work_item_id != item.id or old.scope_revision_id != revision.id
                or old.context_sha256 != context_hash or old.request_sha256 != request_hash):
            raise ValueError("source_import_replay_conflict")
        return {"status": "already_recorded", "import_id": old.id}
    count = (await db.scalars(select(GithubAcceptedSourceImport.id).where(
        GithubAcceptedSourceImport.work_item_id == item.id,
        GithubAcceptedSourceImport.scope_revision_id == revision.id,
        GithubAcceptedSourceImport.context_sha256 == context_hash).limit(64))).all()
    if len(count) >= 64:
        raise ValueError("source_import_read_limit")
    frozen_revision = fields(revision, ("id", "status", "work_item_id", "dispatch_nonce", "revision",
        "phase", "execution_target", "baseline_head_sha", "baseline_tree_sha",
        "allowed_paths", "allowed_actions", "allowed_commands", "prohibited_actions", "tool_fallbacks",
        "owner_slot_id", "owner_member_id", "expected_workspace_id", "expected_lease_token_hash",
        "approval_request_id", "max_failed_heads"))
    frozen_revision["acknowledged_at"] = revision.acknowledged_at
    frozen_policy = policy_context(item)
    frozen_item = fields(item, ("id", "scope_id", "dispatch_nonce", "owner_slot_id",
                               "active_scope_revision", "pr_number"))
    frozen_workspace = fields(workspace, ("id", "path", "leased_item_id", "enabled",
                                         "leased_owner_pid", "leased_owner_proc_start"))
    frozen_scope = fields(scope, ("id", "preset_id", "repo_owner", "repo_name", "base_ref"))
    frozen_approval = fields(approval, ("id", "status", "request_kind", "scope_revision_id",
                                       "work_item_id", "dispatch_nonce", "owner_member_id"))
    record_values = import_record_values(
        item, revision, workspace, scope, operation_id=request.operation_id,
        request_sha256=request_hash, accepted_pull_number=request.accepted_pull_number,
        accepted_source_sha=request.accepted_source_sha, accepted_merge_sha=request.accepted_merge_sha,
        observed_head_sha=request.expected_head, path_snapshots={})
    lease = workspace.lease_token
    policy = effective_policy(item, scope)
    token = await github_approval_service.github_read_token(scope)
    owner_name, repo = scope.repo_owner, scope.repo_name
    accepted = await client.get_pull(owner_name, repo, request.accepted_pull_number, token=token)
    if (not scoped_pull(accepted, scope, request.accepted_pull_number, request.accepted_source_sha)
            or accepted.get("merged") is not True
            or accepted.get("merge_commit_sha") != request.accepted_merge_sha):
        raise ValueError("source_import_accepted_pull_changed")
    pull = await client.get_pull(owner_name, repo, frozen_item["pr_number"], token=token)
    def current_pull(value):
        return (scoped_pull(value, scope, frozen_item["pr_number"], request.expected_head)
                and value.get("state") == "open")
    if not current_pull(pull):
        raise ValueError("source_import_head_changed")
    for ancestor in (revision.baseline_head_sha, request.accepted_merge_sha):
        if not await client.is_commit_ancestor(owner_name, repo, ancestor, request.expected_head, token=token):
            raise ValueError("source_import_ancestry_required")
    snapshot = await client.get_commit_snapshot(owner_name, repo, request.expected_head, token=token)
    merged = await client.get_commit_snapshot(owner_name, repo, request.accepted_merge_sha, token=token)
    baseline = await client.get_recursive_tree(owner_name, repo, revision.baseline_tree_sha, token=token)
    current = await client.get_recursive_tree(owner_name, repo, snapshot.tree_sha, token=token)
    accepted_tree = await client.get_recursive_tree(owner_name, repo, merged.tree_sha, token=token)
    paths = verified_import_snapshots(baseline, current, accepted_tree, revision.allowed_paths, request.paths)
    checks = await client.list_check_runs_for_ref(owner_name, repo, request.accepted_source_sha, token=token)
    if required_check_blockers(policy, checks, request.accepted_source_sha):
        raise ValueError("source_import_checks_required")
    confirmed = await client.get_pull(owner_name, repo, frozen_item["pr_number"], token=token)
    if not current_pull(confirmed):
        raise ValueError("source_import_head_changed")
    revision_guard = [getattr(GithubAttemptScopeRevision, key) == value
                      for key, value in frozen_revision.items()]
    claimed = await db.execute(update(GithubWorkItem).where(
        *(getattr(GithubWorkItem, key) == value for key, value in frozen_item.items()),
        GithubWorkItem.dispatch_status == "dispatched",
        *policy_context_conditions(frozen_policy),
        select(func.count(GithubAcceptedSourceImport.id)).where(
            GithubAcceptedSourceImport.work_item_id == item.id,
            GithubAcceptedSourceImport.scope_revision_id == revision.id,
            GithubAcceptedSourceImport.context_sha256 == context_hash).scalar_subquery() < 64,
        exists(select(GithubAttemptScopeRevision.id).where(*revision_guard)),
        exists(select(GithubApprovalRequest.id).where(
            *(getattr(GithubApprovalRequest, key) == value for key, value in frozen_approval.items()))),
        exists(select(GithubWorkspace.id).where(
            *(getattr(GithubWorkspace, key) == value for key, value in frozen_workspace.items()),
            GithubWorkspace.lease_token == lease)),
        exists(select(TeamGithubScope.id).where(
            *(getattr(TeamGithubScope, key) == value for key, value in frozen_scope.items()))),
    ).values(updated_at=GithubWorkItem.updated_at).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        raise ValueError("source_import_context_changed")
    record_values["path_snapshots"] = paths
    record = GithubAcceptedSourceImport(**record_values)
    db.add(record)
    await db.commit()
    return {"status": "recorded", "import_id": record.id, "paths": sorted(paths)}
