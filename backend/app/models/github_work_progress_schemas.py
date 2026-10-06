"""Public progress metadata contains no file names or private authority."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class GithubPublicationObservation(BaseModel):
    state: Literal["current", "historical", "unavailable"]
    observed_at: datetime | None = None
    local_sha: str | None = None
    published_sha: str | None = None
    unpublished_commits: int | None = None
    tracked_changes: int | None = None
    untracked_files: int | None = None
    relation: Literal["synchronized", "ahead", "behind", "diverged", "not_published", "unknown"] = "unknown"
    reason: str | None = None
    publication_first_observed_at: datetime | None = None
    publication_time_source: Literal["github_head_observation"] | None = None
    destination_url: str | None = None


class GithubWorkProgressResponse(BaseModel):
    work_item_id: int
    checked_at: datetime
    valid_until: datetime
    phase: str
    next_actor: Literal["owner", "leader", "operator", "controller", "none"]
    next_action: str
    next_poll_expected_at: datetime | None = None
    last_check_head: str | None = None
    publication: GithubPublicationObservation
