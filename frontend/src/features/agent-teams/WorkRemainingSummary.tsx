import type { GithubWorkItem } from '@/types/agentTeams'
import { formatServerTime } from '@/lib/serverTime'

import type { RemainingWork } from './workRemaining'

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
      {report.reported_by ?? 'Team report'} · Updated {formatServerTime(report.reported_at)}
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
        <dt>Report updated</dt><dd>{report.reported_at ? formatServerTime(report.reported_at) : 'Unavailable'}</dd>
      </dl>
    </details>}
    <a href={issueUrl} target="_blank" rel="noreferrer" className="inline-flex text-xs font-medium text-primary">Details on GitHub</a>
  </section>
}
