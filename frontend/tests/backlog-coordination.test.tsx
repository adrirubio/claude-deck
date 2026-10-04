import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BacklogCoordination } from '../src/features/agent-teams/BacklogCoordination'
import { apiClient } from '../src/lib/api'

vi.mock('../src/lib/api', () => ({ apiClient: vi.fn() }))
const summary = {
  scope_id: 1, repo: 'o/r', enabled: true, version: 1, issue_numbers: [7, 8],
  fallback_seconds: 1800, max_daily_requests: 12, requests_today: 1,
  status: 'assessed', last_polled_at: '2026-10-04T10:00:00', last_assessed_at: '2026-10-04T10:00:00',
  active_implementations: 0, execution_limit: 2, available_workspaces: 1, leased_workspaces: 1,
  eligible_count: 0, assessment_current: true,
  entries: [
    { issue_number: 7, disposition: 'human_decision_blocked', reason: 'human_merge', required_actor: 'operator', evidence_issue_numbers: [7] },
    { issue_number: 8, disposition: 'human_decision_blocked', reason: 'pilot_decision', required_actor: 'operator', evidence_issue_numbers: [7, 8] },
  ],
}
const withToken = <T,>(action: (token: string) => Promise<T>) => action('fixture-token')
beforeEach(() => { vi.mocked(apiClient).mockReset(); vi.mocked(apiClient).mockResolvedValue(summary) })

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
})
