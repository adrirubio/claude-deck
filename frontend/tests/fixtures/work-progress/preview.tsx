// Synthetic visual evidence only. This entry does not use a live backend.
import { createRoot } from 'react-dom/client'
import { useState } from 'react'
import '../../../src/index.css'
import { WorkPublicationPanel } from '../../../src/features/agent-teams/WorkPublicationPanel'
import { BacklogCoordination } from '../../../src/features/agent-teams/BacklogCoordination'
import type { GithubWorkItem } from '../../../src/types/agentTeams'

let scenario = 'ahead'
const item = { id: 1, dispatch_nonce: 'fixture', owner_slot_id: 2, repo_owner: 'example', repo_name: 'project',
  dispatch_head_ref: 'task', issue_number: 10, dispatch_status: 'dispatched' } as GithubWorkItem
window.fetch = async (input) => {
  const url = String(input)
  const now = new Date().toISOString()
  const expires = new Date(Date.now() + 15000).toISOString()
  if (url.endsWith('/progress')) return Response.json({
    work_item_id: 1, dispatch_nonce: 'fixture', owner_slot_id: 2, checked_at: now, valid_until: expires,
    phase: scenario === 'review' ? 'review' : 'implementation', next_actor: scenario === 'review' ? 'operator' : 'owner',
    next_action: scenario === 'review' ? 'Read the human summary and exact-head review and CI evidence.' : 'Continue approved work and publish a safe draft checkpoint.',
    next_poll_expected_at: new Date(Date.now() + 10000).toISOString(), last_check_head: null,
    publication: { state: scenario === 'historical' ? 'historical' : 'current', observed_at: now,
      local_sha: 'a'.repeat(40), published_sha: scenario === 'match' ? 'a'.repeat(40) : 'b'.repeat(40),
      unpublished_commits: scenario === 'match' ? 0 : 2, tracked_changes: null, untracked_files: null,
      file_counts_reason: 'safe_metadata_read', relation: scenario === 'match' ? 'synchronized' : 'ahead',
      reason: scenario === 'historical' ? 'workspace_not_leased' : null,
      publication_first_observed_at: now, publication_time_source: 'github_head_observation', destination_url: null,
    },
  })
  if (url.endsWith('/coordination')) return Response.json({
    scope_id: 1, repo: 'example/project', enabled: true, version: 1, issue_numbers: [10], fallback_seconds: 1800,
    max_daily_requests: 24, requests_today: 24, notifications_remaining: 0, notification_cap_reason: 'daily',
    notification_budget_resets_at: '2026-10-07T00:00:00Z', autonomy_enabled: true,
    status: 'coordination_capped', last_polled_at: now, last_assessed_at: '2026-10-06T18:00:00Z', observation_expires_at: expires,
    active_implementations: 1, execution_limit: 2, available_workspaces: 1, leased_workspaces: 1,
    eligible_count: null, assessment_current: false, owner_followups: [], observations: [],
    entries: [{ issue_number: 10, disposition: 'human_decision_blocked', reason: 'milestone_decision', required_actor: 'operator', evidence_issue_numbers: [9] }],
  })
  throw new Error('No live request is allowed in this fixture')
}
function Preview() {
  const [selected, setSelected] = useState('ahead')
  return <main className="mx-auto max-w-3xl space-y-5 p-5">
    <h1 className="text-xl font-semibold">Progress and publication fixture</h1>
    <p className="text-sm text-muted-foreground">Synthetic observations. This is not a live team or an approval request.</p>
    <div className="flex flex-wrap gap-3">{['ahead', 'match', 'historical', 'review'].map((value) =>
      <button key={value} className="rounded border px-3 py-2" onClick={() => { scenario = value; setSelected(value) }}>{value}</button>)}</div>
    <WorkPublicationPanel key={selected} item={{ ...item, dispatch_status: selected === 'review' ? 'ready_for_review' : 'dispatched' }} ownerName="B2" />
    <BacklogCoordination scopeId={1} withOperatorToken={() => { throw new Error('Fixture does not permit mutations') }} />
  </main>
}
createRoot(document.getElementById('root')!).render(<Preview />)
