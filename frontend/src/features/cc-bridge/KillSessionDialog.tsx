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
import { Input } from '@/components/ui/input'
import { MODAL_SIZES } from '@/lib/constants'
import { ApiHttpError } from '@/lib/api'
import { clearOperatorToken, getOperatorToken, setOperatorToken } from '@/features/agent-teams/operatorAuth'
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
  const [operatorTokenInput, setOperatorTokenInput] = useState('')

  async function handleKill() {
    if (!session) return
    const operatorToken = getOperatorToken() ?? operatorTokenInput.trim()
    if (!operatorToken) {
      setError('Enter the Deck operator token to terminate a session.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const result = await killSession(session.session_name, operatorToken, cleanupWorktree)
      if (result.error) {
        setError(result.error)
      } else {
        setOperatorToken(operatorToken)
        handleOpenChange(false)
        onKilled()
      }
    } catch (err) {
      if (err instanceof ApiHttpError && err.status === 401) {
        clearOperatorToken()
        setOperatorTokenInput('')
        setError('The Deck operator token was rejected. Enter a valid token and retry.')
      } else {
        setError(err instanceof Error ? err.message : 'Failed to kill session')
      }
    } finally {
      setSubmitting(false)
    }
  }

  function handleOpenChange(value: boolean) {
    if (!value) {
      setCleanupWorktree(false)
      setError(null)
      setOperatorTokenInput('')
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

        {!getOperatorToken() && (
          <div className="space-y-2">
            <Label htmlFor="kill-session-operator-token">Operator token</Label>
            <Input
              id="kill-session-operator-token"
              type="password"
              autoComplete="off"
              value={operatorTokenInput}
              onChange={(event) => setOperatorTokenInput(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">Use the token configured in backend/.env; an agent session token cannot terminate another session.</p>
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
