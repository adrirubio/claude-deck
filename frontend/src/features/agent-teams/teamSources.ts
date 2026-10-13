import type { AgentSession } from '@/features/cc-bridge/types'
import type { MailMemberResponse } from '@/types/agentMail'
import type { AgentTeamSlotInput } from '@/types/agentTeams'
import type { AgentProviderId } from '@/types/providers'

// The providers that a team slot can use. The backend accepts the same list.
export const PROVIDER_IDS: AgentProviderId[] = ['codex-cli', 'claude-code', 'copilot-cli', 'opencode-cli', 'pi-cli']

// One row of a "create a team from ..." picker.
export interface PickItem {
  id: string
  label: string
  detail: string
  status?: string
  // The name of the team that already holds this member, or null.
  team: string | null
}

export interface PickGroup {
  title: string
  items: PickItem[]
}

/** "Not in a team" first, then one group for each existing team, by name. */
export function groupPickItems(items: PickItem[]): PickGroup[] {
  const free = items.filter((item) => item.team === null)
  const byTeam = new Map<string, PickItem[]>()
  for (const item of items) {
    if (item.team !== null) byTeam.set(item.team, [...(byTeam.get(item.team) ?? []), item])
  }
  return [
    ...(free.length ? [{ title: 'Not in a team', items: free }] : []),
    ...[...byTeam.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([team, rows]) => ({ title: `Already in ${team}`, items: rows })),
  ]
}

/** A folder under /tmp or /var/tmp holds a temporary session. */
export function isTemporaryPath(path: string) {
  return /^\/(var\/)?tmp(\/|$)/.test(path)
}

// ---- From Agent Bridge -----------------------------------------------------

/** A live session that can become a slot: it has a folder and a supported provider. */
export function usableSessions(sessions: AgentSession[]) {
  return sessions.filter((session) => Boolean(session.cwd?.trim()) && PROVIDER_IDS.includes(session.provider))
}

export const sessionKey = (session: AgentSession) => session.tmux_target

export function sessionItems(sessions: AgentSession[]): PickItem[] {
  return usableSessions(sessions).map((session) => ({
    id: sessionKey(session),
    label: session.session_name || folderName(session.cwd),
    detail: `${session.provider_display_name} · ${session.cwd}`,
    team: session.team_preset_name ?? null,
  }))
}

function folderName(path: string) {
  return path.split('/').filter(Boolean).pop() ?? path
}

/**
 * One slot for each selected session. This is the mapping that the backend uses
 * for "create from Agent Bridge": name, provider and folder, in the same order.
 */
export function sessionsToSlots(sessions: AgentSession[]): AgentTeamSlotInput[] {
  return [...sessions]
    .sort((a, b) =>
      a.cwd.localeCompare(b.cwd) || a.provider.localeCompare(b.provider) || a.tmux_target.localeCompare(b.tmux_target))
    .map((session) => ({
      display_name: session.session_name?.trim() || folderName(session.cwd),
      provider: session.provider,
      repo_path: session.cwd,
    }))
}

// ---- From Agent Mail -------------------------------------------------------

export function memberItems(members: MailMemberResponse[]): PickItem[] {
  return members.map((member) => ({
    id: String(member.id),
    label: member.display_name,
    detail: member.repo_path,
    status: member.status,
    team: member.team_preset_id != null ? (member.team_preset_name ?? `team ${member.team_preset_id}`) : null,
  }))
}

/** Offline and temporary members are hidden until the person asks for them. */
export function isHiddenByDefault(member: MailMemberResponse) {
  return member.status === 'offline' || isTemporaryPath(member.repo_path)
}
