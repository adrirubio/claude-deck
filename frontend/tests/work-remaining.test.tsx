import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WorkPublicationPanel } from '../src/features/agent-teams/WorkPublicationPanel'
import { apiClient } from '../src/lib/api'
import type { GithubWorkItem } from '../src/types/agentTeams'

vi.mock('../src/lib/api', () => ({ apiClient: vi.fn() }))
const item = { id: 1, dispatch_nonce: 'dispatch', owner_slot_id: 2, repo_owner: 'owner', repo_name: 'repo',
  dispatch_head_ref: 'task', dispatch_status: 'dispatched', issue_number: 10 } as GithubWorkItem
function progress(state = 'current') {
  return { work_item_id: 1, dispatch_nonce: 'dispatch', owner_slot_id: 2,
    checked_at: new Date().toISOString(), valid_until: new Date(Date.now() + 15000).toISOString(),
    phase: 'implementation', next_actor: 'owner', next_action: 'Continue approved work.',
    next_poll_expected_at: null, last_check_head: null,
    publication: { state: 'current', local_sha: 'a'.repeat(40), published_sha: 'a'.repeat(40),
      unpublished_commits: 0, tracked_changes: null, untracked_files: null, relation: 'synchronized', reason: null },
    remaining_work: { state, remaining: 'Fix the interface, then review and merge.',
      estimate: 'About 30–60 minutes of active work (low confidence; interface fixes).', next_action: 'B2 publishes the next checkpoint.',
      reported_at: new Date().toISOString(), reported_by: 'Team member 3', source_sha: 'a'.repeat(40),
      reason: null, source_url: 'https://malicious.invalid', completed: 'The data service is complete.', assumptions: 'No new review findings.' } }
}
beforeEach(() => { vi.mocked(apiClient).mockReset(); vi.mocked(apiClient).mockResolvedValue(progress()) })
afterEach(() => vi.useRealTimers())

it('shows exactly three short lines and keeps source details in a closed disclosure', async () => {
  render(<WorkPublicationPanel item={item} />)
  const section = await screen.findByRole('region', { name: 'Work remaining' })
  const lines = within(section).getAllByRole('listitem')
  expect(lines).toHaveLength(3)
  expect(lines[0].textContent).toBe('Remaining: Fix the interface, then review and merge.')
  expect(lines[1].textContent).toContain('30–60 minutes of active work (low confidence; interface fixes)')
  expect(lines[2].textContent).toBe('Next: B2 publishes the next checkpoint.')
  expect(within(section).getByText('Report details').parentElement).not.toHaveAttribute('open')
  expect(within(section).getByRole('link', { name: 'Details on GitHub' })).toHaveAttribute('href', 'https://github.com/owner/repo/issues/10#work-remaining')
  expect(section.textContent).not.toMatch(/percent|%|finished by/i)
})

it('keeps historical claims in details and shows Unknown with the authoritative next action', async () => {
  vi.mocked(apiClient).mockResolvedValue(progress('historical'))
  render(<WorkPublicationPanel item={item} />)
  const section = await screen.findByRole('region', { name: 'Work remaining' })
  const lines = within(section).getAllByRole('listitem')
  expect(lines[0].textContent).toContain('No current team report')
  expect(lines[1].textContent).toBe('Estimate: Unknown.')
  expect(lines[2].textContent).toBe('Next: Continue approved work.')
  expect(within(section).getByText('The previous report is out of date.')).toBeTruthy()
})

it('expires a report while refresh hangs and does not restore it after A to B to A', async () => {
  vi.useFakeTimers()
  vi.mocked(apiClient).mockResolvedValueOnce(progress()).mockImplementation(() => new Promise(() => {}))
  const view = render(<WorkPublicationPanel item={item} />)
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByText('Next:').parentElement?.textContent).toContain('B2 publishes')
  await act(async () => { await vi.advanceTimersByTimeAsync(15001) })
  expect(screen.getByText('Estimate:').parentElement?.textContent).toBe('Estimate: Unknown.')
  view.rerender(<WorkPublicationPanel item={{ ...item, id: 2, dispatch_nonce: 'other' }} />)
  view.rerender(<WorkPublicationPanel item={item} />)
  expect(screen.queryByText(/B2 publishes/)).toBeNull()
})

it('shows missing reports without inventing a range and complete items without remaining work', async () => {
  const missing = progress('unavailable')
  Object.assign(missing.remaining_work, { remaining: null, estimate: null, next_action: null,
    reported_at: null, reported_by: null, source_sha: null, completed: null, assumptions: null })
  vi.mocked(apiClient).mockResolvedValueOnce(missing)
  render(<WorkPublicationPanel item={item} />)
  expect((await screen.findByText('Estimate:')).parentElement).toHaveTextContent('Unknown.')
  vi.mocked(apiClient).mockResolvedValue({ ...missing, phase: 'complete', next_actor: 'none' })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh progress' }))
  expect(await screen.findByText('None. This tracked item is complete.', { exact: false })).toBeTruthy()
})
