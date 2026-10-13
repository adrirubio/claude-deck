import { CampaignProgress } from '@/features/factory/components/overview/CampaignProgress'
import { useObservation } from '@/features/factory/reads'
import type { AgentTeamPreset, AgentTeamSummary } from '@/types/agentTeams'

/** The Progress row of the Overview, for this team only. It reads the shared team summary. */
export function TeamProgress({ preset }: { preset: AgentTeamPreset }) {
  const summary = useObservation<AgentTeamSummary>(`agent-teams/presets/${preset.id}/summary`).data
  return <CampaignProgress presets={[preset]} summaries={[summary]} />
}
