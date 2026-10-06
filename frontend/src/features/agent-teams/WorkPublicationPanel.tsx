import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api'
import type { AgentActivityObservation, GithubWorkItem } from '@/types/agentTeams'

type Publication = {
  state: 'current' | 'historical' | 'unavailable'
  observed_at: string | null
  local_sha: string | null
  published_sha: string | null
  unpublished_commits: number | null
  tracked_changes: number | null
  untracked_files: number | null
  relation: string
  reason: string | null
  file_counts_reason: 'safe_metadata_read'
  publication_first_observed_at: string | null
  publication_time_source: 'github_head_observation' | null
  destination_url: string | null
}
type Progress = {
  work_item_id: number
  dispatch_nonce: string | null
  owner_slot_id: number | null
  checked_at: string
  valid_until: string
  phase: string
  next_actor: 'owner' | 'leader' | 'operator' | 'controller' | 'none'
  next_action: string
  next_poll_expected_at: string | null
  last_check_head: string | null
  publication: Publication
}

const phases: Record<string, string> = {
  paused: 'Automation paused', complete: 'Tracked work complete', intervention: 'Intervention needed',
  plan_review: 'Plan review', handoff: 'Owner handoff', queue: 'Admission or capacity wait',
  review: 'Review and merge', diagnostic_review: 'Diagnostic review', ci: 'Automatic checks',
  planning: 'Owner planning or acknowledgement', implementation: 'Approved implementation', unknown: 'Unknown',
}
const reasons: Record<string, string> = {
  workspace_not_leased: 'The workspace is no longer leased to this item.',
  workspace_identity_unavailable: 'The registered workspace identity could not be confirmed.',
  git_unavailable: 'Git observations are unavailable.',
  invalid_git_observation: 'The Git result could not be confirmed.',
  observation_limit: 'The observation exceeded its supported size.',
  observation_timeout: 'The observation exceeded its time limit.',
  branch_not_assigned: 'No valid task branch is assigned.',
  detached_head: 'The workspace has a detached head. The task-branch comparison is unavailable.',
  branch_mismatch: 'The workspace is not on the assigned task branch.',
  remote_unavailable: 'The published branch head could not be confirmed.',
  published_object_unavailable: 'The published commit is unavailable in the local checkout.',
  ancestry_unavailable: 'This checkout has incomplete history. Commit counts are unavailable.',
  changed_during_read: 'The source or its lease changed during the observation.',
  snapshot_unavailable: 'The previous observation could not be confirmed.',
}

function timestamp(value: string | null | undefined) {
  if (!value) return NaN
  return Date.parse(/[Zz]$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
}
function date(value: string | null | undefined) {
  const time = timestamp(value)
  return Number.isFinite(time) ? new Date(time).toLocaleString() : 'Unavailable'
}
function valid(data: Progress, itemId: number, nonce: string | null, owner: number | null) {
  const publication = data?.publication
  return data?.work_item_id === itemId && data.dispatch_nonce === nonce && data.owner_slot_id === owner
    && Number.isFinite(timestamp(data.checked_at)) && Number.isFinite(timestamp(data.valid_until))
    && timestamp(data.valid_until) <= timestamp(data.checked_at) + 30_000
    && typeof data.phase === 'string' && typeof data.next_action === 'string'
    && ['owner', 'leader', 'operator', 'controller', 'none'].includes(data.next_actor)
    && publication && ['current', 'historical', 'unavailable'].includes(publication.state)
    && [publication.local_sha, publication.published_sha, data.last_check_head]
      .every((sha) => sha === null || typeof sha === 'string' && /^[0-9a-f]{40}$/.test(sha))
    && [publication.unpublished_commits, publication.tracked_changes, publication.untracked_files]
      .every((count) => count === null || Number.isSafeInteger(count) && count >= 0)
}

export function WorkPublicationPanel({ item, ownerName, ownerActivity }: {
  item: GithubWorkItem; ownerName?: string; ownerActivity?: AgentActivityObservation
}) {
  const id = item.id
  const nonce = item.dispatch_nonce ?? null
  const owner = item.owner_slot_id ?? null
  const requestKey = JSON.stringify([id, nonce, owner, item.dispatch_status,
    item.pending_approval_request_id, item.ack_evidence_message_id])
  const [result, setResult] = useState<{ key: string; data: Progress } | null>(null)
  const data = result?.key === requestKey ? result.data : null
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [clock, setClock] = useState(Date.now)

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    let request: AbortController | undefined
    const poll = async () => {
      request?.abort()
      const controller = new AbortController()
      request = controller
      let deadline: ReturnType<typeof setTimeout> | undefined
      setLoading(true)
      try {
        const next = await Promise.race([
          apiClient<Progress>(`agent-teams/github-work-items/${id}/progress`, {
            signal: controller.signal, cache: 'no-store',
          }),
          new Promise<never>((_, reject) => {
            deadline = setTimeout(() => { controller.abort(); reject(new Error('Progress timeout')) }, 12_000)
          }),
        ])
        if (!valid(next, id, nonce, owner)) throw new Error('Invalid progress observation')
        if (active && !controller.signal.aborted) {
          setResult({ key: requestKey, data: next }); setError(false); setClock(Date.now())
        }
      } catch {
        if (active) { setError(true); setClock(Date.now()) }
      } finally {
        clearTimeout(deadline)
        if (active) {
          setLoading(false)
          timer = setTimeout(() => { void poll() }, 15_000)
        }
      }
    }
    void poll()
    return () => { active = false; clearTimeout(timer); request?.abort() }
  }, [id, nonce, owner, requestKey, refresh])

  const matches = data?.work_item_id === id && data.dispatch_nonce === nonce && data.owner_slot_id === owner
  const expiry = data && matches ? timestamp(data.valid_until) : NaN
  useEffect(() => {
    const update = () => setClock(Date.now())
    const timer = Number.isFinite(expiry) ? setTimeout(update, Math.max(0, expiry - Date.now() + 1)) : undefined
    window.addEventListener('focus', update)
    return () => { clearTimeout(timer); window.removeEventListener('focus', update) }
  }, [expiry])
  const current = Boolean(matches && !error && clock < expiry)
  const publication = matches ? data?.publication : null
  const publicationCurrent = current && publication?.state === 'current'
  const actors = { owner: ownerName ?? 'Assigned owner', leader: 'Team Leader', operator: 'Operator', controller: 'Deck', none: 'None' }
  const branchUrl = item.dispatch_head_ref ? `https://github.com/${encodeURIComponent(item.repo_owner)}/${encodeURIComponent(item.repo_name)}/tree/${item.dispatch_head_ref.split('/').map(encodeURIComponent).join('/')}` : null
  let summary = 'Publication status unavailable'
  if (publicationCurrent && publication?.relation === 'synchronized') summary = 'Local HEAD matches the published SHA'
  else if (publicationCurrent && publication?.relation === 'diverged') summary = `Branches have diverged · ${publication.unpublished_commits ?? 'Unknown'} local commits are unpublished`
  else if (publicationCurrent && publication?.unpublished_commits != null && publication.unpublished_commits > 0) {
    summary = `${publication.unpublished_commits} unpublished ${publication.unpublished_commits === 1 ? 'commit' : 'commits'}`
  } else if (publicationCurrent && publication?.relation === 'behind') summary = 'The local branch is behind the published branch'
  else if (publication?.state === 'historical' || matches && !current) summary = 'Previous publication observation'

  return <section className="space-y-3 rounded-lg border p-4" aria-label="Progress and publication">
    <div className="flex items-center justify-between gap-3">
      <h3 className="font-semibold">Progress and publication</h3>
      <Button variant="outline" size="sm" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>
        {loading ? 'Refreshing…' : 'Refresh progress'}
      </Button>
    </div>
    {ownerActivity?.slot_id === owner && <p className="text-xs text-muted-foreground">
      {ownerActivity.state === 'working' ? 'The owner harness reports a working turn.'
        : ownerActivity.state === 'idle' ? 'The owner turn ended. A completed turn does not establish that this item is complete.'
          : ownerActivity.state === 'stopped' ? 'The owner process is stopped.' : 'Owner activity is unavailable.'}
      {' '}Owner activity can cover other items. The Leader follow-up view records any current settlement action.
    </p>}
    {error && <p role="status" className="text-sm text-muted-foreground">Unable to refresh progress. Retained details are historical.</p>}
    {!matches || !data ? <p className="text-sm text-muted-foreground">{loading ? 'Reading progress…' : 'No progress observation is available.'}</p> : <>
      <p className="text-sm"><span className="font-medium">{current ? 'Phase' : 'Previous phase'}:</span> {phases[data.phase] ?? 'Unknown'}
        {' · '}{current ? 'Next actor' : 'Previous actor'}: {actors[data.next_actor]}</p>
      <p className="text-sm">{current ? data.next_action : `Previous next action: ${data.next_action}`}</p>
      <p className="text-sm font-medium">{summary}</p>
      <p className="text-xs text-muted-foreground">File-change counts are unavailable in this metadata read. Matching commits do not establish that the workspace has no edits.</p>
      {publication?.reason && <p className="text-sm text-muted-foreground">{reasons[publication.reason] ?? 'The observation is incomplete.'}</p>}
      <details className="text-sm">
        <summary className="cursor-pointer font-medium">Source and publication details</summary>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          {[
            ['Local SHA observed', publication?.local_sha ?? 'Unavailable'],
            ['Published SHA observed', publication?.published_sha ?? 'Unavailable'],
            ['Unpublished commits', publication?.unpublished_commits ?? 'Unavailable'],
            ['Branch relationship', publication?.relation ?? 'Unavailable'],
            ['Changed tracked files', publication?.tracked_changes ?? 'Unavailable'],
            ['Untracked files', publication?.untracked_files ?? 'Unavailable'],
            ['Source observation', date(publication?.observed_at)],
            ['Checkpoint first observed', date(publication?.publication_first_observed_at)],
            ['Last check head recorded by Deck', data.last_check_head ?? 'Unavailable'],
            ['Next expected controller poll', date(data.next_poll_expected_at)],
          ].map(([label, value]) => <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="break-all">{value}</dd></div>)}
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">The checkpoint time is a GitHub head observation. Push time is unavailable. The controller poll time is an estimate.</p>
        <p className="mt-1 text-xs text-muted-foreground">Publication and a recorded check head do not prove review acceptance or merge eligibility.</p>
        {branchUrl && <a className="mt-3 inline-flex font-medium text-primary" href={branchUrl} target="_blank" rel="noreferrer">Open assigned branch on GitHub</a>}
      </details>
    </>}
  </section>
}
