import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { AgentMailPage } from '@/features/agent-mail/AgentMailPage'
import { HarnessMailDetails, HarnessMailSetup } from '@/features/agent-mail/HarnessMailSetup'
import {
  connectedHarnessNames,
  isCompleteInstallStatus,
  joinNames,
  mailConfirm,
  mailSetupActions,
  mailSetupLine,
  mailSetupState,
  mailTechnicalLines,
} from '@/features/agent-mail/mailSetup'
import { setOperatorToken } from '@/features/agent-teams/operatorAuth'
import type { AgentMailSetup } from '@/features/agent-mail/useAgentMailSetup'
import type { AgentMailInstallStatus, AgentMailSnippets } from '@/types/agentMail'

vi.mock('@/features/agent-mail/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/agent-mail/api')>()
  return {
    ...actual,
    fetchAgentMailTeam: vi.fn(),
    fetchAgentMailMessages: vi.fn(),
    fetchAgentMailInstallStatus: vi.fn(),
  }
})
import { fetchAgentMailInstallStatus, fetchAgentMailMessages, fetchAgentMailTeam } from '@/features/agent-mail/api'

beforeEach(() => setOperatorToken('test-director-key'))

const FULL_HOOKS = ['SessionStart', 'UserPromptSubmit', 'SessionEnd', 'PostToolUse', 'PreToolUse']

function status(overrides: Partial<AgentMailInstallStatus> = {}): AgentMailInstallStatus {
  return {
    mail_capability_tokens_required: true,
    pi_cli_available: true,
    pi_mail_ready: true,
    claude_code_hooks: FULL_HOOKS,
    claude_code_hooks_missing: [],
    claude_code_prompt_block_installed: true,
    claude_code_mcp_installed: true,
    codex_cli_available: true,
    codex_mcp_installed: true,
    codex_hooks: ['SessionStart', 'UserPromptSubmit'],
    codex_hooks_missing: [],
    copilot_cli_available: false,
    copilot_mcp_installed: false,
    copilot_hooks: [],
    copilot_hooks_missing: [],
    opencode_cli_available: false,
    opencode_mcp_installed: false,
    opencode_plugin_events: [],
    opencode_plugin_events_missing: [],
    curl_available: true,
    shim_path: '/opt/deck/agent_mail_server.py',
    python_path: '/opt/deck/python',
    deck_url: 'http://localhost:8000',
    claude_settings_path: '/home/user/.claude/settings.json',
    claude_mcp_config_path: '/home/user/.claude.json',
    codex_hooks_path: '/home/user/.codex/hooks.json',
    ...overrides,
  }
}

function setup(next: AgentMailInstallStatus | null, overrides: Partial<AgentMailSetup> = {}): AgentMailSetup {
  return {
    status: next, snippets: null, loading: false, reload: vi.fn(), loadSnippets: vi.fn(), run: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as AgentMailSetup
}

describe('mailSetupState', () => {
  it('tells connected, partial and not set up apart for each harness', () => {
    expect(mailSetupState('claude-code', status())).toBe('connected')
    expect(mailSetupState('claude-code', status({ claude_code_hooks: ['SessionStart'], claude_code_hooks_missing: ['PreToolUse'] }))).toBe('partial')
    expect(mailSetupState('claude-code', status({ claude_code_hooks: [], claude_code_hooks_missing: FULL_HOOKS, claude_code_mcp_installed: false }))).toBe('not_set_up')
    expect(mailSetupState('codex-cli', status())).toBe('connected')
    expect(mailSetupState('codex-cli', status({ codex_hooks_missing: ['SessionStart'] }))).toBe('partial')
    expect(mailSetupState('copilot-cli', status())).toBe('not_set_up')
    expect(mailSetupState('copilot-cli', status({ copilot_mcp_installed: true, copilot_hooks_missing: ['x'] }))).toBe('partial')
    expect(mailSetupState('opencode-cli', status({ opencode_mcp_installed: true }))).toBe('connected')
    expect(mailSetupState('pi-cli', status())).toBe('automatic_ready')
    expect(mailSetupState('pi-cli', status({ pi_mail_ready: false }))).toBe('automatic_unavailable')
  })

  it('writes one line and offers Set up and Remove by state', () => {
    expect(mailSetupLine('connected')).toBe('✓ Connected · Restart sessions to apply changes')
    expect(mailSetupLine('not_set_up')).toBe('Not set up')
    expect(mailSetupActions('not_set_up')).toEqual({ setUp: true, remove: false })
    expect(mailSetupActions('connected')).toEqual({ setUp: false, remove: true })
    expect(mailSetupActions('partial')).toEqual({ setUp: true, remove: true })
    expect(mailSetupActions('automatic_ready')).toEqual({ setUp: false, remove: false })
  })

  it('names the connected harnesses for the Agent Mail page', () => {
    expect(connectedHarnessNames(status())).toEqual(['Claude Code', 'Codex', 'Pi'])
    expect(connectedHarnessNames(null)).toEqual([])
    expect(joinNames(['Claude Code', 'Codex', 'Pi'])).toBe('Claude Code, Codex and Pi')
    expect(joinNames(['Pi'])).toBe('Pi')
  })

  it('keeps the real hook total and the prompt block in the technical lines', () => {
    const lines = mailTechnicalLines('claude-code', status({
      claude_code_hooks: FULL_HOOKS.slice(0, 4), claude_code_hooks_missing: ['PreToolUse'], claude_code_prompt_block_installed: false,
    }))
    expect(lines).toContainEqual({ label: 'Hooks', value: '4/5 installed' })
    expect(lines).toContainEqual({ label: 'Question prompt block', value: 'not installed' })
    expect(lines).toContainEqual({ label: 'Hooks file', value: '/home/user/.claude/settings.json' })
  })

  it('keeps the confirm texts of the Install tab', () => {
    expect(mailConfirm('claude-code', 'setup', status())).toMatchObject({
      title: 'Install Agent Mail for Claude Code',
      description: 'A backup is attempted before these user-scope config changes are made.',
    })
    expect(mailConfirm('codex-cli', 'remove', status()).mutations[0]).toBe('Codex CLI: run `codex mcp remove claude-deck-mail`')
    expect(mailConfirm('opencode-cli', 'remove', status()).title).toBe('Remove Agent Mail from OpenCode CLI')
  })

  it('treats a status without its lists as unavailable', () => {
    expect(isCompleteInstallStatus(status())).toBe(true)
    expect(isCompleteInstallStatus({})).toBe(false)
    expect(isCompleteInstallStatus(null)).toBe(false)
  })
})

describe('HarnessMailSetup', () => {
  it('shows one plain line and Remove for a connected harness, with no path', () => {
    render(<HarnessMailSetup providerId="claude-code" harnessInstalled setup={setup(status())} />)
    const section = screen.getByRole('region', { name: 'Agent Mail' })
    expect(section.textContent).toContain('Agent Mail: ✓ Connected · Restart sessions to apply changes')
    expect(within(section).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: 'Set up' })).not.toBeInTheDocument()
    expect(section.textContent).not.toMatch(/\/home\/|\/opt\/|settings\.json|shim|hooks \d/i)
    expect(within(section).queryByRole('button', { name: /uninstall|install/i })).not.toBeInTheDocument()
  })

  it('offers Set up for a harness that is not set up, and both for a partial setup', () => {
    const { unmount } = render(<HarnessMailSetup providerId="copilot-cli" harnessInstalled setup={setup(status())} />)
    expect(screen.getByRole('button', { name: 'Set up' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    unmount()
    render(<HarnessMailSetup providerId="codex-cli" harnessInstalled setup={setup(status({ codex_hooks_missing: ['SessionStart'] }))} />)
    expect(screen.getByText(/Needs repair/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set up' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it('shows only "Install the harness first." for a harness that is not installed', () => {
    render(<HarnessMailSetup providerId="copilot-cli" harnessInstalled={false} setup={setup(status())} />)
    expect(screen.getByText(/Install the harness first\./)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows Pi as ready with no button', () => {
    render(<HarnessMailSetup providerId="pi-cli" harnessInstalled setup={setup(status())} />)
    expect(screen.getByText(/✓ Ready · Deck adds it when it launches Pi/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says when the state is loading or unavailable', () => {
    const { unmount } = render(<HarnessMailSetup providerId="codex-cli" harnessInstalled setup={setup(null, { loading: true })} />)
    expect(screen.getByText(/Checking the setup/)).toBeInTheDocument()
    unmount()
    render(<HarnessMailSetup providerId="codex-cli" harnessInstalled setup={setup(null)} />)
    expect(screen.getByText(/The setup state is unavailable/)).toBeInTheDocument()
  })

  it('confirms before it runs, with the Install tab texts, and runs the same action', async () => {
    const run = vi.fn().mockResolvedValue(undefined)
    render(<HarnessMailSetup providerId="copilot-cli" harnessInstalled setup={setup(status(), { run })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText('Install Agent Mail for GitHub Copilot CLI')).toBeInTheDocument()
    expect(run).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(run).toHaveBeenCalledWith('copilot-cli', 'setup'))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('keeps the dialog open when the action fails, and does not run on Cancel', async () => {
    const run = vi.fn().mockRejectedValue(new Error('refused'))
    render(<HarnessMailSetup providerId="claude-code" harnessInstalled setup={setup(status(), { run })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText('Remove Agent Mail from Claude Code')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(run).toHaveBeenCalledWith('claude-code', 'remove'))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(run).toHaveBeenCalledTimes(1)
  })
})

describe('HarnessMailDetails', () => {
  const snippets: AgentMailSnippets = {
    codex_config_toml: 'codex-config', codex_agents_md: 'codex-agents', copilot_mcp_command: 'copilot-cmd',
    copilot_hooks_json: 'copilot-hooks', opencode_config_json: 'opencode-config', opencode_plugin_js: 'opencode-plugin',
  }

  it('lists the paths and counts, and loads the snippets for a managed harness', () => {
    const loadSnippets = vi.fn()
    render(<HarnessMailDetails providerId="codex-cli" setup={setup(status(), { snippets, loadSnippets })} />)
    expect(loadSnippets).toHaveBeenCalled()
    expect(screen.getByText('/home/user/.codex/hooks.json')).toBeInTheDocument()
    expect(screen.getByDisplayValue('codex-config')).toBeInTheDocument()
    expect(screen.getByDisplayValue('codex-agents')).toBeInTheDocument()
  })

  it('loads no snippets for Claude Code or Pi', () => {
    const loadSnippets = vi.fn()
    const { unmount } = render(<HarnessMailDetails providerId="claude-code" setup={setup(status(), { loadSnippets })} />)
    unmount()
    render(<HarnessMailDetails providerId="pi-cli" setup={setup(status(), { loadSnippets })} />)
    expect(loadSnippets).not.toHaveBeenCalled()
  })

  it('shows nothing without a status', () => {
    const { container } = render(<HarnessMailDetails providerId="codex-cli" setup={setup(null)} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('Agent Mail page', () => {
  it('has no Install tab and links to Harnesses for the setup', async () => {
    vi.mocked(fetchAgentMailTeam).mockResolvedValue({ members: [] })
    vi.mocked(fetchAgentMailMessages).mockResolvedValue([])
    vi.mocked(fetchAgentMailInstallStatus).mockResolvedValue(status())
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    expect(await screen.findByRole('tab', { name: 'Team' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Conversations' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /install/i })).not.toBeInTheDocument()
    expect(await screen.findByText(/Mail is set up for Claude Code, Codex and Pi/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage in Harnesses' })).toHaveAttribute('href', '/harnesses')
  })

  it('shows the totals in one compact line with the same numbers', async () => {
    vi.mocked(fetchAgentMailTeam).mockResolvedValue({ members: [
      { id: 1, display_name: 'A', participant_kind: 'repo', status: 'connected', unread_count: 3, pending_count: 2,
        unseen_pending_count: 1, stale_pending_count: 1, can_nudge: false, sessions: [] },
      { id: 2, display_name: 'B', participant_kind: 'repo', status: 'observed', unread_count: 0, pending_count: 0,
        unseen_pending_count: 0, stale_pending_count: 0, can_nudge: false, sessions: [] },
    ] as never })
    vi.mocked(fetchAgentMailMessages).mockResolvedValue([])
    vi.mocked(fetchAgentMailInstallStatus).mockResolvedValue(status())
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    const totals = await screen.findByRole('group', { name: 'Agent Mail totals' })
    await waitFor(() => expect(totals.textContent).toContain('2 participants'))
    expect(totals.textContent).toContain('1 connected')
    expect(totals.textContent).toContain('1 observed only')
    expect(totals.textContent).toContain('3 unread')
    expect(totals.textContent).toContain('2 pending')
    expect(totals.textContent).toContain('1 unseen')
    expect(totals.textContent).toContain('1 stale')
  })

  it('points the setup notice at Harnesses when nothing is set up', async () => {
    vi.mocked(fetchAgentMailTeam).mockResolvedValue({ members: [] })
    vi.mocked(fetchAgentMailMessages).mockResolvedValue([])
    vi.mocked(fetchAgentMailInstallStatus).mockResolvedValue(status({
      claude_code_hooks: [], claude_code_hooks_missing: FULL_HOOKS, claude_code_mcp_installed: false,
      codex_mcp_installed: false, codex_hooks: [], pi_mail_ready: false,
    }))
    render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
    const link = await screen.findByRole('link', { name: /Set up in Harnesses/ })
    expect(link).toHaveAttribute('href', '/harnesses')
    expect(screen.queryByText(/Mail is set up for/)).not.toBeInTheDocument()
  })
})
