import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionList } from '../src/features/cc-bridge/SessionList'
import type { CCSession } from '../src/features/cc-bridge/types'

function session(over: Partial<CCSession> & { pane_id: string }): CCSession {
  return {
    provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: `coordinator-9d91:0.${over.pane_id}`,
    session_name: `s-${over.pane_id}`, window_name: 'w', cwd: '/work/demo', pid: '4242', status: 'running',
    mail_member_id: 8, mail_mcp_session_id: 7, mail_repo_id: '08523080a62458f4', mail_wake_enabled: null,
    mail_wake_state: 'stale', mail_wake_reason: 'wake_target_stale', agent_status: null,
    ...over,
  } as unknown as CCSession
}

const sessions = [
  session({ pane_id: '1', team_slot_name: 'R1 release implementer with a long role name', team_slot_role: 'implementer', team_preset_name: 'major-release-v3' }),
  session({ pane_id: '2', team_slot_name: 'R2 Leader', team_slot_role: 'leader', team_preset_name: 'major-release-v3' }),
  session({ pane_id: '3', team_slot_name: 'B3 Frontend', team_preset_name: 'other-team' }),
  session({ pane_id: '4', team_slot_name: undefined, session_name: 'solo' }),
]

function renderList(over: Partial<React.ComponentProps<typeof SessionList>> = {}) {
  const props = {
    sessions, loading: false, error: null, activeTargets: [] as string[], onToggleTarget: vi.fn(), onRefresh: vi.fn(),
    onNewSession: vi.fn(), onKillSession: vi.fn(), providerFilter: 'all' as const, teamLabel: null, canCreateSession: true,
    createDisabledReason: null, ...over,
  }
  render(<SessionList {...props} />)
  return props
}

/** The text of an element without its "Technical details" disclosures. */
function plainText(element: Element) {
  const clone = element.cloneNode(true) as Element
  clone.querySelectorAll('details').forEach(details => details.remove())
  return (clone.textContent ?? '').replace(/\s+/g, ' ')
}

afterEach(cleanup)

describe('SessionList', () => {
  it('groups the sessions under their team and puts sessions with no team last', () => {
    renderList()

    const names = screen.getAllByRole('heading', { level: 3 }).map(heading => heading.textContent)
    expect(names).toEqual(['major-release-v3', 'other-team', 'Not in a team'])
    expect(within(screen.getByRole('region', { name: 'major-release-v3' })).getAllByRole('button', { name: /^Watch / })).toHaveLength(2)
  })

  it('shows the full role name, the harness and Watch on a row', () => {
    renderList()

    const row = screen.getByText('R1 release implementer with a long role name').closest('div.border-b') as HTMLElement
    expect(within(row).getByText('Claude Code · implementer')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Watch R1 release implementer with a long role name' })).toBeInTheDocument()
  })

  it('shows no hash, tmux target, Mail member or reason code outside Technical details', () => {
    renderList()

    const text = plainText(screen.getByRole('region', { name: 'major-release-v3' }))
    expect(text).not.toMatch(/tmux|coordinator-9d91|Mail member|MCP binding|08523080a62458f4|wake_target_stale|Repo:/)
    const details = screen.getAllByText('Technical details')[0].closest('details') as HTMLElement
    expect(details).not.toHaveAttribute('open')
    expect(details.textContent).toMatch(/tmux: coordinator-9d91/)
    expect(details.textContent).toMatch(/Mail member #8/)
    expect(details.textContent).toMatch(/Repo: 08523080a62458f4/)
  })

  it('watches a session with the Watch button and marks a watched session', () => {
    const props = renderList({ activeTargets: ['coordinator-9d91:0.2'] })

    fireEvent.click(screen.getByRole('button', { name: 'Watch R1 release implementer with a long role name' }))
    expect(props.onToggleTarget).toHaveBeenCalledWith('coordinator-9d91:0.1')
    const watching = screen.getByRole('button', { name: 'Stop watching R2 Leader' })
    expect(watching).toHaveTextContent('Watching · 1')
    expect(watching).toHaveAttribute('aria-pressed', 'true')
  })

  it('keeps Kill out of the row until the menu opens, and asks through the kill dialog', () => {
    const props = renderList()

    expect(screen.queryByRole('button', { name: /^Kill/ })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: 'Kill session…' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'More actions for R2 Leader' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Kill session…' }))

    expect(props.onKillSession).toHaveBeenCalledWith(expect.objectContaining({ pane_id: '2' }))
    expect(screen.queryByRole('menuitem', { name: 'Kill session…' })).toBeNull()
  })

  it('closes the menu on Escape', () => {
    renderList()

    const button = screen.getByRole('button', { name: 'More actions for R2 Leader' })
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menuitem', { name: 'Kill session…' })).toBeNull()
  })

  it('says Live sessions, not Agent Bridge, in the empty state', () => {
    renderList({ sessions: [], teamLabel: 'major-release-v3' })

    expect(screen.queryByText(/Agent Bridge/)).toBeNull()
    expect(screen.getByText(/New sessions from Live sessions are standalone/)).toBeInTheDocument()
  })
})
