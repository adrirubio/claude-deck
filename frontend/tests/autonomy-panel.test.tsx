import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AutonomyPanel } from '../src/features/agent-teams/AutonomyPanel'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { ApiHttpError } from '../src/lib/api'
import type { AgentTeamPreset, GithubScopeRevision, GithubWorkItem, TeamGithubScope } from '../src/types/agentTeams'

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
    }))
  })

  it('does not PATCH an unchanged scope', async () => {
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)

    await user.click(screen.getByRole('button', { name: 'Edit example/project' }))
    await user.click(screen.getByRole('button', { name: 'Save repo' }))

    expect(props.onUpdateScope).not.toHaveBeenCalled()
  })
})
