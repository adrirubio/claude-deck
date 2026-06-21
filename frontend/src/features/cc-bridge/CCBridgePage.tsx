import { useState, useEffect, useCallback } from 'react'
import { MonitorPlay, Monitor } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'
import { NewSessionDialog } from './NewSessionDialog'
import { KillSessionDialog } from './KillSessionDialog'
import type { CCSession } from './types'
import { useProviderContext } from '@/contexts/ProviderContext'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import type { AgentProviderId, AgentProviderStatus } from '@/types/providers'

const MAX_GRID_PANES = 4
type ProviderFilter = 'all' | AgentProviderId

const PROVIDER_FILTERS: { value: ProviderFilter; label: string }[] = [
  { value: 'all', label: 'All agents' },
  { value: 'claude-code', label: 'Claude Code' },
  { value: 'codex-cli', label: 'Codex' },
  { value: 'copilot-cli', label: 'Copilot' },
]

function addTarget(prev: string[], target: string): string[] {
  if (prev.includes(target)) return prev
  if (prev.length >= MAX_GRID_PANES) return prev
  return [...prev, target]
}

export function CCBridgePage() {
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>('all')
  const { providers, selectedProviderId } = useProviderContext()
  const status = useSystemStatus()
  const instance = status?.instance ?? null
  const { sessions, loading, error, refresh } = useCCSessions()
  const [activeTargets, setActiveTargets] = useState<string[]>([])
  const [fullscreenTarget, setFullscreenTarget] = useState<string | null>(null)
  const [focusedTarget, setFocusedTarget] = useState<string | null>(null)
  const [newSessionOpen, setNewSessionOpen] = useState(false)
  const [killSession, setKillSession] = useState<CCSession | null>(null)

  const isFullscreen = fullscreenTarget !== null
  const visibleSessions = providerFilter === 'all'
    ? sessions
    : sessions.filter((session) => session.provider === providerFilter)

  const providersById = providers.reduce<Partial<Record<AgentProviderId, AgentProviderStatus>>>((acc, provider) => {
    acc[provider.id] = provider
    return acc
  }, {})

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
  const createDisabledReason = providerFilter === 'all'
    ? 'No installed provider can launch sessions.'
    : !selectedFilterProvider
      ? 'Provider metadata is not available.'
      : !selectedFilterProvider.installed
        ? `${selectedFilterProvider.display_name} is not installed.`
        : selectedFilterProvider.capability_details?.spawn?.reason
          ?? `${selectedFilterProvider.display_name} cannot launch sessions from Agent Bridge.`

  const filterCounts: Record<ProviderFilter, number> = {
    all: sessions.length,
    'claude-code': sessions.filter((session) => session.provider === 'claude-code').length,
    'codex-cli': sessions.filter((session) => session.provider === 'codex-cli').length,
    'copilot-cli': sessions.filter((session) => session.provider === 'copilot-cli').length,
  }

  const initialDialogProvider = providerFilter === 'all' ? selectedProviderId : providerFilter

  useEffect(() => {
    if (!isFullscreen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreenTarget(null)
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [isFullscreen])

  const toggleTarget = useCallback((target: string) => {
    setActiveTargets((prev) =>
      prev.includes(target) ? prev.filter((t) => t !== target) : addTarget(prev, target)
    )
    setFullscreenTarget((cur) => (cur === target ? null : cur))
  }, [])

  const removeTarget = useCallback((target: string) => {
    setActiveTargets((prev) => prev.filter((t) => t !== target))
    setFullscreenTarget((cur) => (cur === target ? null : cur))
  }, [])

  const handleSpawned = (tmuxTarget: string) => {
    refresh()
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

  return (
    <div className={cn(
      'flex flex-col',
      isFullscreen
        ? 'fixed inset-0 z-50 bg-background'
        : 'h-[calc(100vh-8.5rem)] border rounded-lg overflow-hidden'
    )}>
      {!isFullscreen && (
        <div className="flex items-center gap-3 px-4 py-3 border-b shrink-0 bg-muted/30">
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
              canCreateSession={canCreateSession}
              createDisabledReason={canCreateSession ? null : createDisabledReason}
              instance={instance}
            />
          </div>
        )}

        <div className="flex-1 min-w-0 relative">
          {activeTargets.length === 0 ? (
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
                const isThisFullscreen = fullscreenTarget === target
                const hidden = isFullscreen && !isThisFullscreen
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
                        onToggleFullscreen={() =>
                          setFullscreenTarget(isThisFullscreen ? null : target)
                        }
                        onClose={() => removeTarget(target)}
                        instance={instance}
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
