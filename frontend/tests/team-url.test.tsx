import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentTeamsPage } from '../src/features/agent-teams/AgentTeamsPage'
import {
  fetchAgentTeamActivity, fetchAgentTeamPresets, fetchGithubWorkItems, fetchTeamGithubScopes,
} from '../src/features/agent-teams/api'
import { clearOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { resetFactoryReads } from '../src/features/factory/reads'
import type { AgentTeamPreset } from '../src/types/agentTeams'
import { fixtureFetch, jsonResponse, settle } from './helpers/factory'

// #544: a team URL that names no team selects nothing and sends no per-team request.
vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return {
    ...actual,
    fetchAgentTeamPresets: vi.fn(),
    fetchTeamGithubScopes: vi.fn().mockResolvedValue({ scopes: [] }),
    fetchGithubWorkItems: vi.fn().mockResolvedValue({ items: [] }),
    fetchGithubRecoveryGateActive: vi.fn().mockResolvedValue({ active: false }),
    fetchAgentTeamActivity: vi.fn().mockImplementation(async (presetId: number) => ({
      preset_id: presetId, checked_at: new Date().toISOString(), valid_until: new Date(Date.now() + 60000).toISOString(), slots: [],
    })),
    planAgentTeamLaunch: vi.fn(),
  }
})
vi.mock('../src/features/agent-teams/BacklogCoordination', () => ({ BacklogCoordination: () => null }))
vi.mock('../src/hooks/useProviders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/hooks/useProviders')>()
  return {
    ...actual,
    fetchProviderLaunchOptions: vi.fn(async (provider: string) => ({ provider, supported_launch_modes: ['plain'] })),
  }
})

const stamp = '2026-10-12T12:00:00Z'
const slot = (id: number, name: string, extra: Record<string, unknown> = {}) => ({
  id, preset_id: 1, position: id, display_name: name, provider: 'claude-code', repo_id: 'repo',
  repo_path: '/tmp/repo', repo_name: 'repo', launch_mode: 'plain', launch_options: {}, enabled: true,
  created_at: stamp, updated_at: stamp, ...extra,
})
const team = (id: number, name: string, slots: unknown[] = [], leader: number | null = null) => ({
  id, name, created_at: stamp, updated_at: stamp, autonomy_enabled: false, leader_slot_id: leader, slots,
}) as unknown as AgentTeamPreset

let paths: string[] = []
beforeEach(() => {
  resetFactoryReads()
  clearOperatorToken()
  paths = []
  vi.mocked(fetchAgentTeamPresets).mockResolvedValue({
    presets: [
      team(1, 'Release crew', [
        slot(11, 'R1 Leader'),
        slot(12, 'R2 Worker', { area_labels: ['deck-v3-code'], expertise: 'Backend work' }),
        slot(13, 'R3 Expert', { expertise: 'Knows the website' }),
      ], 11),
      team(2, 'Quiet team'),
    ],
  })
  fixtureFetch((path) => {
    paths.push(path)
    return jsonResponse({ detail: 'x' }, 404)
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

function open(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/teams" element={<AgentTeamsPage />} />
        <Route path="/teams/:teamId" element={<AgentTeamsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe.each(['abc', '999', '0', '1e3'])('/teams/%s', (id) => {
  it('shows no team and no editable form, and the team list stays', async () => {
    open(`/teams/${id}`)
    expect(await screen.findByText('This team does not exist. Select a team from the list.')).toBeInTheDocument()
    await settle()
    expect(screen.getByText('Release crew')).toBeInTheDocument()
    expect(screen.getByText('Quiet team')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit team' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()
    for (const name of ['Save', 'Duplicate', 'Delete']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('region', { name: /Team summary/ })).not.toBeInTheDocument()
  })

  it('sends no per-team request', async () => {
    open(`/teams/${id}`)
    await screen.findByText('This team does not exist. Select a team from the list.')
    await settle()
    await settle()
    expect(fetchAgentTeamActivity).not.toHaveBeenCalled()
    expect(fetchTeamGithubScopes).not.toHaveBeenCalled()
    expect(fetchGithubWorkItems).not.toHaveBeenCalled()
    expect(paths.filter((path) => /^agent-teams\/presets\/[^/]+\//.test(path))).toEqual([])
  })
})

describe('known and missing team ids', () => {
  it('/teams selects the first team', async () => {
    open('/teams')
    expect(await screen.findByRole('heading', { level: 2, name: 'Release crew' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit team' })).toBeInTheDocument()
    expect(screen.queryByText(/does not exist/)).not.toBeInTheDocument()
  })

  it('/teams/2 selects that team and reads only its activity', async () => {
    open('/teams/2')
    expect(await screen.findByRole('heading', { level: 2, name: 'Quiet team' })).toBeInTheDocument()
    await waitFor(() => expect(fetchAgentTeamActivity).toHaveBeenCalledWith(2, expect.anything()))
    expect(vi.mocked(fetchAgentTeamActivity).mock.calls.every(([presetId]) => presetId === 2)).toBe(true)
  })
})

describe('routing label', () => {
  // The routing block shows when the member row is expanded.
  const card = async (name: string) => {
    open('/teams/1?tab=roster')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: `Details for ${name}` }))
    return screen.getByRole('button', { name: `Details for ${name}` }).closest('li') as HTMLElement
  }

  it('says none for a leader without area labels, and keeps expertise under its own label', async () => {
    const leader = await card('R1 Leader')
    expect(leader).toHaveTextContent('Folder')
    expect(within(leader).queryByText('GitHub dispatch routing')).not.toBeInTheDocument()
    cleanup()
    resetFactoryReads()
    const expert = await card('R3 Expert')
    expect(within(expert).getByText('GitHub dispatch routing')).toBeInTheDocument()
    expect(within(expert).getByText('None')).toBeInTheDocument()
    expect(within(expert).getByText('Expertise')).toBeInTheDocument()
    expect(within(expert).getByText('Knows the website')).toBeInTheDocument()
  })

  it('shows the area labels first and the expertise under its own label', async () => {
    const worker = await card('R2 Worker')
    const text = worker.textContent ?? ''
    expect(text.indexOf('deck-v3-code')).toBeGreaterThan(text.indexOf('GitHub dispatch routing'))
    expect(text.indexOf('Expertise')).toBeGreaterThan(text.indexOf('deck-v3-code'))
    expect(within(worker).queryByText('None')).not.toBeInTheDocument()
  })

  it('names the Leader when a leader slot has expertise but no labels', async () => {
    vi.mocked(fetchAgentTeamPresets).mockResolvedValue({
      presets: [team(1, 'Release crew', [slot(11, 'R1 Leader', { expertise: 'Coordinates the release' })], 11)],
    })
    const leader = await card('R1 Leader')
    expect(within(leader).getByText('None (the Leader routes this slot)')).toBeInTheDocument()
    expect(within(leader).getByText('Coordinates the release')).toBeInTheDocument()
  })
})

describe('Plan launch', () => {
  it('states the reason in the key dialog, and the key is still required', async () => {
    const user = userEvent.setup()
    open('/teams/1?tab=roster')
    await user.click(await screen.findByRole('button', { name: /Plan launch/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Deck needs the key to plan a launch.')).toBeInTheDocument()
  })
})
