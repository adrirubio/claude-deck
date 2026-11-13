import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentMailPage } from '@/features/agent-mail/AgentMailPage'
import { clearOperatorToken, setOperatorToken } from '@/features/agent-teams/operatorAuth'
import { useOperatorTokenFlow } from '@/features/agent-teams/useOperatorTokenFlow'
import type { AgentMailInstallStatus, MailMemberResponse } from '@/types/agentMail'

// #763: while the Director key is needed and not given, the Team list says so.
// It never says "Loading participants..." for a read that has not started.

vi.mock('@/features/agent-mail/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/features/agent-mail/api')>(),
  fetchAgentMailAuthenticationStatus: vi.fn(),
  fetchAgentMailTeam: vi.fn(),
  fetchAgentMailMessages: vi.fn(),
  fetchAgentMailInstallStatus: vi.fn(),
}))
vi.mock('@/features/agent-teams/useOperatorTokenFlow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/agent-teams/useOperatorTokenFlow')>()
  return { ...actual, useOperatorTokenFlow: vi.fn(actual.useOperatorTokenFlow) }
})
import { fetchAgentMailAuthenticationStatus, fetchAgentMailInstallStatus, fetchAgentMailMessages, fetchAgentMailTeam } from '@/features/agent-mail/api'

const KEY_MESSAGE = 'Enter the Director key to see participants'
const LOADING_LABEL = 'Loading participants...'

const installStatus = {
  mail_capability_tokens_required: true,
  claude_code_hooks: [], claude_code_hooks_missing: [], claude_code_mcp_installed: false,
  codex_mcp_installed: false, codex_hooks: [], codex_hooks_missing: [],
  copilot_hooks: [], copilot_hooks_missing: [], opencode_plugin_events: [], opencode_plugin_events_missing: [],
} as AgentMailInstallStatus

const participant = {
  id: 1, identity_key: 'slot:1', repo_id: 'r', repo_path: '/work/repo', repo_name: 'repo',
  display_name: 'R1 Leader', participant_kind: 'team_slot', team_preset_name: 'synth-city-v4.1', role: 'implementer', status: 'connected',
  unread_count: 0, pending_count: 0, unseen_pending_count: 0, stale_pending_count: 0,
  can_nudge: false, sessions: [], agent_status: null,
} as MailMemberResponse

// A token flow whose key vanishes after it is given: the key is stored when refreshAll checks it,
// and gone when the protected reads start. Only the early returns can then clear loading.
const flowThatLosesTheKey = {
  operatorTokenStored: true,
  requestToken: async () => {
    clearOperatorToken()
    return 'key-that-just-vanished'
  },
  clearStoredToken: () => undefined,
  withOperatorToken: async <Result,>(action: (token: string) => Promise<Result>) => action('key-that-just-vanished'),
  tokenDialog: null,
}

beforeEach(async () => {
  sessionStorage.clear()
  vi.clearAllMocks()
  const actual = await vi.importActual<typeof import('@/features/agent-teams/useOperatorTokenFlow')>('@/features/agent-teams/useOperatorTokenFlow')
  vi.mocked(useOperatorTokenFlow).mockImplementation(actual.useOperatorTokenFlow)
  vi.mocked(fetchAgentMailAuthenticationStatus).mockResolvedValue({ director_key_configured: true })
  vi.mocked(fetchAgentMailTeam).mockResolvedValue({ members: [participant] })
  vi.mocked(fetchAgentMailMessages).mockResolvedValue([])
  vi.mocked(fetchAgentMailInstallStatus).mockResolvedValue(installStatus)
})
afterEach(() => {
  sessionStorage.clear()
})

function renderPage() {
  return render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
}

describe('Agent Mail Team list while the Director key is needed', () => {
  it('names the Director key while the dialog is open, not a loading label', async () => {
    renderPage()
    await screen.findByRole('dialog', { name: 'Director key' })
    expect(screen.getByText(KEY_MESSAGE)).toBeInTheDocument()
    expect(screen.queryByText(LOADING_LABEL)).not.toBeInTheDocument()
    expect(fetchAgentMailTeam).not.toHaveBeenCalled()
  })

  it('keeps the key message after the dialog is dismissed, with a button that reopens it', async () => {
    renderPage()
    const dialog = await screen.findByRole('dialog', { name: 'Director key' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(screen.getByText(KEY_MESSAGE)).toBeInTheDocument()
    expect(screen.queryByText(LOADING_LABEL)).not.toBeInTheDocument()
    expect(screen.queryByText('No participants match the current filters.')).not.toBeInTheDocument()
    expect(fetchAgentMailTeam).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Enter the Director key' }))
    expect(await screen.findByRole('dialog', { name: 'Director key' })).toBeInTheDocument()
  })

  it('loads the participants and drops the key message once a key is supplied', async () => {
    renderPage()
    await screen.findByRole('dialog', { name: 'Director key' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Enter the Director key' }))
    const dialog = await screen.findByRole('dialog', { name: 'Director key' })
    fireEvent.change(dialog.querySelector('input')!, { target: { value: 'fresh-director-key' } })
    fireEvent.click(screen.getByRole('button', { name: 'Use key' }))

    await waitFor(() => expect(fetchAgentMailTeam).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('R1 Leader')).toBeInTheDocument()
    expect(screen.queryByText(KEY_MESSAGE)).not.toBeInTheDocument()
    expect(screen.queryByText(LOADING_LABEL)).not.toBeInTheDocument()
  })

  it('shows no key message when the installation needs no Director key', async () => {
    vi.mocked(fetchAgentMailAuthenticationStatus).mockResolvedValue({ director_key_configured: false })
    renderPage()
    expect(await screen.findByText('R1 Leader')).toBeInTheDocument()
    expect(screen.queryByText(KEY_MESSAGE)).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('Agent Mail loading state after an early return', () => {
  it('leaves loading false when the protected reads return early', async () => {
    setOperatorToken('director-key-for-the-first-check')
    vi.mocked(useOperatorTokenFlow).mockImplementation(() => flowThatLosesTheKey)
    renderPage()
    // The key is gone when the reads start, so loadOperationalData and loadInstallData return early.
    expect(await screen.findByText('No participants match the current filters.')).toBeInTheDocument()
    expect(screen.queryByText(LOADING_LABEL)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeEnabled()
    expect(fetchAgentMailTeam).not.toHaveBeenCalled()
    expect(fetchAgentMailInstallStatus).not.toHaveBeenCalled()
  })
})
