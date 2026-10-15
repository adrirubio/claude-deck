import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { HARNESS_NAMES, connectedHarnessNames, hasMailAction, mailConfirm, mailSetupState, mailTechnicalLines } from '@/features/agent-mail/mailSetup'
import { ProviderLaunchOptionsFields } from '@/features/providers/ProviderLaunchOptionsFields'
import type { AgentMailInstallStatus } from '@/types/agentMail'
import type { ProviderLaunchOptionsResponse } from '@/types/providers'

function status(overrides: Partial<AgentMailInstallStatus>): AgentMailInstallStatus {
  return {
    claude_code_hooks: [], claude_code_hooks_missing: ['SessionStart'], claude_code_mcp_installed: false,
    codex_hooks: [], codex_hooks_missing: ['SessionStart'], codex_mcp_installed: false,
    copilot_hooks: [], copilot_hooks_missing: ['sessionStart'], copilot_mcp_installed: false,
    opencode_plugin_events: [], opencode_plugin_events_missing: ['session.created'], opencode_mcp_installed: false,
    pi_mail_ready: false,
    muse_cli_available: true, muse_mcp_installed: false, muse_hooks: [], muse_hooks_missing: ['SessionStart', 'UserPromptSubmit'],
    ...overrides,
  } as AgentMailInstallStatus
}

describe('Muse Code harness', () => {
  it('has a managed Agent Mail setup with its own name', () => {
    expect(HARNESS_NAMES['muse-cli']).toBe('Muse Code')
    expect(hasMailAction('muse-cli')).toBe(true)
  })

  it('reads its setup state from the Muse install fields', () => {
    expect(mailSetupState('muse-cli', status({}))).toBe('not_set_up')
    expect(mailSetupState('muse-cli', status({ muse_mcp_installed: true }))).toBe('partial')
    expect(mailSetupState('muse-cli', status({ muse_hooks: ['SessionStart'], muse_hooks_missing: ['UserPromptSubmit'] }))).toBe('partial')
    const connected = status({ muse_mcp_installed: true, muse_hooks: ['SessionStart', 'UserPromptSubmit'], muse_hooks_missing: [] })
    expect(mailSetupState('muse-cli', connected)).toBe('connected')
    expect(connectedHarnessNames(connected)).toContain('Muse Code')
  })

  it('confirms its own setup and removal, naming the Muse settings file', () => {
    const value = status({ muse_settings_path: '/home/u/.config/muse/settings.json' } as Partial<AgentMailInstallStatus>)
    const setup = mailConfirm('muse-cli', 'setup', value)
    expect(setup.title).toBe('Install Agent Mail for Muse Code')
    expect(JSON.stringify(setup)).toContain('/home/u/.config/muse/settings.json')
    expect(mailConfirm('muse-cli', 'remove', value).title).toBe('Remove Agent Mail from Muse Code')
    expect(JSON.stringify(mailTechnicalLines('muse-cli', value))).toContain('/home/u/.config/muse/settings.json')
  })

  it('offers a model field and reasoning effort, but no platform', () => {
    const descriptor = {
      provider: 'muse-cli', bedrock_supported: false, reasoning_effort_supported: true,
      reasoning_effort_options: [{ value: 'high', label: 'high' }, { value: 'ultra', label: 'ultra' }],
      model_options: [{ value: 'muse-wonder-1.0', label: 'Muse Wonder', source: 'example' }],
    } as unknown as ProviderLaunchOptionsResponse
    render(<ProviderLaunchOptionsFields provider="muse-cli" value={{}} onChange={() => {}} descriptor={descriptor} />)
    expect(screen.getByLabelText('Model')).toHaveAttribute('placeholder', 'muse-wonder-1.0')
    expect(screen.getByText('Reasoning effort')).toBeInTheDocument()
    expect(screen.queryByText('Platform')).toBeNull()
    expect(screen.getByText(/Muse subscription/)).toBeInTheDocument()
  })
})
