import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { apiClient } from '@/lib/api'

type Entry = {
  issue_number: number
  disposition: string
  reason: string
  required_actor: string
  evidence_issue_numbers: number[]
}
type Summary = {
  scope_id: number
  repo: string
  enabled: boolean
  version: number
  issue_numbers: number[]
  fallback_seconds: number
  max_daily_requests: number
  requests_today: number
  status: string
  last_polled_at: string | null
  observation_expires_at: string | null
  last_assessed_at: string | null
  active_implementations: number | null
  execution_limit: number
  available_workspaces: number | null
  leased_workspaces: number | null
  eligible_count: number | null
  entries: Entry[]
  assessment_current: boolean
}
type Policy = Pick<Summary, 'enabled' | 'issue_numbers' | 'fallback_seconds' | 'max_daily_requests'>

const reasons: Record<string, string> = {
  admission: 'Leader must verify and admit this work', dependency: 'Prerequisite work must be accepted',
  m1a_acceptance: 'M1a acceptance is required', pilot_decision: 'An operator pilot decision is required',
  m1b_acceptance: 'M1b acceptance is required', authority_prerequisite: 'Authority prerequisites must be integrated',
  human_merge: 'Human review or merge is required', review_evidence: 'Review evidence is required',
  resource: 'Workspace or build capacity is unavailable', owner: 'The required owner is unavailable',
  scope_clarification: 'The remaining scope needs reconciliation', complete: 'Completed work has been reconciled',
  standing: 'Standing validation or documentation work may continue within its gates', unknown: 'Evidence is unavailable',
}
const statuses: Record<string, string> = {
  disabled: 'Leader backlog coordination is disabled', paused: 'Coordination is paused with autonomy off',
  awaiting_assessment: 'Waiting for the Leader’s backlog assessment', unknown: 'Backlog has not been observed yet',
  stale: 'Backlog observations are stale', backlog_unavailable: 'Backlog observations are unavailable',
  leader_unavailable: 'The current Leader is unavailable', leader_identity_unavailable: 'Leader identity cannot be confirmed',
  coordination_capped: 'Coordination notification limit reached', hold: 'Coordination is paused by a safety hold',
  hold_unavailable: 'Safety hold status cannot be confirmed', recovery_only: 'Coordination is paused during scoped recovery',
  single_scope_required: 'Coordination requires one enabled repository scope',
  coordination_context_limit: 'Coordination context exceeds its supported limit. The operator must review the assignment and resources.',
}
function policy(data: Summary): Policy {
  return { enabled: data.enabled, issue_numbers: data.issue_numbers,
    fallback_seconds: data.fallback_seconds, max_daily_requests: data.max_daily_requests }
}
function date(value: string | null) {
  if (!value) return 'not yet'
  return new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString()
}
function timestamp(value: string | null | undefined) {
  if (!value) return NaN
  return Date.parse(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
}

export function BacklogCoordination({ scopeId, withOperatorToken }: {
  scopeId: number
  withOperatorToken: <T>(action: (token: string) => Promise<T>) => Promise<T>
}) {
  const [data, setData] = useState<Summary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [enabled, setEnabled] = useState(false)
  const [numbers, setNumbers] = useState('')
  const [minutes, setMinutes] = useState('30')
  const [daily, setDaily] = useState('12')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [clock, setClock] = useState(Date.now)
  const originalPolicy = useRef<Policy | null>(null)
  const controller = useRef<AbortController | null>(null)
  const serial = useRef(0)
  const path = `agent-teams/github-scopes/${scopeId}/coordination`
  const refresh = useCallback(async () => {
    const request = ++serial.current
    controller.current?.abort()
    const abort = new AbortController()
    controller.current = abort
    let timeout: ReturnType<typeof setTimeout> | undefined
    let timedOut = false
    try {
      const deadline = new Promise<never>((_resolve, reject) => {
        abort.signal.addEventListener('abort', () => reject(new Error('Coordination refresh ended')), { once: true })
        timeout = setTimeout(() => { timedOut = true; abort.abort() }, 10000)
      })
      const next = await Promise.race([apiClient<Summary>(path, { signal: abort.signal, cache: 'no-store' }), deadline])
      if (next?.scope_id !== scopeId || !Array.isArray(next.entries) || !Array.isArray(next.issue_numbers)) throw new Error('Invalid coordination response')
      if (request === serial.current && !abort.signal.aborted) { setData(next); setClock(Date.now()); setError(null) }
    } catch {
      if (request === serial.current && (timedOut || !abort.signal.aborted)) setError('Unable to refresh coordination. Any retained assessment is historical.')
    } finally {
      clearTimeout(timeout)
    }
  }, [path, scopeId])
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      await refresh()
      if (active) timer = setTimeout(() => { void poll() }, 15000)
    }
    void poll()
    const pending = controller
    return () => { active = false; clearTimeout(timer); pending.current?.abort() }
  }, [refresh])
  const expiresAt = timestamp(data?.observation_expires_at)
  useEffect(() => {
    const updateClock = () => setClock(Date.now())
    const timer = Number.isFinite(expiresAt) ? setTimeout(updateClock, Math.max(0, expiresAt - Date.now() + 1)) : undefined
    document.addEventListener('visibilitychange', updateClock)
    window.addEventListener('focus', updateClock)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', updateClock)
      window.removeEventListener('focus', updateClock)
    }
  }, [expiresAt])

  const configure = () => {
    if (!data) return
    originalPolicy.current = policy(data)
    setEnabled(data.enabled); setNumbers(data.issue_numbers.join(', '))
    setMinutes(String(data.fallback_seconds / 60)); setDaily(String(data.max_daily_requests))
    setSaveError(null); setOpen(true)
  }
  const save = async () => {
    setSaving(true); setSaveError(null)
    try {
      const pieces = numbers.trim() ? numbers.split(',').map((value) => value.trim()) : []
      if (pieces.some((value) => !/^[1-9]\d*$/.test(value))) throw new Error('Enter positive issue numbers separated by commas.')
      const selected = pieces.map(Number).sort((a, b) => a - b)
      if (selected.length > 32 || new Set(selected).size !== selected.length || selected.some((n) => !Number.isSafeInteger(n))) throw new Error('Select at most 32 distinct issue numbers.')
      if (enabled && !selected.length) throw new Error('Select assigned issues before enabling coordination.')
      const fallback = Number(minutes) * 60
      const cap = Number(daily)
      if (!minutes.trim() || !Number.isInteger(fallback) || fallback < 300 || fallback > 86400) throw new Error('Use a reconciliation fallback from 5 to 1440 minutes.')
      if (!daily.trim() || !Number.isInteger(cap) || cap < 1 || cap > 48) throw new Error('Use a daily notification limit from 1 to 48.')
      const latest = await apiClient<Summary>(path, { cache: 'no-store' })
      if (JSON.stringify(policy(latest)) !== JSON.stringify(originalPolicy.current)) throw new Error('Coordination policy changed. Close and reopen this dialog to review it.')
      await withOperatorToken((token) => apiClient<Summary>(`${path}-policy`, {
        method: 'PUT', headers: { 'X-Deck-Operator-Token': token },
        body: JSON.stringify({ expected_version: latest.version, enabled, issue_numbers: selected,
          fallback_seconds: fallback, max_daily_requests: cap }),
      }))
      setOpen(false); await refresh()
    } catch (failure) {
      setSaveError(failure instanceof Error ? failure.message : 'Could not save coordination policy.')
    } finally { setSaving(false) }
  }
  const expired = !Number.isFinite(expiresAt) || clock >= expiresAt
  const current = Boolean(data?.assessment_current && !error && !expired && data.scope_id === scopeId)
  const heading = error ? 'Coordination status is unavailable' : current
    ? data?.eligible_count === 0 ? 'No eligible implementation work' : `${data?.eligible_count} ${data?.eligible_count === 1 ? 'item' : 'items'} assessed as eligible`
    : data?.assessment_current && expired ? statuses.stale
    : statuses[data?.status ?? 'unknown'] ?? 'Coordination status is unavailable'
  return <section aria-label="Leader backlog coordination" className="mt-4 border-t pt-4 text-sm">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><h4 className="font-medium">{heading}</h4>
        <p className="mt-1 text-muted-foreground">Independent work can continue while another PR awaits your merge. The Leader must verify its gates and admit it.</p>
      </div>
      <Button variant="outline" size="sm" disabled={!data} onClick={configure}>Configure backlog</Button>
    </div>
    {error && <p role="alert" className="mt-2 text-amber-500">{error}</p>}
    {data && <>
      <p className="mt-2 text-muted-foreground">
        Last observed: {date(data.last_polled_at)} · Last Leader assessment: {date(data.last_assessed_at)}
      </p>
      <p className="mt-1 text-muted-foreground">
        Last observed execution: {data.active_implementations ?? 'unknown'}/{data.execution_limit} · Available workspaces: {data.available_workspaces ?? 'unknown'} · Leased: {data.leased_workspaces ?? 'unknown'}
      </p>
      <p className="mt-1 text-muted-foreground">Coordination notifications today: {data.requests_today}/{data.max_daily_requests}. Limits do not change implementation or retry budgets.</p>
      {data.entries.length > 0 && <div className="mt-3">
        <p className="font-medium">{current ? 'Leader dispositions and next actions' : 'Previous assessment — not current eligibility'}</p>
        <ul className="mt-2 space-y-2">{data.entries.map((entry) => <li key={entry.issue_number}>
          <a className="underline" href={`https://github.com/${data.repo}/issues/${entry.issue_number}`} target="_blank" rel="noreferrer">#{entry.issue_number}</a>
          {' · '}{reasons[entry.reason] ?? 'Needs reconciliation'}{' · '}
          {entry.required_actor === 'none' ? 'No action required' : `Next actor: ${entry.required_actor}`}
          <span className="ml-2 text-muted-foreground">Evidence: {entry.evidence_issue_numbers.map((n) => `#${n}`).join(', ')}</span>
        </li>)}</ul>
      </div>}
    </>}
    <Dialog open={open} onOpenChange={(next) => { if (!saving) setOpen(next) }}>
      <DialogContent><DialogHeader><DialogTitle>Leader backlog coordination</DialogTitle>
        <DialogDescription>Select the issues already assigned to this team. The Leader assesses their remaining work and reviewed gates; selecting issues does not make them dispatch-ready or authorize a merge.</DialogDescription>
      </DialogHeader>
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3"><Label htmlFor={`coordination-enabled-${scopeId}`}>Enable backlog coordination</Label><Switch id={`coordination-enabled-${scopeId}`} checked={enabled} onCheckedChange={setEnabled} disabled={saving} /></div>
          <div><Label htmlFor={`coordination-issues-${scopeId}`}>Assigned issue numbers</Label><Input id={`coordination-issues-${scopeId}`} value={numbers} onChange={(e) => setNumbers(e.target.value)} placeholder="7, 8, 11, 12" disabled={saving} /><p className="mt-1 text-xs text-muted-foreground">At most 32, separated by commas. Include assigned issues that do not yet have the dispatch-ready label.</p></div>
          <div><Label htmlFor={`coordination-minutes-${scopeId}`}>Fallback interval in minutes</Label><Input id={`coordination-minutes-${scopeId}`} inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} disabled={saving} /></div>
          <div><Label htmlFor={`coordination-budget-${scopeId}`}>Maximum coordination notifications per day</Label><Input id={`coordination-budget-${scopeId}`} inputMode="numeric" value={daily} onChange={(e) => setDaily(e.target.value)} disabled={saving} /><p className="mt-1 text-xs text-muted-foreground">At most three notifications for an unchanged backlog. Stable blocked work does not cause a model turn on every poll.</p></div>
          <p className="text-xs text-muted-foreground">Configuration can be staged while autonomy is off. Execution and assessment writes stop while autonomy is off or held.</p>
          {saveError && <p role="alert" className="text-sm text-destructive">{saveError}</p>}
        </div>
        <DialogFooter><Button variant="outline" disabled={saving} onClick={() => setOpen(false)}>Cancel</Button><Button disabled={saving} onClick={() => { void save() }}>{saving ? 'Saving…' : 'Save coordination'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </section>
}
