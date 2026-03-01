import { useState } from 'react'
import { MonitorPlay } from 'lucide-react'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'

export function CCBridgePage() {
  const { sessions, loading, error, refresh } = useCCSessions()
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null)

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      <div className="flex items-center gap-2 px-6 py-4 border-b shrink-0">
        <MonitorPlay className="h-5 w-5" />
        <div>
          <h1 className="text-lg font-semibold">CC Bridge</h1>
          <p className="text-sm text-muted-foreground">
            Live Claude Code sessions
          </p>
        </div>
      </div>

      <div className="flex flex-1 min-h-0">
        <div className="w-56 border-r shrink-0">
          <SessionList
            sessions={sessions}
            loading={loading}
            error={error}
            selectedTarget={selectedTarget}
            onSelect={setSelectedTarget}
            onRefresh={refresh}
          />
        </div>

        <div className="flex-1 min-w-0">
          <TerminalView target={selectedTarget} />
        </div>
      </div>
    </div>
  )
}
