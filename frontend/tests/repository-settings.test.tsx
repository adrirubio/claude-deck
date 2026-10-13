import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render as renderUi, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { RepositorySettings } from '../src/features/agent-teams/RepositorySettings'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { deleteTeamGithubScope, updateTeamGithubContinuationPolicy, updateTeamGithubScope } from '../src/features/agent-teams/api'
import type { TeamGithubScope } from '../src/types/agentTeams'

vi.mock('../src/features/agent-teams/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/features/agent-teams/api')>()
  return {
    ...actual,
    updateTeamGithubScope: vi.fn().mockResolvedValue({}),
    updateTeamGithubContinuationPolicy: vi.fn().mockResolvedValue({}),
    deleteTeamGithubScope: vi.fn().mockResolvedValue(undefined),
  }
})

// The settings link to the team, so they render inside a router.
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

function settingsProps(overrides: Partial<Parameters<typeof RepositorySettings>[0]> = {}) {
  return {
    scope,
    autonomyEnabled: false,
    refresh: vi.fn().mockResolvedValue(undefined),
    onRemoved: vi.fn(),
    ...overrides,
  }
}

const EDIT = 'Edit labels and routing for example/project'
const POLICY = 'Edit recovery policy for example/project'

beforeEach(() => {
  vi.mocked(updateTeamGithubScope).mockClear()
  vi.mocked(updateTeamGithubContinuationPolicy).mockClear()
  vi.mocked(deleteTeamGithubScope).mockClear()
})

describe('RepositorySettings', () => {
  it('shows the settings in plain words, with the technical details closed', () => {
    render(<RepositorySettings {...settingsProps()} />)
    expect(screen.getByRole('heading', { name: 'Labels and routing' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Merging and limits' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Recovery' })).toBeInTheDocument()
    expect(screen.getByText('You (human merge)')).toBeInTheDocument()
    expect(screen.getByText('Technical details').closest('details')).not.toHaveAttribute('open')
  })

  it('distinguishes a missing polling token from unresolved dispatch mode', () => {
    const view = render(<RepositorySettings {...settingsProps({ scope: { ...scope, github_auth_mode: 'unknown', github_poll_token_configured: false } })} />)
    expect(screen.getByText('Polling token not set')).toHaveAttribute('title', expect.stringContaining('backend/.env'))
    view.rerender(<RepositorySettings {...settingsProps({ scope: { ...scope, github_auth_mode: 'unknown', last_polled_at: '2026-09-29T12:00:00Z' } })} />)
    expect(screen.getByText('Dispatch auth: not selected')).toHaveAttribute('title', expect.stringContaining('successful poll'))
    expect(screen.queryByText('Polling token not set')).not.toBeInTheDocument()
  })

  it('defines recovery limits and phase and status badges', async () => {
    const user = userEvent.setup()
    render(<RepositorySettings {...settingsProps()} />)
    await user.click(screen.getByRole('button', { name: POLICY }))
    expect(screen.getByText(/A failed head is a pushed PR commit whose checks fail/)).toBeInTheDocument()
    expect(screen.getByText('Scope revisions allowed across one attempt.')).toBeInTheDocument()
    expect(screen.getByText('Saving requires the Director key.', { exact: false })).toBeInTheDocument()
  })

  it('sends only changed scope fields and an explicit null when clearing the build hint', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)

    await user.click(screen.getByRole('button', { name: EDIT }))
    fireEvent.change(screen.getByLabelText('Build command hint'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Max approval rounds'), { target: { value: '4' } })
    await user.click(screen.getByRole('button', { name: 'Save repo' }))

    await waitFor(() => expect(updateTeamGithubScope).toHaveBeenCalledWith(2, {
      build_command_hint: null,
      max_approval_rounds: 4,
    }, 'test-token'))
  })

  it('does not PATCH an unchanged scope', async () => {
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)

    await user.click(screen.getByRole('button', { name: EDIT }))
    await user.click(screen.getByRole('button', { name: 'Save repo' }))

    expect(updateTeamGithubScope).not.toHaveBeenCalled()
  })

  it('confirms watched-repo removal in the app instead of using a native dialog', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const props = settingsProps()
    const confirm = vi.spyOn(window, 'confirm')
    render(<RepositorySettings {...props} />)

    await user.click(screen.getByText('Technical details'))
    await user.click(screen.getByRole('button', { name: 'Remove example/project' }))
    expect(screen.getByText('Remove watched repo?')).toBeInTheDocument()
    expect(screen.getByText(/permanently deletes its saved work-item history/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(deleteTeamGithubScope).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove example/project' })).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Remove example/project' }))
    await user.click(screen.getByRole('button', { name: 'Remove repo' }))
    await waitFor(() => expect(deleteTeamGithubScope).toHaveBeenCalledWith(2, 'test-token'))
    await waitFor(() => expect(props.onRemoved).toHaveBeenCalled())
    expect(props.refresh).toHaveBeenCalled()
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

describe('RepositorySettings numeric limits', () => {
  it.each(scopeLimits)('keeps $label editable and normalizes only on blur before a changed-field save', async ({ key, label }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = settingsProps({ scope: { ...scope, merge_policy: 'auto' } })
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: EDIT }))
    const input = screen.getByLabelText(label) as HTMLInputElement
    expect(input).not.toHaveAttribute('max')
    await user.clear(input)
    expect(input.value).toBe('')
    await user.type(input, '12')
    expect(input.value).toBe('12')
    fireEvent.change(input, { target: { value: '1.2e1' } })
    expect(input.value).toBe('1.2e1')
    expect(updateTeamGithubScope).not.toHaveBeenCalled()
    await user.tab()
    expect(input.value).toBe('12')
    await user.click(screen.getByRole('button', { name: 'Save repo' }))
    await waitFor(() => expect(updateTeamGithubScope).toHaveBeenCalledWith(2, { [key]: 12 }, 'synthetic-token'))
  })

  it.each(scopeLimits)('clamps $label to server minimum on blur and on submit without blur', async ({ key, label, minimum }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = settingsProps({ scope: { ...scope, merge_policy: 'auto' } })
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: EDIT }))
    const input = screen.getByLabelText(label) as HTMLInputElement
    expect(input).toHaveAttribute('min', String(minimum))
    fireEvent.change(input, { target: { value: String(minimum - 1) } })
    expect(input.value).toBe(String(minimum - 1))
    fireEvent.blur(input)
    expect(input.value).toBe(String(minimum))
    expect(updateTeamGithubScope).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: String(minimum - 1) } })
    fireEvent.click(screen.getByRole('button', { name: 'Save repo' }))
    await waitFor(() => expect(updateTeamGithubScope).toHaveBeenCalledWith(2, { [key]: minimum }, 'synthetic-token'))
  })

  it.each(policyLimits)('keeps $label editable and applies only the declared blur bounds', async ({ key, label }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: POLICY }))
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
    expect(updateTeamGithubContinuationPolicy).not.toHaveBeenCalled()
    await user.tab()
    expect(input.value).toBe(String(expected))
    await user.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    await waitFor(() => expect(updateTeamGithubContinuationPolicy).toHaveBeenCalledWith(2, expect.objectContaining({ [key]: expected }), 'synthetic-token'))
  })

  it.each(policyLimits)('clamps $label on blur and on submit without blur', async ({ key, label, minimum }) => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: POLICY }))
    const input = screen.getByLabelText(label) as HTMLInputElement
    expect(input).toHaveAttribute('min', String(minimum))
    fireEvent.change(input, { target: { value: '0' } })
    expect(input.value).toBe('0')
    fireEvent.blur(input)
    expect(input.value).toBe('1')
    expect(updateTeamGithubContinuationPolicy).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    await waitFor(() => expect(updateTeamGithubContinuationPolicy).toHaveBeenCalledWith(2, expect.objectContaining({ [key]: minimum }), 'synthetic-token'))
  })

  it.each(['', '1.5', '1.0000000000000001', '1e-999', '1e309', '9007199254740993'])('blocks invalid scope value %j before requesting credentials or saving', async (value) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: EDIT }))
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
    expect(updateTeamGithubScope).not.toHaveBeenCalled()
    await user.clear(input)
    await user.type(input, '5')
    await user.tab()
    expect(input.value).toBe('5')
    expect(input).toHaveAttribute('aria-invalid', 'false')
  })

  it.each(['', '1.5', '1.0000000000000001', '1e-999', '1e309', '9007199254740993'])('blocks invalid policy value %j before requesting credentials or saving', async (value) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: POLICY }))
    const input = screen.getByLabelText('Attempt failed-head cap') as HTMLInputElement
    fireEvent.change(input, { target: { value } })
    const editingValue = input.value
    fireEvent.blur(input)
    expect(input.value).toBe(editingValue)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    expect(await screen.findAllByText(/whole number for max continuation failed heads/i)).not.toHaveLength(0)
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
    expect(updateTeamGithubContinuationPolicy).not.toHaveBeenCalled()
  })

  it('clamps per-revision down to the current attempt cap without raising the attempt cap', async () => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: POLICY }))
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
    await waitFor(() => expect(updateTeamGithubContinuationPolicy).toHaveBeenCalledWith(2,
      expect.objectContaining({ max_continuation_failed_heads: 1, max_failed_heads_per_revision: 1 }), 'synthetic-token'))
  })

  it.each(['', '1.0000000000000001', '1e-999'])('does not infer a relational maximum from invalid attempt cap %j', async (value) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: POLICY }))
    fireEvent.change(screen.getByLabelText('Attempt failed-head cap'), { target: { value } })
    const perRevision = screen.getByLabelText('Per-revision failed-head cap') as HTMLInputElement
    expect(perRevision).not.toHaveAttribute('max')
    fireEvent.change(perRevision, { target: { value: '12' } })
    fireEvent.blur(perRevision)
    expect(perRevision.value).toBe('12')
    fireEvent.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    expect(await screen.findByText(/whole number for max continuation failed heads/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
    expect(updateTeamGithubContinuationPolicy).not.toHaveBeenCalled()
  })

  it.each(['scope', 'policy'] as const)('cancels %s edits and pending protected authorization without a mutation', async (kind) => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = settingsProps()
    render(<RepositorySettings {...props} />)
    const open = kind === 'scope' ? EDIT : POLICY
    const label = kind === 'scope' ? 'Max approval rounds' : 'Attempt revision cap'
    const save = kind === 'scope' ? 'Save repo' : 'Save recovery policy'
    await user.click(screen.getByRole('button', { name: open }))
    fireEvent.change(screen.getByLabelText(label), { target: { value: '0' } })
    fireEvent.blur(screen.getByLabelText(label))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(updateTeamGithubScope).not.toHaveBeenCalled()
    expect(updateTeamGithubContinuationPolicy).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: open }))
    fireEvent.change(screen.getByLabelText(label), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: save }))
    const tokenDialog = await screen.findByRole('dialog', { name: 'Director key' })
    // Normalized values are visible before authorization; the token dialog is separate.
    expect((screen.getByLabelText(label) as HTMLInputElement).value).toBe('1')
    await user.click(within(tokenDialog).getByRole('button', { name: 'Cancel' }))
    expect(updateTeamGithubScope).not.toHaveBeenCalled()
    expect(updateTeamGithubContinuationPolicy).not.toHaveBeenCalled()
  })

  it('does not PATCH when blur normalization returns to the original scope value', async () => {
    clearOperatorToken()
    const user = userEvent.setup()
    const props = settingsProps({ scope: { ...scope, max_approval_rounds: 1 } })
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: EDIT }))
    fireEvent.change(screen.getByLabelText('Max approval rounds'), { target: { value: '0' } })
    fireEvent.blur(screen.getByLabelText('Max approval rounds'))
    await user.click(screen.getByRole('button', { name: 'Save repo' }))
    expect(updateTeamGithubScope).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Director key' })).not.toBeInTheDocument()
  })

  it('preserves live recovery-enable confirmation after numeric normalization', async () => {
    setOperatorToken('synthetic-token')
    const user = userEvent.setup()
    const props = settingsProps({ autonomyEnabled: true })
    render(<RepositorySettings {...props} />)
    await user.click(screen.getByRole('button', { name: POLICY }))
    fireEvent.change(screen.getByLabelText('Attempt revision cap'), { target: { value: '0' } })
    fireEvent.blur(screen.getByLabelText('Attempt revision cap'))
    await user.click(screen.getByText('Enable bounded attempt continuation'))
    await user.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    expect(await screen.findByText('Confirm the live recovery effect before saving this policy.')).toBeInTheDocument()
    expect(updateTeamGithubContinuationPolicy).not.toHaveBeenCalled()
    await user.click(screen.getByText(/Autonomy is already on. I understand/))
    await user.click(screen.getByRole('button', { name: 'Save recovery policy' }))
    await waitFor(() => expect(updateTeamGithubContinuationPolicy).toHaveBeenCalledWith(2,
      expect.objectContaining({ continuation_enabled: true, max_continuation_revisions: 1 }), 'synthetic-token'))
  })
})

