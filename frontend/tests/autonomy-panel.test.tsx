import { StrictMode, useState } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AutonomyPanel } from '../src/features/agent-teams/AutonomyPanel'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { ApiHttpError } from '../src/lib/api'
import { fetchGithubRecoveryGateActive } from '../src/features/agent-teams/api'
import type { AgentTeamPreset, GithubScopeRevision, GithubWorkItem, TeamGithubScope } from '../src/types/agentTeams'

vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return { ...actual, fetchGithubRecoveryGateActive: vi.fn().mockResolvedValue({ active: false }) }
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

const revision = {
  id: 10,
  revision: 1,
  summary: 'Hosted-only diagnostic',
  phase: 'diagnostic',
  status: 'proposed',
  failed_head_count: 0,
  max_failed_heads: 1,
  allowed_paths: [],
  allowed_actions: [],
  allowed_commands: [],
  evidence: null,
} as unknown as GithubScopeRevision

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
    onCreateScope: vi.fn().mockResolvedValue(undefined),
    onUpdateScope: vi.fn().mockResolvedValue(undefined),
    onUpdateContinuationPolicy: vi.fn().mockResolvedValue(undefined),
    onDeleteScope: vi.fn().mockResolvedValue(undefined),
    onRetryWorkItem: vi.fn().mockResolvedValue(undefined),
    onFetchScopeRevisions: vi.fn().mockResolvedValue([revision]),
    onCancelContinuationRequest: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('AutonomyPanel', () => {
  it('distinguishes a missing polling token from unresolved dispatch mode after a poll', () => {
    const view = render(<AutonomyPanel {...panelProps({ scopes: [{ ...scope, github_auth_mode: 'unknown', github_poll_token_configured: false }], workItems: [] })} />)
    expect(screen.getByText('Polling token not set')).toHaveAttribute('title', expect.stringContaining('backend/.env'))
    view.rerender(<AutonomyPanel {...panelProps({ scopes: [{ ...scope, github_auth_mode: 'unknown', last_polled_at: '2026-09-29T12:00:00Z' }], workItems: [] })} />)
    expect(screen.getByText('Dispatch auth: not selected')).toHaveAttribute('title', expect.stringContaining('successful poll'))
    expect(screen.queryByText('Polling token not set')).not.toBeInTheDocument()
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

  it('offers keyboard-accessible status, phase, and route explanations', async () => {
    const user = userEvent.setup()
    render(<AutonomyPanel {...panelProps()} />)
    const helpButton = screen.getByRole('button', { name: 'What do statuses, phases, and routes mean?' })
    helpButton.focus()
    await user.keyboard('{Enter}')
    expect(helpButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/Label match means an area label chose the owner/)).toBeVisible()
  })

  it('does not claim an escalated active revision is still running', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const props = panelProps({ workItems: [{ ...workItem, active_scope_status: 'active', escalation_reason: 'dispatch_label_removed' }] })
    const view = render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'View issue #821 details' }))
    expect(screen.getByText('This issue is escalated. Review the reason above before continuing recovery.')).toBeInTheDocument()
    expect(screen.queryByText(/No operator action is needed/)).not.toBeInTheDocument()
    view.rerender(<AutonomyPanel {...props} workItems={[{ ...workItem, dispatch_status: 'dispatched', active_scope_status: 'active', continuation_block_code: 'continuation_disabled' }]} />)
    expect(screen.getByText('Recovery policy is off for this repo. Existing work may still need attention.')).toBeInTheDocument()
    expect(screen.queryByText(/No operator action is needed/)).not.toBeInTheDocument()
  })

  it('defines recovery limits and phase and status badges', async () => {
    const user = userEvent.setup()
    render(<AutonomyPanel {...panelProps()} />)
    const row = screen.getByRole('row', { name: /#821 — Fix playback/ })
    expect(within(row).getByText('Your intervention is needed')).toHaveAttribute('title', expect.stringContaining('Deck stopped this attempt'))
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    expect(screen.getByText(/A failed head is a pushed PR commit whose checks fail/)).toBeInTheDocument()
    expect(screen.getByText('Scope revisions allowed across one attempt.')).toBeInTheDocument()
    expect(screen.getByText('Saving requires the operator token.', { exact: false })).toBeInTheDocument()
  })

  it('explains first-run setup and optional build hints', async () => {
    const user = userEvent.setup()
    render(<AutonomyPanel {...panelProps({ scopes: [], workItems: [] })} />)
    expect(screen.getByText('Before you enable autonomy')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add repo' }))
    expect(screen.getByText('Build instructions for the agent (optional)')).toBeInTheDocument()
    expect(screen.getByText(/Deck does not run a build/)).toBeInTheDocument()
    expect(screen.getByText(/may include \{issue_number\}/)).toBeInTheDocument()
  })

  it('asks for a token on the first history load, then shows the history', async () => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = panelProps()
    render(<AutonomyPanel {...props} />)

    await user.click(screen.getByRole('button', { name: 'View issue #821 details' }))
    expect(screen.getByText('Enter an operator token to load recovery history.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry loading history' }))
    await user.type(screen.getByPlaceholderText('Enter secret value'), 'test-token')
    await user.click(screen.getByRole('button', { name: 'Use token' }))

    expect(await screen.findByText('Hosted-only diagnostic')).toBeInTheDocument()
    expect(props.onFetchScopeRevisions).toHaveBeenCalledWith(23, 'test-token')
  })

  it('shows a rejected-token prompt and retries with the replacement token', async () => {
    setOperatorToken('old-token')
    const user = userEvent.setup()
    const fetchRevisions = vi.fn()
      .mockRejectedValueOnce(new ApiHttpError('The operator token was rejected.', 401))
      .mockResolvedValue([revision])
    render(<AutonomyPanel {...panelProps({ onFetchScopeRevisions: fetchRevisions })} />)

    await user.click(screen.getByRole('button', { name: 'View issue #821 details' }))
    expect(await screen.findByText('The operator token was rejected. Enter a valid token to retry.')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('Enter secret value'), 'new-token')
    await user.click(screen.getByRole('button', { name: 'Use token' }))

    expect(await screen.findByText('Hosted-only diagnostic')).toBeInTheDocument()
    expect(fetchRevisions).toHaveBeenLastCalledWith(23, 'new-token')
  })

  it('keeps a delayed history request alive across StrictMode and parent polling', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    let resolveHistory: (rows: GithubScopeRevision[]) => void = () => {}
    const fetchRevisions = vi.fn(() => new Promise<GithubScopeRevision[]>((resolve) => { resolveHistory = resolve }))
    const props = panelProps({ onFetchScopeRevisions: fetchRevisions })
    const view = render(<StrictMode><AutonomyPanel {...props} /></StrictMode>)

    await user.click(screen.getByRole('button', { name: 'View issue #821 details' }))
    await waitFor(() => expect(fetchRevisions).toHaveBeenCalled())
    view.rerender(<StrictMode><AutonomyPanel {...props} workItems={[{ ...workItem }]} refreshing /></StrictMode>)
    resolveHistory([revision])

    expect(await screen.findByText('Hosted-only diagnostic')).toBeInTheDocument()
    expect(screen.queryByText('Loading recovery history…')).not.toBeInTheDocument()
  })

  it('shows pending authentication failures in the activity row', () => {
    render(<AutonomyPanel {...panelProps({ workItems: [{ ...workItem, dispatch_status: 'pending', pending_reason: 'queued_auth_mode_unresolved', status_note: 'Configure a GitHub App.' }] })} />)
    const row = screen.getByRole('row', { name: /#821 — Fix playback/ })
    expect(within(row).getByText('queued · GitHub authentication needs configuration')).toBeInTheDocument()
    expect(within(row).getByText('Configure a GitHub App.')).toBeInTheDocument()
  })

  it('sends only changed scope fields and an explicit null when clearing the build hint', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)

    await user.click(screen.getByRole('button', { name: 'Edit example/project' }))
    fireEvent.change(screen.getByLabelText('Build command hint'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Max approval rounds'), { target: { value: '4' } })
    await user.click(screen.getByRole('button', { name: 'Save repo' }))

    await waitFor(() => expect(props.onUpdateScope).toHaveBeenCalledWith(2, {
      build_command_hint: null,
      max_approval_rounds: 4,
    }, 'test-token'))
  })

  it('does not PATCH an unchanged scope', async () => {
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)

    await user.click(screen.getByRole('button', { name: 'Edit example/project' }))
    await user.click(screen.getByRole('button', { name: 'Save repo' }))

    expect(props.onUpdateScope).not.toHaveBeenCalled()
  })

  it('submits the operator token with Enter', async () => {
    clearOperatorToken()
    const user = userEvent.setup()
    render(<AutonomyPanel {...panelProps({ workItems: [] })} />)

    await user.click(screen.getByRole('button', { name: 'Set operator token' }))
    await user.type(screen.getByPlaceholderText('Enter secret value'), 'test-token{Enter}')

    expect(await screen.findByText('Token set for this tab')).toBeInTheDocument()
  })

  it('confirms watched-repo removal in the app instead of using a native dialog', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    const confirm = vi.spyOn(window, 'confirm')
    function RemovalHarness() {
      const [scopes, setScopes] = useState([scope])
      return <AutonomyPanel {...props} scopes={scopes} onDeleteScope={async (target, token) => {
        await props.onDeleteScope(target, token)
        setScopes([])
      }} />
    }
    render(<RemovalHarness />)

    await user.click(screen.getByRole('button', { name: 'Remove example/project' }))
    expect(screen.getByText('Remove watched repo?')).toBeInTheDocument()
    expect(screen.getByText(/permanently deletes its saved work-item history/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(props.onDeleteScope).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove example/project' })).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Remove example/project' }))
    await user.click(screen.getByRole('button', { name: 'Remove repo' }))
    await waitFor(() => expect(props.onDeleteScope).toHaveBeenCalledWith(scope, 'test-token'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add repo' })).toHaveFocus())
    expect(confirm).not.toHaveBeenCalled()
    confirm.mockRestore()
  })

  it('reports a prepared attempt as queued after the backend returns pending', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(
      JSON.stringify({ ...workItem, dispatch_status: 'pending' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    render(<AutonomyPanel {...panelProps({ workItems: [{ ...workItem, escalation_reason: 'prepared_owner_unavailable' }] })} />)

    await user.click(screen.getByRole('button', { name: 'View issue #821 details' }))
    await user.click(screen.getByRole('button', { name: 'Resume prepared attempt' }))
    await user.click(screen.getByRole('button', { name: 'Confirm action' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Prepared attempt queued for resumption.')
    fetchMock.mockRestore()
  })
})
