import { MemoryRouter } from 'react-router-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiHttpError } from '@/lib/api'
import { AgentMailPage } from '@/features/agent-mail/AgentMailPage'
import { HarnessMailSetup } from '@/features/agent-mail/HarnessMailSetup'
import { useAgentMailSetup } from '@/features/agent-mail/useAgentMailSetup'
import { setOperatorToken } from '@/features/agent-teams/operatorAuth'
import type { AgentMailInstallStatus } from '@/types/agentMail'

vi.mock('@/features/agent-mail/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/features/agent-mail/api')>(),
  applyCodexAgentMailInstall: vi.fn(),
  fetchAgentMailAuthenticationStatus: vi.fn(),
  fetchAgentMailTeam: vi.fn(),
  fetchAgentMailMessages: vi.fn(),
  fetchAgentMailInstallStatus: vi.fn(),
}))
import { applyCodexAgentMailInstall, fetchAgentMailAuthenticationStatus, fetchAgentMailInstallStatus, fetchAgentMailMessages, fetchAgentMailTeam,
  fetchAgentMailThread, sendAgentMailMessage } from '@/features/agent-mail/api'

const status = (required = true) => ({
  mail_capability_tokens_required: required,
  claude_code_hooks: [], claude_code_hooks_missing: [], claude_code_mcp_installed: false,
  codex_mcp_installed: false, codex_hooks: [], codex_hooks_missing: [],
  copilot_hooks: [], copilot_hooks_missing: [], opencode_plugin_events: [], opencode_plugin_events_missing: [],
} as AgentMailInstallStatus)

beforeEach(() => {
  sessionStorage.clear()
  vi.clearAllMocks()
  vi.mocked(fetchAgentMailAuthenticationStatus).mockResolvedValue({ director_key_configured: true })
  vi.mocked(fetchAgentMailTeam).mockResolvedValue({ members: [] })
  vi.mocked(fetchAgentMailMessages).mockResolvedValue([])
  vi.mocked(fetchAgentMailInstallStatus).mockResolvedValue(status())
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

function SetupProbe() {
  const setup = useAgentMailSetup()
  return <button onClick={() => void setup.reload()}>{setup.loading ? 'Loading' : 'Reload'}</button>
}

describe('Agent Mail authentication', () => {
  it('requests the shared Director key before protected reads and stops after Cancel', async () => {
    const interval = vi.spyOn(window, 'setInterval')
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    const dialog = await screen.findByRole('dialog')
    expect(fetchAgentMailTeam).not.toHaveBeenCalled()
    expect(fetchAgentMailMessages).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    for (const [callback] of interval.mock.calls) {
      if (typeof callback === 'function') await act(async () => { callback() })
    }
    expect(fetchAgentMailTeam).not.toHaveBeenCalled()
    expect(fetchAgentMailMessages).not.toHaveBeenCalled()
  })

  it.each([401, 403])('stops protected polling after HTTP %s', async (code) => {
    setOperatorToken('test-director-key')
    vi.mocked(fetchAgentMailTeam).mockRejectedValue(new ApiHttpError('Refused', code))
    const interval = vi.spyOn(window, 'setInterval')
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    await waitFor(() => expect(fetchAgentMailTeam).toHaveBeenCalledTimes(1))
    await act(async () => { await Promise.resolve() })
    for (const [callback] of interval.mock.calls) {
      if (typeof callback === 'function') await act(async () => { callback(); callback() })
    }
    expect(fetchAgentMailTeam).toHaveBeenCalledTimes(1)
    expect(fetchAgentMailMessages).toHaveBeenCalledTimes(1)
    expect(fetchAgentMailAuthenticationStatus).toHaveBeenCalledTimes(code === 401 ? 2 : 1)
  })

  it('keeps polling after a temporary server failure', async () => {
    setOperatorToken('test-director-key')
    vi.mocked(fetchAgentMailTeam).mockRejectedValueOnce(new ApiHttpError('Temporary failure', 500))
    const interval = vi.spyOn(window, 'setInterval')
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    await waitFor(() => expect(fetchAgentMailTeam).toHaveBeenCalledTimes(1))
    await act(async () => { await Promise.resolve() })
    for (const [callback] of interval.mock.calls) {
      if (typeof callback === 'function') await act(async () => { callback() })
    }
    expect(fetchAgentMailTeam).toHaveBeenCalledTimes(2)
  })

  it('shows the explicit authentication opt-out', async () => {
    setOperatorToken('test-director-key')
    vi.mocked(fetchAgentMailInstallStatus).mockResolvedValue(status(false))
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    expect(await screen.findByText('Agent Mail uses legacy authentication.')).toBeInTheDocument()
  })

  it('keeps protected install reads idle until the shared key exists', async () => {
    render(<SetupProbe />)
    const reload = await screen.findByRole('button', { name: 'Reload' })
    expect(fetchAgentMailInstallStatus).not.toHaveBeenCalled()
    setOperatorToken('test-director-key')
    fireEvent.click(reload)
    await waitFor(() => expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1))
  })

  it('stops further protected install reads after refusal', async () => {
    setOperatorToken('test-director-key')
    vi.mocked(fetchAgentMailInstallStatus).mockRejectedValue(new ApiHttpError('Refused', 401))
    render(<SetupProbe />)
    await waitFor(() => expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1))
    const reload = await screen.findByRole('button', { name: 'Reload' })
    fireEvent.click(reload)
    await act(async () => { await Promise.resolve() })
    expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1)
  })

  it('sends the shared key for protected install information', async () => {
    setOperatorToken('test-director-key')
    const actual = await vi.importActual<typeof import('@/features/agent-mail/api')>('@/features/agent-mail/api')
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}')))
    vi.stubGlobal('fetch', fetch)
    await actual.fetchAgentMailInstallStatus()
    await actual.fetchAgentMailSnippets()
    expect(fetch.mock.calls).toHaveLength(2)
    for (const [, options] of fetch.mock.calls) {
      expect(options.headers['X-Deck-Operator-Token']).toBe('test-director-key')
    }
  })

  it('sends the shared key for Mail reads and actor provisioning', async () => {
    setOperatorToken('test-director-key')
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ root: {}, replies: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'test-actor-token' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: { id: 1 } })))
    vi.stubGlobal('fetch', fetch)
    await fetchAgentMailThread(1)
    await sendAgentMailMessage({ kind: 'message', recipient_member_id: 1, body_markdown: 'Test message' })
    expect(fetch.mock.calls[0][1].headers['X-Deck-Operator-Token']).toBe('test-director-key')
    expect(fetch.mock.calls[1][1].headers['X-Deck-Operator-Token']).toBe('test-director-key')
    expect(fetch.mock.calls[2][1].headers.Authorization).toBe('Bearer test-actor-token')
    expect(fetch.mock.calls[2][1].headers['X-Deck-Operator-Token']).toBeUndefined()
  })
})


function HarnessSetupProbe() {
  const setup = useAgentMailSetup()
  return <HarnessMailSetup providerId="codex-cli" harnessInstalled setup={setup} />
}

describe('Harness Mail key entry', () => {
  it('waits for deliberate key entry before its first protected read', async () => {
    render(<HarnessSetupProbe />)
    const enter = await screen.findByRole('button', { name: 'Enter the Director key' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchAgentMailInstallStatus).not.toHaveBeenCalled()
    fireEvent.click(enter)
    const dialog = await screen.findByRole('dialog', { name: 'Director key' })
    fireEvent.change(dialog.querySelector('input')!, { target: { value: 'fresh-director-key' } })
    fireEvent.click(screen.getByRole('button', { name: 'Use key' }))
    await waitFor(() => expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('button', { name: 'Set up' })).toBeInTheDocument()
  })

  it('keeps protected reads stopped after key entry is cancelled', async () => {
    render(<HarnessSetupProbe />)
    fireEvent.click(await screen.findByRole('button', { name: 'Enter the Director key' }))
    await screen.findByRole('dialog', { name: 'Director key' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(fetchAgentMailInstallStatus).not.toHaveBeenCalled()
  })

  it('recovers once with a changed key after a refusal', async () => {
    setOperatorToken('refused-director-key')
    vi.mocked(fetchAgentMailInstallStatus).mockRejectedValueOnce(new ApiHttpError('Refused', 401))
    render(<HarnessSetupProbe />)
    await waitFor(() => expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1))
    fireEvent.click(await screen.findByRole('button', { name: 'Enter the Director key' }))
    const dialog = await screen.findByRole('dialog', { name: 'Director key' })
    fireEvent.change(dialog.querySelector('input')!, { target: { value: 'recovered-director-key' } })
    fireEvent.click(screen.getByRole('button', { name: 'Use key' }))
    await waitFor(() => expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(2))
    expect(fetchAgentMailAuthenticationStatus).toHaveBeenCalledTimes(2)
    expect(await screen.findByRole('button', { name: 'Set up' })).toBeInTheDocument()
  })

  it('refuses another protected read when the entered key is unchanged', async () => {
    setOperatorToken('refused-director-key')
    vi.mocked(fetchAgentMailInstallStatus).mockRejectedValue(new ApiHttpError('Refused', 401))
    render(<HarnessSetupProbe />)
    await waitFor(() => expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1))
    fireEvent.click(await screen.findByRole('button', { name: 'Enter the Director key' }))
    const dialog = await screen.findByRole('dialog', { name: 'Director key' })
    fireEvent.change(dialog.querySelector('input')!, { target: { value: 'refused-director-key' } })
    fireEvent.click(screen.getByRole('button', { name: 'Use key' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1)
  })
})


describe('Mail without a configured Director key', () => {
  it('keeps Mail reads available and shows a non-blocking recommendation', async () => {
    vi.mocked(fetchAgentMailAuthenticationStatus).mockResolvedValue({ director_key_configured: false })
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    expect(await screen.findByText('Set a Director key')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(fetchAgentMailTeam).toHaveBeenCalledTimes(1))
    expect(fetchAgentMailMessages).toHaveBeenCalledTimes(1)
    expect(fetchAgentMailAuthenticationStatus).toHaveBeenCalledTimes(1)
  })

  it('keeps harness setup available and recommends a key without prompting', async () => {
    vi.mocked(fetchAgentMailAuthenticationStatus).mockResolvedValue({ director_key_configured: false })
    render(<HarnessSetupProbe />)
    expect(await screen.findByText('Set a Director key to protect Director actions.')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Set up' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1)
    expect(fetchAgentMailAuthenticationStatus).toHaveBeenCalledTimes(1)
  })
})


it('refreshes public key mode after 401 and keeps automatic reads stopped', async () => {
  setOperatorToken('refused-director-key')
  vi.mocked(fetchAgentMailAuthenticationStatus).mockResolvedValueOnce({ director_key_configured: true })
    .mockResolvedValue({ director_key_configured: false })
  vi.mocked(fetchAgentMailTeam).mockRejectedValueOnce(new ApiHttpError('Refused', 401))
  const interval = vi.spyOn(window, 'setInterval')
  render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
  expect(await screen.findByText('Set a Director key')).toBeInTheDocument()
  expect(fetchAgentMailAuthenticationStatus).toHaveBeenCalledTimes(2)
  for (const [callback] of interval.mock.calls) {
    if (typeof callback === 'function') await act(async () => { callback(); callback() })
  }
  expect(fetchAgentMailTeam).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})


it.each([401, 503])('keeps the install confirmation open after HTTP %s', async (code) => {
  setOperatorToken('test-director-key')
  vi.mocked(applyCodexAgentMailInstall).mockRejectedValue(new ApiHttpError('Install unavailable', code))
  render(<HarnessSetupProbe />)
  fireEvent.click(await screen.findByRole('button', { name: 'Set up' }))
  const dialog = await screen.findByRole('alertdialog')
  fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
  await waitFor(() => expect(applyCodexAgentMailInstall).toHaveBeenCalledTimes(1))
  await waitFor(() => {
    expect(dialog).toBeVisible()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeEnabled()
  })
  expect(fetchAgentMailInstallStatus).toHaveBeenCalledTimes(1)
})
