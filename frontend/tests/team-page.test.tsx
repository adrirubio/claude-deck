import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentTeamsPage } from '../src/features/agent-teams/AgentTeamsPage'
import {
  deleteAgentTeamPreset, deleteAgentTeamSlot, duplicateAgentTeamPreset, fetchAgentTeamPresets,
  planAgentTeamLaunch, reorderAgentTeamSlots, updateAgentTeamLeader, updateAgentTeamPreset,
} from '../src/features/agent-teams/api'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { resetFactoryReads } from '../src/features/factory/reads'
import type { AgentTeamPreset, AgentTeamSummary } from '../src/types/agentTeams'
import { fixtureFetch, jsonResponse } from './helpers/factory'

// #542: a team opens as a readable page. Header and members first, editing behind Edit team.
vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return {
    ...actual,
    fetchAgentTeamPresets: vi.fn(),
    fetchTeamGithubScopes: vi.fn().mockResolvedValue({ scopes: [] }),
    fetchGithubWorkItems: vi.fn().mockResolvedValue({ items: [] }),
    fetchGithubRecoveryGateActive: vi.fn().mockResolvedValue({ active: false }),
    fetchAgentTeamActivity: vi.fn().mockResolvedValue({ preset_id: 1, checked_at: '', valid_until: '2000-01-01T00:00:00Z', slots: [] }),
    updateAgentTeamPreset: vi.fn(),
    duplicateAgentTeamPreset: vi.fn(),
    deleteAgentTeamPreset: vi.fn(),
    deleteAgentTeamSlot: vi.fn(),
    reorderAgentTeamSlots: vi.fn(),
    updateAgentTeamLeader: vi.fn(),
    planAgentTeamLaunch: vi.fn().mockResolvedValue({ preset_id: 1, items: [], plan_hash: 'h', warnings: [] }),
  }
})
vi.mock('../src/features/agent-teams/BacklogCoordination', () => ({ BacklogCoordination: () => null }))
vi.mock('../src/features/agent-teams/HumanActionSummary', () => ({ HumanActionSummary: () => <p>HUMAN-ACTIONS</p> }))
vi.mock('../src/hooks/useProviders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/hooks/useProviders')>()
  return { ...actual, fetchProviderLaunchOptions: vi.fn(async (provider: string) => ({ provider, supported_launch_modes: ['plain'] })) }
})

const stamp = '2026-10-12T12:00:00Z'
const slot = (id: number, name: string, extra: Record<string, unknown> = {}) => ({
  id, preset_id: 1, position: id, display_name: name, provider: 'claude-code', repo_id: 'repo',
  repo_path: `/work/${name}`, repo_name: 'repo', launch_mode: 'plain', launch_options: { model: 'Sonnet 5.5' }, enabled: true,
  created_at: stamp, updated_at: stamp, role: 'Implements', ...extra,
})
const team = {
  id: 1, name: 'major-release-v3', description: 'Release Deck v3.0.0 and its website.', created_at: stamp, updated_at: stamp,
  autonomy_enabled: false, leader_slot_id: 11,
  slots: [
    slot(11, 'R1 Leader', { role: 'Leader', charter: 'Coordinate the release across repositories.' }),
    slot(12, 'R2 implementer'),
    slot(13, 'R3 implementer', { enabled: false }),
    slot(14, 'R4 verifier', { role: 'Reviews' }),
  ],
} as unknown as AgentTeamPreset

const summary = {
  preset_id: 1, description: 'Release Deck v3.0.0 and its website.', parent_issue_url: 'https://github.com/o/r/issues/490',
  supervisor: 'none', supervisor_observation: { status: 'healthy', actor_id: 1, checked_at: new Date(Date.now() - 120000).toISOString(), next_check_at: new Date(Date.now() + 480000).toISOString(), grace_seconds: 1800, note: null, attention: null },
  checked_at: new Date().toISOString(), valid_until: new Date(Date.now() + 15000).toISOString(), coverage_complete: true, hold_code: null,
  attention: [], human_actions: [], remaining_work: { state: 'known', unfinished_items: 0, reported_items: 0, confidence: 'unknown', reason: 'complete' },
  next_actors: [], next_actor_coverage_complete: true,
  campaign: { backlog_state: 'available', done_count: 2, latest_done: [{ title: 'Notes', merged_at: null }], under_way_count: 1, under_way: [{ title: 'Files', owner_short_name: 'R2', state_phrase: 'building it' }], queued_count: 0, queued: [], not_started_count: 1, not_started_groups: [], decisions_ahead: [] },
} as unknown as AgentTeamSummary

beforeEach(() => {
  resetFactoryReads()
  clearOperatorToken()
  setOperatorToken('test-key')
  vi.mocked(fetchAgentTeamPresets).mockResolvedValue({ presets: [team] })
  vi.mocked(updateAgentTeamPreset).mockResolvedValue({ ...team, name: 'renamed' } as AgentTeamPreset)
  vi.mocked(duplicateAgentTeamPreset).mockResolvedValue({ ...team, id: 2, name: 'major-release-v3 copy' } as AgentTeamPreset)
  vi.mocked(deleteAgentTeamPreset).mockResolvedValue(undefined as never)
  vi.mocked(deleteAgentTeamSlot).mockResolvedValue(team)
  vi.mocked(reorderAgentTeamSlots).mockResolvedValue(team)
  vi.mocked(updateAgentTeamLeader).mockResolvedValue(team)
  fixtureFetch((path) => {
    if (path === 'agent-teams/presets/1/summary') return jsonResponse(summary)
    if (path === 'agent-teams/presets/1/github-scopes') return jsonResponse({ scopes: [{ id: 1 }, { id: 2 }] })
    if (path === 'factory/work-items') return jsonResponse({ counts: { total: 2, active: 0, attention: 0, finished: 0, queued: 0, review: 0, unknown: 0 }, items: [], total: 2, has_more: false, next_cursor: null, generated_at: stamp, filters: {}, schema_version: 1 })
    return jsonResponse({ detail: 'x' }, 404)
  })
})
afterEach(() => {
  cleanup()
  clearOperatorToken()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

function open(path = '/teams/1?tab=roster') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/teams/:teamId" element={<AgentTeamsPage />} /></Routes>
    </MemoryRouter>,
  )
}

describe('header', () => {
  it('shows the name, state, description, Leader, supervisor, repositories and work first', async () => {
    open()
    const header = await screen.findByRole('banner', { name: 'Team: major-release-v3' })
    expect(within(header).getByRole('heading', { level: 2, name: 'major-release-v3' })).toBeInTheDocument()
    expect(within(header).getByText('Paused')).toBeInTheDocument()
    expect(within(header).getByText('Release Deck v3.0.0 and its website.')).toBeInTheDocument()
    expect(within(header).getByText('R1 Leader')).toBeInTheDocument()
    await within(header).findByText('Healthy')
    expect(within(header).getByRole('link', { name: 'Manage ›' })).toHaveAttribute('href', '/repositories')
    await waitFor(() => expect(within(header).getByText(/2 items, 0 active/)).toBeInTheDocument())
    expect(within(header).getByRole('link', { name: 'View in Work ›' })).toHaveAttribute('href', '/work?team_id=1')
    expect(within(header).getByRole('button', { name: 'Plan launch' })).toBeEnabled()
    expect(within(header).getByRole('button', { name: 'Turn on autonomy' })).toBeInTheDocument()
  })

  it('has no counter tiles and the new subtitle', async () => {
    open()
    await screen.findByRole('banner', { name: /Team:/ })
    expect(screen.getByText('Teams of agents that work on your repositories.')).toBeInTheDocument()
    for (const word of ['Slots', 'Enabled']) expect(screen.queryByText(word, { exact: true })).not.toBeInTheDocument()
  })

  it('shows the Progress row of this team below the members and above the team status', async () => {
    open()
    const header = await screen.findByRole('banner', { name: /Team:/ })
    const members = screen.getByRole('heading', { name: /^Members/ })
    const progress = await screen.findByRole('heading', { name: /^Progress/ })
    const status = screen.getByText('Team status')
    const before = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
    expect(before(header, members)).toBe(true)
    expect(before(members, progress)).toBe(true)
    expect(before(progress, status)).toBe(true)
    expect(screen.getByRole('img', { name: /2 done, 1 under way, 1 still to do, backlog known/ })).toBeInTheDocument()
  })

  it('opens the Autonomy tab at the existing switch, and moves no switch into the header', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Turn on autonomy' }))
    expect(screen.getByRole('tab', { name: 'Autonomy' })).toHaveAttribute('data-state', 'active')
    const toggle = await screen.findByRole('switch', { name: 'Enable autonomous GitHub dispatch' })
    await waitFor(() => expect(toggle).toHaveFocus())
    expect(screen.getAllByRole('switch')).toHaveLength(1)
  })

  it('keeps the team status behind a closed disclosure', async () => {
    open()
    const status = (await screen.findByText('Team status')).closest('details')!
    expect(status).not.toHaveAttribute('open')
    expect(within(status).getByRole('region', { name: 'Team summary' }).closest('details')).toBe(status)
  })
})

describe('Edit team', () => {
  it('shows no editable team field until Edit team is selected', async () => {
    const user = userEvent.setup()
    open()
    await screen.findByRole('banner', { name: /Team:/ })
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Description')).not.toBeInTheDocument()
    for (const name of ['Save', 'Duplicate']) expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit team' }))
    const dialog = within(await screen.findByRole('dialog'))
    expect(dialog.getByLabelText('Name')).toHaveValue('major-release-v3')
    expect(dialog.getByLabelText('Description')).toHaveValue('Release Deck v3.0.0 and its website.')
    for (const name of ['Save', 'Duplicate', 'Delete']) expect(dialog.getByRole('button', { name })).toBeInTheDocument()
  })

  it('saves with the same request as before and closes', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Edit team' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.clear(dialog.getByLabelText('Name'))
    await user.type(dialog.getByLabelText('Name'), 'renamed')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(updateAgentTeamPreset).toHaveBeenCalledWith(1, { name: 'renamed', description: 'Release Deck v3.0.0 and its website.' }, 'test-key'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('keeps the dialog and the text when a save fails', async () => {
    vi.mocked(updateAgentTeamPreset).mockRejectedValue(new Error('refused'))
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Edit team' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText('Name'), ' x')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(updateAgentTeamPreset).toHaveBeenCalled())
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(dialog.getByLabelText('Name')).toHaveValue('major-release-v3 x')
  })

  it('duplicates and deletes through the existing handlers', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Edit team' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Duplicate' }))
    await waitFor(() => expect(duplicateAgentTeamPreset).toHaveBeenCalledWith(1, { name: 'major-release-v3 copy' }, 'test-key'))
  })

  it('deletes through the existing handler', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Edit team' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deleteAgentTeamPreset).toHaveBeenCalledWith(1, 'test-key'))
  })
})

describe('members', () => {
  it('lists every member as a compact row, with no charter or folder until a row is expanded', async () => {
    open()
    const rows = await screen.findAllByRole('listitem')
    const members = rows.filter((row) => within(row).queryByRole('button', { name: /^Details for / }))
    expect(members).toHaveLength(4)
    expect(screen.getByRole('heading', { name: /^Members/ })).toHaveTextContent('4')
    expect(screen.queryByText('Coordinate the release across repositories.')).not.toBeInTheDocument()
    expect(screen.queryByText('/work/R1 Leader')).not.toBeInTheDocument()
    const leader = members[0]
    expect(leader).toHaveTextContent('R1 Leader')
    expect(leader).toHaveTextContent('Leader')
    expect(leader).toHaveTextContent('Claude Code · Sonnet 5.5')
    expect(members[2]).toHaveTextContent('Disabled')
  })

  it('shows the charter, folder and technical fields when a row is expanded', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Details for R1 Leader' }))
    expect(screen.getByText('Coordinate the release across repositories.')).toBeInTheDocument()
    expect(screen.getByText('/work/R1 Leader')).toBeInTheDocument()
    expect(screen.getByText('ASD-STE100')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Details for R1 Leader' }))
    expect(screen.queryByText('Coordinate the release across repositories.')).not.toBeInTheDocument()
  })

  it('puts the actions in the row menu', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Actions for R2 implementer' }))
    const menu = within(screen.getByRole('menu', { name: 'Actions for R2 implementer' }))
    expect(menu.getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Launch', 'Edit', 'Set Leader', 'Move up', 'Move down', 'Delete'])
    // The Leader row has no Set Leader, and the first row cannot move up.
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: 'Actions for R1 Leader' }))
    const leaderMenu = within(screen.getByRole('menu', { name: 'Actions for R1 Leader' }))
    expect(leaderMenu.queryByRole('menuitem', { name: 'Set Leader' })).not.toBeInTheDocument()
    expect(leaderMenu.getByRole('menuitem', { name: 'Move up' })).toBeDisabled()
  })

  it('runs Set Leader, Move and Launch through the existing handlers', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Actions for R2 implementer' }))
    await user.click(screen.getByRole('menuitem', { name: 'Set Leader' }))
    await waitFor(() => expect(updateAgentTeamLeader).toHaveBeenCalledWith(1, expect.objectContaining({ leader_slot_id: 12 }), 'test-key'))
    await user.click(screen.getByRole('button', { name: 'Actions for R2 implementer' }))
    await user.click(screen.getByRole('menuitem', { name: 'Move down' }))
    await waitFor(() => expect(reorderAgentTeamSlots).toHaveBeenCalledWith(1, [11, 13, 12, 14], 'test-key'))
    await user.click(screen.getByRole('button', { name: 'Actions for R2 implementer' }))
    await user.click(screen.getByRole('menuitem', { name: 'Launch' }))
    await waitFor(() => expect(planAgentTeamLaunch).toHaveBeenCalledWith(1, expect.objectContaining({ slot_ids: [12] }), 'test-key'))
  })

  it('runs Delete through the existing handler', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Actions for R4 verifier' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete' }))
    await waitFor(() => expect(deleteAgentTeamSlot).toHaveBeenCalledWith(14, 'test-key'))
  })

  it('cannot launch a disabled member', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Actions for R3 implementer' }))
    expect(screen.getByRole('menuitem', { name: 'Launch' })).toBeDisabled()
  })

  it('opens the slot form from Edit and keeps Add member', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Add member' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})
