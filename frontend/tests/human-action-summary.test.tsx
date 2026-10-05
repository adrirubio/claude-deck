import { StrictMode } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HumanActionSummary } from '../src/features/agent-teams/HumanActionSummary'
import { apiClient } from '../src/lib/api'

vi.mock('../src/lib/api', () => ({ apiClient:vi.fn() }))
const pr = { scope_id:1,repo:'o/r',issue_number:11,kind:'review_pr',state:'requested',pull_request_number:38,
  instructions_state:'current',context_request_id:'b'.repeat(24),
  expected_head_sha:'a'.repeat(40),source:'leader',last_assessed_at:'2026-10-04T10:00:00',prerequisite_issue_numbers:[],evidence_issue_numbers:[11] }
const gate = { ...pr,issue_number:8,kind:'pilot_decision',state:'waiting_for_prerequisites',pull_request_number:null,expected_head_sha:null,prerequisite_issue_numbers:[7,11] }
const summary = () => ({ preset_id:1,observation_expires_at:new Date(Date.now()+60000).toISOString(),coverage_complete:true,actions:[pr,gate] })
beforeEach(() => { vi.mocked(apiClient).mockReset();vi.mocked(apiClient).mockImplementation(async () => summary()) })
afterEach(() => vi.useRealTimers())

describe('Human actions above the team tabs', () => {
  it('shows the direct PR action separately from an unready pilot gate', async () => {
    const inspect=vi.fn()
    render(<HumanActionSummary presetId={1} onInspectAutonomy={inspect} />)
    expect(await screen.findByText('1 action requested · 1 decision gate waiting')).toBeTruthy()
    expect(screen.getByRole('link',{name:'Open PR #38'}).getAttribute('href')).toBe('https://github.com/o/r/pull/38')
    expect(screen.getAllByRole('link',{name:'Read action instructions'}).some((link) => link.getAttribute('href')==='https://github.com/o/r/issues/8#current-operator-actions')).toBeTruthy()
    expect(screen.getByText('This decision is not ready. Complete its required evidence first.')).toBeTruthy()
    fireEvent.click(screen.getByText('Open Autonomy details'));expect(inspect).toHaveBeenCalledOnce()
  })
  it('keeps historical requests visible without asserting action readiness or no actions', async () => {
    vi.mocked(apiClient).mockResolvedValue({...summary(),coverage_complete:false,actions:[{...pr,state:'historical'}]})
    render(<HumanActionSummary presetId={1} onInspectAutonomy={() => {}} />)
    expect(await screen.findByText('Last reported — awaiting confirmation')).toBeTruthy()
    expect(screen.getByRole('link',{name:'Open PR #38'})).toBeTruthy()
    expect(screen.queryByText('Operator action requested')).toBeNull()
    expect(screen.queryByText('No pending human actions are currently reported.')).toBeNull()
  })
  it('does not count changed or unavailable PR evidence as a requested action', async () => {
    vi.mocked(apiClient).mockResolvedValue({...summary(),coverage_complete:false,actions:[{...pr,state:'head_changed'},{...gate,state:'pr_unavailable'}]})
    render(<HumanActionSummary presetId={1} onInspectAutonomy={() => {}} />)
    expect(await screen.findByText('0 actions requested · 0 decision gates waiting')).toBeTruthy()
    expect(screen.getByText('PR head changed — Leader confirmation needed')).toBeTruthy()
    expect(screen.getByText('PR status unavailable — verify on GitHub')).toBeTruthy()
  })
  it('removes resolved PRs from pending actions', async () => {
    vi.mocked(apiClient).mockResolvedValue({...summary(),actions:[{...pr,state:'resolved'}]})
    render(<HumanActionSummary presetId={1} onInspectAutonomy={() => {}} />)
    expect(await screen.findByText('No pending human actions are currently reported.')).toBeTruthy()
    expect(screen.queryByRole('link',{name:'Open PR #38'})).toBeNull()
  })
  it('ignores previous-preset and StrictMode responses', async () => {
    let resolveOld: (value:unknown) => void=() => {}
    vi.mocked(apiClient).mockImplementation((path) => path.includes('/1/')
      ? new Promise((resolve) => { resolveOld=resolve }) : Promise.resolve({...summary(),preset_id:2,actions:[]}))
    const view=render(<StrictMode><HumanActionSummary presetId={1} onInspectAutonomy={() => {}} /></StrictMode>)
    view.rerender(<StrictMode><HumanActionSummary presetId={2} onInspectAutonomy={() => {}} /></StrictMode>)
    await screen.findByText('No pending human actions are currently reported.')
    await act(async () => { resolveOld(summary()) })
    expect(screen.queryByRole('link',{name:'Open PR #38'})).toBeNull()
  })
  it('expires retained actions during a stalled refresh and keeps bounded polling', async () => {
    vi.useFakeTimers()
    vi.mocked(apiClient).mockResolvedValueOnce({...summary(),observation_expires_at:new Date(Date.now()+16000).toISOString()})
      .mockImplementation(() => new Promise(() => {}))
    render(<HumanActionSummary presetId={1} onInspectAutonomy={() => {}} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByText('Operator action requested')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(16001) })
    expect(screen.queryByText('Operator action requested')).toBeNull()
    expect(screen.getAllByText('Last reported — awaiting confirmation')).toHaveLength(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
    expect(apiClient).toHaveBeenCalledTimes(3)
  })
  it('expires retained requests when a suspended tab becomes visible', async () => {
    vi.useFakeTimers()
    render(<HumanActionSummary presetId={1} onInspectAutonomy={() => {}} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    vi.setSystemTime(Date.now()+120000)
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })
    expect(screen.queryByText('Operator action requested')).toBeNull()
    expect(screen.getByRole('link',{name:'Open PR #38'})).toBeTruthy()
  })
})
