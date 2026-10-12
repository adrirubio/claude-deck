import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InstallTab } from '@/features/agent-mail/InstallTab'
import type { AgentMailInstallStatus } from '@/types/agentMail'

const handler = vi.fn().mockResolvedValue(undefined)

function status(overrides: Partial<AgentMailInstallStatus> = {}): AgentMailInstallStatus {
  return {
    claude_code_hooks: ['SessionStart', 'UserPromptSubmit', 'SessionEnd', 'PostToolUse', 'PreToolUse'],
    claude_code_hooks_missing: [],
    claude_code_prompt_block_installed: true,
    claude_code_mcp_installed: true,
    codex_cli_available: false,
    codex_mcp_installed: false,
    codex_hooks: [],
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
    shim_path: '/tmp/shim',
    python_path: '/tmp/python',
    deck_url: 'http://localhost:8000',
    ...overrides,
  }
}

function renderTab(next: AgentMailInstallStatus) {
  render(
    <InstallTab
      status={next}
      snippets={null}
      loading={false}
      onRefresh={handler}
      onApplyClaudeCode={handler}
      onUninstallClaudeCode={handler}
      onApplyCodex={handler}
      onUninstallCodex={handler}
      onApplyCopilot={handler}
      onUninstallCopilot={handler}
      onApplyOpenCode={handler}
      onUninstallOpenCode={handler}
    />,
  )
}

describe('InstallTab Claude Code status', () => {
  it('shows that the question prompt block is installed', () => {
    renderTab(status())

    expect(screen.getByText('question prompt block installed')).toBeInTheDocument()
  })

  it('shows that the question prompt block is not installed, with the real hook total', () => {
    renderTab(status({
      claude_code_hooks: ['SessionStart', 'UserPromptSubmit', 'SessionEnd', 'PostToolUse'],
      claude_code_hooks_missing: ['PreToolUse'],
      claude_code_prompt_block_installed: false,
    }))

    expect(screen.getByText('question prompt block not installed')).toBeInTheDocument()
    expect(screen.getByText('hooks 4/5 installed')).toBeInTheDocument()
  })
})
