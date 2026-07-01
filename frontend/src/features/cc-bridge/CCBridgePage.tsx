import { useState, useEffect, useCallback, useMemo } from 'react'
import { AlertTriangle, MonitorPlay, Monitor } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'
import { TeamLanesView } from './TeamLanesView'
import { LeaderHintOverlay } from './LeaderHintOverlay'
import { NewSessionDialog } from './NewSessionDialog'
import { KillSessionDialog } from './KillSessionDialog'
import type { CCSession, LeaderNavigationDirection } from './types'
import { useProviderContext } from '@/contexts/ProviderContext'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import type { AgentProviderId, AgentProviderStatus } from '@/types/providers'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

const MAX_GRID_PANES = 4
type ProviderFilter = 'all' | AgentProviderId
type TeamFilter = 'all' | number
type LayoutMode =
  | { kind: 'grid' }
  | { kind: 'single'; target: string }
  | { kind: 'lanes'; teamId: number }

interface TeamFilterOption {
  id: number
  name: string
  count: number
}

const PROVIDER_FILTERS: { value: ProviderFilter; label: string }[] = [
  { value: 'all', label: 'All agents' },
  { value: 'claude-code', label: 'Claude Code' },
  { value: 'codex-cli', label: 'Codex' },
  { value: 'copilot-cli', label: 'Copilot' },
  { value: 'opencode-cli', label: 'OpenCode' },
]

function addTarget(prev: string[], target: string): string[] {
  if (prev.includes(target)) return prev
  if (prev.length >= MAX_GRID_PANES) return prev
  return [...prev, target]
}

function slotOrderValue(session: CCSession): number {
  if (typeof session.team_slot_position === 'number') return session.team_slot_position
  return typeof session.team_slot_id === 'number' ? session.team_slot_id : Number.MAX_SAFE_INTEGER
}

function compareTeamLaneSessions(a: CCSession, b: CCSession): number {
  const slotOrder = slotOrderValue(a) - slotOrderValue(b)
  if (slotOrder !== 0) return slotOrder
  const roleOrder = (a.team_slot_role ?? '').localeCompare(b.team_slot_role ?? '')
  if (roleOrder !== 0) return roleOrder
  const nameOrder = (a.team_slot_name ?? '').localeCompare(b.team_slot_name ?? '')
  if (nameOrder !== 0) return nameOrder
  return a.tmux_target.localeCompare(b.tmux_target)
}

export function CCBridgePage() {
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>('all')
  const [teamFilter, setTeamFilter] = useState<TeamFilter>('all')
  const { providers, selectedProviderId } = useProviderContext()
  const status = useSystemStatus()
  const instance = status?.instance ?? null
  const { sessions, loading, error, refresh } = useCCSessions()
  const [activeTargets, setActiveTargets] = useState<string[]>([])
  const [layoutMode, setLayoutMode] = useState<LayoutMode>({ kind: 'grid' })
  const [focusedTarget, setFocusedTarget] = useState<string | null>(null)
  const [leaderHintTarget, setLeaderHintTarget] = useState<string | null>(null)
  const [newSessionOpen, setNewSessionOpen] = useState(false)
  const [killSession, setKillSession] = useState<CCSession | null>(null)

  const isFullscreen = layoutMode.kind !== 'grid'
  const laneTeamId = layoutMode.kind === 'lanes' ? layoutMode.teamId : null
  const sessionsByTarget = useMemo(
    () => new Map(sessions.map((session) => [session.tmux_target, session])),
    [sessions]
  )

  const providersById = useMemo(() => providers.reduce<Partial<Record<AgentProviderId, AgentProviderStatus>>>((acc, provider) => {
    acc[provider.id] = provider
    return acc
  }, {}), [providers])

  const teamOptions = useMemo<TeamFilterOption[]>(() => {
    const teams = new Map<number, TeamFilterOption>()
    for (const session of sessions) {
      if (typeof session.team_preset_id !== 'number') continue
      const current = teams.get(session.team_preset_id)
      if (current) {
        current.count += 1
      } else {
        teams.set(session.team_preset_id, {
          id: session.team_preset_id,
          name: session.team_preset_name ?? `Team ${session.team_preset_id}`,
          count: 1,
        })
      }
    }
    return [...teams.values()].sort((a, b) => a.name.localeCompare(b.name))
  }, [sessions])

  const teamFilterAvailable = teamFilter === 'all' || teamOptions.some((team) => team.id === teamFilter)
  const effectiveTeamFilter = teamFilterAvailable ? teamFilter : 'all'

  const visibleSessions = useMemo(() => sessions.filter((session) => (
    (providerFilter === 'all' || session.provider === providerFilter)
    && (effectiveTeamFilter === 'all' || session.team_preset_id === effectiveTeamFilter)
  )), [effectiveTeamFilter, providerFilter, sessions])

  const selectedTeamLabel = effectiveTeamFilter === 'all'
    ? null
    : teamOptions.find((team) => team.id === effectiveTeamFilter)?.name ?? `Team ${effectiveTeamFilter}`

  const laneTeamLabel = laneTeamId === null
    ? null
    : teamOptions.find((team) => team.id === laneTeamId)?.name ?? `Team ${laneTeamId}`

  const teamLanes = useMemo(() => {
    if (laneTeamId === null) return { sessions: [], overflowCount: 0 }
    const teamSessions = sessions
      .filter((session) => session.team_preset_id === laneTeamId)
      .sort(compareTeamLaneSessions)
    return {
      sessions: teamSessions.slice(0, MAX_GRID_PANES),
      overflowCount: Math.max(0, teamSessions.length - MAX_GRID_PANES),
    }
  }, [laneTeamId, sessions])

  const displayedTargets = useMemo(() => {
    if (layoutMode.kind === 'lanes') return teamLanes.sessions.map((session) => session.tmux_target)
    if (layoutMode.kind === 'single') return [layoutMode.target]
    return activeTargets
  }, [activeTargets, layoutMode, teamLanes.sessions])

  const canProviderSpawn = (provider: AgentProviderStatus | undefined) => (
    Boolean(provider?.installed)
    && provider?.capability_details?.spawn?.state !== 'unsupported'
    && provider?.capability_details?.spawn?.state !== 'read_only'
    && provider?.capabilities.spawn === true
  )

  const selectedFilterProvider = providerFilter === 'all' ? null : providersById[providerFilter]
  const canCreateSession = providerFilter === 'all'
    ? providers.some(canProviderSpawn)
    : canProviderSpawn(selectedFilterProvider ?? undefined)
  const agentCliWarning = status?.environment?.agent_cli_warning ?? null
  const createDisabledReason = providerFilter === 'all'
    ? agentCliWarning ?? 'No installed provider can launch sessions.'
    : !selectedFilterProvider
      ? 'Provider metadata is not available.'
      : !selectedFilterProvider.installed
        ? selectedFilterProvider.unavailable_reason ?? `${selectedFilterProvider.display_name} is not installed.`
        : selectedFilterProvider.capability_details?.spawn?.reason
          ?? `${selectedFilterProvider.display_name} cannot launch sessions from Agent Bridge.`

  const filterCounts: Record<ProviderFilter, number> = {
    all: sessions.length,
    'claude-code': sessions.filter((session) => session.provider === 'claude-code').length,
    'codex-cli': sessions.filter((session) => session.provider === 'codex-cli').length,
    'copilot-cli': sessions.filter((session) => session.provider === 'copilot-cli').length,
    'opencode-cli': sessions.filter((session) => session.provider === 'opencode-cli').length,
  }

  const initialDialogProvider = providerFilter === 'all' ? selectedProviderId : providerFilter

  useEffect(() => {
    if (teamFilterAvailable) return
    const resetId = window.setTimeout(() => setTeamFilter('all'), 0)
    return () => window.clearTimeout(resetId)
  }, [teamFilterAvailable])

  const applyTeamFilter = useCallback((nextTeamFilter: TeamFilter) => {
    setTeamFilter(nextTeamFilter)
    if (nextTeamFilter === 'all') {
      setLayoutMode((cur) => (cur.kind === 'lanes' ? { kind: 'grid' } : cur))
      return
    }
    const sessionInSelectedTeam = (target: string) => (
      sessionsByTarget.get(target)?.team_preset_id === nextTeamFilter
    )
    setActiveTargets((prev) => prev.filter(sessionInSelectedTeam))
    setLayoutMode((cur) => {
      if (cur.kind === 'lanes' && cur.teamId !== nextTeamFilter) return { kind: 'grid' }
      if (cur.kind === 'single' && !sessionInSelectedTeam(cur.target)) return { kind: 'grid' }
      return cur
    })
    setFocusedTarget((cur) => (cur && !sessionInSelectedTeam(cur) ? null : cur))
  }, [sessionsByTarget])

  const openTeamLanes = useCallback(() => {
    if (effectiveTeamFilter === 'all') return
    setLayoutMode({ kind: 'lanes', teamId: effectiveTeamFilter })
    setFocusedTarget(null)
  }, [effectiveTeamFilter])

  const exitFullscreen = useCallback(() => {
    setLayoutMode({ kind: 'grid' })
  }, [])

  const handleLeaderNavigate = useCallback((sourceTarget: string, direction: LeaderNavigationDirection) => {
    setFocusedTarget(sourceTarget)
    const sourceIndex = displayedTargets.indexOf(sourceTarget)
    if (sourceIndex === -1) return

    if (typeof direction === 'number') {
      const target = displayedTargets[direction - 1]
      if (target) setFocusedTarget(target)
      return
    }

    if (displayedTargets.length === 0) return
    const delta = direction === 'next' ? 1 : -1
    const nextIndex = (sourceIndex + delta + displayedTargets.length) % displayedTargets.length
    setFocusedTarget(displayedTargets[nextIndex])
  }, [displayedTargets])

  const handleLeaderStateChange = useCallback((sourceTarget: string, active: boolean) => {
    if (active) {
      setFocusedTarget(sourceTarget)
      setLeaderHintTarget(sourceTarget)
      return
    }
    setLeaderHintTarget((current) => (current === sourceTarget ? null : current))
  }, [])

  useEffect(() => {
    if (!isFullscreen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') exitFullscreen()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [exitFullscreen, isFullscreen])

  const shouldExitEmptyLanes = layoutMode.kind === 'lanes' && teamLanes.sessions.length === 0

  useEffect(() => {
    if (!shouldExitEmptyLanes) return
    const exitId = window.setTimeout(() => {
      setLayoutMode((cur) => (cur.kind === 'lanes' ? { kind: 'grid' } : cur))
    }, 0)
    return () => window.clearTimeout(exitId)
  }, [shouldExitEmptyLanes])

  const toggleTarget = useCallback((target: string) => {
    setActiveTargets((prev) =>
      prev.includes(target) ? prev.filter((t) => t !== target) : addTarget(prev, target)
    )
    setLayoutMode((cur) => (cur.kind === 'single' && cur.target === target ? { kind: 'grid' } : cur))
  }, [])

  const removeTarget = useCallback((target: string) => {
    setActiveTargets((prev) => prev.filter((t) => t !== target))
    setLayoutMode((cur) => (cur.kind === 'single' && cur.target === target ? { kind: 'grid' } : cur))
  }, [])

  const handleSpawned = (tmuxTarget: string) => {
    refresh()
    if (effectiveTeamFilter !== 'all') return
    setActiveTargets((prev) => addTarget(prev, tmuxTarget))
  }

  const handleKilled = () => {
    if (killSession) {
      removeTarget(killSession.tmux_target)
    }
    setKillSession(null)
    refresh()
  }

  const gridCols = activeTargets.length <= 1 ? 'grid-cols-1' : 'grid-cols-2'
  const showLeaderHint = leaderHintTarget !== null && displayedTargets.includes(leaderHintTarget)

  return (
    <div className={cn(
      'flex flex-col',
      isFullscreen
        ? 'fixed inset-0 z-50 bg-background'
        : 'h-[calc(100vh-8.5rem)] border rounded-lg overflow-hidden'
    )}>
      {showLeaderHint && <LeaderHintOverlay />}

      {!isFullscreen && (
        <div className="border-b shrink-0 bg-muted/30">
          <div className="flex items-center gap-3 px-4 py-3">
            <MonitorPlay className="h-5 w-5 shrink-0" />
            <div className="flex items-baseline gap-2 flex-wrap min-w-0">
              <h1 className="text-base font-semibold">Agent Bridge</h1>
              <span className="text-xs text-muted-foreground">
                Discover and observe Claude Code, Codex, and Copilot sessions running in tmux. Select up to 4 sessions to monitor simultaneously.
              </span>
            </div>
            <div className="ml-auto flex rounded-md bg-background border p-0.5 shrink-0">
              {PROVIDER_FILTERS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  className={cn(
                    'px-2.5 py-1 text-xs rounded-sm transition-colors',
                    providerFilter === value
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                  onClick={() => setProviderFilter(value)}
                >
                  {label} <span className="opacity-70">({filterCounts[value]})</span>
                </button>
              ))}
            </div>
          </div>
          {teamOptions.length > 0 && (
            <div className="px-4 pb-3">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-medium text-muted-foreground shrink-0">Teams</span>
                <div className="flex rounded-md bg-background border p-0.5 shrink-0 max-w-full overflow-x-auto">
                  <button
                    type="button"
                    className={cn(
                      'px-2.5 py-1 text-xs rounded-sm transition-colors whitespace-nowrap',
                      effectiveTeamFilter === 'all'
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground'
                    )}
                    onClick={() => applyTeamFilter('all')}
                  >
                    All teams <span className="opacity-70">({sessions.length})</span>
                  </button>
                  {teamOptions.map((team) => (
                    <button
                      key={team.id}
                      type="button"
                      className={cn(
                        'px-2.5 py-1 text-xs rounded-sm transition-colors whitespace-nowrap',
                        effectiveTeamFilter === team.id
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                      onClick={() => applyTeamFilter(team.id)}
                    >
                      {team.name} <span className="opacity-70">({team.count})</span>
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className={cn(
                    'px-2.5 py-1 text-xs rounded-md border transition-colors whitespace-nowrap shrink-0',
                    effectiveTeamFilter === 'all'
                      ? 'bg-muted text-muted-foreground cursor-not-allowed opacity-60'
                      : 'bg-background text-foreground hover:bg-muted'
                  )}
                  disabled={effectiveTeamFilter === 'all'}
                  onClick={openTeamLanes}
                  title={selectedTeamLabel ? `Show ${selectedTeamLabel} in fullscreen lanes` : 'Select a team to open team lanes'}
                >
                  Team lanes
                </button>
              </div>
            </div>
          )}
          {agentCliWarning && (
            <div className="px-4 pb-3">
              <Alert variant="destructive" className="py-3">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Agent CLIs unavailable in this runtime</AlertTitle>
                <AlertDescription>
                  {agentCliWarning} Run Claude Deck natively on the host where Claude Code, Codex, Copilot, or OpenCode are installed.
                </AlertDescription>
              </Alert>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {!isFullscreen && (
          <div className="w-52 border-r shrink-0">
            <SessionList
              sessions={visibleSessions}
              loading={loading}
              error={error}
              activeTargets={activeTargets}
              onToggleTarget={toggleTarget}
              onRefresh={refresh}
              onNewSession={() => setNewSessionOpen(true)}
              onKillSession={setKillSession}
              providerFilter={providerFilter}
              teamLabel={selectedTeamLabel}
              canCreateSession={canCreateSession}
              createDisabledReason={canCreateSession ? null : createDisabledReason}
              instance={instance}
            />
          </div>
        )}

        <div className="flex-1 min-w-0 relative">
          {layoutMode.kind === 'lanes' ? (
            <TeamLanesView
              sessions={teamLanes.sessions}
              overflowCount={teamLanes.overflowCount}
              teamLabel={laneTeamLabel}
              focusedTarget={focusedTarget}
              onFocusTarget={setFocusedTarget}
              onLeaderNavigate={handleLeaderNavigate}
              onLeaderStateChange={handleLeaderStateChange}
              onExit={exitFullscreen}
              instance={instance}
            />
          ) : activeTargets.length === 0 ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground bg-background">
              <Monitor className="h-12 w-12 mb-3" />
              <p className="text-sm">Select a session to attach</p>
            </div>
          ) : (
            <div className={cn(
              'absolute inset-0 grid auto-rows-fr',
              isFullscreen ? 'grid-cols-1' : gridCols
            )}>
              {activeTargets.map((target) => {
                const isThisFullscreen = layoutMode.kind === 'single' && layoutMode.target === target
                const hidden = isFullscreen && !isThisFullscreen
                const session = sessionsByTarget.get(target) ?? null
                return (
                  <div
                    key={target}
                    className={cn(
                      hidden
                        ? 'hidden'
                        : 'relative min-h-0 min-w-0 overflow-hidden',
                      !isFullscreen && !hidden && 'border-b border-r last:border-r-0',
                      !hidden && (focusedTarget === target ? 'bg-primary/60' : 'bg-border/30'),
                    )}
                    onMouseDown={() => setFocusedTarget(target)}
                    onFocusCapture={() => setFocusedTarget(target)}
                  >
                    <div className={cn(
                      'absolute inset-[2px] rounded-sm',
                      hidden && 'inset-0 rounded-none',
                    )}>
                      <TerminalView
                        target={target}
                        fullscreen={isThisFullscreen}
                        focused={focusedTarget === target}
                        onLeaderNavigate={handleLeaderNavigate}
                        onLeaderStateChange={handleLeaderStateChange}
                        onToggleFullscreen={() =>
                          setLayoutMode(isThisFullscreen ? { kind: 'grid' } : { kind: 'single', target })
                        }
                        onClose={() => removeTarget(target)}
                        instance={instance}
                        session={session}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <NewSessionDialog
        open={newSessionOpen}
        onOpenChange={setNewSessionOpen}
        onSpawned={handleSpawned}
        initialProvider={initialDialogProvider}
      />

      <KillSessionDialog
        open={killSession !== null}
        onOpenChange={(open) => { if (!open) setKillSession(null) }}
        session={killSession}
        isWorktreeSession={false}
        onKilled={handleKilled}
        instance={instance}
      />
    </div>
  )
}
