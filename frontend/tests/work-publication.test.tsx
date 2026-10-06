import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkPublicationPanel } from '../src/features/agent-teams/WorkPublicationPanel'
import { apiClient } from '../src/lib/api'
import type { GithubWorkItem } from '../src/types/agentTeams'

vi.mock('../src/lib/api', () => ({ apiClient: vi.fn() }))
const item = { id: 1, dispatch_nonce: 'dispatch', owner_slot_id: 2, repo_owner: 'owner', repo_name: 'repo',
  dispatch_head_ref: 'task', dispatch_status: 'dispatched', issue_number: 10 } as GithubWorkItem
function progress(changes = {}) {
  return { work_item_id: 1, dispatch_nonce: 'dispatch', owner_slot_id: 2,
    checked_at: new Date(Date.now()).toISOString(), valid_until: new Date(Date.now() + 15000).toISOString(),
    phase: 'implementation', next_actor: 'owner', next_action: 'Continue approved work.',
    next_poll_expected_at: null, last_check_head: null,
    publication: { state: 'current', observed_at: new Date(Date.now()).toISOString(), local_sha: 'a'.repeat(40),
      published_sha: 'b'.repeat(40), unpublished_commits: 2, tracked_changes: null, untracked_files: null,
      relation: 'ahead', reason: null, file_counts_reason: 'safe_metadata_read',
      publication_first_observed_at: new Date(Date.now()).toISOString(),
      publication_time_source: 'github_head_observation', destination_url: 'https://malicious.invalid/' }, ...changes }
}
beforeEach(() => { vi.mocked(apiClient).mockReset(); vi.mocked(apiClient).mockResolvedValue(progress()) })
afterEach(() => vi.useRealTimers())

describe('Work publication observations', () => {
  it('shows a compact exact commit gap, source time and truthful unavailable file counts', async () => {
    render(<WorkPublicationPanel item={item} ownerName="B2" />)
    expect(await screen.findByText('2 unpublished commits')).toBeTruthy()
    expect(screen.getByText(/Next actor/).textContent).toContain('B2')
    expect(screen.getByText(/File-change counts are unavailable/)).toBeTruthy()
    expect(screen.getByText(/Push time is unavailable/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Open assigned branch on GitHub' }).getAttribute('href')).toBe('https://github.com/owner/repo/tree/task')
    expect(screen.getByText('Source and publication details').parentElement).not.toHaveAttribute('open')
    expect(apiClient).toHaveBeenCalledTimes(1)
    expect(apiClient).toHaveBeenCalledWith('agent-teams/github-work-items/1/progress', expect.objectContaining({ cache: 'no-store', signal: expect.any(AbortSignal) }))
  })
  it('does not treat matching commits as a clean tree or review acceptance', async () => {
    const value = progress(); value.publication.relation = 'synchronized'; value.publication.unpublished_commits = 0
    vi.mocked(apiClient).mockResolvedValue(value)
    render(<WorkPublicationPanel item={item} />)
    expect(await screen.findByText('Local HEAD matches the published SHA')).toBeTruthy()
    expect(screen.getByText(/Matching commits do not establish/)).toBeTruthy()
    expect(screen.getByText(/do not prove review acceptance/)).toBeTruthy()
  })
  it('shows divergence and historical counts without claiming a current gap', async () => {
    const value = progress(); value.publication.relation = 'diverged'
    vi.mocked(apiClient).mockResolvedValue(value)
    const view = render(<WorkPublicationPanel item={item} />)
    expect(await screen.findByText('Branches have diverged · 2 local commits are unpublished')).toBeTruthy()
    value.publication.state = 'historical'; value.publication.reason = 'workspace_not_leased'
    vi.mocked(apiClient).mockResolvedValue({ ...value })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh progress' }))
    expect(await screen.findByText('Previous publication observation')).toBeTruthy()
    expect(screen.queryByText('2 unpublished commits')).toBeNull()
    view.unmount()
  })
  it('expires observations during a hanging refresh and bounds that request', async () => {
    vi.useFakeTimers()
    vi.mocked(apiClient).mockResolvedValueOnce(progress()).mockImplementation(() => new Promise(() => {}))
    render(<WorkPublicationPanel item={item} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByText('2 unpublished commits')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(15001) })
    expect(screen.queryByText('2 unpublished commits')).toBeNull()
    expect(screen.getByText('Previous publication observation')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(12000) })
    expect(screen.getByText(/Unable to refresh progress/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Refresh progress' })).not.toBeDisabled()
    expect(apiClient).toHaveBeenCalledTimes(2)
  })
  it('hides prior phase evidence immediately when work status changes', async () => {
    vi.mocked(apiClient).mockResolvedValueOnce(progress()).mockImplementation(() => new Promise(() => {}))
    const view = render(<WorkPublicationPanel item={item} />)
    await screen.findByText('2 unpublished commits')
    view.rerender(<WorkPublicationPanel item={{ ...item, dispatch_status: 'ready_for_review' }} />)
    expect(screen.queryByText('2 unpublished commits')).toBeNull()
    expect(screen.queryByText('Continue approved work.')).toBeNull()
  })
  it('rejects mismatched dispatch data and cancels a request on unmount', async () => {
    vi.mocked(apiClient).mockResolvedValue(progress({ dispatch_nonce: 'old-dispatch' }))
    const view = render(<WorkPublicationPanel item={item} />)
    expect(await screen.findByText(/Unable to refresh progress/)).toBeTruthy()
    expect(screen.queryByText('2 unpublished commits')).toBeNull()
    const options = vi.mocked(apiClient).mock.calls[0][1]
    view.unmount()
    expect(options?.signal?.aborted).toBe(true)
  })
  it('distinguishes an ended owner turn from completed work and human review', async () => {
    vi.mocked(apiClient).mockResolvedValue(progress({ phase: 'review', next_actor: 'operator', next_action: 'Read the issue summary.' }))
    render(<WorkPublicationPanel item={{ ...item, dispatch_status: 'ready_for_review' }} ownerActivity={{ slot_id: 2, state: 'idle', reason: 'native_turn_completed', observed_at: new Date().toISOString() }} />)
    expect(await screen.findByText('Read the issue summary.')).toBeTruthy()
    expect(screen.getByText(/completed turn does not establish/)).toBeTruthy()
    expect(screen.getByText(/Next actor/).textContent).toContain('Operator')
  })
})


it('does not restore prior current data across A to B to A', async () => {
  vi.mocked(apiClient).mockResolvedValueOnce(progress()).mockImplementation(() => new Promise(() => {}))
  const view = render(<WorkPublicationPanel item={item} />)
  await screen.findByText('2 unpublished commits')
  view.rerender(<WorkPublicationPanel item={{ ...item, id: 2, dispatch_nonce: 'other' }} />)
  view.rerender(<WorkPublicationPanel item={item} />)
  expect(screen.queryByText('2 unpublished commits')).toBeNull()
  expect(screen.queryByText('Continue approved work.')).toBeNull()
  expect(screen.queryByText(/Next actor:/)).toBeNull()
})

it('renders the current design human-review instruction', async () => {
  vi.mocked(apiClient).mockResolvedValue(progress({ phase: 'review', next_actor: 'operator', next_action: 'Read the human summary and review the design PR.' }))
  render(<WorkPublicationPanel item={{ ...item, dispatch_status: 'awaiting_human_review' }} />)
  expect(await screen.findByText('Read the human summary and review the design PR.')).toBeTruthy()
  expect(screen.getByText(/Next actor/).textContent).toContain('Operator')
})
