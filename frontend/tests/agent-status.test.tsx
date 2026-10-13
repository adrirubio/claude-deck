import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentStatusBadges } from '../src/components/shared/AgentStatusBadges'
import { agentStatusView, formatIdleDuration } from '../src/lib/agentStatus'
import { TeamTab } from '../src/features/agent-mail/TeamTab'
import { SessionCard } from '../src/features/cc-bridge/SessionCard'
import { AgentTeamsPage } from '../src/features/agent-teams/AgentTeamsPage'
import { fetchAgentTeamPresets, fetchAgentTeamActivity } from '../src/features/agent-teams/api'
import type { MailMemberResponse } from '../src/types/agentMail'
import type { AgentStatus } from '../src/types/agentStatus'
import type { AgentTeamPreset } from '../src/types/agentTeams'
import type { CCSession } from '../src/features/cc-bridge/types'

vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return {
    ...actual,
    fetchAgentTeamPresets: vi.fn(),
    fetchTeamGithubScopes: vi.fn().mockResolvedValue({ scopes: [] }),
    fetchGithubWorkItems: vi.fn().mockResolvedValue({ items: [] }),
    fetchGithubRecoveryGateActive: vi.fn().mockResolvedValue({ active: false }),
    fetchAgentTeamActivity: vi.fn(),
  }
})
vi.mock('../src/features/agent-teams/BacklogCoordination', () => ({ BacklogCoordination: () => null }))
vi.mock('../src/hooks/useProviders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/hooks/useProviders')>()
  return {
    ...actual,
    fetchProviderLaunchOptions: vi.fn(async (provider: string) => ({ provider, supported_launch_modes: ['plain'] })),
  }
})

const HOUR = 3_600_000

/** An idle agent: live MCP session, observation three hours old, wake path found. */
function idleStatus(overrides: Partial<AgentStatus> = {}): AgentStatus {
  const now = Date.now()
  return {
    session_state: 'online',
    activity_state: 'idle',
    activity_reason: 'native_turn_completed',
    wake_state: 'can_wake',
    wake_reason: null,
    idle_since: new Date(now - 3 * HOUR).toISOString(),
    checked_at: new Date(now).toISOString(),
    valid_until: new Date(now + 60_000).toISOString(),
    ...overrides,
  }
}

function expectSameState(root: HTMLElement) {
  const view = within(root)
  expect(view.getByText('Online')).toBeInTheDocument()
  expect(view.getByText('Idle for 3 h')).toBeInTheDocument()
  expect(view.getByText('Can be woken')).toBeInTheDocument()
  expect(view.queryByText(/\bstale\b/i)).not.toBeInTheDocument()
}

const AGENT = 'F2 Frontend'

describe('agentStatusView', () => {
  it('shows an idle duration only when idle_since is known', () => {
    const now = Date.parse('2026-10-12T12:00:00Z')
    const base = idleStatus({ valid_until: '2026-10-12T12:01:00Z' })
    expect(agentStatusView({ ...base, idle_since: '2026-10-12T09:00:00Z' }, now).activity.label).toBe('Idle for 3 h')
    expect(agentStatusView({ ...base, idle_since: null }, now).activity.label).toBe('Idle')
    expect(formatIdleDuration('2026-10-12T12:30:00Z', now)).toBeNull()
  })

  it('shows Unknown for every fact after valid_until', () => {
    const now = Date.parse('2026-10-12T12:00:00Z')
    const status = idleStatus({ valid_until: '2026-10-12T11:59:59Z' })
    const view = agentStatusView(status, now)
    expect(view.current).toBe(false)
    expect(view.session.label).toBe('Status unknown')
    expect(view.activity.label).toBe('Activity unknown')
    expect(view.wake.label).toBe('Wake unknown')
  })

  it('shows the refusal reason when the agent cannot be woken', () => {
    const view = agentStatusView(idleStatus({ wake_state: 'cannot_wake', wake_reason: 'wake_target_ambiguous' }), Date.now())
    expect(view.wake.label).toBe('Cannot be woken')
    expect(view.wake.reason).toBe('More than one session matches this agent.')
  })
})

describe('AgentStatusBadges', () => {
  afterEach(() => vi.useRealTimers())

  it('changes to Unknown when the status expires on screen', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-12T12:00:00Z'))
    render(<AgentStatusBadges status={idleStatus({ valid_until: '2026-10-12T12:00:10Z', idle_since: '2026-10-12T09:00:00Z' })} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(screen.getByText('Online')).toBeInTheDocument()
    expect(screen.getByText('Idle for 3 h')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(11_000) })
    expect(screen.queryByText('Online')).not.toBeInTheDocument()
    expect(screen.getByText('Status unknown')).toBeInTheDocument()
    expect(screen.getByText('Wake unknown')).toBeInTheDocument()
  })

  it('shows the refusal reason beside Cannot be woken', () => {
    render(<AgentStatusBadges status={idleStatus({ wake_state: 'cannot_wake', wake_reason: 'wake_opted_out' })} />)
    expect(screen.getByText('Cannot be woken')).toBeInTheDocument()
    expect(screen.getByText('Wake participation is turned off for this agent.')).toBeInTheDocument()
  })
})

describe('one agent on three pages', () => {
  const member = {
    id: 5, identity_key: 'slot:5', repo_id: 'repo', repo_path: '/tmp/repo', repo_name: 'repo',
    display_name: AGENT, participant_kind: 'team_slot', team_preset_name: 'Release crew', status: 'connected', unread_count: 0,
    pending_count: 0, unseen_pending_count: 0, stale_pending_count: 0, can_nudge: true,
    wake_methods: ['tmux'], wake_state: 'wakeable', sessions: [], agent_status: idleStatus(),
  } as MailMemberResponse

  it('Agent Mail shows online, idle and wake from agent_status', () => {
    const { container } = render(
      <TeamTab members={[member]} loading={false} repoSearch="" statusFilter="all"
        onRepoSearchChange={vi.fn()} onStatusFilterChange={vi.fn()} onEdit={vi.fn()} onCompose={vi.fn()} onQueueInboxCheck={vi.fn()} />,
    )
    expectSameState(container)
  })

  it('Agent Mail ignores the old wake_state field', () => {
    const { container } = render(
      <TeamTab members={[{ ...member, wake_state: 'delivered_waiting', status: 'observed' } as MailMemberResponse]} loading={false}
        repoSearch="" statusFilter="all" onRepoSearchChange={vi.fn()} onStatusFilterChange={vi.fn()} onEdit={vi.fn()}
        onCompose={vi.fn()} onQueueInboxCheck={vi.fn()} />,
    )
    expectSameState(container)
    expect(within(container).queryByText(/Not wakeable|Observed only|Wakeable/)).not.toBeInTheDocument()
  })

  it('Live sessions shows the same state, not the old pane wake state', () => {
    const session = {
      provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: 'deck-e2e-5:0.0', session_name: AGENT,
      window_name: 'w', pane_id: '%5', cwd: '/tmp/repo', pid: '1', status: 'running',
      team_slot_name: AGENT, mail_member_id: 5, mail_mcp_session_id: 7,
      mail_wake_state: 'stale', mail_wake_reason: 'wake_target_stale', agent_status: idleStatus(),
    } as unknown as CCSession
    const { container } = render(<SessionCard session={session} gridPosition={null} onClick={vi.fn()} onRefresh={vi.fn()} onKill={vi.fn()} />)
    expectSameState(container)
  })

  describe('Teams roster', () => {
    const timestamp = '2026-10-12T12:00:00Z'
    const preset = {
      id: 1, name: 'Test team', created_at: timestamp, updated_at: timestamp, autonomy_enabled: false,
      slots: [{
        id: 5, preset_id: 1, position: 1, display_name: AGENT, provider: 'claude-code', repo_id: 'repo',
        repo_path: '/tmp/repo', repo_name: 'repo', launch_mode: 'plain', launch_options: {}, enabled: true,
        created_at: timestamp, updated_at: timestamp,
      }],
    } as unknown as AgentTeamPreset

    beforeEach(() => {
      vi.mocked(fetchAgentTeamPresets).mockResolvedValue({ presets: [preset] })
      vi.mocked(fetchAgentTeamActivity).mockImplementation(async (presetId: number) => {
        const status = idleStatus()
        return {
          preset_id: presetId, checked_at: status.checked_at, valid_until: status.valid_until,
          slots: [{ slot_id: 5, state: 'idle', reason: 'native_turn_completed', observed_at: status.idle_since, agent_status: status }],
        }
      })
    })

    it('shows the same state from the activity agent_status', async () => {
      render(
        <MemoryRouter initialEntries={['/teams/1?tab=roster']}>
          <Routes><Route path="/teams/:teamId" element={<AgentTeamsPage />} /></Routes>
        </MemoryRouter>,
      )
      const name = await screen.findByText(AGENT, { selector: 'p' })
      const card = name.closest('div.rounded-lg') as HTMLElement
      await within(card).findByText('Can be woken')
      // The activity read starts once the team list has loaded (#544), so the badge clock catches up a tick later.
      await within(card).findByText('Idle for 3 h')
      expectSameState(card)
    })
  })
})
