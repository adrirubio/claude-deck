import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TeamSummaryCard } from '../src/features/agent-teams/TeamSummaryCard'
import { parseReminders, reminderAge, reminderSentence } from '../src/features/agent-teams/reminderText'
import { OverviewPage } from '../src/features/factory/pages/OverviewPage'
import { resetFactoryReads } from '../src/features/factory/reads'
import type { AgentTeamPreset, AgentTeamSummary } from '../src/types/agentTeams'
import overview from './fixtures/factory/v1-p04/overview.json'
import { fixtureFetch, jsonResponse, renderRoute, settle } from './helpers/factory'

// #678 (frontend half of #528): unanswered release reminders on the Overview and the team card.
vi.mock('../src/features/agent-teams/WorkPublicationPanel', () => ({ WorkPublicationPanel: () => null }))

beforeEach(() => resetFactoryReads())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const stamp = '2026-10-12T12:00:00Z'
const held = {
  kind: 'workspace_release', scope_id: 1, work_item_id: 4, issue_number: 104, owner_slot_id: 2,
  owner_name: 'B1 Backend', reminder_count: 4, reminder_cap: 4, waiting_since: stamp, elapsed_seconds: 6 * 3600,
}
const backlog = {
  kind: 'backlog_reconcile', scope_id: 1, issue_numbers: [7, 8], owner_name: 'L1 Leader', reminder_count: 3, reminder_cap: 3,
  elapsed_seconds: 1800,
}

function summary(over: Partial<AgentTeamSummary> = {}, presetId = 1): AgentTeamSummary {
  return {
    preset_id: presetId, description: 'Ship it.', parent_issue_url: null, supervisor: 'none', checked_at: stamp,
    valid_until: '2026-10-12T12:00:15Z', coverage_complete: true, hold_code: null, attention: [], human_actions: [],
    remaining_work: { state: 'known', unfinished_items: 0, reported_items: 0, confidence: 'unknown', reason: 'complete' },
    next_actors: [], next_actor_coverage_complete: true, ...over,
  } as AgentTeamSummary
}
const preset = (id: number, name: string): AgentTeamPreset => ({ id, name, created_at: stamp, updated_at: stamp, autonomy_enabled: true, slots: [] })

async function overviewWith(summaries: Record<number, AgentTeamSummary>, presets = [preset(1, 'Release crew')]) {
  fixtureFetch((path) => {
    if (path === 'factory/overview') return jsonResponse(overview.normal.response)
    if (path === 'agent-teams/presets') return jsonResponse({ presets })
    const match = /^agent-teams\/presets\/(\d+)\/summary$/.exec(path)
    if (match) return jsonResponse(summaries[Number(match[1])])
    return jsonResponse({ rows: [], items: [], repositories: [], total: 0, has_more: false, generated_at: stamp })
  })
  renderRoute(<OverviewPage />, '/', '/')
  await settle()
  await settle()
}

describe('parseReminders', () => {
  it('reads a good row and drops everything it cannot read', () => {
    const rows = parseReminders([
      held, backlog,
      { ...held, kind: 'something_new' },
      { ...held, reminder_cap: 0 },
      { ...held, reminder_count: -1 },
      { ...held, reminder_count: '4' },
      { ...held, issue_number: null },
      { ...held, issue_number: 1.5 },
      null, 'text', 7, [],
    ])
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ kind: 'workspace_release', issueNumber: 104, owner: 'B1 Backend', elapsedSeconds: 21600 })
    expect(rows[1]).toMatchObject({ kind: 'backlog_reconcile', issueNumbers: [7, 8] })
  })

  it.each([undefined, null, {}, 'x', 5, []])('gives no row for %j', (value) => {
    expect(parseReminders(value)).toEqual([])
  })

  it('keeps a row with no owner and no age, and cleans bad numbers in the list', () => {
    const [row] = parseReminders([{ ...held, owner_name: null, elapsed_seconds: null }, { ...backlog, issue_numbers: [7, 'x', -2, 9.5] }])
    expect(row).toMatchObject({ owner: null, elapsedSeconds: null })
    expect(reminderSentence(row)).toBe('Release needed: The owner still holds the workspace of #104 after 4 reminders')
    expect(parseReminders([{ ...backlog, issue_numbers: [7, 'x', -2, 9.5] }])[0].issueNumbers).toEqual([7])
  })

  it('writes plain sentences for both kinds', () => {
    const [a, b] = parseReminders([held, backlog])
    expect(reminderSentence(a)).toBe('Release needed: B1 Backend still holds the workspace of #104 after 4 reminders (6 h)')
    expect(reminderSentence(b)).toBe('L1 Leader has not assessed the backlog (#7, #8) after 3 of 3 requests (30 min)')
  })

  it.each([[null, null], [10, 'under 1 min'], [90, '1 min'], [3600, '1 h'], [172800, '2 d']])('ages %j as %j', (seconds, text) => {
    expect(reminderAge(seconds)).toBe(text)
  })
})

describe('Overview Needs you', () => {
  it('shows exactly one item for one held workspace, with the owner, the issue and the age, linked to the work', async () => {
    await overviewWith({ 1: summary({ reminder_attention: [held] as never }) })
    const list = screen.getByRole('heading', { name: /Needs you/ }).closest('section')!
    expect(within(list).getAllByRole('listitem')).toHaveLength(1)
    expect(within(list).getByText('Release needed: B1 Backend still holds the workspace of #104 after 4 reminders (6 h)')).toBeInTheDocument()
    expect(within(list).getByRole('link', { name: /Open #104/ })).toHaveAttribute('href', '/work/4')
  })

  it('shows nothing when the field is absent, empty or malformed', async () => {
    for (const value of [undefined, [], [{ kind: 'x' }], 'broken']) {
      cleanup()
      resetFactoryReads()
      await overviewWith({ 1: summary({ reminder_attention: value as never }) })
      expect(screen.queryByRole('heading', { name: /Needs you/ })).not.toBeInTheDocument()
      expect(screen.getByText('Nothing needs you right now.')).toBeInTheDocument()
    }
  })

  it('shows one row for each team that has the signal', async () => {
    await overviewWith(
      { 1: summary({ reminder_attention: [held] as never }), 2: summary({ reminder_attention: [{ ...held, work_item_id: 9, issue_number: 120 }] as never }, 2) },
      [preset(1, 'Release crew'), preset(2, 'Docs crew')],
    )
    const list = screen.getByRole('heading', { name: /Needs you/ }).closest('section')!
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
  })

  it('links the backlog signal to the team', async () => {
    await overviewWith({ 1: summary({ reminder_attention: [backlog] as never }) })
    const list = screen.getByRole('heading', { name: /Needs you/ }).closest('section')!
    expect(within(list).getByRole('link', { name: /Open the team/ })).toHaveAttribute('href', '/teams/1')
    expect(within(list).getByText(/L1 Leader has not assessed the backlog \(#7, #8\)/)).toBeInTheDocument()
  })
})

describe('team card', () => {
  const card = async (data: AgentTeamSummary) => {
    fixtureFetch(() => jsonResponse(data))
    renderRoute(<TeamSummaryCard presetId={1} />, '/', '/')
    await settle()
    return screen.getByRole('region', { name: 'Team summary' })
  }

  it('shows the signal in the Attention list, with a link to the item', async () => {
    const region = await card(summary({ reminder_attention: [held] as never }))
    const item = within(region).getByText('Release reminders unanswered').closest('li')!
    expect(item).toHaveTextContent('on #104')
    expect(item).toHaveTextContent('B1 Backend · 4 of 4 reminders · 6 h')
    expect(within(item).getByRole('link', { name: '#104' })).toHaveAttribute('href', '/work/4')
    expect(within(region).queryByText('None open.')).not.toBeInTheDocument()
  })

  it('shows the backlog signal in plain words', async () => {
    const region = await card(summary({ reminder_attention: [backlog] as never }))
    expect(within(region).getByText('Backlog requests unanswered').closest('li')).toHaveTextContent('L1 Leader · 3 of 3 requests · 30 min')
  })

  it.each([undefined, [], [{ kind: 'x' }]])('shows nothing about reminders when the field is %j', async (value) => {
    const region = await card(summary({ reminder_attention: value as never }))
    expect(within(region).queryByText(/reminders unanswered|requests unanswered/)).not.toBeInTheDocument()
    expect(within(region).getByText('None open.')).toBeInTheDocument()
  })

  it('says the summary may be incomplete when the list is incomplete', async () => {
    const region = await card(summary({ reminder_attention: [held] as never, reminder_attention_complete: false }))
    expect(within(region).getByText(/may be incomplete/)).toBeInTheDocument()
  })
})
