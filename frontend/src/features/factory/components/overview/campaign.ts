import type { TeamCampaignSummary } from "@/types/agentTeams";

export function campaignHasContent(campaign: TeamCampaignSummary | undefined) {
  return Boolean(
    campaign &&
      (campaign.done_count + campaign.under_way_count + campaign.queued_count + (campaign.not_started_count ?? 0) > 0 ||
        campaign.decisions_ahead.length > 0),
  );
}
