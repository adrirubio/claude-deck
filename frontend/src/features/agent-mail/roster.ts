import type { MailMemberResponse, MailSessionResponse } from '@/types/agentMail'

// #530: the compact roster of the Team tab. This module only groups and
// labels what the page already loads.

export const OTHER_SESSIONS_LABEL = 'Other sessions (not in a team)'

const HARNESS_LABELS: Record<string, string> = {
  'claude-code': 'Claude Code',
  'codex-cli': 'Codex',
  'copilot-cli': 'GitHub Copilot CLI',
  'opencode-cli': 'OpenCode CLI',
  'pi-cli': 'Pi',
}

/** The plain harness name of a member, from its first session. The data has no model name. */
export function harnessLabel(member: MailMemberResponse): string {
  const provider = member.sessions[0]?.provider
  if (!provider) return 'No session'
  return HARNESS_LABELS[provider] ?? 'Other harness'
}

export interface RosterGroup {
  key: string
  label: string
  /** The group of members that belong to no team. It starts collapsed. */
  isOther: boolean
  members: MailMemberResponse[]
}

/** Team groups by name, then one group for members with no team. */
export function groupRoster(members: MailMemberResponse[]): RosterGroup[] {
  const teams = new Map<string, MailMemberResponse[]>()
  const others: MailMemberResponse[] = []
  for (const member of members) {
    if (member.participant_kind === 'team_slot' && member.team_preset_name) {
      const list = teams.get(member.team_preset_name) ?? []
      list.push(member)
      teams.set(member.team_preset_name, list)
    } else {
      others.push(member)
    }
  }
  const groups: RosterGroup[] = [...teams.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, list]) => ({ key: `team:${label}`, label, isOther: false, members: list }))
  if (others.length > 0) {
    groups.push({ key: 'other', label: OTHER_SESSIONS_LABEL, isOther: true, members: others })
  }
  return groups
}

/** Messages that wait for an answer or an acknowledgement. */
export function notAcknowledged(member: MailMemberResponse): number {
  return member.pending_count
}

export interface DisplaySession extends MailSessionResponse {
  bridgeObserved: boolean
}

function sameRuntime(session: MailSessionResponse, observation: MailSessionResponse): boolean {
  return Boolean(
    session.provider === observation.provider &&
      session.cwd &&
      observation.cwd &&
      session.cwd === observation.cwd
  )
}

function hasConnectedReplacement(session: MailSessionResponse, sessions: MailSessionResponse[]): boolean {
  if (session.source !== 'mcp' || session.mailbox_status !== 'offline') {
    return false
  }
  return sessions.some(
    (candidate) =>
      candidate.id !== session.id &&
      candidate.source === 'mcp' &&
      candidate.mailbox_status === 'connected' &&
      sameRuntime(candidate, session)
  )
}

/** The sessions to list: a superseded session and a folded Bridge observation are hidden. */
export function displaySessions(sessions: MailSessionResponse[]): DisplaySession[] {
  const bridgeObservations = sessions.filter((session) => session.source === 'observed')
  const foldedBridgeIds = new Set<number>()
  const supersededSessionIds = new Set(
    sessions
      .filter((session) => hasConnectedReplacement(session, sessions))
      .map((session) => session.id)
  )

  const communicativeSessions = sessions.filter((session) => !supersededSessionIds.has(session.id)).map((session) => {
    if (session.source === 'observed' || session.mailbox_status !== 'connected') {
      return { ...session, bridgeObserved: false }
    }

    const bridgeObservation = bridgeObservations.find(
      (observation) => !foldedBridgeIds.has(observation.id) && sameRuntime(session, observation)
    )
    if (!bridgeObservation) {
      return { ...session, bridgeObserved: false }
    }

    foldedBridgeIds.add(bridgeObservation.id)
    return { ...session, bridgeObserved: true }
  })

  return communicativeSessions.filter((session) => !foldedBridgeIds.has(session.id))
}
