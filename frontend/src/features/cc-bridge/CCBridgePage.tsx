import { useState } from 'react'
import { MonitorPlay } from 'lucide-react'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'

export function CCBridgePage() {
  const { sessions, loading, error, refresh } = useCCSessions()
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null)

  return (
    <div className="flex flex-col h-[calc(100vh-8.5rem)] border rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0 bg-muted/30">
        <MonitorPlay className="h-5 w-5" />
        <div>
          <h1 className="text-base font-semibold">CC Bridge</h1>
          <p className="text-xs text-muted-foreground">
            Live Claude Code sessions
          </p>
        </div>
      </div>

      <div className="flex flex-1 min-h-0">
        <div className="w-52 border-r shrink-0">
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
