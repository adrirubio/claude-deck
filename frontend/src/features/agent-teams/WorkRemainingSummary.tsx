import type { GithubWorkItem } from '@/types/agentTeams'

export type RemainingWork = {
  state: 'current' | 'historical' | 'unavailable'
  remaining: string | null
  estimate: string | null
  next_action: string | null
  reported_at: string | null
  reported_by: string | null
  source_sha: string | null
  reason: string | null
  source_url: string | null
  completed?: string | null
  assumptions?: string | null
}

export function validRemainingWork(value: unknown): value is RemainingWork {
  if (!value || typeof value !== 'object') return false
  const data = value as RemainingWork
  return ['current', 'historical', 'unavailable'].includes(data.state)
    && [data.remaining, data.estimate, data.next_action, data.reported_by]
      .every((text) => text === null || typeof text === 'string' && text.length <= 300)
    && (data.source_sha === null || typeof data.source_sha === 'string' && /^[a-f0-9]{40}$/.test(data.source_sha))
    && (data.reported_at === null || typeof data.reported_at === 'string' && Number.isFinite(Date.parse(data.reported_at)))
    && (data.state !== 'current' || Boolean(data.remaining && data.estimate && data.next_action && data.reported_at))
    && [data.completed, data.assumptions].every((text) => text === undefined || text === null || typeof text === 'string' && text.length <= 200)
}

export function WorkRemainingSummary({ report, current, complete, nextAction, item }: {
  report?: RemainingWork; current: boolean; complete: boolean; nextAction: string; item: GithubWorkItem
}) {
  const fresh = current && report?.state === 'current'
  const done = current && complete
  const remaining = done ? 'None. This tracked item is complete.'
    : fresh ? report.remaining : 'No current team report is available.'
  const estimate = done ? 'No work remains on this item.' : fresh ? report.estimate : 'Unknown.'
  const next = done ? 'No further action on this item.' : fresh ? report.next_action : current ? nextAction : 'Refresh progress.'
  const issueUrl = `https://github.com/${encodeURIComponent(item.repo_owner)}/${encodeURIComponent(item.repo_name)}/issues/${item.issue_number}#work-remaining`
  return <section aria-label="Work remaining" className="space-y-2 rounded-md bg-muted/40 p-3 text-sm">
    <h4 className="font-semibold">Work remaining</h4>
    <ul className="space-y-1">
      <li><span className="font-medium">Remaining:</span> {remaining}</li>
      <li><span className="font-medium">Estimate:</span> {estimate}</li>
      <li><span className="font-medium">Next:</span> {next}</li>
    </ul>
    {fresh && report?.reported_at && <p className="text-xs text-muted-foreground">
      {report.reported_by ?? 'Team report'} · Updated {new Date(report.reported_at).toLocaleString()}
    </p>}
    {report?.state === 'historical' && <p className="text-xs text-muted-foreground">The previous report is out of date.</p>}
    {report && report.state !== 'unavailable' && <details className="text-xs">
      <summary className="cursor-pointer font-medium">Report details</summary>
      <dl className="mt-2 space-y-1">
        {report.state === 'historical' && <><dt>Previous remaining work</dt><dd>{report.remaining}</dd><dt>Previous estimate</dt><dd>{report.estimate}</dd></>}
        {report.completed && <><dt>Reported complete</dt><dd>{report.completed}</dd></>}
        {report.assumptions && <><dt>Assumptions</dt><dd>{report.assumptions}</dd></>}
        <dt>Reported by</dt><dd>{report.reported_by ?? 'Unavailable'}</dd>
        <dt>Source checkpoint</dt><dd className="break-all">{report.source_sha ?? 'Unavailable'}</dd>
        <dt>Report updated</dt><dd>{report.reported_at ? new Date(report.reported_at).toLocaleString() : 'Unavailable'}</dd>
      </dl>
    </details>}
    <a href={issueUrl} target="_blank" rel="noreferrer" className="inline-flex text-xs font-medium text-primary">Details on GitHub</a>
  </section>
}
