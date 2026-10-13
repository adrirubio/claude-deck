import { Link } from 'react-router-dom'
import { Edit, Play, Zap } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { anchor } from '@/features/factory/components/styles'
import { useObservation } from '@/features/factory/reads'
import type { WorkListResponse } from '@/types/factory'
import type { AgentTeamPreset, AgentTeamSummary, TeamGithubScopeListResponse } from '@/types/agentTeams'
import { autonomousLeaderSlotId } from './leaderSlot'
import { SupervisorStatus } from './SupervisorStatus'

/**
 * The first thing on a team page: what the team is, whether it runs, who leads
 * it and where its work and repositories are. It holds no form.
 */
export function TeamHeader({
  preset,
  onEdit,
  onPlan,
  planDisabled,
  onAutonomy,
}: {
  preset: AgentTeamPreset
  onEdit: () => void
  onPlan: () => void
  planDisabled: boolean
  // Opens the Autonomy tab at the existing switch. The switch itself stays there.
  onAutonomy: () => void
}) {
  const summary = useObservation<AgentTeamSummary>(`agent-teams/presets/${preset.id}/summary`).data
  const scopes = useObservation<TeamGithubScopeListResponse>(`agent-teams/presets/${preset.id}/github-scopes`).data
  const work = useObservation<WorkListResponse>(`factory/work-items?team_id=${preset.id}&limit=1`).data
  const leaderId = autonomousLeaderSlotId(preset.leader_slot_id ?? null, preset.slots)
  const leader = preset.slots.find((slot) => slot.id === leaderId)
  const items = work?.counts.total
  return (
    <header className="space-y-2" aria-label={`Team: ${preset.name}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-semibold">{preset.name}</h2>
          <span
            className={`rounded border px-2 text-xs font-medium ${preset.autonomy_enabled
              ? 'border-primary/60 text-primary'
              : 'border-border text-muted-foreground'}`}
          >
            {preset.autonomy_enabled ? 'Running' : 'Paused'}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={onAutonomy}>
            <Zap className="mr-2 h-4 w-4" />
            {preset.autonomy_enabled ? 'Turn off autonomy' : 'Turn on autonomy'}
          </Button>
          <Button onClick={onPlan} disabled={planDisabled}>
            <Play className="mr-2 h-4 w-4" />
            Plan launch
          </Button>
          <Button variant="outline" onClick={onEdit}>
            <Edit className="mr-2 h-4 w-4" />
            Edit team
          </Button>
        </div>
      </div>
      {preset.description && <p className="text-muted-foreground">{preset.description}</p>}
      <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <div className="flex items-center gap-1">
          <dt className="text-muted-foreground">Leader:</dt>
          <dd>{leader ? leader.display_name : 'none set'}</dd>
        </div>
        {summary && (
          <div className="flex items-center gap-1">
            <dt className="text-muted-foreground">Supervisor:</dt>
            <dd><SupervisorStatus summary={summary} /></dd>
          </div>
        )}
        {scopes && (
          <div className="flex items-center gap-1">
            <dt className="text-muted-foreground">Repositories:</dt>
            <dd>
              {scopes.scopes.length}{' '}
              <Link className={anchor} to="/repositories">Manage ›</Link>
            </dd>
          </div>
        )}
        {work && (
          <div className="flex items-center gap-1">
            <dt className="text-muted-foreground">Work:</dt>
            <dd>
              {items} {items === 1 ? 'item' : 'items'}, {work.counts.active} active{' '}
              <Link className={anchor} to={`/work?team_id=${preset.id}`}>View in Work ›</Link>
            </dd>
          </div>
        )}
      </dl>
    </header>
  )
}
