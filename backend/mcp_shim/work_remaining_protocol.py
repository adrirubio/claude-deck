"""Short public team reports. This protocol grants no execution authority."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import unicodedata
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

START = "<!-- deck:work-remaining:start -->"
END = "<!-- deck:work-remaining:end -->"
CONTEXT = "<!-- deck:work-remaining-context "
MAX_AGE = timedelta(hours=2)
_PRIVATE_TEXT = re.compile(
    r"(?:gh[pousr]_|github_pat_|sk-(?:or-v1-)?|bearer\s+|"
    r"(?:token|password|secret|credential)\s*[:=]|[a-f0-9]{16,})", re.I,
)


class ReportContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    work_item_id: int = Field(gt=0)
    dispatch_nonce: str = Field(min_length=1, max_length=100)
    owner_slot_id: int = Field(gt=0)
    scope_revision: int = Field(ge=0)
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    phase: str = Field(min_length=1, max_length=40)


class RemainingReport(ReportContext):
    reported_at: AwareDatetime
    reported_by: str = Field(min_length=1, max_length=80)
    remaining: str = Field(min_length=1, max_length=200)
    next_action: str = Field(min_length=1, max_length=160)
    effort_low_minutes: int | None = Field(default=None, ge=0, le=43200)
    effort_high_minutes: int | None = Field(default=None, ge=0, le=43200)
    confidence: Literal["unknown", "low", "medium", "high"] = "unknown"
    effort_scope: str = Field(default="", max_length=80)
    completed: str = Field(default="", max_length=200)
    assumptions: str = Field(default="", max_length=160)

    @field_validator("remaining", "next_action", "reported_by", "effort_scope", "completed", "assumptions")
    @classmethod
    def public_text(cls, value: str) -> str:
        if (value != value.strip() or any(unicodedata.category(c).startswith("C") for c in value)
                or any(c in value for c in "<>`%[]{}\\*") or _PRIVATE_TEXT.search(value)):
            raise ValueError("Use short public text without markup or private values")
        return value

    @model_validator(mode="after")
    def effort_range(self):
        low, high = self.effort_low_minutes, self.effort_high_minutes
        if low is None and high is None:
            if self.confidence != "unknown" or self.effort_scope:
                raise ValueError("Unknown effort has no range, confidence or scope")
        elif (low is None or high is None or low > high
              or self.confidence == "unknown" or not self.effort_scope):
            raise ValueError("A range requires ordered bounds, confidence and scope")
        return self

    def estimate(self) -> str:
        if self.effort_low_minutes is None:
            return "Unknown."
        low, high = self.effort_low_minutes, self.effort_high_minutes
        if low % 60 == high % 60 == 0 and high >= 60:
            amount = f"{low // 60}–{high // 60} hours"
        else:
            amount = f"{low}–{high} minutes"
        return f"About {amount} of active work ({self.confidence} confidence; {self.effort_scope})."

    def markdown(self) -> str:
        metadata = self.model_dump(mode="json", exclude={"remaining", "next_action"})
        return (f"{START}\n## Work remaining\n\n"
                f"- **Remaining:** {self.remaining}\n"
                f"- **Estimate:** {self.estimate()}\n"
                f"- **Next:** {self.next_action}\n\n"
                f"Updated UTC: {self.reported_at.astimezone(timezone.utc).isoformat()}\n"
                f"{CONTEXT}{json.dumps(metadata, separators=(',', ':'))} -->\n{END}")


def parse_report(body: object, private_values: tuple[str, ...] = ()) -> RemainingReport | None:
    """Read only an explicitly published block; never return the issue body."""
    if not isinstance(body, str) or len(body) > 65536:
        return None
    if body.count(START) != 1 or body.count(END) != 1:
        return None
    begin, end = body.index(START), body.index(END)
    if end <= begin:
        return None
    block = body[begin + len(START):end]
    lines = block.strip().splitlines()
    metadata = [line for line in lines if line.startswith(CONTEXT) and line.endswith(" -->")]
    if len(metadata) != 1 or len(metadata[0]) > 1500:
        return None
    labels = {}
    for label in ("Remaining", "Estimate", "Next"):
        prefix = f"- **{label}:** "
        matches = [line[len(prefix):] for line in lines if line.startswith(prefix)]
        if len(matches) != 1:
            return None
        labels[label] = matches[0]
    try:
        payload = json.loads(metadata[0][len(CONTEXT):-4])
        if not isinstance(payload, dict) or any(key in payload for key in ("remaining", "next_action")):
            return None
        payload.update(remaining=labels["Remaining"], next_action=labels["Next"])
        # JSON mode permits an ISO timestamp, while retaining strict numbers.
        report = RemainingReport.model_validate_json(json.dumps(payload))
        if labels["Estimate"] != report.estimate():
            return None
        # The helper's block is deliberately small. Extra prose, changed update
        # text, or a duplicate metadata field must not become a current report.
        if block.strip() != report.markdown()[len(START):-len(END)].strip():
            return None
        safe = json.dumps(report.model_dump(mode="json"))
        if any(value and value in safe for value in private_values):
            return None
        return report
    except (ValueError, TypeError):
        return None


def report_reason(report: RemainingReport, context: ReportContext | None, now: datetime) -> str | None:
    if context is None:
        return "source_unconfirmed"
    if any(getattr(report, key) != value for key, value in context.model_dump().items()):
        return "context_changed"
    age = now - report.reported_at
    if age < -timedelta(minutes=5) or age > MAX_AGE:
        return "report_expired"
    return None
