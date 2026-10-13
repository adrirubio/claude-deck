import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, MoreHorizontal } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { AgentStatusBadges } from '@/components/shared/AgentStatusBadges'
import { Button } from '@/components/ui/button'
import { getTeamSlotColorClasses } from '@/lib/agentTeamColors'
import { cn } from '@/lib/utils'
import { getOperatorToken } from '@/features/agent-teams/operatorAuth'
import { fetchMailWakeAttempts, updateMailWakeParticipation } from './api'
import type { CCSession } from './types'
import type { InstanceIdentity } from '@/types/status'

interface SessionCardProps {
  session: CCSession
  gridPosition: number | null
  onClick: () => void
  onRefresh: () => void
  onKill: (session: CCSession) => void
  instance?: InstanceIdentity | null
}

function normalizeLabel(value: string | null | undefined) {
  return (value ?? '').trim().toLowerCase().replace(/[\s_-]+/g, ' ')
}

export function SessionCard({ session, gridPosition, onClick, onRefresh, onKill, instance }: SessionCardProps) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [attempts, setAttempts] = useState<Awaited<ReturnType<typeof fetchMailWakeAttempts>>['attempts'] | null>(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditError, setAuditError] = useState<string | null>(null)
  const [wakeReason, setWakeReason] = useState('operator_participation_change')
  const [wakeSaving, setWakeSaving] = useState(false)
  const [wakeError, setWakeError] = useState<string | null>(null)
  const [hasOperatorToken, setHasOperatorToken] = useState(() => Boolean(getOperatorToken()))
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const projectName = session.cwd.split('/').pop() || session.cwd
  const isActive = gridPosition !== null
  const teamSlotLabel = session.team_slot_name?.trim()
  const teamRoleLabel = session.team_slot_role?.trim()
  const teamName = session.team_preset_name?.trim()
  const colorClasses = getTeamSlotColorClasses(session.team_slot_color)
  const primaryLabel = teamSlotLabel || session.session_name
  const showRole = Boolean(
    teamRoleLabel && normalizeLabel(teamRoleLabel) !== normalizeLabel(teamSlotLabel)
  )
  const showProject = !teamName || normalizeLabel(projectName) !== normalizeLabel(teamName)
  const contextLine = teamName
    ? `${teamName}${showProject ? ` · ${projectName}` : ''}`
    : projectName
  const contextTitle = teamName
    ? `Team: ${teamName}${showProject ? ` · Repo: ${projectName}` : ''}`
    : session.cwd
  const isMailBound = Boolean(session.mail_member_id && session.mail_mcp_session_id)
  const canUpdateWake = hasOperatorToken && isMailBound

  // The menu closes on Escape and on a click outside it.
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenuOpen(false) }
    const onPointer = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPointer)
    }
  }, [menuOpen])

  async function openDetails() {
    setDetailsOpen((open) => !open)
    const operatorTokenAvailable = Boolean(getOperatorToken())
    setHasOperatorToken(operatorTokenAvailable)
    if (!detailsOpen && operatorTokenAvailable && session.mail_member_id && attempts === null && !auditLoading) {
      setAuditLoading(true)
      setAuditError(null)
      try {
        const result = await fetchMailWakeAttempts(session.mail_member_id)
        setAttempts(result.attempts)
      } catch (error) {
        setAuditError(error instanceof Error ? error.message : 'Could not load wake audit')
      } finally {
        setAuditLoading(false)
      }
    }
  }

  async function handleWakeToggle() {
    if (!session.mail_mcp_session_id || !/^[a-z][a-z0-9_]{2,63}$/.test(wakeReason.trim())) return
    setWakeSaving(true)
    setWakeError(null)
    try {
      await updateMailWakeParticipation(session.mail_mcp_session_id, !session.mail_wake_enabled, wakeReason.trim())
      onRefresh()
    } catch (error) {
      setWakeError(error instanceof Error ? error.message : 'Could not update wake participation')
    } finally {
      setWakeSaving(false)
    }
  }

  return (
    <div className={cn('border-b px-3 py-3 last:border-b-0', isActive && 'bg-primary/5')}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          {session.team_slot_color && (
            <span
              className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', colorClasses.dot)}
              title={`Slot color: ${session.team_slot_color}`}
            />
          )}
          <div className="min-w-0">
            <p className="break-words text-sm font-medium">{primaryLabel}</p>
            <p className="text-xs text-muted-foreground">
              {session.provider_display_name}{showRole ? ` · ${teamRoleLabel}` : ''}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            type="button"
            variant={isActive ? 'default' : 'outline'}
            size="sm"
            className="h-7 px-2 text-xs"
            aria-pressed={isActive}
            aria-label={`${isActive ? 'Stop watching' : 'Watch'} ${primaryLabel}`}
            onClick={onClick}
          >
            {isActive ? `Watching · ${gridPosition + 1}` : 'Watch'}
          </Button>
          <div className="relative" ref={menuRef}>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="h-7 w-7"
              aria-label={`More actions for ${primaryLabel}`}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </Button>
            {menuOpen && (
              <div role="menu" className="absolute right-0 z-20 mt-1 w-40 rounded-md border bg-popover p-1 shadow-md">
                <button
                  type="button"
                  role="menuitem"
                  className="block w-full rounded px-2 py-1.5 text-left text-sm text-destructive hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => { setMenuOpen(false); onKill(session) }}
                >
                  Kill session…
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      <AgentStatusBadges status={session.agent_status} className="mt-2" />
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-muted-foreground">Technical details</summary>
        <div className="mt-2 space-y-1">
          <p className="truncate text-muted-foreground" title={contextTitle}>{contextLine}</p>
          <p className="break-all text-muted-foreground" title={instance ? `${instance.name} · tmux: ${session.tmux_target}` : session.tmux_target}>
            {instance ? `${instance.name} · ` : ''}tmux: {session.tmux_target}
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">{session.mail_member_id ? `Mail member #${session.mail_member_id}` : 'Mail unbound'}</Badge>
            {session.mail_member_name && <span className="truncate" title={session.mail_member_name}>{session.mail_member_name}</span>}
            <span className="text-muted-foreground">Repo: {session.mail_repo_id ?? '—'}</span>
            <Badge variant="outline">
              {session.mail_wake_enabled == null ? 'Wake participation unknown' : `Wake participation ${session.mail_wake_enabled ? 'enabled' : 'disabled'}`}
            </Badge>
          </div>
          <p className="break-all text-muted-foreground">
            MCP binding: {session.mail_mcp_session_id ?? 'none'}
          </p>
          {session.mail_wake_target && (
            <p className="break-all" title="Exact wake target">Wake target: {session.mail_wake_target}</p>
          )}
          <div className="mt-2 flex items-center gap-2">
            <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={openDetails}>
              {detailsOpen ? <ChevronUp className="mr-1 h-3 w-3" /> : <ChevronDown className="mr-1 h-3 w-3" />}
              {detailsOpen ? 'Hide wake details' : 'Wake details'}
            </Button>
            {!canUpdateWake && (
              <span className="text-xs text-muted-foreground">
                {!hasOperatorToken ? 'Director key required · read-only' : 'Exact MCP binding required · read-only'}
              </span>
            )}
          </div>
          {detailsOpen && (
            <div className="mt-2 space-y-2 border-t pt-2">
              {canUpdateWake && (
                <div className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={Boolean(session.mail_wake_enabled)}
                      disabled={wakeSaving || !/^[a-z][a-z0-9_]{2,63}$/.test(wakeReason.trim())}
                      onChange={handleWakeToggle}
                      aria-label={`Enable wake participation for ${session.mail_mcp_session_id}`}
                    />
                    Wake participation {session.mail_wake_enabled ? 'enabled' : 'disabled'}
                  </label>
                  <input
                    className="h-7 min-w-40 flex-1 rounded border bg-background px-2 text-xs"
                    value={wakeReason}
                    onChange={(event) => setWakeReason(event.target.value)}
                    aria-label="Reason code for wake participation change"
                    placeholder="Reason code, for example operator_opt_in"
                  />
                  {wakeSaving && <span className="text-xs text-muted-foreground">Saving…</span>}
                </div>
              )}
              {wakeError && <p className="text-xs text-destructive">{wakeError}</p>}
              <div>
                <p className="text-xs font-medium">Recent wake audit · member #{session.mail_member_id ?? '—'}</p>
                {!hasOperatorToken && <p className="text-xs text-muted-foreground">Director key required to view audit.</p>}
                {!session.mail_member_id && <p className="text-xs text-muted-foreground">No member binding; audit is unavailable.</p>}
                {auditLoading && <p className="text-xs text-muted-foreground">Loading audit…</p>}
                {auditError && <p className="text-xs text-destructive">{auditError}</p>}
                {attempts?.length === 0 && <p className="text-xs text-muted-foreground">No wake attempts recorded.</p>}
                {attempts?.map((attempt) => (
                  <div key={attempt.id} className="mt-1 rounded bg-background p-1.5 text-xs">
                    <p>{attempt.result} · {attempt.reason_code}{attempt.failure_code ? ` · ${attempt.failure_code}` : ''}</p>
                    <p className="break-all text-muted-foreground">Correlation: {attempt.correlation_id}</p>
                    <p className="text-muted-foreground">{new Date(attempt.created_at).toLocaleString()}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </details>
    </div>
  )
}
