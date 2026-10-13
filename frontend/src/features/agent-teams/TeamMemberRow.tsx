import { useState } from 'react'
import { ChevronDown, ChevronRight, MoreHorizontal } from 'lucide-react'

import { AgentStatusBadges } from '@/components/shared/AgentStatusBadges'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { harnesses } from '@/features/factory/filterHelpers'
import { getTeamSlotColorClasses } from '@/lib/agentTeamColors'
import { cn } from '@/lib/utils'
import type { AgentStatus } from '@/types/agentStatus'
import type { AgentTeamSlot } from '@/types/agentTeams'

export interface MemberActions {
  onLaunch: () => void
  onEdit: () => void
  onSetLeader: (() => void) | null
  onMove: (direction: -1 | 1) => void
  onDelete: () => void
}

/** One compact row. The charter and the technical fields show only when the row is expanded. */
export function TeamMemberRow({
  slot,
  isLeader,
  first,
  last,
  status,
  actions,
}: {
  slot: AgentTeamSlot
  isLeader: boolean
  first: boolean
  last: boolean
  status: AgentStatus | null | undefined
  actions: MemberActions
}) {
  const [expanded, setExpanded] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const colors = getTeamSlotColorClasses(slot.ui_color)
  const harness = (harnesses as Record<string, string>)[slot.provider] ?? slot.provider
  const model = slot.launch_options?.model
  const detailsId = `member-details-${slot.id}`
  const choose = (action: () => void) => () => {
    setMenuOpen(false)
    action()
  }
  return (
    <li className={cn('rounded-lg border', colors.card)}>
      <div className="flex flex-wrap items-center gap-3 px-3 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={`Details for ${slot.display_name}`}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" /> : <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />}
          <span className="truncate font-semibold">{slot.display_name}</span>
          {isLeader && <Badge variant="outline" title="This slot has the explicit Leader assignment.">Leader</Badge>}
          {!slot.enabled && <Badge variant="secondary">Disabled</Badge>}
        </button>
        <span className="text-sm text-muted-foreground">{harness}{model ? ` · ${model}` : ''}</span>
        <span className="min-w-24 text-sm">{slot.role || 'Unassigned'}</span>
        <AgentStatusBadges status={status} compact />
        <div className="relative">
          <Button
            variant="outline"
            size="sm"
            aria-label={`Actions for ${slot.display_name}`}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((value) => !value)}
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
          {menuOpen && (
            <div
              role="menu"
              aria-label={`Actions for ${slot.display_name}`}
              className="absolute right-0 top-full z-20 mt-1 grid w-40 gap-1 rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
              onKeyDown={(event) => { if (event.key === 'Escape') setMenuOpen(false) }}
            >
              <Button role="menuitem" variant="ghost" size="sm" className="justify-start" disabled={!slot.enabled} onClick={choose(actions.onLaunch)}>Launch</Button>
              <Button role="menuitem" variant="ghost" size="sm" className="justify-start" onClick={choose(actions.onEdit)}>Edit</Button>
              {actions.onSetLeader && (
                <Button role="menuitem" variant="ghost" size="sm" className="justify-start" onClick={choose(actions.onSetLeader)}>Set Leader</Button>
              )}
              <Button role="menuitem" variant="ghost" size="sm" className="justify-start" disabled={first} onClick={choose(() => actions.onMove(-1))}>Move up</Button>
              <Button role="menuitem" variant="ghost" size="sm" className="justify-start" disabled={last} onClick={choose(() => actions.onMove(1))}>Move down</Button>
              <Button role="menuitem" variant="ghost" size="sm" className="justify-start text-destructive" onClick={choose(actions.onDelete)}>Delete</Button>
            </div>
          )}
        </div>
      </div>
      {expanded && (
        <div id={detailsId} className="grid gap-3 border-t px-3 py-3 text-sm md:grid-cols-2">
          {slot.charter && (
            <div className="md:col-span-2">
              <p className="text-xs uppercase text-muted-foreground">Charter</p>
              <p className="mt-1 whitespace-pre-wrap">{slot.charter}</p>
            </div>
          )}
          <div>
            <p className="text-xs uppercase text-muted-foreground">Folder</p>
            <p className="mt-1 break-all">{slot.repo_path}</p>
          </div>
          <div>
            <p className="text-xs uppercase text-muted-foreground">Repo</p>
            <p className="mt-1">{slot.repo_name}</p>
          </div>
          <div>
            <p className="text-xs uppercase text-muted-foreground">Session</p>
            <p className="mt-1">{slot.launch_mode}</p>
          </div>
          <div>
            <p className="text-xs uppercase text-muted-foreground">Writing style</p>
            <p className="mt-1">{slot.controlled_language_enabled === false ? 'Own writing style' : 'ASD-STE100'}</p>
          </div>
          {slot.ui_color && (
            <div>
              <p className="text-xs uppercase text-muted-foreground">Colour</p>
              <Badge variant="outline" className={cn('mt-1', colors.badge)}>{slot.ui_color}</Badge>
            </div>
          )}
          {(slot.area_labels?.length || slot.expertise) && (
            <div className="md:col-span-2 rounded-md border border-primary/20 bg-primary/5 p-3">
              <p className="text-xs uppercase text-muted-foreground">GitHub dispatch routing</p>
              {slot.area_labels && slot.area_labels.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {slot.area_labels.map((label) => <Badge key={label} variant="secondary">{label}</Badge>)}
                </div>
              ) : (
                <p className="mt-2">{isLeader ? 'None (the Leader routes this slot)' : 'None'}</p>
              )}
              {slot.expertise && (
                <>
                  <p className="mt-3 text-xs uppercase text-muted-foreground">Expertise</p>
                  <p className="mt-1 text-muted-foreground">{slot.expertise}</p>
                </>
              )}
            </div>
          )}
          {slot.warnings && slot.warnings.length > 0 && (
            <div className="md:col-span-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-800 dark:text-amber-300">
              {slot.warnings.join('; ')}
            </div>
          )}
        </div>
      )}
    </li>
  )
}
