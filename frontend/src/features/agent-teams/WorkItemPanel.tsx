import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'

import { ReadStatus } from '@/features/factory/components/ReadStatus'
import { useObservation } from '@/features/factory/reads'
import type {
  AgentTeamPresetListResponse, GithubWorkItem, GithubWorkItemListResponse, TeamGithubScopeListResponse,
} from '@/types/agentTeams'
import { cancelGithubContinuationRequest, fetchGithubScopeRevisions } from './api'
import { useAgentActivity } from './useAgentActivity'
import { useOperatorTokenFlow } from './useOperatorTokenFlow'
import { useWorkItemOperations } from './useWorkItemOperations'
import { WorkItemActions } from './WorkItemActions'

/**
 * Protected history by work item ID. It needs no item record, so it still works
 * for an item outside the team's latest 200 records.
 */
function HistoryById({ workItemId, withOperatorToken }: {
  workItemId: number
  withOperatorToken: <Result>(action: (token: string) => Promise<Result>) => Promise<Result>
}) {
  const [lines, setLines] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = async () => {
    setBusy(true)
    setError(null)
    try {
      const revisions = await withOperatorToken((token) => fetchGithubScopeRevisions(workItemId, token))
      setLines(revisions.map((revision) => `Revision ${revision.revision}: ${revision.status}`))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Failed to load recovery history')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-2">
      <Button variant="outline" size="sm" disabled={busy} onClick={() => void load()}>
        Inspect protected revision history
      </Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {lines && (lines.length === 0
        ? <p className="text-sm text-muted-foreground">No continuation revisions recorded.</p>
        : <ul className="text-sm">{lines.map((line) => <li key={line}>{line}</li>)}</ul>)}
    </div>
  )
}

/**
 * The recovery and remedy actions of one work item, on the Work item page.
 * The requests are the ones the Autonomy tab sent before they moved here.
 */
export function WorkItemPanel({ presetId, workItemId }: { presetId: number; workItemId: number }) {
  const items = useObservation<GithubWorkItemListResponse>(`agent-teams/presets/${presetId}/github-work-items?limit=200`)
  const scopes = useObservation<TeamGithubScopeListResponse>(`agent-teams/presets/${presetId}/github-scopes`)
  const presets = useObservation<AgentTeamPresetListResponse>('agent-teams/presets')
  const activity = useAgentActivity(presetId)
  const { operatorTokenStored, requestToken, withOperatorToken, tokenDialog } = useOperatorTokenFlow(
    'to change autonomy or recovery settings',
  )
  const refresh = async () => {
    await Promise.all([items.refresh(), scopes.refresh()])
  }
  const operations = useWorkItemOperations({
    presetId,
    withOperatorToken,
    onRefresh: refresh,
    onFetchScopeRevisions: fetchGithubScopeRevisions,
    onCancelContinuationRequest: async (item: GithubWorkItem, requestId: number, token: string) => {
      try {
        await cancelGithubContinuationRequest(item.id, requestId, token)
        await refresh()
        toast.success(`Continuation request #${requestId} cancelled`)
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to cancel continuation')
        throw error
      }
    },
  })
  const item = items.data?.items?.find((candidate) => candidate.id === workItemId)
  const slots = presets.data?.presets?.find((preset) => preset.id === presetId)?.slots ?? []
  const slotName = (slotId?: number | null) => (slotId ? slots.find((slot) => slot.id === slotId)?.display_name : undefined)
  return (
    <section aria-label="Recovery and remedies" className="space-y-3">
      <h3 className="text-lg font-semibold">Recovery and remedies</h3>
      <ReadStatus state={items} />
      {(items.data || items.error) && !item && (
        <div className="space-y-2">
          <p>
            Item actions are unavailable: this item is not in the latest 200 records of its team.
            Its protected recovery history is still available.
          </p>
          <HistoryById workItemId={workItemId} withOperatorToken={withOperatorToken} />
        </div>
      )}
      {item && (
        <WorkItemActions
          item={item}
          scope={scopes.data?.scopes?.find((scope) => scope.id === item.scope_id)}
          ownerActivity={item.owner_slot_id ? activity.get(item.owner_slot_id) : undefined}
          ownerName={slotName(item.owner_slot_id)}
          handoffTargetName={slotName(item.handoff_target_slot_id)}
          onFetchScopeRevisions={operations.fetchRevisions}
          onFetchWorkspaces={operations.fetchWorkspaces}
          operatorTokenStored={operatorTokenStored}
          onRequestOperatorToken={() => requestToken()}
          slots={slots}
          onOperate={operations.operateItem}
          hideSummary
        />
      )}
      {tokenDialog}
    </section>
  )
}
