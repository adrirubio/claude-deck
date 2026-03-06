import { useState, useCallback, useEffect } from 'react'
import { Radio, Plug, Trash2 } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { PresenceCard } from './PresenceCard'
import { ConnectDialog } from './ConnectDialog'
import { fetchPresenceSessions, removeSession, clearAllSessions } from './api'
import { usePresenceWebSocket } from '@/hooks/usePresenceWebSocket'
import { useProjectContext } from '@/contexts/ProjectContext'
import type { PresenceSession } from '@/types/presence'

// Sort: active > error > idle > stopped
const STATUS_ORDER: Record<string, number> = { active: 0, error: 1, idle: 2, stopped: 3 }

function sortSessions(sessions: PresenceSession[]): PresenceSession[] {
  return [...sessions].sort((a, b) => {
    const sa = STATUS_ORDER[a.status] ?? 9
    const sb = STATUS_ORDER[b.status] ?? 9
    if (sa !== sb) return sa - sb
    return new Date(b.last_event_at).getTime() - new Date(a.last_event_at).getTime()
  })
}

export function PresencePage() {
  const [sessions, setSessions] = useState<Map<string, PresenceSession>>(new Map())
  const [loading, setLoading] = useState(true)
  const [connectOpen, setConnectOpen] = useState(false)
  const { activeProject } = useProjectContext()

  const loadSessions = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchPresenceSessions()
      const map = new Map<string, PresenceSession>()
      for (const s of res.sessions) {
        map.set(s.session_id, s)
      }
      setSessions(map)
    } catch {
      // Ignore — empty state will show
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  const onSessionUpdate = useCallback((session: PresenceSession) => {
    setSessions((prev) => {
      const next = new Map(prev)
      next.set(session.session_id, session)
      return next
    })
  }, [])

  const onSessionRemove = useCallback((sessionId: string) => {
    setSessions((prev) => {
      const next = new Map(prev)
      next.delete(sessionId)
      return next
    })
  }, [])

  const onSessionsCleared = useCallback(() => {
    setSessions(new Map())
  }, [])

  const { connected, reconnecting } = usePresenceWebSocket({
    onSessionUpdate,
    onSessionRemove,
    onSessionsCleared,
    enabled: true,
  })

  const handleRemove = async (sessionId: string) => {
    try {
      await removeSession(sessionId)
      onSessionRemove(sessionId)
    } catch {
      // Ignore
    }
  }

  const handleClearStopped = async () => {
    const stopped = [...sessions.values()].filter((s) => s.status === 'stopped' || s.status === 'idle')
    for (const s of stopped) {
      try {
        await removeSession(s.session_id)
        onSessionRemove(s.session_id)
      } catch {
        // Ignore individual failures
      }
    }
  }

  const handleClearAll = async () => {
    try {
      await clearAllSessions()
      setSessions(new Map())
    } catch {
      // Ignore
    }
  }

  const sortedSessions = sortSessions([...sessions.values()])
  const totalEvents = sortedSessions.reduce((acc, s) => acc + s.total_events, 0)
  const activeCount = sortedSessions.filter((s) => s.status === 'active').length
  const errorCount = sortedSessions.filter((s) => s.status === 'error').length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Radio className="h-8 w-8" />
            Presence
          </h1>
          <p className="text-muted-foreground">
            Real-time monitoring of Claude Code sessions
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* WS status indicator */}
          <div className="flex items-center gap-1.5 text-xs">
            <span
              className={`h-2 w-2 rounded-full ${
                connected ? 'bg-green-500 animate-pulse' : reconnecting ? 'bg-yellow-500 animate-pulse' : 'bg-muted-foreground'
              }`}
            />
            <span className="text-muted-foreground">
              {connected ? 'Live' : reconnecting ? 'Reconnecting...' : 'Disconnected'}
            </span>
          </div>
          <RefreshButton onClick={loadSessions} loading={loading} />
          <Button variant="outline" size="sm" onClick={() => setConnectOpen(true)}>
            <Plug className="h-4 w-4 mr-1" />
            Connect to Deck
          </Button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Sessions</CardDescription>
            <CardTitle className="text-3xl">{sortedSessions.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Active</CardDescription>
            <CardTitle className="text-3xl text-green-500">{activeCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Errors</CardDescription>
            <CardTitle className="text-3xl text-red-500">{errorCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Events</CardDescription>
            <CardTitle className="text-3xl">{totalEvents}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Action bar */}
      {sortedSessions.length > 0 && (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleClearStopped}
            disabled={!sortedSessions.some((s) => s.status === 'stopped' || s.status === 'idle')}
          >
            Clear stopped
          </Button>
          <Button variant="outline" size="sm" onClick={handleClearAll}>
            <Trash2 className="h-3.5 w-3.5 mr-1" />
            Clear all
          </Button>
        </div>
      )}

      {/* Session grid */}
      {sortedSessions.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sortedSessions.map((s) => (
            <PresenceCard key={s.session_id} session={s} onRemove={handleRemove} />
          ))}
        </div>
      ) : (
        !loading && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-12 text-center">
              <Radio className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">No sessions yet</h3>
              <p className="text-sm text-muted-foreground max-w-md mb-4">
                Connect Claude Code to this dashboard using HTTP hooks. Sessions will appear here
                in real-time as Claude works.
              </p>
              <Button onClick={() => setConnectOpen(true)}>
                <Plug className="h-4 w-4 mr-2" />
                Connect to Deck
              </Button>
            </CardContent>
          </Card>
        )
      )}

      {/* Connect Dialog */}
      <ConnectDialog
        open={connectOpen}
        onOpenChange={setConnectOpen}
        projectPath={activeProject?.path}
      />
    </div>
  )
}
