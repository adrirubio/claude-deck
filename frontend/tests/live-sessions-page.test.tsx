import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CCBridgePage } from '../src/features/cc-bridge/CCBridgePage'
import type { CCSession } from '../src/features/cc-bridge/types'

const mocks = vi.hoisted(() => ({ sessions: [] as unknown[] }))
vi.mock('../src/features/cc-bridge/useCCSessions', () => ({
  useCCSessions: () => ({ sessions: mocks.sessions, loading: false, error: null, refresh: vi.fn() }),
}))
vi.mock('../src/features/cc-bridge/TerminalView', () => ({ TerminalView: () => <p>Terminal</p> }))
vi.mock('../src/features/cc-bridge/TeamLanesView', () => ({
  TeamLanesView: ({ teamLabel }: { teamLabel: string }) => <p>Lanes for {teamLabel}</p>,
}))
vi.mock('../src/features/cc-bridge/NewSessionDialog', () => ({ NewSessionDialog: () => null }))
vi.mock('../src/features/cc-bridge/KillSessionDialog', () => ({ KillSessionDialog: () => null }))
vi.mock('../src/hooks/useSystemStatus', () => ({ useSystemStatus: () => null }))
vi.mock('../src/contexts/ProviderContext', () => ({
  useProviderContext: () => ({ selectedProviderId: 'claude-code', providers: [{ id: 'claude-code', display_name: 'Claude Code', installed: true, capabilities: { spawn: true } }] }),
}))

function session(id: number, team: number, teamName: string): CCSession {
  return {
    provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: `t:0.${id}`, session_name: `s${id}`, window_name: 'w',
    pane_id: `%${id}`, cwd: '/work/demo', pid: '1', status: 'running', team_slot_name: `Member ${id}`, team_preset_id: team,
    team_preset_name: teamName, agent_status: null,
  } as unknown as CCSession
}

afterEach(cleanup)

describe('Live sessions page', () => {
  it('is titled Live sessions with a plain subtitle', () => {
    mocks.sessions = [session(1, 1, 'Alpha')]
    render(<MemoryRouter><CCBridgePage /></MemoryRouter>)

    expect(screen.getByRole('heading', { name: 'Live sessions' })).toBeInTheDocument()
    expect(screen.getByText('Watch your agents work. Up to 4 at a time.')).toBeInTheDocument()
    expect(screen.queryByText(/Agent Bridge/)).toBeNull()
  })

  it('keeps Team lanes enabled with All teams selected and opens a team picker', () => {
    mocks.sessions = [session(1, 1, 'Alpha'), session(2, 2, 'Beta')]
    render(<MemoryRouter><CCBridgePage /></MemoryRouter>)

    const button = screen.getByRole('button', { name: 'Team lanes' })
    expect(button).toBeEnabled()
    fireEvent.click(button)
    const menu = screen.getByRole('menu', { name: 'Choose a team for team lanes' })
    expect(within(menu).getByRole('menuitem', { name: /Alpha/ })).toBeInTheDocument()

    fireEvent.click(within(menu).getByRole('menuitem', { name: /Beta/ }))

    expect(screen.getByText('Lanes for Beta')).toBeInTheDocument()
  })

  it('opens the lanes of the selected team directly', () => {
    mocks.sessions = [session(1, 1, 'Alpha'), session(2, 2, 'Beta')]
    render(<MemoryRouter><CCBridgePage /></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: /^Alpha/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Team lanes' }))

    expect(screen.queryByRole('menu')).toBeNull()
    expect(screen.getByText('Lanes for Alpha')).toBeInTheDocument()
  })
})
