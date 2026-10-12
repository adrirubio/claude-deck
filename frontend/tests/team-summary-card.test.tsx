import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TeamSummaryCard } from '../src/features/agent-teams/TeamSummaryCard'
import { AgentTeamsPage } from '../src/features/agent-teams/AgentTeamsPage'
import { OverviewPage } from '../src/features/factory/pages/OverviewPage'
import { fetchAgentTeamPresets } from '../src/features/agent-teams/api'
import { resetFactoryReads } from '../src/features/factory/reads'
import type { AgentTeamPreset, AgentTeamSummary } from '../src/types/agentTeams'
import overview from './fixtures/factory/v1-p04/overview.json'
import { fixtureFetch, jsonResponse, renderRoute, settle } from './helpers/factory'

vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return {
    ...actual,
    fetchAgentTeamPresets: vi.fn(),
    fetchTeamGithubScopes: vi.fn().mockResolvedValue({ scopes: [] }),
    fetchGithubWorkItems: vi.fn().mockResolvedValue({ items: [] }),
    fetchGithubRecoveryGateActive: vi.fn().mockResolvedValue({ active: false }),
    fetchAgentTeamActivity: vi.fn().mockResolvedValue({ preset_id: 1, slots: [], valid_until: '2099-01-01T00:00:00Z' }),
  }
})
vi.mock('../src/features/agent-teams/BacklogCoordination', () => ({ BacklogCoordination: () => null }))
vi.mock('../src/features/agent-teams/HumanActionSummary', () => ({ HumanActionSummary: () => null }))

const stamp = '2026-10-12T12:00:00Z'
const ISSUE = 'https://github.com/adrirubio/claude-deck/issues/490'

function summary(overrides: Partial<AgentTeamSummary> = {}): AgentTeamSummary {
  return {
    preset_id: 1,
    description: 'Release Deck v3.0.1 and its website.',
    parent_issue_url: ISSUE,
    supervisor: 'none',
    checked_at: stamp,
    valid_until: '2026-10-12T12:00:15Z',
    coverage_complete: true,
    hold_code: null,
    attention: [],
    human_actions: [],
    remaining_work: { state: 'known', unfinished_items: 0, reported_items: 0, confidence: 'unknown', reason: 'complete' },
    next_actors: [],
    next_actor_coverage_complete: true,
    ...overrides,
  }
}

const noWork = summary()
const activeWork = summary({
  attention: [{ code: 'human_review', work_item_id: 7, issue_number: 495 }],
  human_actions: [{
    scope_id: 1, issue_number: 495, work_item_id: 7, kind: 'review_pr', state: 'requested',
    source: 'leader', assessment_current: true, pull_request_number: 500,
  }],
  remaining_work: {
    state: 'known', unfinished_items: 2, reported_items: 2, effort_low_minutes: 30,
    effort_high_minutes: 90, confidence: 'medium', reason: 'complete',
  },
  next_actors: ['operator'],
})
const hold = summary({
  hold_code: 'hold',
  attention: [{ code: 'hold' }, { code: 'attempt_stopped', work_item_id: 8, issue_number: 496 }],
  remaining_work: { state: 'unknown', unfinished_items: 1, reported_items: 0, confidence: 'unknown', reason: 'report_unknown' },
  next_actors: ['leader'],
})

const cases = [
  {
    name: 'a team with no work', data: noWork,
    expects: ['None open.', 'Nothing is left.'],
  },
  {
    name: 'a team with active work', data: activeWork,
    expects: ['Human review needed on', '2 unfinished items. Estimate: 30–90 active minutes, medium confidence.', /^You$/, 'Review the PR #500 on #495'],
  },
  {
    name: 'a team on HOLD', data: hold,
    expects: ['This team is on HOLD. Deck admits no new work.', 'Attempt stopped on', 'Unknown. The team has not reported.', /^The Leader$/],
  },
]

const preset = {
  id: 1, name: 'Release crew', description: noWork.description, created_at: stamp, updated_at: stamp,
  autonomy_enabled: false, slots: [],
} as unknown as AgentTeamPreset

beforeEach(() => resetFactoryReads())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('team summary card', () => {
  const find = (card: HTMLElement, text: string | RegExp) =>
    typeof text === 'string' ? within(card).getByText(text, { exact: false }) : within(card).getByText(text)
  for (const { name, data, expects } of cases) {
    describe(name, () => {
      it('renders on the Overview', async () => {
        fixtureFetch((path, query) => {
          if (path === 'agent-teams/presets') return jsonResponse({ presets: [preset] })
          if (path === 'agent-teams/presets/1/summary') return jsonResponse(data)
          if (path === 'factory/overview') return jsonResponse(overview.normal.response)
          if (path === 'factory/repositories' && query.get('limit') === '100') return jsonResponse({ repositories: [] })
          return jsonResponse({ items: [], rows: [], total: 0, has_more: false, generated_at: stamp })
        })
        renderRoute(<OverviewPage />, '/', '/')
        await settle()
        await settle()
        const card = screen.getByRole('region', { name: 'Team summary: Release crew' })
        expect(within(card).getByRole('link', { name: 'Release crew' })).toHaveAttribute('href', '/teams/1')
        for (const text of expects) expect(find(card, text)).toBeInTheDocument()
        expect(within(card).getByRole('link', { name: '#490' })).toHaveAttribute('href', ISSUE)
        expect(within(card).getByText('None, not required.')).toBeInTheDocument()
      })

      it('renders at the top of the team page', async () => {
        vi.mocked(fetchAgentTeamPresets).mockResolvedValue({ presets: [preset] })
        fixtureFetch((path) => path === 'agent-teams/presets/1/summary'
          ? jsonResponse(data) : jsonResponse({ detail: 'x' }, 404))
        render(
          <MemoryRouter initialEntries={['/teams/1']}>
            <Routes><Route path="/teams/:teamId" element={<AgentTeamsPage />} /></Routes>
          </MemoryRouter>,
        )
        const card = await screen.findByRole('region', { name: 'Team summary' })
        await settle()
        for (const text of expects) expect(find(card, text)).toBeInTheDocument()
        // The name is in the form already, so the card does not repeat it.
        expect(within(card).queryByRole('heading')).not.toBeInTheDocument()
      })
    })
  }

  it('shows Unknown when the server says unknown, and never an estimate', async () => {
    fixtureFetch(() => jsonResponse(summary({
      remaining_work: { state: 'unknown', unfinished_items: 3, reported_items: 1, confidence: 'unknown', reason: 'context_changed' },
    })))
    renderRoute(<TeamSummaryCard presetId={1} />, '/', '/')
    await settle()
    expect(screen.getByText('Unknown. The last team report is out of date.')).toBeInTheDocument()
    expect(screen.queryByText(/Estimate/)).not.toBeInTheDocument()
  })

  it('says so when the server reports known work without an estimate', async () => {
    fixtureFetch(() => jsonResponse(summary({
      remaining_work: { state: 'known', unfinished_items: 1, reported_items: 1, confidence: 'unknown', reason: 'complete' },
    })))
    renderRoute(<TeamSummaryCard presetId={1} />, '/', '/')
    await settle()
    expect(screen.getByText('1 unfinished item. No estimate reported.')).toBeInTheDocument()
  })

  it('notes an incomplete summary, an unset parent issue and an unknown next actor', async () => {
    fixtureFetch(() => jsonResponse(summary({
      coverage_complete: false, next_actor_coverage_complete: false, parent_issue_url: null, description: null,
    })))
    renderRoute(<TeamSummaryCard presetId={1} />, '/', '/')
    await settle()
    expect(screen.getByText(/may be incomplete/)).toBeInTheDocument()
    expect(screen.getByText('None set.')).toBeInTheDocument()
    expect(screen.getByText('Unknown.')).toBeInTheDocument()
    expect(screen.getByText('No outcome is set.')).toBeInTheDocument()
  })

  it('has no action control: it only displays', async () => {
    fixtureFetch(() => jsonResponse(activeWork))
    renderRoute(<TeamSummaryCard presetId={1} />, '/', '/')
    await settle()
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })

  it('stops reading after a 404 for the summary', async () => {
    vi.useFakeTimers()
    const { requests } = fixtureFetch(() => jsonResponse({ detail: 'preset_not_found' }, 404))
    renderRoute(<TeamSummaryCard presetId={9} />, '/', '/')
    await settle()
    await act(async () => vi.advanceTimersByTimeAsync(120000))
    expect(requests).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveTextContent('preset_not_found')
  })
})
