"""Current summaries replace their own block and preserve issue requirements."""
from datetime import datetime, timezone
import hashlib

import pytest
from pydantic import ValidationError

from mcp_shim.github_summary_protocol import CurrentSummary, START, END, render_summary


def summary(**changes):
    return CurrentSummary(**{**dict(goal="Record delivery results.", status="Working",
        completed="The first checkpoint is published.", remaining="Complete the correction batch and review.",
        next_action="The owner publishes the complete candidate.", human_action="No action is required.",
        reported_at=datetime(2026, 10, 7, 14, tzinfo=timezone.utc)), **changes})


def test_inserts_one_summary_and_preserves_original_requirements():
    body = "## Requirements\n\nOriginal human scope.\n<!-- deck:operator-actions:start -->\nRecords\n<!-- deck:operator-actions:end -->\n"
    result = render_summary(body, summary())
    assert result["body_markdown"] == summary().markdown() + "\n\n" + body
    assert result["source_body_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert result["body_markdown"].count(START) == 1


def test_replaces_only_owned_block_and_repeated_render_is_unchanged():
    prefix, suffix = "Human requirements\n\n", "\n\nForeign history stays.\n"
    body = prefix + summary().markdown() + suffix
    newer = summary(status="Awaiting review", completed="The complete candidate is published.")
    result = render_summary(body, newer, expected_body_sha256=hashlib.sha256(body.encode()).hexdigest())
    assert result["body_markdown"] == prefix + newer.markdown() + suffix
    assert not render_summary(result["body_markdown"], newer)["changed"]


@pytest.mark.parametrize("body", [START, END, END + START, START + END + START + END,
    "```\n" + START + END, "<!--\n" + START + END,
    START + "<!-- deck:operator-actions:start -->" + END])
def test_ambiguous_or_hidden_markers_are_refused(body):
    with pytest.raises(ValueError):
        render_summary(body, summary())


def test_changed_body_and_oversized_body_are_refused():
    with pytest.raises(ValueError, match="body_changed"):
        render_summary("Human changed requirements", summary(), expected_body_sha256="0" * 64)
    with pytest.raises(ValueError, match="body_invalid"):
        render_summary("x" * 65537, summary())
    with pytest.raises(ValueError, match="rendered_body_too_large"):
        render_summary("x" * 65535, summary())


@pytest.mark.parametrize("changes", [{"goal": "password=private"}, {"completed": "ghp_private"},
    {"next_action": "hidden\u202evalue"}, {"human_action": "[Link](private)"},
    {"effort_low_minutes": True}, {"effort_low_minutes": 60}, {"confidence": "high"},
    {"effort_low_minutes": 120, "effort_high_minutes": 60, "confidence": "low", "effort_scope": "repairs"}])
def test_private_text_and_unqualified_effort_are_refused(changes):
    with pytest.raises(ValidationError):
        summary(**changes)


def test_effort_and_waiting_are_separate_and_unknown_is_explicit():
    assert summary().estimate() == "Unknown."
    measured = summary(effort_low_minutes=180, effort_high_minutes=300, confidence="low",
                       effort_scope="corrections", waiting="Review and CI waits are not estimated.")
    text = measured.markdown()
    assert "3–5 hours of active work" in text
    assert "**Waiting:** Review and CI waits are not estimated." in text
    assert "**Human action:** No action is required." in text
