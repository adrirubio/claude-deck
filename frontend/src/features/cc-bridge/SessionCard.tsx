import { Trash2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CLICKABLE_CARD } from '@/lib/constants'
import { getTeamSlotColorClasses } from '@/lib/agentTeamColors'
import { cn } from '@/lib/utils'
import type { CCSession } from './types'
import type { InstanceIdentity } from '@/types/status'

interface SessionCardProps {
  session: CCSession
  gridPosition: number | null
  onClick: () => void
  onKill: (session: CCSession) => void
  instance?: InstanceIdentity | null
}

function normalizeLabel(value: string | null | undefined) {
  return (value ?? '').trim().toLowerCase().replace(/[\s_-]+/g, ' ')
}

export function SessionCard({ session, gridPosition, onClick, onKill, instance }: SessionCardProps) {
  const projectName = session.cwd.split('/').pop() || session.cwd
  const isActive = gridPosition !== null
  const teamSlotLabel = session.team_slot_name?.trim()
  const teamRoleLabel = session.team_slot_role?.trim()
  const teamName = session.team_preset_name?.trim()
  const colorClasses = getTeamSlotColorClasses(session.team_slot_color)
  const primaryLabel = teamSlotLabel || session.session_name
  const showRole = Boolean(
    teamRoleLabel && normalizeLabel(teamRoleLabel) !== normalizeLabel(teamSlotLabel)
  )
  const showProject = !teamName || normalizeLabel(projectName) !== normalizeLabel(teamName)
  const contextLine = teamName
    ? `${teamName}${showProject ? ` · ${projectName}` : ''}`
    : projectName
  const contextTitle = teamName
    ? `Team: ${teamName}${showProject ? ` · Repo: ${projectName}` : ''}`
    : session.cwd

  return (
    <Card
      className={cn(
        CLICKABLE_CARD,
        colorClasses.card,
        isActive && 'border-primary bg-primary/5'
      )}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      tabIndex={0}
      role="button"
    >
      <CardContent className="p-3">
        <div className="flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-2">
            {session.team_slot_color && (
              <span
                className={cn('h-2 w-2 shrink-0 rounded-full', colorClasses.dot)}
                title={`Slot color: ${session.team_slot_color}`}
              />
            )}
            <span
              className="truncate text-sm font-medium"
              title={teamSlotLabel ? `${session.session_name} · ${session.tmux_target}` : session.tmux_target}
            >
              {primaryLabel}
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground/50 hover:text-destructive transition-colors"
              onClick={(e) => { e.stopPropagation(); onKill(session) }}
              onKeyDown={(e) => e.stopPropagation()}
              title="Kill session"
              aria-label={`Kill ${primaryLabel}`}
            >
              <Trash2 className="h-3 w-3" />
            </button>
            {isActive ? (
              <span className="h-5 w-5 flex items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                {gridPosition + 1}
              </span>
            ) : (
              <span className="h-2 w-2 rounded-full bg-green-500" />
            )}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Badge variant="outline" className="max-w-full truncate">
            {session.provider_display_name}
          </Badge>
          {showRole && (
            <Badge variant="secondary" className="max-w-full truncate" title={`Role: ${teamRoleLabel}`}>
              {teamRoleLabel}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground truncate mt-1" title={contextTitle}>
          {contextLine}
        </p>
        <p
          className="text-xs text-muted-foreground mt-0.5 truncate"
          title={instance ? `${instance.name} · tmux: ${session.tmux_target}` : session.tmux_target}
        >
          {instance ? `${instance.name} · ` : ''}tmux: {session.tmux_target}
        </p>
      </CardContent>
    </Card>
  )
}
