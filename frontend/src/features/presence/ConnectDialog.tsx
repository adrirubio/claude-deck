import { useState, useEffect, useCallback } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { MODAL_SIZES } from '@/lib/constants'
import { cn } from '@/lib/utils'
import { fetchConfigSnippet, fetchPresenceHooks, buildPresenceEventsUrl } from './api'
import { apiClient } from '@/lib/api'
import type { PresenceConfigSnippet } from '@/types/presence'
import type { Hook, HookEvent } from '@/types/hooks'
import { Copy, Check, Plug, Unplug, Loader2, FileCode, AlertTriangle, ArrowRight } from 'lucide-react'

interface ConnectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectPath?: string
}

const PRESENCE_EVENTS: { event: HookEvent; label: string }[] = [
  { event: 'Notification', label: 'Notifications (narrative text)' },
  { event: 'PreToolUse', label: 'Pre Tool Use (tool about to run)' },
  { event: 'PostToolUse', label: 'Post Tool Use (file edits, commands)' },
  { event: 'UserPromptSubmit', label: 'User Prompt (user sent a message)' },
  { event: 'Stop', label: 'Stop (session paused)' },
  { event: 'SessionStart', label: 'Session Start' },
  { event: 'SessionEnd', label: 'Session End' },
  { event: 'SubagentStart', label: 'Subagent Start' },
  { event: 'SubagentStop', label: 'Subagent Stop' },
]

type TabId = 'auto' | 'manual'

export function ConnectDialog({ open, onOpenChange, projectPath }: ConnectDialogProps) {
  const [tab, setTab] = useState<TabId>('auto')
  const [selectedEvents, setSelectedEvents] = useState<Set<HookEvent>>(
    new Set(PRESENCE_EVENTS.map((e) => e.event))
  )
  const [scope, setScope] = useState<'user' | 'project'>('user')
  const [existingHooks, setExistingHooks] = useState<Hook[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [snippet, setSnippet] = useState<PresenceConfigSnippet | null>(null)
  const [copied, setCopied] = useState(false)
  const [results, setResults] = useState<{ event: string; ok: boolean }[]>([])

  const fetchExisting = useCallback(async () => {
    setLoading(true)
    try {
      setExistingHooks(await fetchPresenceHooks(projectPath))
    } catch {
      setExistingHooks([])
    }
    setLoading(false)
  }, [projectPath])

  useEffect(() => {
    if (open) {
      fetchExisting()
      setResults([])
    }
  }, [open, fetchExisting])

  const toggleEvent = (event: HookEvent) => {
    setSelectedEvents((prev) => {
      const next = new Set(prev)
      if (next.has(event)) next.delete(event)
      else next.add(event)
      return next
    })
  }

  const handleConnect = async () => {
    setCreating(true)
    setResults([])
    const newResults: { event: string; ok: boolean }[] = []

    for (const { event } of PRESENCE_EVENTS) {
      if (!selectedEvents.has(event)) continue
      // Skip if already exists
      if (existingHooks.some((h) => h.event === event)) {
        newResults.push({ event, ok: true })
        continue
      }
      try {
        const params = scope === 'project' && projectPath
          ? `?project_path=${encodeURIComponent(projectPath)}`
          : ''
        await apiClient<Hook>(`hooks${params}`, {
          method: 'POST',
          body: JSON.stringify({
            event,
            type: 'http',
            url: buildPresenceEventsUrl(),
            scope,
          }),
        })
        newResults.push({ event, ok: true })
      } catch {
        newResults.push({ event, ok: false })
      }
    }

    setResults(newResults)
    await fetchExisting()
    setCreating(false)
  }

  const handleDisconnect = async () => {
    setCreating(true)
    for (const hook of existingHooks) {
      try {
        const params = `?scope=${hook.scope}${hook.scope === 'project' && projectPath ? `&project_path=${encodeURIComponent(projectPath)}` : ''}`
        await apiClient(`hooks/${hook.id}${params}`, { method: 'DELETE' })
      } catch {
        // Ignore individual failures
      }
    }
    await fetchExisting()
    setResults([])
    setCreating(false)
  }

  const loadSnippet = async () => {
    if (!snippet) {
      const s = await fetchConfigSnippet()
      setSnippet(s)
    }
  }

  const copySnippet = () => {
    if (snippet) {
      navigator.clipboard.writeText(JSON.stringify(snippet.snippet, null, 2))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const isConnected = existingHooks.length > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(MODAL_SIZES.MD)}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {isConnected ? <Unplug className="h-5 w-5" /> : <Plug className="h-5 w-5" />}
            {isConnected ? 'Connected to Deck' : 'Connect to Deck'}
          </DialogTitle>
          <DialogDescription>
            {isConnected
              ? `${existingHooks.length} HTTP hook(s) are sending events to the Presence Dashboard.`
              : 'Set up HTTP hooks so Claude Code sessions report their activity here.'}
          </DialogDescription>
        </DialogHeader>

        {/* Tab switcher */}
        <div className="flex gap-1 border-b">
          <button
            className={cn(
              'px-3 py-1.5 text-sm transition-colors',
              tab === 'auto' ? 'border-b-2 border-primary font-medium' : 'text-muted-foreground'
            )}
            onClick={() => setTab('auto')}
          >
            Auto-setup
          </button>
          <button
            className={cn(
              'px-3 py-1.5 text-sm transition-colors',
              tab === 'manual' ? 'border-b-2 border-primary font-medium' : 'text-muted-foreground'
            )}
            onClick={() => { setTab('manual'); loadSnippet() }}
          >
            Manual snippet
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : tab === 'auto' ? (
          <div className="space-y-4">
            {/* Already connected — show status + restart warning */}
            {isConnected && (
              <div className="space-y-3">
                {results.some((r) => r.ok) && (
                  <>
                    <div className="rounded-md border border-yellow-500/50 bg-yellow-500/10 p-3 space-y-2">
                      <div className="flex items-center gap-2 text-sm font-medium text-yellow-600 dark:text-yellow-400">
                        <AlertTriangle className="h-4 w-4 shrink-0" />
                        Restart running sessions
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Hooks only take effect for <strong>new</strong> Claude Code sessions. Any currently running sessions won&apos;t send events until restarted.
                      </p>
                    </div>
                    <div className="rounded-md border bg-muted/50 p-3 space-y-1.5">
                      <span className="text-xs font-medium">What&apos;s next</span>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <ArrowRight className="h-3 w-3 shrink-0" />
                        Start (or restart) a Claude Code session
                      </div>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <ArrowRight className="h-3 w-3 shrink-0" />
                        Come back to this page — cards will appear in real-time
                      </div>
                    </div>
                  </>
                )}
                <div className="space-y-1">
                  {existingHooks.map((h) => (
                    <div key={h.id} className="flex items-center gap-2 text-sm">
                      <span className="h-2 w-2 rounded-full bg-green-500" />
                      <span>{h.event}</span>
                      <Badge variant="outline" className="text-[10px]">{h.scope}</Badge>
                    </div>
                  ))}
                </div>
                <Button
                  variant="destructive"
                  onClick={handleDisconnect}
                  disabled={creating}
                  className="w-full"
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Unplug className="h-4 w-4 mr-2" />}
                  Disconnect
                </Button>
              </div>
            )}

            {/* Not connected — show setup */}
            {!isConnected && (
              <>
                {/* Events checklist */}
                <div className="space-y-2">
                  <span className="text-sm font-medium">Events to monitor</span>
                  {PRESENCE_EVENTS.map(({ event, label }) => (
                    <label key={event} className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedEvents.has(event)}
                        onChange={() => toggleEvent(event)}
                        className="rounded"
                      />
                      {label}
                    </label>
                  ))}
                </div>

                {/* Scope */}
                <div className="space-y-2">
                  <span className="text-sm font-medium">Scope</span>
                  <div className="flex gap-2">
                    <Button
                      variant={scope === 'user' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setScope('user')}
                    >
                      All projects
                    </Button>
                    <Button
                      variant={scope === 'project' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setScope('project')}
                      disabled={!projectPath}
                    >
                      This project only
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {scope === 'user'
                      ? 'Hooks apply to all Claude Code sessions regardless of project.'
                      : projectPath
                        ? `Hooks apply only to sessions in ${projectPath.replace(/\/+$/, '').split('/').pop() || projectPath}.`
                        : 'Select a project in the sidebar to enable project-scoped hooks.'}
                  </p>
                </div>

                {/* Results */}
                {results.length > 0 && (
                  <div className="space-y-1">
                    {results.map((r) => (
                      <div key={r.event} className="flex items-center gap-2 text-sm">
                        {r.ok ? (
                          <Check className="h-4 w-4 text-green-500" />
                        ) : (
                          <span className="h-4 w-4 text-red-500 text-center">!</span>
                        )}
                        {r.event}
                      </div>
                    ))}
                  </div>
                )}

                <Button
                  onClick={handleConnect}
                  disabled={creating || selectedEvents.size === 0}
                  className="w-full"
                >
                  {creating ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <Plug className="h-4 w-4 mr-2" />
                  )}
                  Connect
                </Button>
              </>
            )}
          </div>
        ) : (
          /* Manual snippet tab */
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {snippet?.instructions || 'Loading...'}
            </p>
            {snippet && (
              <>
                <div className="relative">
                  <pre className="rounded-md bg-muted p-3 text-xs overflow-auto max-h-64">
                    {JSON.stringify(snippet.snippet, null, 2)}
                  </pre>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="absolute top-2 right-2 h-7 w-7"
                    onClick={copySnippet}
                  >
                    {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                  </Button>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <FileCode className="h-3.5 w-3.5" />
                  <code>~/.claude/settings.json</code>
                </div>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
