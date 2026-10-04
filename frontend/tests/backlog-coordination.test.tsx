import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BacklogCoordination } from '../src/features/agent-teams/BacklogCoordination'
import { apiClient } from '../src/lib/api'

vi.mock('../src/lib/api', () => ({ apiClient: vi.fn() }))
const summary = {
  scope_id: 1, repo: 'o/r', enabled: true, version: 1, issue_numbers: [7, 8],
  fallback_seconds: 1800, max_daily_requests: 12, requests_today: 1,
  status: 'assessed', last_polled_at: '2026-10-04T10:00:00', last_assessed_at: '2026-10-04T10:00:00',
  observation_expires_at: new Date(Date.now() + 120000).toISOString(),
  active_implementations: 0, execution_limit: 2, available_workspaces: 1, leased_workspaces: 1,
  eligible_count: 0, assessment_current: true,
  entries: [
    { issue_number: 7, disposition: 'human_decision_blocked', reason: 'human_merge', required_actor: 'operator', evidence_issue_numbers: [7] },
    { issue_number: 8, disposition: 'human_decision_blocked', reason: 'pilot_decision', required_actor: 'operator', evidence_issue_numbers: [7, 8] },
  ],
}
const withToken = <T,>(action: (token: string) => Promise<T>) => action('fixture-token')
beforeEach(() => { vi.mocked(apiClient).mockReset(); vi.mocked(apiClient).mockResolvedValue(summary) })
afterEach(() => vi.useRealTimers())

describe('Leader backlog coordination', () => {
  it('shows why no implementation is eligible, capacity and the required actor', async () => {
    render(<BacklogCoordination scopeId={1} withOperatorToken={withToken} />)
    expect(await screen.findByText('No eligible implementation work')).toBeTruthy()
    expect(screen.getByText(/operator pilot decision is required/)).toBeTruthy()
    expect(screen.getByText(/Last observed execution: 0\/2/)).toBeTruthy()
    expect(document.querySelector('.agent-working-pulse')).toBeNull()
  })
  it('distinguishes a current eligible assessment from Leader admission', async () => {
    vi.mocked(apiClient).mockResolvedValue({ ...summary, eligible_count: 1 })
    render(<BacklogCoordination scopeId={1} withOperatorToken={withToken} />)
    expect(await screen.findByText('1 item assessed as eligible')).toBeTruthy()
    expect(screen.getByText(/Leader must verify its gates and admit it/)).toBeTruthy()
  })
  it('does not present stale assessments as verified empty eligibility', async () => {
    vi.mocked(apiClient).mockResolvedValue({ ...summary, status: 'stale', assessment_current: false, eligible_count: null })
    render(<BacklogCoordination scopeId={1} withOperatorToken={withToken} />)
    expect(await screen.findByText('Backlog observations are stale')).toBeTruthy()
    expect(screen.getByText('Previous assessment — not current eligibility')).toBeTruthy()
    expect(screen.queryByText('No eligible implementation work')).toBeNull()
  })
  it('rejects duplicated assigned numbers before an operator mutation', async () => {
    const token = vi.fn(withToken)
    render(<BacklogCoordination scopeId={1} withOperatorToken={token} />)
    await screen.findByText('No eligible implementation work')
    fireEvent.click(screen.getByText('Configure backlog'))
    fireEvent.change(screen.getByLabelText('Assigned issue numbers'), { target: { value: '7,7' } })
    fireEvent.click(screen.getByText('Save coordination'))
    expect(await screen.findByText('Select at most 32 distinct issue numbers.')).toBeTruthy()
    expect(token).not.toHaveBeenCalled()
  })
  it('stages a version-checked policy without enabling autonomy', async () => {
    render(<BacklogCoordination scopeId={1} withOperatorToken={withToken} />)
    await screen.findByText('No eligible implementation work')
    fireEvent.click(screen.getByText('Configure backlog'))
    fireEvent.change(screen.getByLabelText('Assigned issue numbers'), { target: { value: '7,8,11' } })
    fireEvent.click(screen.getByText('Save coordination'))
    await waitFor(() => expect(apiClient).toHaveBeenCalledWith(
      'agent-teams/github-scopes/1/coordination-policy', expect.objectContaining({
        method: 'PUT', headers: { 'X-Deck-Operator-Token': 'fixture-token' },
        body: JSON.stringify({ expected_version: 1, enabled: true, issue_numbers: [7, 8, 11], fallback_seconds: 1800, max_daily_requests: 12 }),
      }),
    ))
  })
  it('ignores obsolete StrictMode and previous-scope responses', async () => {
    let resolveOld: (value: unknown) => void = () => {}
    vi.mocked(apiClient).mockImplementation((path) => path.includes('/1/')
      ? new Promise((resolve) => { resolveOld = resolve })
      : Promise.resolve({ ...summary, scope_id: 2, repo: 'o/new', status: 'unknown', assessment_current: false }))
    const view = render(<StrictMode><BacklogCoordination scopeId={1} withOperatorToken={withToken} /></StrictMode>)
    view.rerender(<StrictMode><BacklogCoordination scopeId={2} withOperatorToken={withToken} /></StrictMode>)
    await screen.findByText('Backlog has not been observed yet')
    resolveOld(summary)
    await waitFor(() => expect(screen.queryByText('No eligible implementation work')).toBeNull())
  })
  it('expires retained eligibility and bounds a pending refresh before polling again', async () => {
    vi.useFakeTimers()
    const now = Date.now()
    vi.mocked(apiClient).mockResolvedValueOnce({ ...summary, observation_expires_at: new Date(now + 16000).toISOString() })
      .mockImplementation(() => new Promise(() => {}))
    render(<BacklogCoordination scopeId={1} withOperatorToken={withToken} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByText('No eligible implementation work')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(16001) })
    expect(screen.queryByText('No eligible implementation work')).toBeNull()
    expect(screen.getByText('Backlog observations are stale')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(screen.getByText('Coordination status is unavailable')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
    expect(apiClient).toHaveBeenCalledTimes(3)
  })
  it('expires retained eligibility when a suspended tab becomes visible', async () => {
    vi.useFakeTimers()
    render(<BacklogCoordination scopeId={1} withOperatorToken={withToken} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByText('No eligible implementation work')).toBeTruthy()
    vi.setSystemTime(Date.now() + 180000)
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })
    expect(screen.queryByText('No eligible implementation work')).toBeNull()
    expect(screen.getByText('Previous assessment — not current eligibility')).toBeTruthy()
  })
})
