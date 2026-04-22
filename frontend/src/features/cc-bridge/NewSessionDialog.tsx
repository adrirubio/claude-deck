import { useState, useEffect } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { MODAL_SIZES } from '@/lib/constants'
import { cn } from '@/lib/utils'
import { formatTimestamp } from '@/features/usage/utils'
import { spawnSession } from './api'
import { useSessionsApi } from '@/hooks/useSessionsApi'
import { useProjectContext } from '@/contexts/ProjectContext'
import type { SpawnSessionRequest } from './types'
import type { SessionSummary } from '@/types/sessions'

type Mode = 'plain' | 'worktree' | 'resume'

interface NewSessionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSpawned: (tmuxTarget: string) => void
}

const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'plain', label: 'Plain' },
  { value: 'worktree', label: 'Worktree' },
  { value: 'resume', label: 'Resume' },
]

export function NewSessionDialog({ open, onOpenChange, onSpawned }: NewSessionDialogProps) {
  const [directory, setDirectory] = useState('')
  const [mode, setMode] = useState<Mode>('plain')
  const [worktreeName, setWorktreeName] = useState('')
  const [skipPermissions, setSkipPermissions] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [recentSessions, setRecentSessions] = useState<SessionSummary[]>([])
  const [selectedSession, setSelectedSession] = useState<SessionSummary | null>(null)
  const [loadingSessions, setLoadingSessions] = useState(false)

  const { listSessions } = useSessionsApi()
  const { projects } = useProjectContext()

  // Fetch sessions when switching to resume mode
  useEffect(() => {
    if (mode !== 'resume') return
    let cancelled = false
    setLoadingSessions(true)
    listSessions({ limit: 20, sort_by: 'date', sort_order: 'desc' })
      .then((data) => { if (!cancelled) setRecentSessions(data.sessions) })
      .catch(() => { if (!cancelled) setRecentSessions([]) })
      .finally(() => { if (!cancelled) setLoadingSessions(false) })
    return () => { cancelled = true }
  }, [mode, listSessions])

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setDirectory('')
      setMode('plain')
      setWorktreeName('')
      setSkipPermissions(false)
      setError(null)
      setSelectedSession(null)
      setRecentSessions([])
      setSubmitting(false)
    }
  }, [open])

  const canLaunch = (() => {
    if (submitting) return false
    if (mode === 'resume') return selectedSession !== null
    return directory.trim().length > 0
  })()

  async function handleLaunch() {
    setError(null)
    setSubmitting(true)

    try {
      const request: SpawnSessionRequest = {
        directory: mode === 'resume' ? '' : directory.trim(),
        mode,
        ...(mode === 'worktree' && worktreeName.trim() && { worktree_name: worktreeName.trim() }),
        ...(mode === 'resume' && selectedSession && {
          session_id: selectedSession.id,
          project_folder: selectedSession.project_folder,
        }),
        ...(skipPermissions && { skip_permissions: true }),
      }

      const response = await spawnSession(request)
      onSpawned(response.tmux_target)
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to spawn session')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.MD}>
        <DialogHeader>
          <DialogTitle>New Claude Code Session</DialogTitle>
          <DialogDescription>
            Launch a new Claude Code instance in a tmux session.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Mode selector */}
          <div className="space-y-1.5">
            <Label>Mode</Label>
            <div className="flex gap-1 rounded-md bg-muted p-1">
              {MODE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={cn(
                    'flex-1 px-3 py-1.5 rounded text-sm font-medium transition-colors',
                    mode === opt.value
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                  onClick={() => {
                    setMode(opt.value)
                    setSelectedSession(null)
                    setError(null)
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Directory input (hidden in resume mode) */}
          {mode !== 'resume' && (
            <div className="space-y-1.5">
              <Label htmlFor="session-directory">Project Directory</Label>
              <Input
                id="session-directory"
                list="session-directory-projects"
                value={directory}
                onChange={(e) => setDirectory(e.target.value)}
                placeholder="/home/user/project"
                autoComplete="off"
              />
              {projects.length > 0 && (
                <>
                  <datalist id="session-directory-projects">
                    {projects.map((p) => (
                      <option key={p.id} value={p.path} label={p.name} />
                    ))}
                  </datalist>
                  <p className="text-xs text-muted-foreground">
                    Pick from configured projects or type any path.
                  </p>
                </>
              )}
            </div>
          )}

          {/* Worktree name (only in worktree mode) */}
          {mode === 'worktree' && (
            <div className="space-y-1.5">
              <Label htmlFor="worktree-name">Worktree Name</Label>
              <Input
                id="worktree-name"
                value={worktreeName}
                onChange={(e) => setWorktreeName(e.target.value)}
                placeholder="feature-name"
              />
              <p className="text-xs text-muted-foreground">
                Optional. A git worktree will be created for isolated development.
              </p>
            </div>
          )}

          {/* Resume session picker */}
          {mode === 'resume' && (
            <div className="space-y-1.5">
              <Label>Recent Sessions</Label>
              {loadingSessions ? (
                <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                  Loading sessions...
                </div>
              ) : recentSessions.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                  No recent sessions found.
                </div>
              ) : (
                <div className="max-h-48 overflow-y-auto rounded-md border">
                  {recentSessions.map((session) => (
                    <button
                      key={session.id}
                      type="button"
                      className={cn(
                        'w-full text-left px-3 py-2 border-b last:border-b-0 transition-colors',
                        selectedSession?.id === session.id
                          ? 'border-l-2 border-l-primary bg-primary/5'
                          : 'hover:bg-muted/50'
                      )}
                      onClick={() => setSelectedSession(session)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium truncate">
                          {session.project_name}
                        </span>
                        <span className="text-xs text-muted-foreground shrink-0">
                          {formatTimestamp(session.modified_at)}
                        </span>
                      </div>
                      {session.summary && (
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">
                          {session.summary}
                        </p>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Skip permissions checkbox */}
          <div className="space-y-1">
            <div className="flex items-center space-x-2">
              <Checkbox
                id="skip-permissions"
                checked={skipPermissions}
                onCheckedChange={(checked) => setSkipPermissions(checked === true)}
              />
              <Label htmlFor="skip-permissions" className="cursor-pointer">
                Skip permission prompts
              </Label>
            </div>
            <p className="text-xs text-destructive/80 ml-6">
              Allows Claude to run tools without asking for confirmation
            </p>
          </div>

          {/* Error message */}
          {error && (
            <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleLaunch} disabled={!canLaunch}>
            {submitting ? 'Launching...' : 'Launch'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
