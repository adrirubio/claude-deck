"""Three short public lines; no inferred progress or authority."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from pydantic import ValidationError

from mcp_shim.work_remaining_protocol import RemainingReport, ReportContext, parse_report, report_reason

NOW = datetime(2026, 10, 6, 20, tzinfo=timezone.utc)
CONTEXT = dict(work_item_id=1, dispatch_nonce="dispatch", owner_slot_id=2,
               scope_revision=0, source_sha="a" * 40, phase="implementation")


def report(**changes):
    return RemainingReport(**{**CONTEXT, "reported_at": NOW, "reported_by": "Team member 2",
        "remaining": "Fix the interface, then review and merge.", "next_action": "B2 publishes the next checkpoint.", **changes})


def test_three_line_round_trip_unknown_and_qualified_range():
    unknown = report()
    assert parse_report("Issue facts\n" + unknown.markdown() + "\nOther facts") == unknown
    assert unknown.estimate() == "Unknown."
    measured = report(effort_low_minutes=30, effort_high_minutes=60, confidence="low",
                      effort_scope="interface corrections", assumptions="No new review findings.",
                      completed="The data service is complete.")
    assert parse_report(measured.markdown()) == measured
    assert measured.estimate() == "About 30–60 minutes of active work (low confidence; interface corrections)."
    assert sum(line.startswith("- **") for line in measured.markdown().splitlines()) == 3
    assert report(effort_low_minutes=60, effort_high_minutes=120, confidence="medium", effort_scope="corrections").estimate().startswith("About 1–2 hours")


@pytest.mark.parametrize("changes", [
    {"remaining": "Finished 90%"}, {"remaining": "password=private"},
    {"remaining": "sk-or-v1-example"}, {"next_action": "[Click](https://example.invalid)"},
    {"remaining": "a\u202eb"}, {"completed": "x" * 201},
    {"effort_low_minutes": True, "effort_high_minutes": 60, "confidence": "low", "effort_scope": "fixes"},
    {"effort_low_minutes": 30}, {"confidence": "high"},
    {"effort_low_minutes": 60, "effort_high_minutes": 30, "confidence": "low", "effort_scope": "fixes"},
])
def test_bounded_plain_text_and_estimate_contract(changes):
    with pytest.raises(ValidationError):
        report(**changes)


def test_rejects_duplicate_tampered_or_private_blocks():
    block = report().markdown()
    for invalid in (None, block * 2, block.replace("Unknown.", "Tomorrow."),
                    block.replace("Updated UTC:", "Update:"), block.replace("## Work remaining", "## Work remaining\nExtra prose"),
                    block.replace('"scope_revision":0', '"scope_revision":0,"scope_revision":0'),
                    "x" * 65536 + block):
        assert parse_report(invalid) is None
    assert parse_report(report(remaining="private-lease-value").markdown(), ("private-lease-value",)) is None


@pytest.mark.parametrize("key,value", [("work_item_id", 3), ("dispatch_nonce", "new"), ("owner_slot_id", 3),
    ("scope_revision", 1), ("source_sha", "b" * 40), ("phase", "review")])
def test_context_change_is_historical(key, value):
    changed = ReportContext(**{**CONTEXT, key: value})
    assert report_reason(report(), changed, NOW) == "context_changed"


def test_missing_source_expiry_and_future_time():
    context = ReportContext(**CONTEXT)
    assert report_reason(report(), context, NOW) is None
    assert report_reason(report(), None, NOW) == "source_unconfirmed"
    assert report_reason(report(), context, NOW + timedelta(hours=2, seconds=1)) == "report_expired"
    assert report_reason(report(reported_at=NOW + timedelta(minutes=6)), context, NOW) == "report_expired"
    payload = report().model_dump(mode="json")
    payload["reported_at"] = "2026-10-06T20:00:00"
    with pytest.raises(ValidationError):
        RemainingReport.model_validate_json(json.dumps(payload))
