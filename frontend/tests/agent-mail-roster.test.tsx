import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { TeamTab } from '@/features/agent-mail/TeamTab'
import { OTHER_SESSIONS_LABEL, groupRoster, harnessLabel } from '@/features/agent-mail/roster'
import type { AgentStatus } from '@/types/agentStatus'
import type { MailMemberResponse, MailSessionResponse } from '@/types/agentMail'

const NOW = Date.now()

function agentStatus(overrides: Partial<AgentStatus> = {}): AgentStatus {
  return {
    session_state: 'online', activity_state: 'working', activity_reason: 'native_turn_started',
    wake_state: 'can_wake', wake_reason: null, idle_since: null,
    checked_at: new Date(NOW).toISOString(), valid_until: new Date(NOW + 60_000).toISOString(), ...overrides,
  }
}

function session(id: number, overrides: Partial<MailSessionResponse> = {}): MailSessionResponse {
  return {
    id, provider: 'claude-code', source: 'mcp', session_key: `key-${id}`, cwd: `/work/repo-${id}`,
    mailbox_status: 'connected', last_seen_at: '2026-10-13T08:20:00Z', ...overrides,
  } as MailSessionResponse
}

function member(id: number, name: string, team: string | null, overrides: Partial<MailMemberResponse> = {}): MailMemberResponse {
  return {
    id, identity_key: `slot:${id}`, repo_id: 'r', repo_path: `/work/repo-${id}`, repo_name: 'repo', display_name: name,
    participant_kind: team ? 'team_slot' : 'repo', team_preset_name: team, role: 'implementer',
    charter: `Charter of ${name}: a long instruction text.`, status: 'connected', unread_count: 0, pending_count: 0,
    unseen_pending_count: 0, stale_pending_count: 0, can_nudge: false, wake_methods: ['tmux'], wake_state: 'wakeable',
    last_inbox_checked_at: '2026-10-13T08:20:00Z', sessions: [session(id)], agent_status: agentStatus(), ...overrides,
  } as MailMemberResponse
}

const MEMBERS = [
  member(1, 'R1 Leader', 'major-release-v3'),
  member(2, 'R2 release implementer', 'major-release-v3', { agent_status: agentStatus({ activity_state: 'idle' }) }),
  member(3, 'B2 Product Backend', 'product-reposition-fork', {
    pending_count: 4, unread_count: 2, sessions: [session(3, { provider: 'codex-cli' })],
    agent_status: agentStatus({ session_state: 'offline', wake_state: 'cannot_wake', wake_reason: 'wake_target_unbound' }),
  }),
  member(4, 'claude-deck', null, { participant_kind: 'repo', role: null, charter: null, sessions: [session(4, { provider: 'codex-cli' })] }),
  member(5, 'galactus-ubuntu-upgrade', null, { participant_kind: 'repo', role: null, charter: null, sessions: [] }),
]

function renderTab(members = MEMBERS, handlers: Partial<Record<string, unknown>> = {}) {
  const props = {
    onEdit: vi.fn(), onCompose: vi.fn(), onQueueInboxCheck: vi.fn(), onRepoSearchChange: vi.fn(), onStatusFilterChange: vi.fn(),
    ...handlers,
  }
  render(<TeamTab members={members} loading={false} repoSearch="" statusFilter="all" {...(props as object)} />)
  return props as { onEdit: ReturnType<typeof vi.fn>; onCompose: ReturnType<typeof vi.fn>; onQueueInboxCheck: ReturnType<typeof vi.fn> }
}

describe('groupRoster', () => {
  it('groups by team name, then one group for members with no team', () => {
    const groups = groupRoster(MEMBERS)
    expect(groups.map((group) => [group.label, group.members.length])).toEqual([
      ['major-release-v3', 2], ['product-reposition-fork', 1], [OTHER_SESSIONS_LABEL, 2],
    ])
    expect(groups.map((group) => group.isOther)).toEqual([false, false, true])
  })

  it('names the harness in plain words', () => {
    expect(harnessLabel(MEMBERS[0])).toBe('Claude Code')
    expect(harnessLabel(MEMBERS[2])).toBe('Codex')
    expect(harnessLabel(MEMBERS[4])).toBe('No session')
    expect(harnessLabel(member(9, 'x', null, { sessions: [session(9, { provider: 'future-cli' })] }))).toBe('Other harness')
  })
})

describe('Team tab roster', () => {
  it('shows one compact row for each member, grouped under the team name', () => {
    renderTab()
    const first = screen.getByRole('region', { name: 'major-release-v3' })
    expect(within(first).getAllByTestId('roster-row')).toHaveLength(2)
    expect(within(first).getByText('R1 Leader')).toBeInTheDocument()
    expect(within(first).getAllByText('Claude Code')).toHaveLength(2)
    expect(within(first).getByText('Idle')).toBeInTheDocument()
    const second = screen.getByRole('region', { name: 'product-reposition-fork' })
    const row = within(second).getByTestId('roster-row')
    expect(within(row).getByText('Offline')).toBeInTheDocument()
    expect(within(row).getByText('Cannot be woken')).toBeInTheDocument()
    expect(within(row).getByText('Codex')).toBeInTheDocument()
    expect(within(row).getByText(/4 not acknowledged/)).toBeInTheDocument()
    expect(within(row).getByText('2 unread')).toBeInTheDocument()
  })

  it('shows no charter, path or session until the row is expanded', () => {
    renderTab()
    expect(screen.queryByText(/Charter of R1 Leader/)).not.toBeInTheDocument()
    expect(screen.queryAllByText('/work/repo-1')).toHaveLength(0)
    expect(screen.queryByText(/Sessions \(/)).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: 'Show details of R1 Leader' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAccessibleName('Hide details of R1 Leader')
    expect(screen.getByText(/Charter of R1 Leader/)).toBeInTheDocument()
    expect(screen.getAllByText('/work/repo-1').length).toBeGreaterThan(0)
    expect(screen.getByText('Sessions (1)')).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.queryByText(/Charter of R1 Leader/)).not.toBeInTheDocument()
  })

  it('collapses the members with no team into one group that Show opens', () => {
    renderTab()
    expect(screen.getByText(`${OTHER_SESSIONS_LABEL} · 2`)).toBeInTheDocument()
    expect(screen.queryByText('claude-deck')).not.toBeInTheDocument()
    const group = screen.getByRole('region', { name: OTHER_SESSIONS_LABEL })
    fireEvent.click(within(group).getByRole('button', { name: /Show/ }))
    expect(within(group).getByText('claude-deck')).toBeInTheDocument()
    expect(within(group).getByText('galactus-ubuntu-upgrade')).toBeInTheDocument()
    expect(within(group).getByRole('button', { name: /Hide/ })).toHaveAttribute('aria-expanded', 'true')
  })

  it('has one row menu instead of four buttons, with Message and Edit first', () => {
    const handlers = renderTab()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Handoff' })).not.toBeInTheDocument()
    const trigger = screen.getByRole('button', { name: 'Actions for R1 Leader' })
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    const menu = screen.getByRole('menu', { name: 'Actions for R1 Leader' })
    const items = within(menu).getAllByRole('menuitem').map((item) => item.textContent)
    expect(items).toEqual(['Message', 'Edit', 'Request context', 'Handoff'])
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Message' }))
    expect(handlers.onCompose).toHaveBeenCalledWith('message', MEMBERS[0])
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Actions for R1 Leader' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    expect(handlers.onEdit).toHaveBeenCalledWith(MEMBERS[0])
    fireEvent.click(screen.getByRole('button', { name: 'Actions for R1 Leader' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Handoff' }))
    expect(handlers.onCompose).toHaveBeenCalledWith('handoff', MEMBERS[0])
  })

  it('closes the menu with Escape and moves focus with the arrow keys', async () => {
    renderTab()
    const trigger = screen.getByRole('button', { name: 'Actions for R1 Leader' })
    fireEvent.click(trigger)
    const items = screen.getAllByRole('menuitem')
    await waitFor(() => expect(document.activeElement).toBe(items[0]))
    fireEvent.keyDown(items[0], { key: 'ArrowDown' })
    expect(document.activeElement).toBe(items[1])
    fireEvent.keyDown(items[1], { key: 'ArrowUp' })
    fireEvent.keyDown(items[0], { key: 'ArrowUp' })
    expect(document.activeElement).toBe(items[items.length - 1])
    fireEvent.keyDown(items[items.length - 1], { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(document.activeElement).toBe(trigger)
  })

  it('offers Queue inbox check only when a wake path exists and mail waits', () => {
    const waiting = member(7, 'R7', 'team-x', { can_nudge: true, unread_count: 1 })
    const handlers = renderTab([waiting, member(8, 'R8', 'team-x', { can_nudge: true })])
    fireEvent.click(screen.getByRole('button', { name: 'Actions for R7' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Queue inbox check' }))
    expect(handlers.onQueueInboxCheck).toHaveBeenCalledWith(waiting)
    fireEvent.click(screen.getByRole('button', { name: 'Actions for R8' }))
    expect(screen.queryByRole('menuitem', { name: 'Queue inbox check' })).not.toBeInTheDocument()
  })

  it('keeps the search and the status filter, and the empty states', () => {
    render(<TeamTab members={[]} loading={false} repoSearch="" statusFilter="all" onRepoSearchChange={vi.fn()}
      onStatusFilterChange={vi.fn()} onEdit={vi.fn()} onCompose={vi.fn()} onQueueInboxCheck={vi.fn()} />)
    expect(screen.getByPlaceholderText('Search repos, roles, charters')).toBeInTheDocument()
    expect(screen.getByText('No participants match the current filters.')).toBeInTheDocument()
  })

  it('filters the roster by the search text', () => {
    render(<TeamTab members={MEMBERS} loading={false} repoSearch="backend" statusFilter="all" onRepoSearchChange={vi.fn()}
      onStatusFilterChange={vi.fn()} onEdit={vi.fn()} onCompose={vi.fn()} onQueueInboxCheck={vi.fn()} />)
    expect(screen.getByText('B2 Product Backend')).toBeInTheDocument()
    expect(screen.queryByText('R1 Leader')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'major-release-v3' })).not.toBeInTheDocument()
  })
})
