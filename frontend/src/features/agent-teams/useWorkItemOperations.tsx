import { useCallback, useState } from 'react'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import type { GithubScopeRevision, GithubWorkItem } from '@/types/agentTeams'
import {
  abandonGithubWorkItem, cancelGithubActiveRevision, fetchGithubWorkspaces,
  forceReleaseGithubWorkspace, releaseGithubRecoveryCheckpoint, resumeGithubWorkItem,
} from './api'
import type { ItemOperatorAction } from './WorkItemActions'

/** Item handlers. Every request, method and body is the one the Autonomy tab sent. */
export function useWorkItemOperations({
  presetId,
  withOperatorToken,
  onRefresh,
  onRetryWorkItem,
  onFetchScopeRevisions,
  onCancelContinuationRequest,
}: {
  presetId: number
  withOperatorToken: <Result>(action: (token: string) => Promise<Result>) => Promise<Result>
  onRefresh: () => Promise<void>
  onRetryWorkItem?: (item: GithubWorkItem, operatorToken: string) => Promise<void>
  onFetchScopeRevisions: (itemId: number, operatorToken: string) => Promise<GithubScopeRevision[]>
  onCancelContinuationRequest: (item: GithubWorkItem, requestId: number, operatorToken: string) => Promise<void>
}) {
  const [retryingWorkItemId, setRetryingWorkItemId] = useState<number | null>(null)
  const [retryTarget, setRetryTarget] = useState<GithubWorkItem | null>(null)

  const fetchRevisions = useCallback(
    (itemId: number) => withOperatorToken((token) => onFetchScopeRevisions(itemId, token)),
    [onFetchScopeRevisions, withOperatorToken]
  )

  const operateItem = async (
    item: GithubWorkItem,
    action: ItemOperatorAction,
    reason: string,
    reassignToSlotId?: number
  ) => {
    let resultMessage: string | undefined
    await withOperatorToken(async (token) => {
      if (action.kind === 'abandon') return abandonGithubWorkItem(item.id, reason, token)
      if (action.kind === 'resume') return resumeGithubWorkItem(presetId, item.id, token, reassignToSlotId)
      if (action.kind === 'force_release') {
        const released = await forceReleaseGithubWorkspace(item.scope_id, action.workspace, reason, token)
        const discardedCount = released.discarded_paths?.split('\n').filter(Boolean).length
        resultMessage = `Released workspace from item #${released.released_item_id}. Local paths flagged: ${discardedCount ?? 'unknown'}; unpushed commits: ${released.unpushed_commits ?? 'unknown'}.`
        return
      }
      if (action.kind === 'cancel_request') {
        const approvalId = action.revision.approval_request_id
        if (!approvalId) throw new Error('This revision has no pending approval request.')
        return onCancelContinuationRequest(item, approvalId, token)
      }
      if (action.kind === 'cancel_revision') return cancelGithubActiveRevision(item.id, action.revision, reason, token)
      if (!('revision' in action)) throw new Error('Unsupported operator action.')
      if (!action.revision.approval_request_id) throw new Error('This revision has no approval request to release.')
      return releaseGithubRecoveryCheckpoint(
        item.id, action.revision, action.kind === 'release_decision' ? 'decision' : 'ack', token
      )
    })
    await onRefresh()
    return resultMessage
  }

  const fetchWorkspaces = (scopeId: number) =>
    withOperatorToken((token) => fetchGithubWorkspaces(scopeId, token))

  const retryWorkItem = async (item: GithubWorkItem) => {
    if (retryingWorkItemId !== null) return
    setRetryingWorkItemId(item.id)
    try {
      if (onRetryWorkItem) await withOperatorToken((token) => onRetryWorkItem(item, token))
    } catch {
      // Parent handlers surface the error toast.
    } finally {
      setRetryingWorkItemId(null)
    }
  }

  const retryDialog = (
      <AlertDialog open={retryTarget !== null} onOpenChange={(open) => { if (!open) setRetryTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Retry issue #{retryTarget?.issue_number}?</AlertDialogTitle>
            <AlertDialogDescription>
              Retry can discard prior PR, handoff, and attempt markers. If the workspace is still leased,
              Deck defers re-dispatch until the current owner releases it. Review the work item before continuing.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => { if (retryTarget) void retryWorkItem(retryTarget) }}>
              Retry issue
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
  )

  return { fetchRevisions, fetchWorkspaces, operateItem, retryTarget, setRetryTarget, retryingWorkItemId, retryWorkItem, retryDialog }
}
