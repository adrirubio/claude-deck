import { useEffect, useRef, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api'

type HumanAction = {
  scope_id: number; repo: string; issue_number: number; kind: string; state: string
  pull_request_number: number | null; expected_head_sha: string | null
  source: 'leader' | 'dispatch'; last_assessed_at: string | null
  prerequisite_issue_numbers: number[]; evidence_issue_numbers: number[]
  pr_observed_at?: string | null
  gate_reason?: string
  context_request_id?: string
  instructions_state?: string
  instructions_updated_at?: string | null
}
type Summary = { preset_id: number; observation_expires_at: string; coverage_complete: boolean; actions: HumanAction[] }
const kinds: Record<string, string> = {
  review_pr: 'Review the pull request', merge_pr: 'Review the evidence and merge on GitHub when ready',
  pilot_decision: 'Operator pilot decision', milestone_acceptance: 'Milestone acceptance',
  provide_evidence: 'Provide acceptance or pilot evidence', scope_clarification: 'Clarify the remaining scope',
  inspect_attempt: 'Inspect the stopped attempt in Autonomy',
  inspect_checkpoint: 'Inspect the operator recovery checkpoint in Autonomy',
}
const states: Record<string, string> = {
  requested: 'Operator action requested', waiting_for_prerequisites: 'Decision gate — waiting for prerequisites',
  context_pending: 'Action details pending — Leader must update the issue',
  historical: 'Last reported — awaiting confirmation', head_changed: 'PR head changed — Leader confirmation needed',
  pr_unavailable: 'PR status unavailable — verify on GitHub',
  pr_identity_unavailable: 'PR identity is missing — inspect in Autonomy',
}
function timestamp(value: string | undefined) {
  if (!value) return NaN
  return Date.parse(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
}

export function HumanActionSummary({ presetId, onInspectAutonomy }: { presetId: number; onInspectAutonomy: () => void }) {
  const [data, setData] = useState<Summary | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [clock, setClock] = useState(Date.now)
  const serial = useRef(0)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let controller: AbortController | undefined
    const poll = async () => {
      const request = ++serial.current
      controller = new AbortController()
      const abort = controller
      let timeout: ReturnType<typeof setTimeout> | undefined
      try {
        const deadline = new Promise<never>((_resolve, reject) => {
          abort.signal.addEventListener('abort', () => reject(new Error('Human-action refresh ended')), { once: true })
          timeout = setTimeout(() => abort.abort(), 10000)
        })
        const next = await Promise.race([apiClient<Summary>(`agent-teams/presets/${presetId}/human-actions`, { signal:abort.signal, cache:'no-store' }), deadline])
        if (next.preset_id !== presetId || !Array.isArray(next.actions) || !next.actions.every((a) => a &&
          Number.isSafeInteger(a.issue_number) && a.issue_number>0 && typeof a.repo==='string' &&
          Array.isArray(a.prerequisite_issue_numbers) && Array.isArray(a.evidence_issue_numbers))) throw new Error('Invalid human-action response')
        if (active && request===serial.current) { setData(next); setUnavailable(false) }
      } catch {
        if (active && request===serial.current) setUnavailable(true)
      } finally {
        clearTimeout(timeout)
        if (active && request===serial.current) {
          setClock(Date.now())
          timer = setTimeout(() => { void poll() }, 15000)
        }
      }
    }
    void poll()
    return () => { active=false; serial.current++; clearTimeout(timer); controller?.abort() }
  }, [presetId])
  const expiresAt = timestamp(data?.observation_expires_at)
  useEffect(() => {
    const update = () => setClock(Date.now())
    const timer = Number.isFinite(expiresAt) ? setTimeout(update, Math.max(0, expiresAt-Date.now()+1)) : undefined
    document.addEventListener('visibilitychange', update); window.addEventListener('focus', update)
    return () => { clearTimeout(timer); document.removeEventListener('visibilitychange', update); window.removeEventListener('focus', update) }
  }, [expiresAt])
  const samePreset = data?.preset_id===presetId
  const historical = unavailable || !Number.isFinite(expiresAt) || clock>=expiresAt || !samePreset
  const actions = samePreset ? data.actions.filter((action) => action.state!=='resolved').map((action) => ({ ...action,
    state: ['requested', 'waiting_for_prerequisites'].includes(action.state) &&
      (action.instructions_state!=='current' || !/^[0-9a-f]{24}$/.test(action.context_request_id ?? ''))
      ? 'context_pending' : action.state,
  })) : []
  const requested = historical ? 0 : actions.filter((a) => a.state==='requested').length
  const gates = historical ? 0 : actions.filter((a) => a.state==='waiting_for_prerequisites').length
  const pending = historical ? 0 : actions.filter((a) => a.state==='context_pending').length
  return <section aria-label="Human actions and decision gates" className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-4 text-sm">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 font-semibold"><AlertCircle className="h-4 w-4" aria-hidden="true" />Human actions and decision gates</h2>
        <p className="mt-1">{!samePreset ? unavailable ? 'Human-action status is unavailable.' : 'Checking reported human actions…'
          : historical ? 'Retained requests need confirmation. Human-action status is unavailable or stale.'
          : `${requested} ${requested===1 ? 'action requested' : 'actions requested'} · ${gates} ${gates===1 ? 'decision gate waiting' : 'decision gates waiting'}${pending ? ` · ${pending} ${pending===1 ? 'action needs details' : 'actions need details'}` : ''}`}</p>
        {!historical && data && !data.coverage_complete && <p className="mt-1 text-muted-foreground">The Leader’s assessment or some observations need confirmation. This is not a complete list of current actions.</p>}
        {!historical && data?.coverage_complete && actions.length===0 && <p className="mt-1 text-muted-foreground">No pending human actions are currently reported.</p>}
      </div>
      <Button variant="outline" size="sm" onClick={onInspectAutonomy}>Open Autonomy details</Button>
    </div>
    {actions.length>0 && <ul className="mt-3 space-y-3">{actions.map((action) => <li key={`${action.scope_id}-${action.issue_number}-${action.kind}-${action.pull_request_number ?? ''}`} className="rounded border bg-background p-3">
      <p className="font-medium">{states[historical ? 'historical' : action.state] ?? states.historical}</p>
      <p className="mt-1">{action.kind==='milestone_acceptance' && ['m1a_acceptance','m1b_acceptance'].includes(action.gate_reason ?? '')
        ? `${action.gate_reason==='m1a_acceptance' ? 'M1a' : 'M1b'} acceptance` : kinds[action.kind] ?? 'Review the reported gate'}{action.pull_request_number ? ` — PR #${action.pull_request_number}` : ` — issue #${action.issue_number}`}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {action.pull_request_number && <a className="underline" href={`https://github.com/${action.repo}/pull/${action.pull_request_number}`} target="_blank" rel="noreferrer">Open PR #{action.pull_request_number}</a>}
        <a className="underline" href={`https://github.com/${action.repo}/issues/${action.issue_number}${action.instructions_state==='current' && /^[0-9a-f]{24}$/.test(action.context_request_id ?? '') ? '#current-operator-actions' : ''}`} target="_blank" rel="noreferrer">{action.instructions_state==='current' ? 'Read action instructions' : `Open issue #${action.issue_number}`}</a>
      </div>
      {!historical && action.state==='context_pending' && <p className="mt-2 text-muted-foreground">The issue instructions are missing, stale, or unavailable. The blockage remains visible. Use Autonomy details if recovery is urgent.</p>}
      {!historical && action.state==='waiting_for_prerequisites' && <p className="mt-2 text-muted-foreground">This decision is not ready. Complete its required evidence first.</p>}
      {action.prerequisite_issue_numbers.length>0 && <p className="mt-2 text-muted-foreground">Required prerequisite evidence: {action.prerequisite_issue_numbers.map((n) => `#${n}`).join(', ')}. Their closure alone does not record acceptance.</p>}
      {action.expected_head_sha && <p className="mt-1 text-muted-foreground">Reported PR head: {action.expected_head_sha.slice(0, 8)}. Review current checks and evidence on GitHub.</p>}
      {action.pr_observed_at && <p className="mt-1 text-muted-foreground">PR observed: {new Date(timestamp(action.pr_observed_at)).toLocaleString()}</p>}
      {action.instructions_updated_at && <p className="mt-1 text-muted-foreground">Issue instructions updated: {new Date(timestamp(action.instructions_updated_at)).toLocaleString()}</p>}
      <p className="mt-1 text-muted-foreground">{action.repo} · {action.source==='leader' ? 'Reported by the Leader' : 'Reported by dispatch'}{action.last_assessed_at ? ` · Assessment ${new Date(timestamp(action.last_assessed_at)).toLocaleString()}` : ''}</p>
    </li>)}</ul>}
    <p className="mt-3 text-xs text-muted-foreground">These requests do not approve work or satisfy a milestone. Waiting gates require their evidence and recorded decision.</p>
  </section>
}
