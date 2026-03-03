import { useState, useEffect, useCallback } from 'react'
import { MonitorPlay, Monitor } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'
import { NewSessionDialog } from './NewSessionDialog'
import { KillSessionDialog } from './KillSessionDialog'
import type { CCSession } from './types'

const MAX_GRID_PANES = 4

function addTarget(prev: string[], target: string): string[] {
  if (prev.includes(target)) return prev
  if (prev.length >= MAX_GRID_PANES) return prev
  return [...prev, target]
}

export function CCBridgePage() {
  const { sessions, loading, error, refresh } = useCCSessions()
  const [activeTargets, setActiveTargets] = useState<string[]>([])
  const [fullscreenTarget, setFullscreenTarget] = useState<string | null>(null)
  const [newSessionOpen, setNewSessionOpen] = useState(false)
  const [killSession, setKillSession] = useState<CCSession | null>(null)

  const isFullscreen = fullscreenTarget !== null

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
          <div className="flex items-baseline gap-2 flex-wrap">
            <h1 className="text-base font-semibold">CC Bridge</h1>
            <span className="text-xs text-muted-foreground">
              Discover and observe Claude Code sessions running in tmux. Select up to 4 sessions to monitor simultaneously.
            </span>
          </div>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {!isFullscreen && (
          <div className="w-52 border-r shrink-0">
            <SessionList
              sessions={sessions}
              loading={loading}
              error={error}
              activeTargets={activeTargets}
              onToggleTarget={toggleTarget}
              onRefresh={refresh}
              onNewSession={() => setNewSessionOpen(true)}
              onKillSession={setKillSession}
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
                  <div key={target} className={cn(
                    hidden
                      ? 'hidden'
                      : 'relative min-h-0 min-w-0 overflow-hidden',
                    !isFullscreen && !hidden && 'border-b border-r last:border-r-0'
                  )}>
                    <div className="absolute inset-0">
                      <TerminalView
                        target={target}
                        fullscreen={isThisFullscreen}
                        onToggleFullscreen={() =>
                          setFullscreenTarget(isThisFullscreen ? null : target)
                        }
                        onClose={() => removeTarget(target)}
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
      />

      <KillSessionDialog
        open={killSession !== null}
        onOpenChange={(open) => { if (!open) setKillSession(null) }}
        session={killSession}
        isWorktreeSession={false}
        onKilled={handleKilled}
      />
    </div>
  )
}
