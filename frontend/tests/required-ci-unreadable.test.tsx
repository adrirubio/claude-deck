import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TeamSummaryCard } from '../src/features/agent-teams/TeamSummaryCard'
import { RequiredCiNotice, requiredCiReason } from '../src/features/factory/components/RequiredCiNotice'
import { WorkDetailPage } from '../src/features/factory/pages/WorkDetailPage'
import { WorkPage } from '../src/features/factory/pages/WorkPage'
import { stateLabel } from '../src/features/factory/filterHelpers'
import { resetFactoryReads } from '../src/features/factory/reads'
import type { AgentTeamSummary, RequiredCIUnreadableSignal } from '../src/types/agentTeams'
import detail from './fixtures/factory/v1-p04/work-item.json'
import work from './fixtures/factory/v1-p04/work-items.json'
import { fixtureFetch, jsonResponse, renderRoute, settle } from './helpers/factory'

// #550 (frontend half, #622): one item whose required CI cannot be read shows
// the warning on the team card, the Work item page and the Work list.
vi.mock('../src/features/agent-teams/WorkPublicationPanel', () => ({ WorkPublicationPanel: () => null }))
vi.mock('../src/features/agent-teams/useAgentActivity', () => ({ useAgentActivity: () => new Map() }))

beforeEach(() => resetFactoryReads())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const signal: RequiredCIUnreadableSignal = {
  code: 'required_ci_unreadable',
  label: 'Required CI cannot be read',
  since: '2026-10-12T10:00:00Z',
  reason: 'permission_missing',
  next_steps: [
    'Check GitHub access and the configured required workflows.',
    'Deck will poll again. Unreadable checks do not grant verification or consume a retry.',
  ],
}

const stamp = '2026-10-12T12:00:00Z'
function summary(overrides: Partial<AgentTeamSummary> = {}): AgentTeamSummary {
  return {
    preset_id: 1, description: 'Ship it.', parent_issue_url: null, supervisor: 'none',
    checked_at: stamp, valid_until: '2026-10-12T12:00:15Z', coverage_complete: true, hold_code: null,
    attention: [], human_actions: [],
    remaining_work: { state: 'known', unfinished_items: 1, reported_items: 1, confidence: 'unknown', reason: 'complete' },
    next_actors: [], next_actor_coverage_complete: true, ...overrides,
  }
}

describe('team summary card', () => {
  it('lists the item with its reason and next step, and links to it', async () => {
    fixtureFetch(() => jsonResponse(summary({
      required_ci_unreadable: [{ ...signal, work_item_id: 12, scope_id: 3, issue_number: 102 }],
    })))
    renderRoute(<TeamSummaryCard presetId={1} />, '/', '/')
    await settle()
    const row = screen.getByText(/Required CI cannot be read on/).closest('li')!
    expect(within(row).getByRole('link', { name: '#102' })).toHaveAttribute('href', '/work/12')
    expect(row).toHaveTextContent('The GitHub token or App has no permission to read the checks.')
    expect(row).toHaveTextContent('Check GitHub access and the configured required workflows.')
    expect(screen.queryByText('None open.')).not.toBeInTheDocument()
  })

  it.each([undefined, []])('shows nothing about CI when the list is %j', async (value) => {
    fixtureFetch(() => jsonResponse(summary({ required_ci_unreadable: value })))
    renderRoute(<TeamSummaryCard presetId={1} />, '/', '/')
    await settle()
    expect(screen.queryByText(/Required CI cannot be read/)).not.toBeInTheDocument()
    expect(screen.getByText('None open.')).toBeInTheDocument()
  })
})

describe('Work item page', () => {
  const base = detail.awaiting_human_review.response
  const serve = (item: Record<string, unknown>) =>
    fixtureFetch((path) => path.startsWith('factory/work-items/')
      ? jsonResponse({ ...base, work_item: { ...base.work_item, item: { ...base.work_item.item, ...item } } })
      : jsonResponse({}, 404))

  it('shows the warning with the reason and the next steps from the wire', async () => {
    serve({ required_ci_unreadable: signal, pr_number: 202 })
    renderRoute(<WorkDetailPage />, '/work/2', '/work/:workItemId')
    await settle()
    const block = screen.getByRole('region', { name: 'Required CI cannot be read' })
    expect(within(block).getByRole('heading')).toHaveTextContent('Required CI cannot be read')
    expect(block).toHaveTextContent('Deck cannot read the required checks for PR #202')
    expect(block).toHaveTextContent('The GitHub token or App has no permission to read the checks.')
    expect(within(block).getAllByRole('listitem')).toHaveLength(2)
    expect(block).toHaveTextContent('Check GitHub access')
  })

  it('shows no warning when the signal is null', async () => {
    serve({ required_ci_unreadable: null })
    renderRoute(<WorkDetailPage />, '/work/2', '/work/:workItemId')
    await settle()
    expect(screen.queryByText('Required CI cannot be read')).not.toBeInTheDocument()
  })
})

describe('Work list', () => {
  const page = work.first_page.response
  it('adds a CI unreadable badge to that item only, and keeps the state word', async () => {
    const items = page.items.map((row, index) => index === 0
      ? { ...row, item: { ...row.item, required_ci_unreadable: signal } } : row)
    fixtureFetch((path) => path === 'factory/work-items' ? jsonResponse({ ...page, items }) : jsonResponse({}, 404))
    renderRoute(<WorkPage />, '/work')
    await settle()
    const badges = screen.getAllByText('CI unreadable')
    expect(badges).toHaveLength(1)
    const row = badges[0].closest('tr')!
    expect(within(row).getByText(stateLabel(page.items[0] as never))).toBeInTheDocument()
  })

  it('shows no badge when no item has the signal', async () => {
    fixtureFetch((path) => path === 'factory/work-items' ? jsonResponse(page) : jsonResponse({}, 404))
    renderRoute(<WorkPage />, '/work')
    await settle()
    expect(screen.queryByText('CI unreadable')).not.toBeInTheDocument()
  })
})

describe('reason text', () => {
  it.each(['permission_missing', 'workflow_missing', 'api_error', 'unknown'] as const)('has fixed text for %s', (reason) => {
    expect(requiredCiReason(reason)).toMatch(/\.$/)
  })

  it('never shows a raw server string', () => {
    expect(requiredCiReason('401 Unauthorized: token ghp_secret')).toBe('Deck does not know why the checks cannot be read.')
    expect(requiredCiReason(null)).toBe('Deck does not know why the checks cannot be read.')
    render(<RequiredCiNotice signal={{ ...signal, reason: 'ghp_secret' as never }} pullRequest={null} />)
    expect(document.body).not.toHaveTextContent('ghp_secret')
  })
})
