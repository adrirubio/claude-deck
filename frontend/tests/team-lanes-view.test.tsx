import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TeamLanesView } from '../src/features/cc-bridge/TeamLanesView'
import { shiftStart, startToShow } from '../src/features/cc-bridge/teamLanesWindow'
import type { CCSession } from '../src/features/cc-bridge/types'

// A terminal costs one relay. The mock counts how many are mounted at one time.
const relays = vi.hoisted(() => ({ mounted: new Set<string>(), peak: 0 }))
vi.mock('../src/features/cc-bridge/TerminalView', async () => {
  const React = await import('react')
  return {
    TerminalView: ({ target, fullscreen, onToggleFullscreen }: { target: string; fullscreen?: boolean; onToggleFullscreen?: () => void }) => {
      React.useEffect(() => {
        relays.mounted.add(target)
        relays.peak = Math.max(relays.peak, relays.mounted.size)
        return () => { relays.mounted.delete(target) }
      }, [target])
      return (
        <div data-testid={`terminal-${target}`}>
          <button type="button" onClick={onToggleFullscreen}>{fullscreen ? 'Restore' : 'Zoom'} {target}</button>
        </div>
      )
    },
  }
})

const members: CCSession[] = Array.from({ length: 8 }, (_, index) => ({
  provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: `t:0.${index}`, session_name: `s${index}`,
  window_name: 'w', pane_id: `%${index}`, cwd: '/work/demo', pid: '1', status: 'running', team_slot_name: `Member ${index + 1}`,
  team_slot_role: index === 0 ? 'leader' : 'implementer', team_preset_id: 1, team_preset_name: 'Big team', agent_status: null,
} as unknown as CCSession))

function Harness({ onExit = vi.fn() }: { onExit?: () => void }) {
  const [start, setStart] = useState(0)
  const [zoomed, setZoomed] = useState<string | null>(null)
  return (
    <TeamLanesView
      sessions={members}
      start={start}
      zoomed={zoomed}
      teamLabel="Big team"
      focusedTarget={null}
      onFocusTarget={vi.fn()}
      onLeaderNavigate={vi.fn()}
      onLeaderStateChange={vi.fn()}
      onShift={(delta) => setStart((current) => shiftStart(current, members.length, delta))}
      onShowMember={(target) => {
        const index = members.findIndex((member) => member.tmux_target === target)
        setStart((current) => startToShow(current, members.length, index))
        if (zoomed) setZoomed(target)
      }}
      onToggleZoom={(target) => setZoomed((current) => (current === target ? null : target))}
      onExit={onExit}
    />
  )
}

const terminals = () => screen.queryAllByTestId(/^terminal-/).map((element) => element.getAttribute('data-testid'))

afterEach(() => { cleanup(); relays.mounted.clear(); relays.peak = 0 })

describe('TeamLanesView with 8 members', () => {
  it('shows four lanes, the label and a strip with every member', () => {
    render(<Harness />)

    expect(terminals()).toEqual(['terminal-t:0.0', 'terminal-t:0.1', 'terminal-t:0.2', 'terminal-t:0.3'])
    expect(screen.getByText('Showing 1–4 of 8')).toBeInTheDocument()
    const strip = screen.getByRole('navigation', { name: 'Team members' })
    expect(within(strip).getAllByRole('button')).toHaveLength(8)
    expect(within(strip).getByRole('button', { name: /Member 1 / })).toHaveAttribute('aria-pressed', 'true')
    expect(within(strip).getByRole('button', { name: /Member 5 / })).toHaveAttribute('aria-pressed', 'false')
    expect(within(strip).getAllByText('Activity unknown')).toHaveLength(8)
    expect(screen.queryByText(/not shown/)).toBeNull()
  })

  it('shifts through all members and never opens more than four terminals', () => {
    render(<Harness />)

    const right = screen.getByRole('button', { name: 'Show the next member' })
    const left = screen.getByRole('button', { name: 'Show the previous member' })
    expect(left).toBeDisabled()
    for (let step = 1; step <= 4; step += 1) fireEvent.click(right)

    expect(terminals()).toEqual(['terminal-t:0.4', 'terminal-t:0.5', 'terminal-t:0.6', 'terminal-t:0.7'])
    expect(screen.getByText('Showing 5–8 of 8')).toBeInTheDocument()
    expect(right).toBeDisabled()
    expect(left).toBeEnabled()
    expect(relays.peak).toBeLessThanOrEqual(4)
    expect(relays.mounted.size).toBe(4)
    fireEvent.click(left)
    expect(screen.getByText('Showing 4–7 of 8')).toBeInTheDocument()
    expect(terminals()).toEqual(['terminal-t:0.3', 'terminal-t:0.4', 'terminal-t:0.5', 'terminal-t:0.6'])
  })

  it('brings a member from the strip into view', () => {
    render(<Harness />)

    fireEvent.click(within(screen.getByRole('navigation', { name: 'Team members' })).getByRole('button', { name: /Member 7 / }))

    expect(screen.getByText('Showing 4–7 of 8')).toBeInTheDocument()
    expect(terminals()).toContain('terminal-t:0.6')
    expect(relays.mounted.size).toBe(4)
  })

  it('zooms one lane with the same four terminals mounted, and restores them', () => {
    render(<Harness />)
    const before = [...relays.mounted].sort()

    fireEvent.click(screen.getByRole('button', { name: 'Zoom t:0.2' }))

    expect([...relays.mounted].sort()).toEqual(before)
    expect(relays.mounted.size).toBe(4)
    expect(screen.getByTestId('terminal-t:0.2').closest('.hidden')).toBeNull()
    expect(screen.getByTestId('terminal-t:0.0').closest('.hidden')).not.toBeNull()
    expect(screen.queryByRole('button', { name: 'Show the next member' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Restore t:0.2' }))
    expect(screen.getByTestId('terminal-t:0.0').closest('.hidden')).toBeNull()
    expect([...relays.mounted].sort()).toEqual(before)
    expect(screen.getByRole('button', { name: 'Show the next member' })).toBeInTheDocument()
  })

  it('zooms the member that is selected in the strip while a lane is zoomed', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'Zoom t:0.1' }))

    fireEvent.click(within(screen.getByRole('navigation', { name: 'Team members' })).getByRole('button', { name: /Member 6 / }))

    expect(screen.getByText('Showing 3–6 of 8')).toBeInTheDocument()
    expect(screen.getByTestId('terminal-t:0.5').closest('.hidden')).toBeNull()
    expect(relays.peak).toBeLessThanOrEqual(4)
    expect(relays.mounted.size).toBe(4)
  })
})
