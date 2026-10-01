import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentTeamsPage } from '../src/features/agent-teams/AgentTeamsPage'
import { fetchAgentTeamPresets, launchAgentTeam, planAgentTeamLaunch } from '../src/features/agent-teams/api'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { ApiHttpError } from '../src/lib/api'
import type { AgentTeamLaunchPlan, AgentTeamLaunchResult, AgentTeamPreset } from '../src/types/agentTeams'

vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return {
    ...actual,
    fetchAgentTeamPresets: vi.fn(),
    planAgentTeamLaunch: vi.fn(),
    launchAgentTeam: vi.fn(),
  }
})

vi.mock('../src/hooks/useProviders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/hooks/useProviders')>()
  return {
    ...actual,
    fetchProviderLaunchOptions: vi.fn(async (provider: string) => ({
      provider,
      supported_launch_modes: ['plain'],
    })),
  }
})

const timestamp = '2026-10-01T12:00:00Z'

const preset: AgentTeamPreset = {
  id: 1,
  name: 'Test team',
  created_at: timestamp,
  updated_at: timestamp,
  autonomy_enabled: false,
  slots: [{
    id: 2,
    preset_id: 1,
    position: 1,
    display_name: 'Leader',
    provider: 'codex-cli',
    repo_id: 'repo',
    repo_path: '/tmp/repo',
    repo_name: 'repo',
    launch_mode: 'plain',
    launch_options: {},
    enabled: true,
    created_at: timestamp,
    updated_at: timestamp,
  }],
}

const plan: AgentTeamLaunchPlan = {
  preset_id: 1,
  preset_name: 'Test team',
  plan_hash: 'plan-hash',
  generated_at: timestamp,
  can_launch: true,
  items: [{
    slot_id: 2,
    slot_name: 'Leader',
    provider: 'codex-cli',
    repo_id: 'repo',
    repo_path: '/tmp/repo',
    repo_name: 'repo',
    action: 'spawn',
    status: 'ready',
    reasons: [],
  }],
  reuse_count: 0,
  adopt_count: 0,
  spawn_count: 1,
  skipped_count: 0,
  blocked_count: 0,
}

const result: AgentTeamLaunchResult = {
  launch_id: 3,
  preset_id: 1,
  preset_name: 'Test team',
  plan_hash: 'plan-hash',
  status: 'completed',
  launched_at: timestamp,
  completed_at: timestamp,
  items: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  clearOperatorToken()
  vi.mocked(fetchAgentTeamPresets).mockResolvedValue({ presets: [preset] })
  vi.mocked(planAgentTeamLaunch).mockResolvedValue(plan)
  vi.mocked(launchAgentTeam).mockResolvedValue(result)
})

describe('AgentTeamsPage launch authorization', () => {
  it('shows only the token dialog before the first plan request', async () => {
    const user = userEvent.setup()
    render(<AgentTeamsPage />)

    await user.click(await screen.findByRole('button', { name: 'Plan launch' }))
    const tokenDialog = await screen.findByRole('dialog', { name: 'Operator token' })
    expect(screen.queryByRole('dialog', { name: 'Launch Plan' })).not.toBeInTheDocument()
    expect(planAgentTeamLaunch).not.toHaveBeenCalled()

    const input = within(tokenDialog).getByLabelText(/Operator token/)
    await user.click(input)
    expect(input).toHaveFocus()
    await user.type(input, 'test-token{Enter}')

    await waitFor(() => expect(planAgentTeamLaunch).toHaveBeenCalledWith(
      1, { slot_ids: null, adopt_unbound_sessions: false, reuse_existing: true }, 'test-token'
    ))
    expect(await screen.findByRole('dialog', { name: 'Launch Plan' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Operator token' })).not.toBeInTheDocument()
  })

  it('hides the plan while re-prompting after a rejected launch token', async () => {
    setOperatorToken('old-token')
    vi.mocked(launchAgentTeam)
      .mockRejectedValueOnce(new ApiHttpError('The operator token was rejected.', 401))
      .mockResolvedValueOnce(result)
    const user = userEvent.setup()
    render(<AgentTeamsPage />)

    await user.click(await screen.findByRole('button', { name: 'Plan launch' }))
    expect(await screen.findByRole('dialog', { name: 'Launch Plan' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Launch' }))

    const tokenDialog = await screen.findByRole('dialog', { name: 'Operator token' })
    expect(screen.queryByRole('dialog', { name: 'Launch Plan' })).not.toBeInTheDocument()
    const input = within(tokenDialog).getByLabelText(/Operator token/)
    await user.click(input)
    await user.type(input, 'new-token{Enter}')

    await waitFor(() => expect(launchAgentTeam).toHaveBeenLastCalledWith(
      1, expect.objectContaining({ confirm_plan_hash: 'plan-hash' }), 'new-token'
    ))
    expect(await screen.findByRole('dialog', { name: 'Launch Plan' })).toBeInTheDocument()
  })
})
