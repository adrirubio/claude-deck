"""Bounded, public-safe coordination contracts. Assessments grant no authority."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IssueNumber = Annotated[int, Field(gt=0, strict=True)]


class CoordinationHumanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["review_pr", "merge_pr", "pilot_decision", "milestone_acceptance", "provide_evidence", "scope_clarification", "inspect_attempt", "inspect_checkpoint"]
    readiness: Literal["requested", "waiting_for_prerequisites"]
    pull_request_number: IssueNumber | None = None
    expected_head_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    prerequisite_issue_numbers: list[IssueNumber] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def references(self):
        if len(set(self.prerequisite_issue_numbers)) != len(self.prerequisite_issue_numbers):
            raise ValueError("Prerequisite references must be unique")
        if self.kind in {"review_pr", "merge_pr"}:
            if self.pull_request_number is None or self.expected_head_sha is None:
                raise ValueError("PR actions require a PR number and exact expected head")
        elif self.pull_request_number is not None or self.expected_head_sha is not None:
            raise ValueError("Only PR actions accept PR identity fields")
        return self


class CoordinationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, strict=True)
    enabled: bool = False
    issue_numbers: list[IssueNumber] = Field(default_factory=list, max_length=32)
    fallback_seconds: int = Field(default=1800, ge=300, le=86400, strict=True)
    max_daily_requests: int = Field(default=12, ge=1, le=48, strict=True)

    @model_validator(mode="after")
    def assigned_issues(self):
        if any(type(n) is not int or n <= 0 for n in self.issue_numbers):
            raise ValueError("Issue numbers must be positive integers")
        if len(set(self.issue_numbers)) != len(self.issue_numbers):
            raise ValueError("Issue numbers must be unique")
        if self.enabled and not self.issue_numbers:
            raise ValueError("Select assigned issues before enabling coordination")
        return self


class CoordinationDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_number: int = Field(gt=0, strict=True)
    disposition: Literal[
        "eligible", "dependency_blocked", "human_decision_blocked",
        "resource_blocked", "completed", "needs_scope_clarification", "standing",
    ]
    reason: Literal[
        "admission", "dependency", "m1a_acceptance", "pilot_decision",
        "m1b_acceptance", "authority_prerequisite", "human_merge", "review_evidence",
        "resource", "owner", "scope_clarification", "complete", "standing", "unknown",
    ]
    required_actor: Literal["leader", "operator", "owner", "reviewer", "none"]
    evidence_issue_numbers: list[IssueNumber] = Field(min_length=1, max_length=32)
    human_actions: list[CoordinationHumanAction] = Field(default_factory=list, max_length=4)

    @property
    def operator_decision_required(self) -> bool:
        """Keep a reported human decision distinct from Leader coordination."""
        return self.disposition != "completed" and (
            self.disposition == "human_decision_blocked"
            or self.reason in {"m1a_acceptance", "m1b_acceptance", "pilot_decision"}
            or any(action.kind in {"milestone_acceptance", "pilot_decision"} for action in self.human_actions)
        )

    @model_validator(mode="after")
    def evidence(self):
        if any(type(n) is not int or n <= 0 for n in self.evidence_issue_numbers):
            raise ValueError("Evidence must reference positive assigned issue numbers")
        if len(set(self.evidence_issue_numbers)) != len(self.evidence_issue_numbers):
            raise ValueError("Evidence references must be unique")
        if self.disposition == "eligible" and (
            self.reason != "admission" or self.required_actor != "leader"
        ):
            raise ValueError("Eligible work requires explicit Leader admission")
        return self


class CoordinationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(gt=0, strict=True)
    request_sequence: int = Field(ge=0, strict=True)
    snapshot_token: str | None = Field(default=None, min_length=1, max_length=2048)
    entries: list[CoordinationDisposition] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def bounded_human_actions(self):
        actions = [(entry.issue_number, action) for entry in self.entries for action in entry.human_actions]
        if len(actions) > 16 or len({a.pull_request_number for _, a in actions if a.pull_request_number}) > 8:
            raise ValueError("At most 16 human actions and eight PRs per assessment")
        keys = [(a.kind, a.pull_request_number or issue) for issue, a in actions]
        if len(set(keys)) != len(keys):
            raise ValueError("Human actions must be unique")
        return self


class OperatorActionContextPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[CoordinationDisposition] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def bounded_actions(self):
        actions = [(e.issue_number, a) for e in self.entries for a in e.human_actions]
        if (not actions or len(actions) > 16
            or len({a.pull_request_number for _, a in actions if a.pull_request_number}) > 8
            or len({(a.kind, a.pull_request_number or number) for number, a in actions}) != len(actions)):
            raise ValueError("Prepare one to sixteen unique actions and at most eight PRs")
        if len({e.issue_number for e in self.entries}) != len(self.entries):
            raise ValueError("Issue entries must be unique")
        return self
