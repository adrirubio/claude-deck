import type { TeamCampaignSummary } from "@/types/agentTeams";

export function campaignHasContent(campaign: TeamCampaignSummary | undefined) {
  return Boolean(
    campaign &&
      (campaign.done_count + campaign.under_way_count + campaign.queued_count + (campaign.not_started_count ?? 0) > 0 ||
        campaign.decisions_ahead.length > 0),
  );
}

export function campaignBarLabel(c: TeamCampaignSummary) {
  const known = c.backlog_state === "available";
  const todo = c.queued_count + (c.not_started_count ?? 0);
  return `${c.done_count} done, ${c.under_way_count} under way, ${todo} still to do, backlog ${known ? "known" : "unknown"}`;
}
