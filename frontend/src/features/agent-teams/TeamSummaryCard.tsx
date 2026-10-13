import { Link } from 'react-router-dom'

import { ReadStatus } from '@/features/factory/components/ReadStatus'
import { anchor } from '@/features/factory/components/styles'
import { requiredCiReason } from '@/features/factory/components/RequiredCiNotice'
import { useObservation } from '@/features/factory/reads'
import { formatServerTime } from '@/lib/serverTime'
import type {
  AgentTeamPresetListResponse, AgentTeamSummary, TeamRemainingWork, TeamSummaryAttention, TeamSummaryHumanAction,
} from '@/types/agentTeams'

const HOLD_TEXT: Record<NonNullable<AgentTeamSummary['hold_code']>, string> = {
  hold: 'This team is on HOLD. Deck admits no new work.',
  recovery_only: 'This team is in recovery-only mode. Deck admits no new work.',
  hold_unavailable: 'Deck could not read the HOLD state of this team.',
}

const ATTENTION_TEXT: Record<TeamSummaryAttention['code'], string> = {
  attempt_stopped: 'Attempt stopped',
  recovery_decision: 'Recovery decision needed',
  human_review: 'Human review needed',
  owner_stalled: 'Owner stalled',
  observation_pause: 'Observation paused',
  hold: 'Team on HOLD',
  recovery_only: 'Team in recovery-only mode',
  hold_unavailable: 'HOLD state unknown',
}

const ACTION_TEXT: Record<TeamSummaryHumanAction['kind'], string> = {
  review_pr: 'Review the PR',
  merge_pr: 'Merge the PR',
  inspect_attempt: 'Inspect the attempt',
  inspect_checkpoint: 'Inspect the checkpoint',
  milestone_acceptance: 'Accept the milestone',
  pilot_decision: 'Make the pilot decision',
  scope_clarification: 'Clarify the scope',
  provide_evidence: 'Provide evidence',
}

const ACTORS = {
  owner: 'The owner agent',
  leader: 'The Leader',
  operator: 'You',
  controller: 'Deck',
} as const

const UNKNOWN_REASON: Record<TeamRemainingWork['reason'], string> = {
  complete: 'Deck read every item.',
  report_unknown: 'The team has not reported.',
  observation_incomplete: 'Deck could not read every item.',
  context_changed: 'The last team report is out of date.',
}

function remainingText(work: TeamRemainingWork) {
  if (work.state === 'unknown') return `Unknown. ${UNKNOWN_REASON[work.reason]}`
  if (work.unfinished_items === 0) return 'Nothing is left.'
  const items = `${work.unfinished_items} unfinished ${work.unfinished_items === 1 ? 'item' : 'items'}`
  const low = work.effort_low_minutes
  const high = work.effort_high_minutes
  if (low == null || high == null) return `${items}. No estimate reported.`
  const range = low === high ? `${low}` : `${low}–${high}`
  const confidence = work.confidence === 'unknown' ? '' : `, ${work.confidence} confidence`
  return `${items}. Estimate: ${range} active minutes${confidence}.`
}

function parentIssueLabel(url: string) {
  const match = /\/issues\/(\d+)\/?$/.exec(url)
  return match ? `#${match[1]}` : url
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[7.5rem_1fr]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

// Display only: the card grants no approval, retry or merge action.
export function TeamSummaryCard({ presetId, name }: { presetId: number; name?: string }) {
  const state = useObservation<AgentTeamSummary>(`agent-teams/presets/${presetId}/summary`)
  const summary = state.data
  const unreadable = summary?.required_ci_unreadable ?? []
  const actions = summary?.human_actions.filter(
    (action) => action.state === 'requested' || action.state === 'context_pending',
  ) ?? []
  return (
    <section
      aria-label={name ? `Team summary: ${name}` : 'Team summary'}
      className="space-y-3 rounded-lg border bg-card p-4 text-sm"
    >
      {name && (
        <h4 className="text-base font-semibold">
          <Link className={anchor} to={`/teams/${presetId}`}>{name}</Link>
        </h4>
      )}
      <ReadStatus state={state} />
      {summary && (
        <>
          {summary.hold_code && (
            <p
              role="note"
              className={summary.hold_code === 'hold_unavailable'
                ? 'rounded border border-amber-500 p-2 text-amber-800 dark:text-amber-300'
                : 'rounded border border-destructive p-2 text-destructive'}
            >
              {HOLD_TEXT[summary.hold_code]}
            </p>
          )}
          <dl className="space-y-2">
            <Row label="Outcome">{summary.description || 'No outcome is set.'}</Row>
            <Row label="Parent issue">
              {summary.parent_issue_url ? (
                <a className={anchor} href={summary.parent_issue_url} target="_blank" rel="noreferrer">
                  {parentIssueLabel(summary.parent_issue_url)}
                </a>
              ) : 'None set.'}
            </Row>
            <Row label="Supervisor">{summary.supervisor === 'none' ? 'None, not required.' : summary.supervisor}</Row>
            <Row label="Attention">
              {summary.attention.length === 0 && unreadable.length === 0 ? 'None open.' : (
                <ul className="space-y-1">
                  {summary.attention.map((item, index) => (
                    <li
                      key={`${item.code}-${item.work_item_id ?? item.pause_id ?? index}`}
                      className={item.code === 'attempt_stopped' ? 'text-destructive' : undefined}
                    >
                      {item.work_item_id && item.issue_number ? (
                        <>{ATTENTION_TEXT[item.code]} on <Link className={anchor} to={`/work/${item.work_item_id}`}>#{item.issue_number}</Link></>
                      ) : ATTENTION_TEXT[item.code]}
                      {item.resume_deadline && <> · resume by {formatServerTime(item.resume_deadline)}</>}
                    </li>
                  ))}
                  {unreadable.map((item) => (
                    <li key={`ci-${item.work_item_id}`} className="text-amber-800 dark:text-amber-300">
                      {item.label} on <Link className={anchor} to={`/work/${item.work_item_id}`}>#{item.issue_number}</Link>
                      . {requiredCiReason(item.reason)} {item.next_steps[0]}
                    </li>
                  ))}
                </ul>
              )}
            </Row>
            <Row label="Remaining">{remainingText(summary.remaining_work)}</Row>
            <Row label="Next actor">
              {summary.next_actors.length
                ? summary.next_actors.map((actor) => ACTORS[actor]).join(', ')
                : summary.next_actor_coverage_complete ? 'None.' : 'Unknown.'}
            </Row>
            {actions.length > 0 && (
              <Row label="Your action">
                <ul className="space-y-1">
                  {actions.map((action) => (
                    <li key={`${action.kind}-${action.scope_id}-${action.issue_number}`}>
                      {ACTION_TEXT[action.kind]}
                      {action.pull_request_number ? ` #${action.pull_request_number}` : ''} on #{action.issue_number}
                      {action.state === 'context_pending' ? ' (details pending)' : ''}
                    </li>
                  ))}
                </ul>
              </Row>
            )}
          </dl>
          {(!summary.coverage_complete || !summary.next_actor_coverage_complete) && (
            <p role="note" className="text-xs text-muted-foreground">
              This summary may be incomplete: Deck did not read every item.
            </p>
          )}
          <p className="text-xs text-muted-foreground">Checked {formatServerTime(summary.checked_at)}</p>
        </>
      )}
    </section>
  )
}

// One card for each team. A team filter limits the list to that team.
export function TeamSummaries({ teamId }: { teamId?: string | null }) {
  const state = useObservation<AgentTeamPresetListResponse>('agent-teams/presets')
  const presets = (state.data?.presets ?? []).filter(
    (preset) => !teamId || String(preset.id) === teamId,
  )
  return (
    <section aria-label="Teams" className="space-y-3">
      <h3 className="text-lg font-semibold">Teams</h3>
      <ReadStatus state={state} />
      {state.data && presets.length === 0 && <p>No teams to show.</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        {presets.map((preset) => (
          <TeamSummaryCard key={preset.id} presetId={preset.id} name={preset.name} />
        ))}
      </div>
    </section>
  )
}
