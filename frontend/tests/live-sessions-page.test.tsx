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
  TeamLanesView: ({ teamLabel, start, zoomed, sessions, onToggleZoom }: { teamLabel: string; start: number; zoomed: string | null; sessions: Array<{ tmux_target: string }>; onToggleZoom: (target: string) => void }) => (
    <div>
      <p>Lanes for {teamLabel}</p>
      <p>start {start} of {sessions.length}</p>
      <p>{zoomed ? `zoomed ${zoomed}` : 'not zoomed'}</p>
      <button type="button" onClick={() => onToggleZoom(sessions[0].tmux_target)}>zoom first</button>
    </div>
  ),
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

  it('restores the four lanes on the first Escape and exits team lanes on the second', () => {
    mocks.sessions = [session(1, 1, 'Alpha'), session(2, 1, 'Alpha')]
    render(<MemoryRouter><CCBridgePage /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /^Alpha/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Team lanes' }))
    fireEvent.click(screen.getByRole('button', { name: 'zoom first' }))
    expect(screen.getByText('zoomed t:0.1')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByText('Lanes for Alpha')).toBeInTheDocument()
    expect(screen.getByText('not zoomed')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText('Lanes for Alpha')).toBeNull()
  })

  it('shifts the lanes window with Alt+Arrow keys only when no lane is zoomed', () => {
    mocks.sessions = Array.from({ length: 6 }, (_, index) => session(index + 1, 1, 'Alpha'))
    render(<MemoryRouter><CCBridgePage /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /^Alpha/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Team lanes' }))
    expect(screen.getByText('start 0 of 6')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'ArrowRight', altKey: true })
    expect(screen.getByText('start 1 of 6')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'ArrowRight' })
    expect(screen.getByText('start 1 of 6')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'ArrowLeft', altKey: true })
    expect(screen.getByText('start 0 of 6')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'zoom first' }))
    fireEvent.keyDown(document, { key: 'ArrowRight', altKey: true })
    expect(screen.getByText('start 0 of 6')).toBeInTheDocument()
  })
})
