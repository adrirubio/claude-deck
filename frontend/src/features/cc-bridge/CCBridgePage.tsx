import { useState, useEffect } from 'react'
import { MonitorPlay } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'
import { NewSessionDialog } from './NewSessionDialog'
import { KillSessionDialog } from './KillSessionDialog'
import type { CCSession } from './types'

export function CCBridgePage() {
  const { sessions, loading, error, refresh } = useCCSessions()
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null)
  const [newSessionOpen, setNewSessionOpen] = useState(false)
  const [killSession, setKillSession] = useState<CCSession | null>(null)
  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    if (!fullscreen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [fullscreen])

  const handleSpawned = (tmuxTarget: string) => {
    refresh()
    setSelectedTarget(tmuxTarget)
  }

  const handleKilled = () => {
    if (killSession && selectedTarget === killSession.tmux_target) {
      setSelectedTarget(null)
    }
    setKillSession(null)
    refresh()
  }

  return (
    <div className={cn(
      'flex flex-col',
      fullscreen
        ? 'fixed inset-0 z-50 bg-background'
        : 'h-[calc(100vh-8.5rem)] border rounded-lg overflow-hidden'
    )}>
      {!fullscreen && (
        <div className="flex items-center gap-3 px-4 py-3 border-b shrink-0 bg-muted/30">
          <MonitorPlay className="h-5 w-5 shrink-0" />
          <div className="flex items-baseline gap-2 flex-wrap">
            <h1 className="text-base font-semibold">CC Bridge</h1>
            <span className="text-xs text-muted-foreground">
              Discover and observe Claude Code sessions running in tmux. Select a session to attach in read-only or interactive mode.
            </span>
          </div>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {!fullscreen && (
          <div className="w-52 border-r shrink-0">
            <SessionList
              sessions={sessions}
              loading={loading}
              error={error}
              selectedTarget={selectedTarget}
              onSelect={setSelectedTarget}
              onRefresh={refresh}
              onNewSession={() => setNewSessionOpen(true)}
              onKillSession={setKillSession}
            />
          </div>
        )}

        <div className="flex-1 min-w-0">
          <TerminalView
            target={selectedTarget}
            fullscreen={fullscreen}
            onToggleFullscreen={() => setFullscreen((f) => !f)}
          />
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
