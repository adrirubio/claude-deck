"""Public progress metadata contains no file names or private authority."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from mcp_shim.work_remaining_protocol import ReportContext


class GithubWorkRemainingView(BaseModel):
    state: Literal["current", "historical", "unavailable"] = "unavailable"
    remaining: str | None = None
    estimate: str | None = None
    next_action: str | None = None
    reported_at: datetime | None = None
    reported_by: str | None = None
    source_sha: str | None = None
    reason: Literal["report_missing", "report_invalid", "report_unavailable", "source_unconfirmed",
                    "context_changed", "report_expired"] | None = "report_missing"
    source_url: str | None = None
    completed: str | None = None
    assumptions: str | None = None


class GithubPublicationObservation(BaseModel):
    state: Literal["current", "historical", "unavailable"]
    observed_at: datetime | None = None
    local_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    published_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    unpublished_commits: int | None = Field(default=None, ge=0, le=10000)
    tracked_changes: int | None = Field(default=None, ge=0, le=200000)
    untracked_files: int | None = Field(default=None, ge=0, le=200000)
    relation: Literal["synchronized", "ahead", "behind", "diverged", "not_published", "unknown"] = "unknown"
    reason: Literal[
        "workspace_not_leased", "workspace_identity_unavailable", "git_unavailable",
        "invalid_git_observation", "observation_limit", "observation_timeout",
        "branch_not_assigned", "detached_head", "branch_mismatch", "remote_unavailable",
        "published_object_unavailable", "changed_during_read", "snapshot_unavailable",
        "ancestry_unavailable",
    ] | None = None
    file_counts_reason: Literal["safe_metadata_read"] = "safe_metadata_read"
    publication_first_observed_at: datetime | None = None
    publication_time_source: Literal["github_head_observation"] | None = None
    destination_url: str | None = None


class GithubWorkProgressResponse(BaseModel):
    work_item_id: int
    dispatch_nonce: str | None
    owner_slot_id: int | None
    checked_at: datetime
    valid_until: datetime
    phase: str
    next_actor: Literal["owner", "leader", "operator", "controller", "none"]
    next_action: str
    next_poll_expected_at: datetime | None = None
    last_check_head: str | None = None
    publication: GithubPublicationObservation
    remaining_work: GithubWorkRemainingView = Field(default_factory=GithubWorkRemainingView)
    remaining_work_context: ReportContext | None = None
