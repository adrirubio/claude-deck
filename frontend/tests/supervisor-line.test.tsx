import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TeamSummaryCard } from '../src/features/agent-teams/TeamSummaryCard'
import { supervisorWords, waitingScreen } from '../src/features/agent-teams/supervisorText'
import { OverviewPage } from '../src/features/factory/pages/OverviewPage'
import { resetFactoryReads } from '../src/features/factory/reads'
import type { AgentTeamPreset, AgentTeamSummary, SupervisorObservation } from '../src/types/agentTeams'
import overview from './fixtures/factory/v1-p04/overview.json'
import { fixtureFetch, jsonResponse, renderRoute, settle } from './helpers/factory'

// #549 (frontend half, #623): the supervisor line and the "waiting for input" signal.
vi.mock('../src/features/agent-teams/WorkPublicationPanel', () => ({ WorkPublicationPanel: () => null }))

const NOW = Date.parse('2026-10-12T12:00:00Z')
beforeEach(() => {
  resetFactoryReads()
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const minutesFromNow = (m: number) => new Date(NOW + m * 60000).toISOString()
const observation = (over: Partial<SupervisorObservation>): SupervisorObservation => ({
  status: 'healthy', actor_id: 1, checked_at: minutesFromNow(-2), next_check_at: minutesFromNow(8),
  grace_seconds: 1800, note: null, attention: null, ...over,
})
function summary(over: Partial<AgentTeamSummary> = {}): AgentTeamSummary {
  return {
    preset_id: 1, description: 'Ship it.', parent_issue_url: null, supervisor: 'none',
    supervisor_observation: observation({}), checked_at: minutesFromNow(0), valid_until: minutesFromNow(1),
    coverage_complete: true, hold_code: null, attention: [], human_actions: [],
    remaining_work: { state: 'known', unfinished_items: 0, reported_items: 0, confidence: 'unknown', reason: 'complete' },
    next_actors: [], next_actor_coverage_complete: true, ...over,
  }
}

async function card(data: AgentTeamSummary, slotNames?: Record<number, string>) {
  fixtureFetch(() => jsonResponse(data))
  renderRoute(<TeamSummaryCard presetId={1} slotNames={slotNames} />, '/', '/')
  await settle()
  return screen.getByRole('region', { name: 'Team summary' })
}
const supervisorRow = (region: HTMLElement) => within(region).getByText('Supervisor').parentElement!

describe('supervisor line on the team card', () => {
  it('None: no supervisor registered, and not an error', async () => {
    const row = supervisorRow(await card(summary({ supervisor_observation: observation({ status: 'none', actor_id: null, checked_at: null, next_check_at: null }) })))
    expect(row).toHaveTextContent('None')
    expect(row).toHaveTextContent('not required')
    expect(row.textContent).not.toMatch(/error|late|absent|overdue/i)
  })

  it('Healthy: states when it checked and when the next check is due', async () => {
    const row = supervisorRow(await card(summary()))
    expect(row).toHaveTextContent('Healthy')
    expect(row).toHaveTextContent('checked 2 min ago · next in 8 min')
  })

  it('Late: says the check is overdue and that work can still run, and raises attention', async () => {
    const region = await card(summary({
      supervisor_observation: observation({ status: 'late', next_check_at: minutesFromNow(-5), attention: 'Supervisor check-in overdue' }),
    }))
    const row = supervisorRow(region)
    expect(row).toHaveTextContent('Late')
    expect(row).toHaveTextContent('check-in overdue by 5 min · work can still run')
    expect(within(region).getByText('Supervisor check-in overdue')).toBeInTheDocument()
    expect(within(region).queryByText('None open.')).not.toBeInTheDocument()
  })

  it('Absent: states the last check, or that there was none', async () => {
    const region = await card(summary({
      supervisor_observation: observation({ status: 'absent', checked_at: minutesFromNow(-300), next_check_at: minutesFromNow(-290), attention: 'Supervisor check-in overdue' }),
    }))
    expect(supervisorRow(region)).toHaveTextContent('Absent')
    expect(supervisorRow(region)).toHaveTextContent('no check-in since 5 h ago')
    cleanup()
    resetFactoryReads()
    const none = await card(summary({
      supervisor_observation: observation({ status: 'absent', checked_at: null, next_check_at: null, attention: 'Supervisor check-in overdue' }),
    }))
    expect(supervisorRow(none)).toHaveTextContent('no check-in yet')
  })

  it('keeps the old text when an older server sends no observation', async () => {
    const region = await card(summary({ supervisor_observation: undefined }))
    expect(supervisorRow(region)).toHaveTextContent('None, not required.')
  })

  it('always shows a word with the colour', () => {
    for (const status of ['none', 'healthy', 'late', 'absent'] as const) {
      const { chip } = supervisorWords(observation({ status }), NOW)
      expect(chip).toBe({ none: 'None', healthy: 'Healthy', late: 'Late', absent: 'Absent' }[status])
    }
  })
})

describe('waiting for input', () => {
  it('names the member and the screen on the team card', async () => {
    const region = await card(
      summary({ waiting_input: [
        { slot_id: 5, reason: 'question', label: 'Waiting for input' },
        { slot_id: 6, reason: 'sign_in', label: 'Waiting for input' },
        { slot_id: 9, reason: 'trust', label: 'Waiting for input' },
      ] }),
      { 5: 'R2 release implementer', 6: 'R3 website implementer' },
    )
    const row = within(region).getByText('Waiting for input').parentElement!
    expect(row).toHaveTextContent('R2 release implementer is waiting at a question')
    expect(row).toHaveTextContent('R3 website implementer is waiting at a sign-in screen')
    expect(row).toHaveTextContent('A member is waiting at a trust prompt')
  })

  it.each([null, undefined, []])('shows nothing when the field is %j', async (value) => {
    const region = await card(summary({ waiting_input: value }))
    expect(within(region).queryByText('Waiting for input')).not.toBeInTheDocument()
  })

  it('shows only the fixed screen words, never other text', () => {
    expect(waitingScreen('question')).toBe('a question')
    expect(waitingScreen('trust')).toBe('a trust prompt')
    expect(waitingScreen('sign_in')).toBe('a sign-in screen')
    expect(waitingScreen('Password: hunter2')).toBe('an input screen')
  })
})

describe('Overview Needs you', () => {
  const preset: AgentTeamPreset = {
    id: 1, name: 'Release crew', created_at: '', updated_at: '', autonomy_enabled: true,
    slots: [{ id: 5, display_name: 'R2 release implementer' } as AgentTeamPreset['slots'][number]],
  }
  const run = async (data: AgentTeamSummary) => {
    fixtureFetch((path) => {
      if (path === 'factory/overview') return jsonResponse(overview.normal.response)
      if (path === 'agent-teams/presets') return jsonResponse({ presets: [preset] })
      if (path === 'agent-teams/presets/1/summary') return jsonResponse(data)
      return jsonResponse({ rows: [], items: [], repositories: [], total: 0, has_more: false, generated_at: '2026-10-12T12:00:00Z' })
    })
    renderRoute(<OverviewPage />, '/', '/')
    await settle()
    await settle()
  }

  it('lists a waiting member with the exact screen, linked to Live sessions', async () => {
    await run(summary({ waiting_input: [{ slot_id: 5, reason: 'trust', label: 'Waiting for input' }] }))
    const list = screen.getByRole('heading', { name: /Needs you/ }).closest('section')!
    expect(within(list).getByText('Waiting for input')).toBeInTheDocument()
    expect(within(list).getByText(/R2 release implementer is waiting at a trust prompt/)).toBeInTheDocument()
    expect(within(list).getByRole('link', { name: /Open live sessions/ })).toHaveAttribute('href', '/agent-bridge')
  })

  it('lists an overdue supervisor and links to the team', async () => {
    await run(summary({ supervisor_observation: observation({ status: 'absent', attention: 'Supervisor check-in overdue' }) }))
    const list = screen.getByRole('heading', { name: /Needs you/ }).closest('section')!
    expect(within(list).getByText('Supervisor check-in overdue')).toBeInTheDocument()
    expect(within(list).getByRole('link', { name: /Open the team/ })).toHaveAttribute('href', '/teams/1')
  })

  it('shows no row for a healthy supervisor or when nobody waits', async () => {
    await run(summary({ waiting_input: [] }))
    expect(screen.queryByRole('heading', { name: /Needs you/ })).not.toBeInTheDocument()
    expect(screen.getByText('Nothing needs you right now.')).toBeInTheDocument()
  })
})
