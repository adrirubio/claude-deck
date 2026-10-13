import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { fetchAgentMailTeam } from '../src/features/agent-mail/api'
import { fetchCCSessions } from '../src/features/cc-bridge/api'
import type { AgentSession } from '../src/features/cc-bridge/types'
import { AgentTeamsPage } from '../src/features/agent-teams/AgentTeamsPage'
import {
  createAgentTeamFromBridge, createAgentTeamFromMail, createAgentTeamPreset, fetchAgentTeamPresets,
} from '../src/features/agent-teams/api'
import { setOperatorToken, clearOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { groupPickItems, isTemporaryPath, sessionsToSlots } from '../src/features/agent-teams/teamSources'
import type { MailMemberResponse } from '../src/types/agentMail'
import type { AgentTeamPreset } from '../src/types/agentTeams'
import { resetFactoryReads } from '../src/features/factory/reads'
import { fixtureFetch, jsonResponse } from './helpers/factory'

// #543: a create dialog adds only the members that the person saw and selected.
vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return {
    ...actual,
    fetchAgentTeamPresets: vi.fn(),
    fetchTeamGithubScopes: vi.fn().mockResolvedValue({ scopes: [] }),
    fetchGithubWorkItems: vi.fn().mockResolvedValue({ items: [] }),
    fetchGithubRecoveryGateActive: vi.fn().mockResolvedValue({ active: false }),
    fetchAgentTeamActivity: vi.fn().mockResolvedValue({ preset_id: 1, checked_at: '', valid_until: '2000-01-01T00:00:00Z', slots: [] }),
    createAgentTeamPreset: vi.fn(),
    createAgentTeamFromMail: vi.fn(),
    createAgentTeamFromBridge: vi.fn(),
  }
})
vi.mock('../src/features/cc-bridge/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/cc-bridge/api')>()
  return { ...actual, fetchCCSessions: vi.fn() }
})
vi.mock('../src/features/agent-mail/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-mail/api')>()
  return { ...actual, fetchAgentMailTeam: vi.fn() }
})
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))
vi.mock('../src/features/agent-teams/BacklogCoordination', () => ({ BacklogCoordination: () => null }))
vi.mock('../src/hooks/useProviders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/hooks/useProviders')>()
  return { ...actual, fetchProviderLaunchOptions: vi.fn(async (provider: string) => ({ provider, supported_launch_modes: ['plain'] })) }
})

const stamp = '2026-10-12T12:00:00Z'
const created = { id: 9, name: 'New', created_at: stamp, updated_at: stamp, autonomy_enabled: false, slots: [] } as unknown as AgentTeamPreset

function session(name: string, cwd: string, extra: Partial<AgentSession> = {}): AgentSession {
  return {
    provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: `${name}:0.0`, session_name: name,
    window_name: 'w', pane_id: '%1', cwd, pid: '1', status: 'running', ...extra,
  }
}
function member(id: number, name: string, path: string, extra: Partial<MailMemberResponse> = {}): MailMemberResponse {
  return {
    id, identity_key: `k${id}`, repo_id: 'r', repo_path: path, repo_name: name, display_name: name,
    participant_kind: 'repo', status: 'connected', unread_count: 0, pending_count: 0, unseen_pending_count: 0,
    stale_pending_count: 0, can_nudge: false, sessions: [], ...extra,
  } as MailMemberResponse
}

beforeEach(() => {
  resetFactoryReads()
  setOperatorToken('test-key')
  vi.mocked(fetchAgentTeamPresets).mockResolvedValue({ presets: [] })
  vi.mocked(createAgentTeamPreset).mockResolvedValue(created)
  vi.mocked(createAgentTeamFromMail).mockResolvedValue(created)
  fixtureFetch(() => jsonResponse({ detail: 'x' }, 404))
})
afterEach(() => {
  cleanup()
  clearOperatorToken()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

function open() {
  return render(
    <MemoryRouter initialEntries={['/teams']}>
      <Routes><Route path="/teams" element={<AgentTeamsPage />} /></Routes>
    </MemoryRouter>,
  )
}
const dialog = async () => within(await screen.findByRole('dialog'))
const checkbox = (view: ReturnType<typeof within>, name: RegExp) =>
  view.getByText(name).closest('label')!.querySelector('button[role="checkbox"]') as HTMLElement

describe('From Bridge', () => {
  const sessions = [
    session('free-b', '/work/b'),
    session('free-a', '/work/a'),
    session('held', '/work/held', { team_preset_name: 'major-release-v3', team_preset_id: 1 }),
    session('no-folder', ''),
    session('odd', '/work/odd', { provider: 'unknown-cli' as AgentSession['provider'] }),
  ]
  beforeEach(() => vi.mocked(fetchCCSessions).mockResolvedValue({ sessions, count: sessions.length }))

  it('lists the live sessions in groups and preselects only sessions that are not in a team', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Bridge/ }))
    const view = await dialog()
    await view.findByText('free-a')
    expect(view.getByRole('region', { name: 'Not in a team' })).toBeInTheDocument()
    const held = view.getByRole('region', { name: 'Already in major-release-v3' })
    expect(within(held).getByText('held')).toBeInTheDocument()
    expect(within(held).getByText('in major-release-v3')).toBeInTheDocument()
    expect(view.queryByText('no-folder')).not.toBeInTheDocument()
    expect(view.queryByText('odd')).not.toBeInTheDocument()
    expect(checkbox(view, /^free-a$/)).toHaveAttribute('aria-checked', 'true')
    expect(checkbox(view, /^free-b$/)).toHaveAttribute('aria-checked', 'true')
    expect(checkbox(view, /^held$/)).toHaveAttribute('aria-checked', 'false')
    expect(view.getByRole('button', { name: 'Create team with 2 members' })).toBeEnabled()
  })

  it('creates the team with exactly the selected sessions, through the create route', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Bridge/ }))
    const view = await dialog()
    await view.findByText('free-a')
    await user.click(checkbox(view, /^free-b$/)) // deselect b
    await user.click(checkbox(view, /^held$/)) // select a session that is in a team
    expect(view.getByRole('button', { name: 'Create team with 2 members' })).toBeEnabled()
    await user.click(view.getByRole('button', { name: 'Create team with 2 members' }))
    await waitFor(() => expect(createAgentTeamPreset).toHaveBeenCalledTimes(1))
    const [input, token] = vi.mocked(createAgentTeamPreset).mock.calls[0]
    expect(token).toBe('test-key')
    expect(input.slots).toEqual([
      { display_name: 'free-a', provider: 'claude-code', repo_path: '/work/a' },
      { display_name: 'held', provider: 'claude-code', repo_path: '/work/held' },
    ])
    expect(createAgentTeamFromBridge).not.toHaveBeenCalled()
  })

  it('disables Create at zero selected', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Bridge/ }))
    const view = await dialog()
    await view.findByText('free-a')
    await user.click(checkbox(view, /^free-a$/))
    await user.click(checkbox(view, /^free-b$/))
    expect(view.getByRole('button', { name: 'Create team with 0 members' })).toBeDisabled()
  })

  it('says so when there are no live sessions', async () => {
    vi.mocked(fetchCCSessions).mockResolvedValue({ sessions: [], count: 0 })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Bridge/ }))
    const view = await dialog()
    expect(await view.findByText('No live sessions found.')).toBeInTheDocument()
    expect(view.getByRole('button', { name: 'Create team with 0 members' })).toBeDisabled()
  })

  it('shows the backend error for a refused folder and keeps the dialog open', async () => {
    vi.mocked(createAgentTeamPreset).mockRejectedValue(new Error('Repository path is not a Git repository'))
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Bridge/ }))
    const view = await dialog()
    await view.findByText('free-a')
    await user.click(view.getByRole('button', { name: 'Create team with 2 members' }))
    await waitFor(() => expect(createAgentTeamPreset).toHaveBeenCalled())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Repository path is not a Git repository'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})

describe('From Mail', () => {
  const members = [
    member(1, 'free-online', '/work/free'),
    member(2, 'in-team', '/work/team', { team_preset_id: 5, team_preset_name: 'major-release-v3', participant_kind: 'team_slot' }),
    member(3, 'gone', '/work/gone', { status: 'offline' }),
    member(4, 'scratch', '/tmp/b2-head-check/backend'),
  ]
  beforeEach(() => vi.mocked(fetchAgentMailTeam).mockResolvedValue({ members }))

  it('hides offline and temporary members and preselects only members that are not in a team', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Mail/ }))
    const view = await dialog()
    await view.findByText('free-online')
    expect(view.getByText('in-team')).toBeInTheDocument()
    expect(view.queryByText('gone')).not.toBeInTheDocument()
    expect(view.queryByText('scratch')).not.toBeInTheDocument()
    expect(checkbox(view, /^free-online$/)).toHaveAttribute('aria-checked', 'true')
    expect(checkbox(view, /^in-team$/)).toHaveAttribute('aria-checked', 'false')
    expect(view.getByRole('button', { name: 'Create team with 1 member' })).toBeEnabled()
    await user.click(view.getByLabelText('Show offline and temporary'))
    expect(view.getByText('gone')).toBeInTheDocument()
    expect(view.getByText('scratch')).toBeInTheDocument()
    // Showing them selects nothing.
    expect(checkbox(view, /^gone$/)).toHaveAttribute('aria-checked', 'false')
    expect(checkbox(view, /^scratch$/)).toHaveAttribute('aria-checked', 'false')
  })

  it('sends exactly the selected member ids, and drops hidden ones when the box is cleared', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Mail/ }))
    const view = await dialog()
    await view.findByText('free-online')
    await user.click(view.getByLabelText('Show offline and temporary'))
    await user.click(checkbox(view, /^gone$/))
    await user.click(checkbox(view, /^in-team$/))
    expect(view.getByRole('button', { name: 'Create team with 3 members' })).toBeEnabled()
    await user.click(view.getByLabelText('Show offline and temporary'))
    expect(view.getByRole('button', { name: 'Create team with 2 members' })).toBeEnabled()
    await user.click(view.getByRole('button', { name: 'Create team with 2 members' }))
    await waitFor(() => expect(createAgentTeamFromMail).toHaveBeenCalledTimes(1))
    const [input] = vi.mocked(createAgentTeamFromMail).mock.calls[0]
    expect([...(input.member_ids ?? [])].sort()).toEqual([1, 2])
    expect(input.include_offline).toBe(true)
  })

  it('marks members of an existing team with its name', async () => {
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: /From Mail/ }))
    const view = await dialog()
    const held = await view.findByRole('region', { name: 'Already in major-release-v3' })
    expect(within(held).getByText('in major-release-v3')).toBeInTheDocument()
  })
})

describe('pure helpers', () => {
  it('maps sessions to slots the way the backend does: name, provider, folder, sorted by folder', () => {
    const slots = sessionsToSlots([
      session('b', '/z/b'),
      session('', '/a/folder-name'),
      session('c', '/a/folder-name', { provider: 'codex-cli', tmux_target: 'c:0.0' }),
    ])
    expect(slots).toEqual([
      { display_name: 'folder-name', provider: 'claude-code', repo_path: '/a/folder-name' },
      { display_name: 'c', provider: 'codex-cli', repo_path: '/a/folder-name' },
      { display_name: 'b', provider: 'claude-code', repo_path: '/z/b' },
    ])
  })

  it('groups free members first, then each team by name', () => {
    const groups = groupPickItems([
      { id: '1', label: 'a', detail: '', team: 'Zed' },
      { id: '2', label: 'b', detail: '', team: null },
      { id: '3', label: 'c', detail: '', team: 'Alpha' },
    ])
    expect(groups.map((group) => group.title)).toEqual(['Not in a team', 'Already in Alpha', 'Already in Zed'])
  })

  it.each([['/tmp/x', true], ['/var/tmp/x/y', true], ['/tmp', true], ['/home/u/tmp/x', false], ['/work/tmpfs', false]])(
    'knows temporary folder %s is %s', (path, expected) => {
      expect(isTemporaryPath(path)).toBe(expected)
    },
  )
})
