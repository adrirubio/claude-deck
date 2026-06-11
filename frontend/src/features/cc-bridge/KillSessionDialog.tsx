import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { MODAL_SIZES } from '@/lib/constants'
import { killSession } from './api'
import type { CCSession } from './types'
import type { InstanceIdentity } from '@/types/status'

interface KillSessionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  session: CCSession | null
  isWorktreeSession: boolean
  onKilled: () => void
  instance?: InstanceIdentity | null
}

export function KillSessionDialog({
  open,
  onOpenChange,
  session,
  isWorktreeSession,
  onKilled,
  instance,
}: KillSessionDialogProps) {
  const [cleanupWorktree, setCleanupWorktree] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleKill() {
    if (!session) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await killSession(session.session_name, cleanupWorktree)
      if (result.error) {
        setError(result.error)
      } else {
        onOpenChange(false)
        onKilled()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to kill session')
    } finally {
      setSubmitting(false)
    }
  }

  function handleOpenChange(value: boolean) {
    if (!value) {
      setCleanupWorktree(false)
      setError(null)
      setSubmitting(false)
    }
    onOpenChange(value)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>
            Kill {session?.session_name ?? 'session'}{instance ? ` on ${instance.name}` : ''}?
          </DialogTitle>
          <DialogDescription>
            This will terminate tmux target <strong>{session?.tmux_target}</strong>
            {instance ? ` on hostname ${instance.hostname}` : ''} and stop the{' '}
            {session?.provider_display_name ?? 'agent'} process.
          </DialogDescription>
        </DialogHeader>

        {isWorktreeSession && (
          <div className="flex items-center space-x-2">
            <Checkbox
              id="cleanup-worktree"
              checked={cleanupWorktree}
              onCheckedChange={(checked) =>
                setCleanupWorktree(checked === true)
              }
            />
            <Label htmlFor="cleanup-worktree" className="cursor-pointer">
              Also remove git worktree
            </Label>
          </div>
        )}

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleKill}
            disabled={submitting}
          >
            {submitting ? 'Killing...' : 'Kill'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
