import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentActivity } from '../src/features/agent-teams/useAgentActivity'
import { fetchAgentTeamActivity } from '../src/features/agent-teams/api'

vi.mock('../src/features/agent-teams/api', () => ({ fetchAgentTeamActivity: vi.fn() }))

// #698 check: the Teams activity badges must not blank between two good polls.
// The server says an observation is valid for 15 seconds. The page polls every 5.
function response() {
  return {
    preset_id: 1,
    checked_at: new Date().toISOString(),
    valid_until: new Date(Date.now() + 15_000).toISOString(),
    slots: [{ slot_id: 7, state: 'working' as const, reason: 'native_turn_active', observed_at: new Date().toISOString() }],
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(fetchAgentTeamActivity).mockReset()
})
afterEach(() => vi.useRealTimers())

describe('useAgentActivity', () => {
  it('keeps every badge between good polls, with a slow reply', async () => {
    vi.mocked(fetchAgentTeamActivity).mockImplementation(
      () => new Promise(resolve => { setTimeout(() => resolve(response()), 1_500) }),
    )
    const { result } = renderHook(() => useAgentActivity(1))
    // The first reply arrives after 1.5 seconds. From then on the map is never empty.
    await act(async () => { await vi.advanceTimersByTimeAsync(1_600) })
    expect(result.current.size).toBe(1)
    for (let second = 0; second < 60; second++) {
      await act(async () => { await vi.advanceTimersByTimeAsync(1_000) })
      expect(result.current.get(7)?.state, `second ${second}`).toBe('working')
    }
    expect(vi.mocked(fetchAgentTeamActivity).mock.calls.length).toBeGreaterThan(10)
  })

  it('still empties the map when no poll renews the observation', async () => {
    // Control for the test above: the fake clock does run the 15 second expiry.
    vi.mocked(fetchAgentTeamActivity)
      .mockResolvedValueOnce(response())
      .mockImplementation(() => new Promise(() => {}))
    const { result } = renderHook(() => useAgentActivity(1))
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })
    expect(result.current.size).toBe(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(16_000) })
    expect(result.current.size).toBe(0)
  })
})
