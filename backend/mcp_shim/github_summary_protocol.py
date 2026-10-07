"""Render one short current summary. This module grants no authority."""
from __future__ import annotations

from datetime import timezone
import hashlib
import re
from typing import Literal
import unicodedata

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

START = "<!-- deck:current-summary:start -->"
END = "<!-- deck:current-summary:end -->"
MAX_BODY = 65536
_PRIVATE = re.compile(r"(?:gh[pousr]_|github_pat_|sk-(?:or-v1-)?|bearer\s+|"
                      r"(?:token|password|secret|credential)\s*[:=]|[a-f0-9]{16,})", re.I)


class CurrentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    goal: str = Field(min_length=1, max_length=240)
    status: Literal["Working", "Checking", "Awaiting review", "Blocked", "Complete"]
    completed: str = Field(min_length=1, max_length=240)
    remaining: str = Field(min_length=1, max_length=240)
    next_action: str = Field(min_length=1, max_length=200)
    human_action: str = Field(min_length=1, max_length=240)
    waiting: str = Field(default="Not estimated.", min_length=1, max_length=160)
    effort_low_minutes: int | None = Field(default=None, ge=0, le=43200)
    effort_high_minutes: int | None = Field(default=None, ge=0, le=43200)
    confidence: Literal["unknown", "low", "medium", "high"] = "unknown"
    effort_scope: str = Field(default="", max_length=80)
    source_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    reported_at: AwareDatetime

    @field_validator("goal", "completed", "remaining", "next_action", "human_action", "waiting", "effort_scope")
    @classmethod
    def public_text(cls, value: str) -> str:
        if (value != value.strip() or any(unicodedata.category(c).startswith("C") for c in value)
                or any(c in value for c in "<>`%[]{}\\*") or _PRIVATE.search(value)):
            raise ValueError("Use short public text without markup or private values")
        return value

    @model_validator(mode="after")
    def qualified_effort(self):
        low, high = self.effort_low_minutes, self.effort_high_minutes
        if low is None and high is None:
            if self.confidence != "unknown" or self.effort_scope:
                raise ValueError("Unknown effort has no range, confidence or scope")
        elif (low is None or high is None or low > high
              or self.confidence == "unknown" or not self.effort_scope):
            raise ValueError("Use an ordered active-effort range with confidence and scope")
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
        lines = [START, "## Current summary", "", self.goal, "",
                 f"- **Status:** {self.status}", f"- **Done:** {self.completed}",
                 f"- **Remaining:** {self.remaining}", f"- **Estimate:** {self.estimate()}",
                 f"- **Waiting:** {self.waiting}", f"- **Next:** {self.next_action}",
                 f"- **Human action:** {self.human_action}", ""]
        if self.source_sha:
            lines.append(f"Checkpoint: `{self.source_sha}`.")
        lines.extend([f"Updated UTC: {self.reported_at.astimezone(timezone.utc).isoformat()}", END])
        return "\n".join(lines)


def render_summary(body: str, summary: CurrentSummary, *, expected_body_sha256: str | None = None) -> dict:
    """Replace only this renderer's block. Preserve every byte outside it."""
    if not isinstance(body, str) or len(body) > MAX_BODY:
        raise ValueError("body_invalid")
    observed = hashlib.sha256(body.encode()).hexdigest()
    if expected_body_sha256 is not None and expected_body_sha256 != observed:
        raise ValueError("body_changed")
    starts, ends = body.count(START), body.count(END)
    if starts != ends or starts > 1:
        raise ValueError("summary_markers_ambiguous")
    if starts:
        begin, finish = body.index(START), body.index(END)
        prefix = body[:begin]
        if (finish < begin or begin > 4096 or (prefix and not prefix.endswith("\n"))
                or prefix.count("```") % 2 or prefix.count("~~~") % 2
                or prefix.count("<!--") != prefix.count("-->")
                or re.search(r"<(?!\!--)[^>]+>", prefix)):
            raise ValueError("summary_markers_invalid")
        old = body[begin:finish + len(END)]
        # Another Deck section inside this block belongs to another writer.
        if "<!-- deck:" in old[len(START):-len(END)]:
            raise ValueError("summary_contains_foreign_section")
        rendered = prefix + summary.markdown() + body[finish + len(END):]
    else:
        rendered = summary.markdown() + ("\n\n" + body if body else "\n")
    if len(rendered) > MAX_BODY:
        raise ValueError("rendered_body_too_large")
    return {"body_markdown": rendered, "source_body_sha256": observed,
            "rendered_body_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "changed": rendered != body}
