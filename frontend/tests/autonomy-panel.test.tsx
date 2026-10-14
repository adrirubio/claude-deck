import { MemoryRouter } from 'react-router-dom'
import { render as renderUi, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { AutonomyPanel, OperatorTokenDialog } from '../src/features/agent-teams/AutonomyPanel'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { fetchGithubRecoveryGateActive } from '../src/features/agent-teams/api'
import type { AgentTeamPreset, GithubWorkItem, TeamGithubScope } from '../src/types/agentTeams'

vi.mock('../src/features/agent-teams/BacklogCoordination', () => ({ BacklogCoordination: () => null }))
// The publication reader has its own request, expiry and error tests.
vi.mock('../src/features/agent-teams/WorkPublicationPanel', () => ({ WorkPublicationPanel: () => null }))

vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return { ...actual, fetchGithubRecoveryGateActive: vi.fn().mockResolvedValue({ active: false }) }
})

// The panel links to Work, so it renders inside a router.
const render = (ui: React.ReactElement) => renderUi(ui, { wrapper: MemoryRouter })

// JSDOM lacks the browser methods used by Radix's real Select interaction.
const browserMethods = ['hasPointerCapture', 'scrollIntoView'] as const
const descriptors = browserMethods.map(name => Object.getOwnPropertyDescriptor(HTMLElement.prototype, name))
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', { configurable: true, value: () => false })
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: () => undefined })
})
afterAll(() => {
  browserMethods.forEach((name, index) => {
    if (descriptors[index]) Object.defineProperty(HTMLElement.prototype, name, descriptors[index]!)
    else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name]
  })
})

const preset: AgentTeamPreset = {
  id: 1,
  name: 'Test team',
  created_at: '2026-09-29T12:00:00Z',
  updated_at: '2026-09-29T12:00:00Z',
  autonomy_enabled: false,
  slots: [],
}

const scope: TeamGithubScope = {
  id: 2,
  preset_id: 1,
  repo_owner: 'example',
  repo_name: 'project',
  repo_path: '/tmp/project',
  dispatch_label: 'claude-deck-ready',
  design_label: 'claude-deck-design',
  merge_policy: 'human',
  github_auth_mode: 'app',
  github_auth_configured: true,
  github_poll_token_configured: true,
  max_approval_rounds: 3,
  max_concurrent_dispatched: 3,
  max_verification_retries: 2,
  max_auto_merges_per_day: 5,
  base_ref: 'origin/HEAD',
  builds_out_of_tree: false,
  build_dir_template: 'build',
  build_command_hint: 'meson compile',
  max_build_parallelism: 4,
  continuation_enabled: false,
  max_continuation_revisions: 3,
  max_continuation_failed_heads: 8,
  max_failed_heads_per_revision: 1,
  max_scope_paths: 4,
  max_scope_commands: 8,
  enabled: true,
  created_at: '2026-09-29T12:00:00Z',
  updated_at: '2026-09-29T12:00:00Z',
}

const workItem: GithubWorkItem = {
  id: 23,
  scope_id: 2,
  repo_owner: 'example',
  repo_name: 'project',
  issue_number: 821,
  issue_title: 'Fix playback',
  issue_url: 'https://github.com/example/project/issues/821',
  github_updated_at: '2026-09-29T12:00:00Z',
  issue_type: 'code',
  dispatch_status: 'escalated',
  approval_round_count: 1,
  retry_count: 0,
  active_scope_revision: 1,
  attempt_phase: 'implementation',
  diagnostic_retry_count: 0,
  retry_allowed: false,
  created_at: '2026-09-29T12:00:00Z',
  updated_at: '2026-09-29T12:00:00Z',
}

function panelProps(overrides: Partial<Parameters<typeof AutonomyPanel>[0]> = {}) {
  return {
    preset,
    scopes: [scope],
    workItems: [workItem],
    loading: false,
    refreshing: false,
    lastRefreshedAt: null,
    loadError: null,
    onRefresh: vi.fn().mockResolvedValue(undefined),
    onToggleAutonomy: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('AutonomyPanel', () => {
  it('explains the Director key across protected settings and first-run actions', () => {
    render(<AutonomyPanel {...panelProps({ scopes: [], workItems: [] })} />)
    expect(screen.getByText('Protects settings, launch, autonomy and recovery')).toBeInTheDocument()
    expect(screen.getByText(/The Director key protects roster and watched-repo settings/)).toHaveTextContent('separate from the GitHub polling token')
    expect(screen.queryByText(/only needed for protected recovery|needed only for protected recovery/i)).not.toBeInTheDocument()
  })

  it('hides the soak-only gate until active and explains it when active', async () => {
    const view = render(<AutonomyPanel {...panelProps({ workItems: [] })} />)
    expect(screen.queryByRole('button', { name: 'Recovery-only mode' })).not.toBeInTheDocument()
    view.unmount()
    vi.mocked(fetchGithubRecoveryGateActive).mockResolvedValueOnce({ active: true })
    render(<AutonomyPanel {...panelProps({ workItems: [] })} />)
    expect(await screen.findByRole('button', { name: 'Recovery-only mode' })).toBeInTheDocument()
    expect(screen.getByText(/scheduler is limited to one configured issue attempt/)).toBeInTheDocument()
  })

  it('recovers gate visibility after a failed status check and Refresh', async () => {
    vi.mocked(fetchGithubRecoveryGateActive)
      .mockRejectedValueOnce(new Error('backend restarting'))
      .mockRejectedValueOnce(new Error('backend restarting'))
      .mockResolvedValueOnce({ active: true })
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    expect(await screen.findByText('Recovery-only mode could not be checked. Refresh before enabling autonomy.')).toBeInTheDocument()
    await user.click(screen.getByRole('switch', { name: 'Enable autonomous GitHub dispatch' }))
    expect(props.onToggleAutonomy).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Enable autonomous dispatch?' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(await screen.findByRole('button', { name: 'Recovery-only mode' })).toBeInTheDocument()
  })

  it('refuses enablement when the gate changes after confirmation', async () => {
    const user = userEvent.setup()
    const props = panelProps({ preset: { ...preset, slots: [] }, workItems: [] })
    render(<AutonomyPanel {...props} />)
    await waitFor(() => expect(screen.queryByText('Checking recovery-only mode…')).not.toBeInTheDocument())
    vi.mocked(fetchGithubRecoveryGateActive)
      .mockResolvedValueOnce({ active: false })
      .mockResolvedValueOnce({ active: true })
    await user.click(screen.getByRole('switch', { name: 'Enable autonomous GitHub dispatch' }))
    await user.click(screen.getByRole('button', { name: 'Enable autonomy' }))
    expect(await screen.findByText(/Recovery-only mode changed or could not be checked/)).toBeInTheDocument()
    expect(props.onToggleAutonomy).not.toHaveBeenCalled()
  })

  it('explains first-run setup and sends adding a repository to the one setup flow', () => {
    render(<AutonomyPanel {...panelProps({ scopes: [], workItems: [] })} />)
    expect(screen.getByText('Before you enable autonomy')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add a repository' })).toHaveAttribute('href', '/repositories/new?team_id=1')
    expect(screen.queryByRole('button', { name: /add repo/i })).not.toBeInTheDocument()
  })

  it('submits the Director key with Enter', async () => {
    clearOperatorToken()
    const user = userEvent.setup()
    render(<AutonomyPanel {...panelProps({ workItems: [] })} />)

    await user.click(screen.getByRole('button', { name: 'Set Director key' }))
    await user.type(screen.getByPlaceholderText('Enter secret value'), 'test-token{Enter}')

    expect(await screen.findByText('Director key set for this tab')).toBeInTheDocument()
  })

  it('lists watched repos as short cards that link to the Repository page', () => {
    render(<AutonomyPanel {...panelProps({ workItems: [] })} />)
    expect(screen.getByText('example/project')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage example/project' })).toHaveAttribute('href', '/repositories/2')
    expect(screen.getByText('Off · team autonomy off')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit example/project' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove example/project' })).not.toBeInTheDocument()
  })

  it('shows Off for a repo that is switched off and On when the team autonomy is on', () => {
    const view = render(<AutonomyPanel {...panelProps({ scopes: [{ ...scope, enabled: false }], workItems: [] })} />)
    expect(screen.getByText('Off')).toBeInTheDocument()
    view.rerender(<AutonomyPanel {...panelProps({ preset: { ...preset, autonomy_enabled: true }, workItems: [] })} />)
    expect(screen.getByText('On')).toBeInTheDocument()
  })
})

describe('OperatorTokenDialog', () => {
  const noop = () => undefined

  it('asks for one thing, states the reason and hides the setup steps', () => {
    render(<OperatorTokenDialog open value="" error={null} reason="to read audit events" onValueChange={noop} onSubmit={noop} onCancel={noop} />)

    const dialog = screen.getByRole('dialog', { name: 'Director key' })
    expect(within(dialog).getByText(/It is the value of/)).toHaveTextContent('OPERATOR_TOKEN')
    expect(within(dialog).getByText('Deck needs the key to read audit events.')).toBeInTheDocument()
    expect(within(dialog).getByText('First time? Set up the key on the server').closest('details')).not.toHaveAttribute('open')
    expect(within(dialog).getByRole('link', { name: 'installation guide', hidden: true })).toHaveAttribute('href', expect.stringContaining('docs/guide/installation.md'))
  })

  it('omits the reason line when the caller gives no reason', () => {
    render(<OperatorTokenDialog open value="" error={null} onValueChange={noop} onSubmit={noop} onCancel={noop} />)

    expect(screen.queryByText(/Deck needs the key/)).not.toBeInTheDocument()
  })
})
