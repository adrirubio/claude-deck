"""#919: every prompt that explains the continuation phases uses one wording, and it does not call a permanent
change 'restoration'."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.database import MailMessage
from app.services.agent_mail_service import agent_mail_service
from app.services.continuation_phase_guidance import PHASE_GUIDANCE
from app.services.github_approval_service import github_approval_service
from app.services.github_dispatch_service import github_dispatch_service
from tests.agent_teams.test_github_dispatch_service import (  # noqa: F401  (fixtures and helpers shared with the dispatch tests)
    _isolate_agent_mail_nudges, _recoverable_escalated_item, db, host_has_enough_memory, no_discovered_panes,
)

DOCS = Path(__file__).resolve().parents[3] / "docs" / "api" / "agent-mail.md"


def test_the_shared_wording_separates_temporary_diagnostics_from_changes_that_stay():
    assert "Temporary diagnostic changes" in PHASE_GUIDANCE and "`diagnostic`" in PHASE_GUIDANCE
    assert "`revert_diagnostic_changes`" in PHASE_GUIDANCE
    assert "stays in the PR" in PHASE_GUIDANCE and "re-adding tests or code" in PHASE_GUIDANCE
    assert "`implementation`" in PHASE_GUIDANCE
    assert "`push_pr_head`" in PHASE_GUIDANCE and "`request_verification`" in PHASE_GUIDANCE
    assert "restoration" not in PHASE_GUIDANCE.lower()


def test_the_leader_decision_prompt_carries_the_shared_wording():
    prompt = github_approval_service.continuation_leader_decision_nudge_prompt(
        SimpleNamespace(request_message_id=14186, work_item_id=175), SimpleNamespace(revision=3))
    assert PHASE_GUIDANCE in prompt
    assert "restoration" not in prompt.lower()
    assert "synth_city_decide_continuation" in prompt  # the rest of the prompt is unchanged


@pytest.mark.asyncio
async def test_the_recovery_proposal_message_and_nudge_carry_the_shared_wording(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    monkeypatch.setattr(settings, "github_nudge_grace_seconds", 0)
    _preset, slots, scope, item, _workspace, owner, _session = await _recoverable_escalated_item(db)
    item.escalation_reason = "retry_count_exhausted"
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **kwargs):
        nudges.append(kwargs)

    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "merged_at": None}

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)
    monkeypatch.setattr("app.services.github_dispatch_service.github_client.get_pull", get_pull)

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    message = (await db.execute(select(MailMessage).where(
        MailMessage.recipient_member_id == owner.id,
        MailMessage.subject.like("Recovery proposal requested:%")))).scalars().one()
    assert PHASE_GUIDANCE in message.body_markdown
    assert len(nudges) == 1 and PHASE_GUIDANCE in nudges[0]["nudge_prompt"]
    for text in (message.body_markdown, nudges[0]["nudge_prompt"]):
        assert "restoration" not in text.lower()
        assert "read-only diagnosis" in text  # the rest of each text is unchanged


def test_the_docs_describe_both_phases_with_one_example_each():
    text = DOCS.read_text()
    assert "### Continuation phases" in text
    section = text.split("### Continuation phases", 1)[1].split("\n### ", 1)[0]
    assert PHASE_GUIDANCE in section
    diagnostic = [line for line in section.splitlines() if line.startswith("- **Example, `diagnostic`")]
    implementation = [line for line in section.splitlines() if line.startswith("- **Example, `implementation`")]
    assert len(diagnostic) == 1 and "`revert_diagnostic_changes`" in diagnostic[0]
    assert len(implementation) == 1 and "`push_pr_head`" in implementation[0] and "`request_verification`" in implementation[0]
