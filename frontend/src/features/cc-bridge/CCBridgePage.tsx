import { useState } from 'react'
import { MonitorPlay, Info, X } from 'lucide-react'
import { useCCSessions } from './useCCSessions'
import { SessionList } from './SessionList'
import { TerminalView } from './TerminalView'
import { Button } from '@/components/ui/button'

export function CCBridgePage() {
  const { sessions, loading, error, refresh } = useCCSessions()
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null)
  const [showInfo, setShowInfo] = useState(false)

  return (
    <div className="flex flex-col h-[calc(100vh-8.5rem)] border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0 bg-muted/30">
        <div className="flex items-center gap-2">
          <MonitorPlay className="h-5 w-5" />
          <div>
            <h1 className="text-base font-semibold">CC Bridge</h1>
            <p className="text-xs text-muted-foreground">
              Live Claude Code sessions
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setShowInfo(!showInfo)}
        >
          {showInfo ? <X className="h-4 w-4" /> : <Info className="h-4 w-4" />}
        </Button>
      </div>

      {showInfo && (
        <div className="px-4 py-3 border-b bg-muted/20 text-sm text-muted-foreground space-y-1 shrink-0">
          <p>
            CC Bridge discovers Claude Code sessions running in tmux on this machine
            and lets you observe them in real time through a live terminal view.
          </p>
          <p>
            Select a session from the sidebar to attach. Use <strong>Read-only</strong> mode
            to watch safely, or switch to <strong>Interactive</strong> to type into the session.
          </p>
        </div>
      )}

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
