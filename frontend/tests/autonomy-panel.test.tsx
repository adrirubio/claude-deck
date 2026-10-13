import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render as renderUi, screen, waitFor, within } from '@testing-library/react'
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
    onCreateScope: vi.fn().mockResolvedValue(undefined),
    onUpdateScope: vi.fn().mockResolvedValue(undefined),
    onUpdateContinuationPolicy: vi.fn().mockResolvedValue(undefined),
    onDeleteScope: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('AutonomyPanel', () => {
  it('explains the Director key across protected settings and first-run actions', () => {
    render(<AutonomyPanel {...panelProps({ scopes: [], workItems: [] })} />)
    expect(screen.getByText('Needed for protected settings, launch, autonomy, and recovery actions')).toBeInTheDocument()
    expect(screen.getByText(/The Director key protects roster and watched-repo settings/)).toHaveTextContent('separate from the GitHub polling token')
    expect(screen.queryByText(/only needed for protected recovery|needed only for protected recovery/i)).not.toBeInTheDocument()
  })

  it('distinguishes a missing polling token from unresolved dispatch mode after a poll', () => {
    const view = render(<AutonomyPanel {...panelProps({ scopes: [{ ...scope, github_auth_mode: 'unknown', github_poll_token_configured: false }], workItems: [] })} />)
    expect(screen.getByText('Polling token not set')).toHaveAttribute('title', expect.stringContaining('backend/.env'))
    expect(screen.getByText(/Last polled/)).toHaveTextContent('Last polled never')
    view.rerender(<AutonomyPanel {...panelProps({ scopes: [{ ...scope, github_auth_mode: 'unknown', last_polled_at: '2026-09-29T12:00:00Z' }], workItems: [] })} />)
    expect(screen.getByText('Dispatch auth: not selected')).toHaveAttribute('title', expect.stringContaining('successful poll'))
    expect(screen.queryByText('Polling token not set')).not.toBeInTheDocument()
    expect(screen.getByText(/Last polled/)).toHaveTextContent(`Last polled ${new Date('2026-09-29T12:00:00Z').toLocaleString()}`)
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

  it('defines recovery limits and phase and status badges', async () => {
    const user = userEvent.setup()
    render(<AutonomyPanel {...panelProps()} />)
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    expect(screen.getByText(/A failed head is a pushed PR commit whose checks fail/)).toBeInTheDocument()
    expect(screen.getByText('Scope revisions allowed across one attempt.')).toBeInTheDocument()
    expect(screen.getByText('Saving requires the Director key.', { exact: false })).toBeInTheDocument()
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

  it('submits the Director key with Enter', async () => {
    clearOperatorToken()
    const user = userEvent.setup()
    render(<AutonomyPanel {...panelProps({ workItems: [] })} />)

    await user.click(screen.getByRole('button', { name: 'Set Director key' }))
    await user.type(screen.getByPlaceholderText('Enter secret value'), 'test-token{Enter}')

    expect(await screen.findByText('Director key set for this tab')).toBeInTheDocument()
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

})

// Synthetic UI contracts mirror schemas.py minima; the server declares no absolute maxima.
const scopeLimits = [
  { key: 'max_approval_rounds', label: 'Max approval rounds', minimum: 1 },
  { key: 'max_concurrent_dispatched', label: 'Max concurrent dispatched', minimum: 1 },
  { key: 'max_verification_retries', label: 'Max verification retries', minimum: 0 },
  { key: 'max_auto_merges_per_day', label: 'Max auto-merges per day', minimum: 0 },
  { key: 'max_build_parallelism', label: 'Max build parallelism', minimum: 1 },
] as const
const policyLimits = [
  { key: 'max_continuation_revisions', label: 'Attempt revision cap', minimum: 1 },
  { key: 'max_continuation_failed_heads', label: 'Attempt failed-head cap', minimum: 1 },
  { key: 'max_failed_heads_per_revision', label: 'Per-revision failed-head cap', minimum: 1 },
  { key: 'max_scope_paths', label: 'Paths per revision', minimum: 1 },
  { key: 'max_scope_commands', label: 'Commands per revision', minimum: 1 },
] as const

describe('AutonomyPanel numeric limits', () => {
  it.each(scopeLimits)('keeps $label editable and normalizes only on blur before a changed-field save', async ({ key, label }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = panelProps({ scopes: [{ ...scope, merge_policy: 'auto' }], workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Edit example/project' }))
    const input = screen.getByLabelText(label) as HTMLInputElement
    expect(input).not.toHaveAttribute('max')
    await user.clear(input)
    expect(input.value).toBe('')
    await user.type(input, '12')
    expect(input.value).toBe('12')
    fireEvent.change(input, { target: { value: '1.2e1' } })
    expect(input.value).toBe('1.2e1')
    expect(props.onUpdateScope).not.toHaveBeenCalled()
    await user.tab()
    expect(input.value).toBe('12')
    await user.click(screen.getByRole('button', { name: 'Save repo' }))
    await waitFor(() => expect(props.onUpdateScope).toHaveBeenCalledWith(2, { [key]: 12 }, 'synthetic-token'))
  })

  it.each(scopeLimits)('clamps $label to server minimum on blur and on submit without blur', async ({ key, label, minimum }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = panelProps({ scopes: [{ ...scope, merge_policy: 'auto' }], workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Edit example/project' }))
    const input = screen.getByLabelText(label) as HTMLInputElement
    expect(input).toHaveAttribute('min', String(minimum))
    fireEvent.change(input, { target: { value: String(minimum - 1) } })
    expect(input.value).toBe(String(minimum - 1))
    fireEvent.blur(input)
    expect(input.value).toBe(String(minimum))
    expect(props.onUpdateScope).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: String(minimum - 1) } })
    fireEvent.click(screen.getByRole('button', { name: 'Save repo' }))
    await waitFor(() => expect(props.onUpdateScope).toHaveBeenCalledWith(2, { [key]: minimum }, 'synthetic-token'))
  })

  it.each(policyLimits)('keeps $label editable and applies only the declared blur bounds', async ({ key, label }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    const input = screen.getByLabelText(label) as HTMLInputElement
    const expected = key === 'max_failed_heads_per_revision' ? 8 : 12
    if (key === 'max_failed_heads_per_revision') expect(input).toHaveAttribute('max', '8')
    else expect(input).not.toHaveAttribute('max')
    await user.clear(input)
    expect(input.value).toBe('')
    await user.type(input, '12')
    expect(input.value).toBe('12')
    fireEvent.change(input, { target: { value: '1.2e1' } })
    expect(input.value).toBe('1.2e1')
    expect(props.onUpdateContinuationPolicy).not.toHaveBeenCalled()
    await user.tab()
    expect(input.value).toBe(String(expected))
    await user.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    await waitFor(() => expect(props.onUpdateContinuationPolicy).toHaveBeenCalledWith(2, expect.objectContaining({ [key]: expected }), 'synthetic-token'))
  })

  it.each(policyLimits)('clamps $label on blur and on submit without blur', async ({ key, label, minimum }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    const input = screen.getByLabelText(label) as HTMLInputElement
    expect(input).toHaveAttribute('min', String(minimum))
    fireEvent.change(input, { target: { value: '0' } })
    expect(input.value).toBe('0')
    fireEvent.blur(input)
    expect(input.value).toBe('1')
    expect(props.onUpdateContinuationPolicy).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    await waitFor(() => expect(props.onUpdateContinuationPolicy).toHaveBeenCalledWith(2, expect.objectContaining({ [key]: minimum }), 'synthetic-token'))
  })

  it.each(['', '1.5', '1.0000000000000001', '1e-999', '1e309', '9007199254740993'])('blocks invalid scope value %j before requesting credentials or saving', async (value) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Edit example/project' }))
    const input = screen.getByLabelText('Max approval rounds') as HTMLInputElement
    fireEvent.change(input, { target: { value } })
    const editingValue = input.value
    fireEvent.blur(input)
    expect(input.value).toBe(editingValue)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent(/whole number for Max approval rounds/)
    fireEvent.click(screen.getByRole('button', { name: 'Save repo' }))
    expect(await screen.findAllByText(/whole number for max approval rounds/i)).not.toHaveLength(0)
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
    expect(props.onUpdateScope).not.toHaveBeenCalled()
    await user.clear(input)
    await user.type(input, '5')
    await user.tab()
    expect(input.value).toBe('5')
    expect(input).toHaveAttribute('aria-invalid', 'false')
  })

  it.each(['', '1.5', '1.0000000000000001', '1e-999', '1e309', '9007199254740993'])('blocks invalid policy value %j before requesting credentials or saving', async (value) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    const input = screen.getByLabelText('Attempt failed-head cap') as HTMLInputElement
    fireEvent.change(input, { target: { value } })
    const editingValue = input.value
    fireEvent.blur(input)
    expect(input.value).toBe(editingValue)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    expect(await screen.findAllByText(/whole number for max continuation failed heads/i)).not.toHaveLength(0)
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
    expect(props.onUpdateContinuationPolicy).not.toHaveBeenCalled()
  })

  it('clamps per-revision down to the current attempt cap without raising the attempt cap', async () => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    const total = screen.getByLabelText('Attempt failed-head cap') as HTMLInputElement
    const perRevision = screen.getByLabelText('Per-revision failed-head cap') as HTMLInputElement
    fireEvent.change(total, { target: { value: '2' } })
    fireEvent.change(perRevision, { target: { value: '5' } })
    expect(perRevision.value).toBe('5')
    fireEvent.blur(perRevision)
    expect(total.value).toBe('2')
    expect(perRevision.value).toBe('2')
    fireEvent.change(total, { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    await waitFor(() => expect(props.onUpdateContinuationPolicy).toHaveBeenCalledWith(2,
      expect.objectContaining({ max_continuation_failed_heads: 1, max_failed_heads_per_revision: 1 }), 'synthetic-token'))
  })

  it.each(['', '1.0000000000000001', '1e-999'])('does not infer a relational maximum from invalid attempt cap %j', async (value) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    fireEvent.change(screen.getByLabelText('Attempt failed-head cap'), { target: { value } })
    const perRevision = screen.getByLabelText('Per-revision failed-head cap') as HTMLInputElement
    expect(perRevision).not.toHaveAttribute('max')
    fireEvent.change(perRevision, { target: { value: '12' } })
    fireEvent.blur(perRevision)
    expect(perRevision.value).toBe('12')
    fireEvent.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    expect(await screen.findByText(/whole number for max continuation failed heads/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
    expect(props.onUpdateContinuationPolicy).not.toHaveBeenCalled()
  })

  it.each(['scope', 'policy'] as const)('cancels %s edits and pending protected authorization without a mutation', async (kind) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = panelProps({ workItems: [] })
    render(<AutonomyPanel {...props} />)
    const open = kind === 'scope' ? 'Edit example/project' : 'Recovery policy for example/project'
    const label = kind === 'scope' ? 'Max approval rounds' : 'Attempt revision cap'
    const save = kind === 'scope' ? 'Save repo' : 'Save recovery policy'
    await user.click(screen.getByRole('button', { name: open }))
    fireEvent.change(screen.getByLabelText(label), { target: { value: '0' } })
    fireEvent.blur(screen.getByLabelText(label))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(props.onUpdateScope).not.toHaveBeenCalled()
    expect(props.onUpdateContinuationPolicy).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: open }))
    fireEvent.change(screen.getByLabelText(label), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: save }))
    const tokenDialog = await screen.findByRole('dialog', { name: 'Director key' })
    // Normalized values are visible before authorization; the token dialog is separate.
    expect((screen.getByLabelText(label) as HTMLInputElement).value).toBe('1')
    await user.click(within(tokenDialog).getByRole('button', { name: 'Cancel' }))
    expect(props.onUpdateScope).not.toHaveBeenCalled()
    expect(props.onUpdateContinuationPolicy).not.toHaveBeenCalled()
  })

  it('does not PATCH when blur normalization returns to the original scope value', async () => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = panelProps({ scopes: [{ ...scope, max_approval_rounds: 1 }], workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Edit example/project' }))
    fireEvent.change(screen.getByLabelText('Max approval rounds'), { target: { value: '0' } })
    fireEvent.blur(screen.getByLabelText('Max approval rounds'))
    await user.click(screen.getByRole('button', { name: 'Save repo' }))
    expect(props.onUpdateScope).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
  })

  it('preserves live recovery-enable confirmation after numeric normalization', async () => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = panelProps({ preset: { ...preset, autonomy_enabled: true }, workItems: [] })
    render(<AutonomyPanel {...props} />)
    await user.click(screen.getByRole('button', { name: 'Recovery policy for example/project' }))
    fireEvent.change(screen.getByLabelText('Attempt revision cap'), { target: { value: '0' } })
    fireEvent.blur(screen.getByLabelText('Attempt revision cap'))
    await user.click(screen.getByText('Enable bounded attempt continuation'))
    await user.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    expect(await screen.findByText('Confirm the live recovery effect before saving this policy.')).toBeInTheDocument()
    expect(props.onUpdateContinuationPolicy).not.toHaveBeenCalled()
    await user.click(screen.getByText(/Autonomy is already on. I understand/))
    await user.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    await waitFor(() => expect(props.onUpdateContinuationPolicy).toHaveBeenCalledWith(2,
      expect.objectContaining({ continuation_enabled: true, max_continuation_revisions: 1 }), 'synthetic-token'))
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
