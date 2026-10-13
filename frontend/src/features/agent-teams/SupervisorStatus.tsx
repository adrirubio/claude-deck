import type { AgentTeamSummary } from '@/types/agentTeams'
import { supervisorWords, type SupervisorChip } from './supervisorText'

const CHIP_STYLE: Record<SupervisorChip, string> = {
  None: 'border-border text-muted-foreground',
  Healthy: 'border-primary/60 text-primary',
  Late: 'border-amber-500/70 text-amber-800 dark:text-amber-300',
  Absent: 'border-destructive/70 text-destructive',
}

// The word is always shown, so colour is never the only signal.
export function SupervisorStatus({ summary }: { summary: AgentTeamSummary }) {
  const observation = summary.supervisor_observation
  if (!observation) return <>{summary.supervisor === 'none' ? 'None, not required.' : summary.supervisor}</>
  // The server's own clock, so a wrong clock in the browser changes nothing.
  const { chip, detail } = supervisorWords(observation, Date.parse(summary.checked_at))
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className={`rounded border px-2 text-xs font-medium ${CHIP_STYLE[chip]}`}>{chip}</span>
      <span className="text-muted-foreground">{detail}</span>
    </span>
  )
}
