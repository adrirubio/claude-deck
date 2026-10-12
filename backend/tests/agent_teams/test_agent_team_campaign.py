"""Campaign data counts stored work and a fixed GitHub backlog."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.database import AgentTeamSlot, GithubWorkItem
from tests.agent_teams.test_agent_team_summary import Attention, seed, service


START = datetime(2026, 10, 12, 12, 0)


class Backlog:
    def __init__(self, issues, *, unavailable=False):
        self.issues = issues
        self.unavailable = unavailable
        self.calls = []

    async def get_issue(self, owner, repo, number):
        self.calls.append(("issue", owner, repo, number))
        if self.unavailable:
            raise OSError("GitHub unavailable")
        return {"number": number, "milestone": {"number": 7, "title": "Campaign"}}

    async def list_milestone_issues(self, owner, repo, milestone):
        self.calls.append(("issues", owner, repo, milestone))
        if self.unavailable:
            raise OSError("GitHub unavailable")
        return self.issues

    async def list_milestones(self, owner, repo):
        self.calls.append(("milestones", owner, repo))
        return [{"number": 7, "title": "Campaign"}]


def issue(number, title, *labels):
    return {"number": number, "title": title, "state": "open",
            "labels": [{"name": label} for label in labels]}


async def fixed_campaign(db, monkeypatch, statuses=("merged", "dispatched", "pending")):
    team, scope, items = await seed(db, statuses)
    scope.base_ref = "origin/release/v3.1"
    slot = await db.scalar(select(AgentTeamSlot).where(AgentTeamSlot.preset_id == team.id))
    slot.display_name = "B1 Backend implementer"
    slot.area_labels = ["area:backend"]
    for index, item in enumerate(items, 1):
        item.issue_title = f"Work {index}"
        item.dispatch_base_ref = scope.base_ref
        if item.dispatch_status == "merged":
            item.auto_merged_at = START + timedelta(minutes=index)
    await db.commit()
    summary, _ = service(monkeypatch)
    return team, scope, items, summary


async def observe_backlog(db, scope, summary, client):
    # The old summary has no campaign reader. Its response assertions fail first.
    campaign = getattr(summary, "campaign", None)
    if campaign is not None:
        await campaign.refresh_scope(db, scope, client)


@pytest.mark.asyncio
async def test_campaign_counts_open_merged_issues_and_excludes_parent(db, monkeypatch):
    team, scope, items, summary = await fixed_campaign(db, monkeypatch)
    client = Backlog([issue(1, "Done but open"), issue(2, "Active"), issue(3, "Admitted"),
                      issue(4, "Backend work", "area:backend"), issue(5, "Other work", "area:unknown"),
                      issue(506, "Parent campaign", "area:backend")])
    await observe_backlog(db, scope, summary, client)
    result = await summary.summary(db, team.id)
    campaign = result.campaign
    assert campaign.backlog_state == "available"
    assert campaign.done_count == 1
    assert campaign.latest_done[0].title == "Work 1"
    assert campaign.latest_done[0].merged_at == (START + timedelta(minutes=1)).replace(tzinfo=timezone.utc)
    assert campaign.under_way_count == 1
    assert campaign.under_way[0].owner_short_name == "B1"
    assert campaign.under_way[0].state_phrase == "building it"
    assert campaign.queued_count == 1
    assert campaign.not_started_count == 2
    assert {group.area: group.count for group in campaign.not_started_groups} == {"area:backend": 1, "Other": 1}
    payload = campaign.model_dump_json()
    assert "2026-10-12T12:01:00Z" in payload
    assert "Parent campaign" not in payload
    assert "private-" not in payload and "work_item_id" not in payload
    states = (await db.scalars(select(GithubWorkItem.dispatch_status).order_by(GithubWorkItem.id))).all()
    assert states == ["merged", "dispatched", "pending"]
    assert await db.scalar(select(GithubWorkItem.auto_merged_at).where(
        GithubWorkItem.issue_number == 1)) == START + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_unreadable_backlog_keeps_deck_counts_and_unknown_not_started(db, monkeypatch):
    team, scope, _, summary = await fixed_campaign(db, monkeypatch)
    await observe_backlog(db, scope, summary, Backlog([], unavailable=True))
    result = await summary.summary(db, team.id)
    assert result.campaign.backlog_state == "backlog unavailable"
    assert result.campaign.done_count == 1
    assert result.campaign.under_way_count == 1
    assert result.campaign.queued_count == 1
    assert result.campaign.not_started_count is None
    assert result.campaign.not_started_groups == []


@pytest.mark.asyncio
async def test_campaign_returns_latest_three_merges(db, monkeypatch):
    team, scope, _, summary = await fixed_campaign(db, monkeypatch, ("merged",) * 4)
    await observe_backlog(db, scope, summary, Backlog([issue(n, f"Work {n}") for n in range(1, 5)]))
    result = await summary.summary(db, team.id)
    assert result.campaign.done_count == 4
    assert [item.title for item in result.campaign.latest_done] == ["Work 4", "Work 3", "Work 2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("title,available", [("Campaign", True), ("No match", False)])
async def test_explicit_milestone_uses_exact_title(db, monkeypatch, title, available):
    team, scope, _, summary = await fixed_campaign(db, monkeypatch)
    team.backlog_milestone = title
    await db.commit()
    client = Backlog([issue(4, "Not started")])
    await observe_backlog(db, scope, summary, client)
    result = await summary.summary(db, team.id)
    assert result.campaign.backlog_state == ("available" if available else "backlog unavailable")
    assert ("milestones", "example", "repo") in client.calls
    assert not any(call[0] == "issue" for call in client.calls)
    assert result.campaign.not_started_count == (1 if available else None)


@pytest.mark.asyncio
async def test_poll_interval_cache_expires_and_configuration_invalidates(db, monkeypatch):
    team, scope, _, summary = await fixed_campaign(db, monkeypatch)
    from app.services.agent_team_campaign_service import AgentTeamCampaignService
    clock = [0.0]
    summary.campaign = AgentTeamCampaignService(interval_seconds=60, clock=lambda: clock[0])
    client = Backlog([issue(4, "Not started")])
    await summary.campaign.refresh_scope(db, scope, client)
    await summary.campaign.refresh_scope(db, scope, client)
    assert len(client.calls) == 2
    clock[0] = 61
    team_id, scope_id = team.id, scope.id
    result = await summary.summary(db, team_id)
    assert result.campaign.not_started_count is None
    team = await db.get(type(team), team_id)
    team.backlog_milestone = "No match"
    await db.commit()
    scope = await db.get(type(scope), scope_id)
    await summary.campaign.refresh_scope(db, scope, client)
    result = await summary.summary(db, team_id)
    assert result.campaign.backlog_state == "backlog unavailable"


@pytest.mark.asyncio
async def test_other_branch_merge_is_not_done_and_parent_is_never_counted(db, monkeypatch):
    team, scope, items, summary = await fixed_campaign(db, monkeypatch, ("merged", "merged", "pending"))
    items[0].dispatch_base_ref = "origin/another-branch"
    items[2].issue_number = 506
    await db.commit()
    await observe_backlog(db, scope, summary, Backlog([issue(1, "Other branch"), issue(2, "Done"), issue(506, "Parent")]))
    result = await summary.summary(db, team.id)
    assert result.campaign.done_count == 1
    assert result.campaign.queued_count == 0
    assert result.campaign.not_started_count == 0


@pytest.mark.asyncio
async def test_under_way_phrases_and_planned_decisions_are_plain(db, monkeypatch):
    team, scope, _, summary = await fixed_campaign(db, monkeypatch,
        ("dispatched", "verifying", "ready_for_review", "awaiting_human_review", "escalated"))
    team.planned_decisions = [{"text": "Decide promotion.", "state": "later"},
                              {"text": "Choose the trial.", "state": "now"},
                              {"text": "Approve the plan.", "state": "done"}]
    await db.commit()
    await observe_backlog(db, scope, summary, Backlog([issue(n, f"Work {n}") for n in range(1, 6)]))
    result = await summary.summary(db, team.id)
    assert result.campaign.under_way_count == 5
    assert [item.state_phrase for item in result.campaign.under_way] == [
        "building it", "waiting for checks", "reviewing it", "waiting for you", "waiting for you"]
    assert [(item.text, item.state) for item in result.campaign.decisions_ahead] == [
        ("Decide promotion.", "later"), ("Choose the trial.", "now"), ("Approve the plan.", "done")]
    assert "dispatched" not in result.campaign.model_dump_json()


@pytest.mark.asyncio
async def test_current_human_decisions_preserve_missing_action_details(db, monkeypatch):
    team, _, _ = await seed(db, ())
    class HumanActions(Attention):
        async def summary(self, db, preset_id):
            value = await super().summary(db, preset_id)
            value["actions"] = [
                {"scope_id": 1, "issue_number": 1, "kind": "scope_clarification",
                 "state": state, "source": "leader", "assessment_current": current,
                 "private_prompt": "private-human-action"}
                for state, current in [("requested", True), ("context_pending", True),
                                       ("historical", False), ("resolved", True)]]
            return value
    summary, _ = service(monkeypatch, attention=HumanActions())
    result = await summary.summary(db, team.id)
    assert [(decision.text, decision.state) for decision in result.campaign.decisions_ahead] == [
        ("Clarify the work scope.", "now"), ("Complete the action details.", "now")]
    assert "private-" not in result.campaign.model_dump_json()


@pytest.mark.asyncio
async def test_empty_milestone_field_uses_parent_milestone(db, monkeypatch):
    team, scope, _, summary = await fixed_campaign(db, monkeypatch)
    from app.models.schemas import AgentTeamPresetUpdate
    team.backlog_milestone = AgentTeamPresetUpdate(backlog_milestone="  ").backlog_milestone
    await db.commit()
    client = Backlog([issue(4, "Not started")])
    await observe_backlog(db, scope, summary, client)
    result = await summary.summary(db, team.id)
    assert result.campaign.not_started_count == 1
    assert client.calls == [("issue", "example", "repo", 506), ("issues", "example", "repo", 7)]
