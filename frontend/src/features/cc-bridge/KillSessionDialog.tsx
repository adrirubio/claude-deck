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

interface KillSessionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  session: CCSession | null
  isWorktreeSession: boolean
  onKilled: () => void
}

export function KillSessionDialog({
  open,
  onOpenChange,
  session,
  isWorktreeSession,
  onKilled,
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
          <DialogTitle>Kill Session</DialogTitle>
          <DialogDescription>
            Are you sure you want to kill session{' '}
            <strong>{session?.session_name}</strong>? This will terminate the
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
