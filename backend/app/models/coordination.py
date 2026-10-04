"""Bounded, public-safe coordination contracts. Assessments grant no authority."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IssueNumber = Annotated[int, Field(gt=0, strict=True)]


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
