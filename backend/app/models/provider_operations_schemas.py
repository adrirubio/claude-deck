"""Safe observational provider operations, independent of native CLI flags."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OPERATION_KEYS = frozenset({
    "launch", "observe_session", "mail_identity", "receive_work", "report_work_status",
    "approval_participation", "workspace_association", "resume_exact", "interactive_terminal",
    "execution_controls",
})


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Operation(WireModel):
    state: Literal["supported", "conditional", "unsupported", "unknown"]
    reason: str
    conditions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class NativeSurface(WireModel):
    state: Literal["available", "unavailable", "unknown"]
    adapter_id: str | None = None
    access: Literal["none", "read_only", "read_write"] = "none"
    reason: str
    conditions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_access(self):
        if self.state != "available" and (self.adapter_id is not None or self.access != "none"):
            raise ValueError("Unavailable native surfaces grant no adapter or access")
        if self.state == "available" and (not self.adapter_id or self.access == "none"):
            raise ValueError("Available native surfaces require an adapter and access")
        return self


class Check(WireModel):
    state: Literal["ready", "blocked", "unknown"]
    code: str
    reason: str
    source: str


class Configuration(WireModel):
    state: Literal["ready", "blocked", "unknown"]
    checks: list[Check]


class CredentialReadiness(WireModel):
    state: Literal["ready", "blocked", "unknown"] = "unknown"
    reason: str = "Credentials not checked; configuration does not prove model access."
    source: str | None = None
    observed_at: datetime | None = None


class SessionReadiness(WireModel):
    state: Literal["bound", "offline", "ambiguous", "unknown"] = "unknown"
    reason: str = "No team slot selected; a generic provider card cannot establish a worker binding."
    team_id: int | None = None
    slot_id: int | None = None
    member_id: int | None = None
    session_id: int | None = None
    observed_provider: str | None = None


class Readiness(WireModel):
    configuration: Configuration
    credentials: CredentialReadiness = Field(default_factory=CredentialReadiness)
    session: SessionReadiness = Field(default_factory=SessionReadiness)
    observed_at: datetime
    observation_started_at: datetime | None = None
    probe_state: Literal["observed", "pending", "failed"] = "observed"
    cache_ttl_seconds: int = 60
    request_wait_seconds: int = 2
    aggregate_probe_seconds: int = 90


class ProviderOperations(WireModel):
    schema_version: Literal[1] = 1
    provider: str
    provider_display_name: str
    operations: dict[str, Operation]
    native_capabilities: dict[str, dict[str, str]]
    native_surfaces: dict[str, NativeSurface]
    readiness: Readiness

    @model_validator(mode="after")
    def complete_operations(self):
        if set(self.operations) != OPERATION_KEYS:
            raise ValueError("Operations must contain the ten reviewed contract keys")
        return self
