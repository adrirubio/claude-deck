import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { AgentMailInstallStatus, AgentMailSnippets } from '@/types/agentMail'
import {
  applyClaudeCodeAgentMailInstall,
  applyCodexAgentMailInstall,
  applyCopilotAgentMailInstall,
  applyOpenCodeAgentMailInstall,
  fetchAgentMailInstallStatus,
  fetchAgentMailSnippets,
  uninstallClaudeCodeAgentMail,
  uninstallCodexAgentMail,
  uninstallCopilotAgentMail,
  uninstallOpenCodeAgentMail,
} from './api'
import { isCompleteInstallStatus, type MailActionHarness, type MailActionMode } from './mailSetup'

// The calls and the toast texts moved unchanged from the Install tab.
const ACTIONS: Record<MailActionHarness, Record<MailActionMode, { run: () => Promise<AgentMailInstallStatus>; label: string }>> = {
  'claude-code': {
    setup: { run: applyClaudeCodeAgentMailInstall, label: 'Claude Code install updated' },
    remove: { run: uninstallClaudeCodeAgentMail, label: 'Claude Code install removed' },
  },
  'codex-cli': {
    setup: { run: applyCodexAgentMailInstall, label: 'Codex MCP install updated' },
    remove: { run: uninstallCodexAgentMail, label: 'Codex MCP install removed' },
  },
  'copilot-cli': {
    setup: { run: applyCopilotAgentMailInstall, label: 'GitHub Copilot CLI install updated' },
    remove: { run: uninstallCopilotAgentMail, label: 'GitHub Copilot CLI install removed' },
  },
  'opencode-cli': {
    setup: { run: applyOpenCodeAgentMailInstall, label: 'OpenCode CLI install updated' },
    remove: { run: uninstallOpenCodeAgentMail, label: 'OpenCode CLI install removed' },
  },
}

/** The Agent Mail install status, the fallback snippets on demand, and the Set up and Remove actions. */
export function useAgentMailSetup() {
  const [status, setStatus] = useState<AgentMailInstallStatus | null>(null)
  const [snippets, setSnippets] = useState<AgentMailSnippets | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const next = await fetchAgentMailInstallStatus()
      setStatus(isCompleteInstallStatus(next) ? next : null)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load install status')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) void load()
    })
    return () => {
      cancelled = true
    }
  }, [load])

  const loadSnippets = useCallback(async () => {
    if (snippets) return
    try {
      setSnippets(await fetchAgentMailSnippets())
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load the fallback snippets')
    }
  }, [snippets])

  const run = useCallback(async (harness: MailActionHarness, mode: MailActionMode) => {
    const action = ACTIONS[harness][mode]
    try {
      const next = await action.run()
      setStatus(isCompleteInstallStatus(next) ? next : null)
      await load()
      toast.success(action.label)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Install action failed')
      throw error
    }
  }, [load])

  return { status, snippets, loading, reload: load, loadSnippets, run }
}

export type AgentMailSetup = ReturnType<typeof useAgentMailSetup>
