import type { AgentMailInstallStatus } from '@/types/agentMail'
import type { AgentProviderId } from '@/types/providers'

// #531: Agent Mail setup of each harness, read from the install status. This
// module only reads the status. The Set up and Remove actions keep their API
// calls and their confirm texts; they moved here from the Install tab.

/** True when the install status has every list that the setup views read. */
export function isCompleteInstallStatus(value: unknown): value is AgentMailInstallStatus {
  if (!value || typeof value !== 'object') return false
  const status = value as Record<string, unknown>
  return ['claude_code_hooks', 'claude_code_hooks_missing', 'codex_hooks', 'codex_hooks_missing',
    'copilot_hooks', 'copilot_hooks_missing', 'opencode_plugin_events', 'opencode_plugin_events_missing']
    .every((name) => Array.isArray(status[name]))
}

export type MailSetupState = 'connected' | 'partial' | 'not_set_up' | 'automatic_ready' | 'automatic_unavailable'

/** The four harnesses with a managed Set up and Remove action. */
export type MailActionHarness = 'claude-code' | 'codex-cli' | 'copilot-cli' | 'opencode-cli'

export const MAIL_ACTION_HARNESSES: MailActionHarness[] = ['claude-code', 'codex-cli', 'copilot-cli', 'opencode-cli']

export const HARNESS_NAMES: Record<AgentProviderId, string> = {
  'claude-code': 'Claude Code',
  'codex-cli': 'Codex',
  'copilot-cli': 'GitHub Copilot CLI',
  'opencode-cli': 'OpenCode CLI',
  'pi-cli': 'Pi',
}

export function hasMailAction(providerId: AgentProviderId): providerId is MailActionHarness {
  return (MAIL_ACTION_HARNESSES as string[]).includes(providerId)
}

/** The state of one harness. Whole = every part installed; partial = some parts. */
export function mailSetupState(providerId: AgentProviderId, status: AgentMailInstallStatus): MailSetupState {
  switch (providerId) {
    case 'claude-code': {
      const whole = status.claude_code_hooks_missing.length === 0 && status.claude_code_mcp_installed
      const some = status.claude_code_mcp_installed || status.claude_code_hooks.length > 0
      return whole ? 'connected' : some ? 'partial' : 'not_set_up'
    }
    case 'codex-cli': {
      const whole = status.codex_mcp_installed && status.codex_hooks_missing.length === 0
      const some = status.codex_mcp_installed || status.codex_hooks.length > 0
      return whole ? 'connected' : some ? 'partial' : 'not_set_up'
    }
    case 'copilot-cli': {
      const whole = status.copilot_mcp_installed && status.copilot_hooks_missing.length === 0
      const some = status.copilot_mcp_installed || status.copilot_hooks.length > 0
      return whole ? 'connected' : some ? 'partial' : 'not_set_up'
    }
    case 'opencode-cli': {
      const whole = status.opencode_mcp_installed && status.opencode_plugin_events_missing.length === 0
      const some = status.opencode_mcp_installed || status.opencode_plugin_events.length > 0
      return whole ? 'connected' : some ? 'partial' : 'not_set_up'
    }
    default:
      return status.pi_mail_ready ? 'automatic_ready' : 'automatic_unavailable'
  }
}

/** The one line of the harness page. It names no path and no code. */
export function mailSetupLine(state: MailSetupState): string {
  switch (state) {
    case 'connected': return '✓ Connected · Restart sessions to apply changes'
    case 'partial': return 'Needs repair · Some parts are missing'
    case 'automatic_ready': return '✓ Ready · Deck adds it when it launches Pi'
    case 'automatic_unavailable': return 'Not ready · See Technical details'
    default: return 'Not set up'
  }
}

/** Set up is offered unless everything is installed. Remove is offered when any part is installed. */
export function mailSetupActions(state: MailSetupState): { setUp: boolean; remove: boolean } {
  return { setUp: state === 'not_set_up' || state === 'partial', remove: state === 'connected' || state === 'partial' }
}

/** The harnesses with a connected setup, for the line on the Agent Mail page. */
export function connectedHarnessNames(status: AgentMailInstallStatus | null): string[] {
  if (!status) return []
  const ids: AgentProviderId[] = ['claude-code', 'codex-cli', 'copilot-cli', 'opencode-cli', 'pi-cli']
  return ids
    .filter((id) => {
      const state = mailSetupState(id, status)
      return state === 'connected' || state === 'automatic_ready'
    })
    .map((id) => HARNESS_NAMES[id])
}

/** "Claude Code, Codex and Pi". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

export interface TechnicalLine {
  label: string
  value: string
}

/** Everything the harness page keeps out of sight: paths, counts and the shim. */
export function mailTechnicalLines(providerId: AgentProviderId, status: AgentMailInstallStatus): TechnicalLine[] {
  const common: TechnicalLine[] = [
    { label: 'MCP server command', value: `${status.python_path} ${status.shim_path}` },
    { label: 'Deck URL', value: status.deck_url },
    { label: 'curl', value: status.curl_available ? 'available' : 'missing' },
  ]
  switch (providerId) {
    case 'claude-code': {
      const total = status.claude_code_hooks.length + status.claude_code_hooks_missing.length
      return [
        { label: 'Hooks file', value: status.claude_settings_path || 'unavailable' },
        { label: 'MCP file', value: status.claude_mcp_config_path || 'unavailable' },
        { label: 'Hooks', value: status.claude_code_hooks_missing.length === 0 ? 'installed' : `${status.claude_code_hooks.length}/${total} installed` },
        { label: 'MCP', value: status.claude_code_mcp_installed ? 'installed' : 'not installed' },
        { label: 'Question prompt block', value: status.claude_code_prompt_block_installed ? 'installed' : 'not installed' },
        ...common,
      ]
    }
    case 'codex-cli': {
      const total = status.codex_hooks.length + status.codex_hooks_missing.length
      return [
        { label: 'Codex CLI', value: status.codex_cli_available ? 'available' : 'missing' },
        { label: 'Hooks file', value: status.codex_hooks_path || 'unavailable' },
        { label: 'Hooks', value: status.codex_hooks_missing.length === 0 ? 'installed' : `${status.codex_hooks.length}/${total} installed` },
        { label: 'MCP', value: status.codex_mcp_installed ? 'installed' : 'not installed' },
        ...common,
      ]
    }
    case 'copilot-cli': {
      const total = status.copilot_hooks.length + status.copilot_hooks_missing.length
      return [
        { label: 'Copilot CLI', value: status.copilot_cli_available ? 'available' : 'missing' },
        { label: 'Hooks file', value: status.copilot_hooks_path || 'unavailable' },
        { label: 'Hooks', value: status.copilot_hooks_missing.length === 0 ? 'installed' : `${status.copilot_hooks.length}/${total} installed` },
        { label: 'MCP', value: status.copilot_mcp_installed ? 'installed' : 'not installed' },
        ...common,
      ]
    }
    case 'opencode-cli': {
      const total = status.opencode_plugin_events.length + status.opencode_plugin_events_missing.length
      return [
        { label: 'OpenCode CLI', value: status.opencode_cli_available ? 'available' : 'missing' },
        { label: 'Config file', value: status.opencode_config_path || 'unavailable' },
        { label: 'Plugin file', value: status.opencode_plugin_path || 'unavailable' },
        { label: 'Plugin events', value: status.opencode_plugin_events_missing.length === 0 ? 'installed' : `${status.opencode_plugin_events.length}/${total} installed` },
        { label: 'MCP', value: status.opencode_mcp_installed ? 'installed' : 'not installed' },
        ...common,
      ]
    }
    default:
      return [
        { label: 'Pi CLI', value: status.pi_cli_available ? 'available' : 'missing' },
        { label: 'Extension', value: status.pi_mail_ready ? 'ready' : 'unavailable' },
        ...(status.pi_mail_reason ? [{ label: 'Reason', value: status.pi_mail_reason }] : []),
        { label: 'Scope', value: 'Explicit Deck launches only. No global Pi configuration is changed.' },
      ]
  }
}

export type MailActionMode = 'setup' | 'remove'

export interface MailConfirm {
  title: string
  description: string
  mutations: string[]
}

/** The confirm dialog texts, moved unchanged from the Install tab. */
export function mailConfirm(harness: MailActionHarness, mode: MailActionMode, status: AgentMailInstallStatus): MailConfirm {
  const server = 'claude-deck-mail'
  const command = `MCP server command: ${status.python_path} ${status.shim_path}`
  const key = `${harness}:${mode}`
  switch (key) {
    case 'claude-code:setup':
      return {
        title: 'Install Agent Mail for Claude Code',
        description: 'A backup is attempted before these user-scope config changes are made.',
        mutations: [
          `${status.claude_settings_path || '~/.claude/settings.json'}: add four Agent Mail curl command hooks`,
          `${status.claude_mcp_config_path || '~/.claude.json'}: add user MCP server ${server}`,
        ],
      }
    case 'claude-code:remove':
      return {
        title: 'Remove Agent Mail from Claude Code',
        description: 'A backup is attempted before the managed hooks and MCP server are removed.',
        mutations: [
          `${status.claude_settings_path || '~/.claude/settings.json'}: remove Agent Mail hook commands`,
          `${status.claude_mcp_config_path || '~/.claude.json'}: remove MCP server ${server}`,
        ],
      }
    case 'codex-cli:setup':
      return {
        title: 'Install Agent Mail for Codex',
        description: 'A backup is attempted before Claude Deck installs the Codex MCP server and lifecycle hooks.',
        mutations: [
          'Codex CLI: run `codex mcp add --env CLAUDE_DECK_URL=... --env CLAUDE_DECK_PROVIDER=codex-cli claude-deck-mail -- ...`',
          `${status.codex_hooks_path || '~/.codex/hooks.json'}: add Agent Mail SessionStart and UserPromptSubmit hooks`,
          command,
        ],
      }
    case 'codex-cli:remove':
      return {
        title: 'Remove Agent Mail from Codex',
        description: 'A backup is attempted before Claude Deck removes the managed MCP server and hooks.',
        mutations: [
          'Codex CLI: run `codex mcp remove claude-deck-mail`',
          `${status.codex_hooks_path || '~/.codex/hooks.json'}: remove Agent Mail hook commands`,
        ],
      }
    case 'copilot-cli:setup':
      return {
        title: 'Install Agent Mail for GitHub Copilot CLI',
        description: 'A backup is attempted before Claude Deck installs the Copilot MCP server and lifecycle hooks.',
        mutations: [
          'Copilot CLI: run `copilot mcp add --env CLAUDE_DECK_URL=... --env CLAUDE_DECK_PROVIDER=copilot-cli claude-deck-mail -- ...`',
          `${status.copilot_hooks_path || '~/.copilot/hooks/claude-deck-mail.json'}: write Agent Mail hook definitions`,
          command,
        ],
      }
    case 'copilot-cli:remove':
      return {
        title: 'Remove Agent Mail from GitHub Copilot CLI',
        description: 'A backup is attempted before Claude Deck removes the managed MCP server and hooks.',
        mutations: [
          'Copilot CLI: run `copilot mcp remove claude-deck-mail`',
          `${status.copilot_hooks_path || '~/.copilot/hooks/claude-deck-mail.json'}: remove managed Agent Mail hook file`,
        ],
      }
    case 'opencode-cli:setup':
      return {
        title: 'Install Agent Mail for OpenCode CLI',
        description: 'A backup is attempted before Claude Deck writes the managed OpenCode MCP entry and lifecycle plugin.',
        mutations: [
          `${status.opencode_config_path || '~/.config/opencode/opencode.json'}: add MCP server ${server}`,
          `${status.opencode_plugin_path || '~/.config/opencode/plugins/claude-deck-agent-mail.js'}: write Agent Mail lifecycle plugin`,
          command,
        ],
      }
    default:
      return {
        title: 'Remove Agent Mail from OpenCode CLI',
        description: 'A backup is attempted before Claude Deck removes the managed MCP entry and plugin file.',
        mutations: [
          `${status.opencode_config_path || '~/.config/opencode/opencode.json'}: remove MCP server ${server}`,
          `${status.opencode_plugin_path || '~/.config/opencode/plugins/claude-deck-agent-mail.js'}: remove managed Agent Mail plugin`,
        ],
      }
  }
}
