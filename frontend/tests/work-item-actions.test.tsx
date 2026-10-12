import { StrictMode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { cleanup, render as renderUi, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { ApiHttpError } from '../src/lib/api'
import { WorkItemActions } from '../src/features/agent-teams/WorkItemActions'
import { WorkItemPanel } from '../src/features/agent-teams/WorkItemPanel'
import { useOperatorTokenFlow } from '../src/features/agent-teams/useOperatorTokenFlow'
import { useWorkItemOperations } from '../src/features/agent-teams/useWorkItemOperations'
import type { GithubScopeRevision, GithubWorkItem, TeamGithubScope } from '../src/types/agentTeams'
import { fixtureFetch, jsonResponse, settle } from './helpers/factory'

// The publication reader has its own request, expiry and error tests.
vi.mock('../src/features/agent-teams/WorkPublicationPanel', () => ({ WorkPublicationPanel: () => null }))
vi.mock('../src/features/agent-teams/useAgentActivity', () => ({ useAgentActivity: () => new Map() }))

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
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const render = (ui: React.ReactElement) => renderUi(ui, { wrapper: MemoryRouter })

const scope = {
  id: 2, preset_id: 1, repo_owner: 'example', repo_name: 'project', merge_policy: 'human', enabled: true,
  continuation_enabled: false,
} as unknown as TeamGithubScope

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

/** The same wiring the Work item page uses, with the handlers the Autonomy tab used to receive. */
function Harness({ item = workItem, onFetchScopeRevisions }: {
  item?: GithubWorkItem
  onFetchScopeRevisions: (itemId: number, token: string) => Promise<GithubScopeRevision[]>
}) {
  const flow = useOperatorTokenFlow('to change autonomy or recovery settings')
  const operations = useWorkItemOperations({
    presetId: 1,
    withOperatorToken: flow.withOperatorToken,
    onRefresh: async () => undefined,
    onFetchScopeRevisions,
    onCancelContinuationRequest: async () => undefined,
  })
  return (
    <>
      <WorkItemActions
        item={item}
        scope={scope}
        onFetchScopeRevisions={operations.fetchRevisions}
        onFetchWorkspaces={operations.fetchWorkspaces}
        operatorTokenStored={flow.operatorTokenStored}
        onRequestOperatorToken={() => flow.requestToken()}
        slots={[]}
        onOperate={operations.operateItem}
        hideSummary
      />
      {flow.tokenDialog}
    </>
  )
}

describe('WorkItemActions (moved from the Autonomy tab dialog)', () => {
  it('does not claim an escalated active revision is still running', async () => {
    setOperatorToken('test-token')
    const fetchRevisions = vi.fn().mockResolvedValue([revision])
    const item = { ...workItem, active_scope_status: 'active', escalation_reason: 'dispatch_label_removed' }
    const view = render(<Harness item={item} onFetchScopeRevisions={fetchRevisions} />)
    expect(screen.getByText('This issue is escalated. Review the reason above before continuing recovery.')).toBeInTheDocument()
    expect(screen.queryByText(/No operator action is needed/)).not.toBeInTheDocument()
    view.rerender(<Harness item={{ ...workItem, dispatch_status: 'dispatched', active_scope_status: 'active', continuation_block_code: 'continuation_disabled' }} onFetchScopeRevisions={fetchRevisions} />)
    expect(screen.getByText('Recovery policy is off for this repo. Existing work may still need attention.')).toBeInTheDocument()
    expect(screen.queryByText(/No operator action is needed/)).not.toBeInTheDocument()
  })

  it('asks for a token on the first history load, then shows the history', async () => {
    clearOperatorToken()
    const user = userEvent.setup()
    const fetchRevisions = vi.fn().mockResolvedValue([revision])
    render(<Harness onFetchScopeRevisions={fetchRevisions} />)

    expect(await screen.findByText('Enter the Director key to load recovery history.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry loading history' }))
    await user.type(screen.getByPlaceholderText('Enter secret value'), 'test-token')
    await user.click(screen.getByRole('button', { name: 'Use key' }))

    expect(await screen.findByText('Hosted-only diagnostic')).toBeInTheDocument()
    expect(fetchRevisions).toHaveBeenCalledWith(23, 'test-token')
  })

  it('shows a rejected-token prompt and retries with the replacement token', async () => {
    setOperatorToken('old-token')
    const user = userEvent.setup()
    const fetchRevisions = vi.fn()
      .mockRejectedValueOnce(new ApiHttpError('The operator token was rejected.', 401))
      .mockResolvedValue([revision])
    render(<Harness onFetchScopeRevisions={fetchRevisions} />)

    expect(await screen.findByText('The Director key was rejected. Enter a valid key to retry.')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('Enter secret value'), 'new-token')
    await user.click(screen.getByRole('button', { name: 'Use key' }))

    expect(await screen.findByText('Hosted-only diagnostic')).toBeInTheDocument()
    expect(fetchRevisions).toHaveBeenLastCalledWith(23, 'new-token')
  })

  it('keeps a delayed history request alive across StrictMode and parent polling', async () => {
    setOperatorToken('test-token')
    let resolveHistory: (rows: GithubScopeRevision[]) => void = () => {}
    const fetchRevisions = vi.fn(() => new Promise<GithubScopeRevision[]>((resolve) => { resolveHistory = resolve }))
    const view = render(<StrictMode><Harness onFetchScopeRevisions={fetchRevisions} /></StrictMode>)

    await waitFor(() => expect(fetchRevisions).toHaveBeenCalled())
    view.rerender(<StrictMode><Harness item={{ ...workItem }} onFetchScopeRevisions={fetchRevisions} /></StrictMode>)
    resolveHistory([revision])

    expect(await screen.findByText('Hosted-only diagnostic')).toBeInTheDocument()
    expect(screen.queryByText('Loading recovery history…')).not.toBeInTheDocument()
  })

  it('reports a prepared attempt as queued after the backend returns pending', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(
      JSON.stringify({ ...workItem, dispatch_status: 'pending' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    render(<Harness item={{ ...workItem, escalation_reason: 'prepared_owner_unavailable' }} onFetchScopeRevisions={vi.fn().mockResolvedValue([revision])} />)

    await user.click(screen.getByRole('button', { name: 'Resume prepared attempt' }))
    await user.click(screen.getByRole('button', { name: 'Confirm action' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Prepared attempt queued for resumption.')
    fetchMock.mockRestore()
  })
})

describe('WorkItemPanel on the Work item page', () => {
  const requestsFor = (item: GithubWorkItem, respond: (path: string, options?: RequestInit) => Response | undefined = () => undefined) => {
    const calls: { path: string; method: string; headers: Headers; body: string | null }[] = []
    fixtureFetch((path, _query, options) => {
      calls.push({
        path,
        method: options?.method ?? 'GET',
        headers: new Headers(options?.headers),
        body: typeof options?.body === 'string' ? options.body : null,
      })
      const custom = respond(path, options)
      if (custom) return custom
      if (path === 'agent-teams/presets/1/github-work-items') return jsonResponse({ items: [item], total: 1 })
      if (path === 'agent-teams/presets/1/github-scopes') return jsonResponse({ scopes: [scope] })
      if (path === 'agent-teams/presets') return jsonResponse({ presets: [{ id: 1, name: 'Team', slots: [] }] })
      if (path.endsWith('/scope-revisions')) return jsonResponse([])
      return jsonResponse({}, 404)
    })
    return calls
  }

  it('sends the Director key and the same requests the Autonomy tab sent to resume a prepared attempt', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const item = { ...workItem, escalation_reason: 'prepared_owner_unavailable' }
    const calls = requestsFor(item, (path) =>
      path === 'agent-teams/presets/1/work-items/23/resume-attempt' ? jsonResponse({ ...item, dispatch_status: 'pending' }) : undefined)
    render(<WorkItemPanel presetId={1} workItemId={23} />)
    await user.click(await screen.findByRole('button', { name: 'Resume prepared attempt' }))
    await user.click(screen.getByRole('button', { name: 'Confirm action' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Prepared attempt queued for resumption.')
    const resume = calls.find((call) => call.path.endsWith('/resume-attempt'))!
    expect(resume.method).toBe('POST')
    expect(resume.path).toBe('agent-teams/presets/1/work-items/23/resume-attempt')
    expect(resume.headers.get('X-Deck-Operator-Token')).toBe('test-token')
  })

  it('sends the same abandon request, with a reason and the key', async () => {
    setOperatorToken('test-token')
    const user = userEvent.setup()
    const item = { ...workItem, dispatch_status: 'dispatched' as const, escalation_reason: undefined }
    const calls = requestsFor(item, (path) =>
      path === 'agent-teams/github-work-items/23/abandon' ? jsonResponse({ ...item, dispatch_status: 'escalated' }) : undefined)
    render(<WorkItemPanel presetId={1} workItemId={23} />)
    await user.click(await screen.findByRole('button', { name: 'Abandon work item' }))
    await user.type(screen.getByLabelText('Reason for audit'), 'Stopped by test')
    await user.click(screen.getByRole('button', { name: 'Confirm action' }))
    await waitFor(() => expect(calls.some((call) => call.path === 'agent-teams/github-work-items/23/abandon')).toBe(true))
    const abandon = calls.find((call) => call.path === 'agent-teams/github-work-items/23/abandon')!
    expect(abandon.method).toBe('POST')
    expect(abandon.headers.get('X-Deck-Operator-Token')).toBe('test-token')
    expect(JSON.parse(abandon.body ?? '{}')).toEqual({ reason: 'Stopped by test' })
  })

  it('loads recovery history only with the key, and prompts for it', async () => {
    clearOperatorToken()
    const calls = requestsFor(workItem)
    render(<WorkItemPanel presetId={1} workItemId={23} />)
    await settle()
    expect(await screen.findByText('Enter the Director key to load recovery history.')).toBeInTheDocument()
    expect(calls.some((call) => call.path.endsWith('/scope-revisions'))).toBe(false)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
