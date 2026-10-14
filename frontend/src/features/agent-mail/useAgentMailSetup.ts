import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ApiHttpError } from '@/lib/api'
import { clearOperatorToken, getOperatorToken } from '@/features/agent-teams/operatorAuth'
import { useOperatorTokenFlow } from '@/features/agent-teams/useOperatorTokenFlow'
import type { AgentMailInstallStatus, AgentMailSnippets } from '@/types/agentMail'
import {
  applyClaudeCodeAgentMailInstall,
  applyCodexAgentMailInstall,
  applyCopilotAgentMailInstall,
  applyOpenCodeAgentMailInstall,
  applyMuseAgentMailInstall,
  fetchAgentMailAuthenticationStatus,
  fetchAgentMailInstallStatus,
  fetchAgentMailSnippets,
  uninstallClaudeCodeAgentMail,
  uninstallCodexAgentMail,
  uninstallCopilotAgentMail,
  uninstallOpenCodeAgentMail,
  uninstallMuseAgentMail,
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
  'muse-cli': {
    setup: { run: applyMuseAgentMailInstall, label: 'Muse Code install updated' },
    remove: { run: uninstallMuseAgentMail, label: 'Muse Code install removed' },
  },
}

/** Public key discovery runs once before reads and refreshes after a 401. */
export function useAgentMailAuthenticationStatus() {
  const knownMode = useRef<boolean | null>(null)
  const pendingMode = useRef<Promise<boolean> | null>(null)
  const [directorKeyConfigured, setDirectorKeyConfigured] = useState<boolean | null>(null)
  const requiresDirectorKey = useCallback(() => knownMode.current !== false, [])
  const readAuthenticationStatus = useCallback(async (refresh = false): Promise<boolean> => {
    if (!refresh && knownMode.current !== null) return knownMode.current
    if (pendingMode.current) return pendingMode.current
    const pending = fetchAgentMailAuthenticationStatus().then((status) => {
      if (typeof status.director_key_configured !== 'boolean') throw new Error('Mail authentication status is unavailable.')
      knownMode.current = status.director_key_configured
      setDirectorKeyConfigured(status.director_key_configured)
      return status.director_key_configured
    }).finally(() => { pendingMode.current = null })
    pendingMode.current = pending
    return pending
  }, [])
  return { directorKeyConfigured, requiresDirectorKey, readAuthenticationStatus }
}

/** The Agent Mail install status, the fallback snippets on demand, and the Set up and Remove actions. */
export function useAgentMailSetup() {
  const { directorKeyConfigured, requiresDirectorKey, readAuthenticationStatus } = useAgentMailAuthenticationStatus()
  const { requestToken, tokenDialog } = useOperatorTokenFlow('Agent Mail requires the Director key.')
  const protectedReadsBlocked = useRef(false)
  const refusedKey = useRef<string | null>(null)
  const loadPromise = useRef<Promise<void> | null>(null)
  const [needsKey, setNeedsKey] = useState(() => !getOperatorToken())
  const [status, setStatus] = useState<AgentMailInstallStatus | null>(null)
  const [snippets, setSnippets] = useState<AgentMailSnippets | null>(null)
  const [loading, setLoading] = useState(true)

  const stopRefusedReads = useCallback(async (error: unknown, key: string | null, preserveStatus = false) => {
    if (error instanceof ApiHttpError && (error.status === 401 || error.status === 403 || error.status === 503)) {
      protectedReadsBlocked.current = true
      refusedKey.current = key
      setNeedsKey(true)
      if (!preserveStatus) {
        setStatus(null)
        setSnippets(null)
      }
      if (error.status === 401) {
        if (getOperatorToken() === key) clearOperatorToken()
        try { await readAuthenticationStatus(true) } catch { /* Keep protected reads stopped. */ }
      }
      setNeedsKey(requiresDirectorKey())
    }
  }, [readAuthenticationStatus, requiresDirectorKey])

  const load = useCallback(async (deliberate = false) => {
    if (loadPromise.current) return loadPromise.current
    setLoading(true)
    const pending = Promise.resolve().then(async () => {
      let key: string | null = null
      try {
        const configured = await readAuthenticationStatus()
        key = getOperatorToken()
        if ((configured && !key) || (protectedReadsBlocked.current && key === refusedKey.current && (configured || !deliberate))) {
          setNeedsKey(configured)
          return
        }
        protectedReadsBlocked.current = false
        const next = await fetchAgentMailInstallStatus()
        setStatus(isCompleteInstallStatus(next) ? next : null)
        setNeedsKey(false)
      } catch (error) {
        await stopRefusedReads(error, key)
        toast.error(error instanceof Error ? error.message : 'Failed to load install status')
      } finally {
        setLoading(false)
        loadPromise.current = null
      }
    })
    loadPromise.current = pending
    return pending
  }, [readAuthenticationStatus, stopRefusedReads])

  const enterKey = useCallback(async () => {
    if (!await readAuthenticationStatus()) { await load(true); return }
    if (protectedReadsBlocked.current && getOperatorToken() === refusedKey.current) clearOperatorToken()
    const token = await requestToken(protectedReadsBlocked.current
      ? 'The Director key was rejected. Enter a valid key to retry.' : null)
    if (!token) return
    await load()
  }, [load, requestToken, readAuthenticationStatus])

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
    const key = getOperatorToken()
    if (snippets || (!key && requiresDirectorKey()) || needsKey || protectedReadsBlocked.current) return
    try {
      setSnippets(await fetchAgentMailSnippets())
    } catch (error) {
      await stopRefusedReads(error, key)
      toast.error(error instanceof Error ? error.message : 'Failed to load the fallback snippets')
    }
  }, [snippets, needsKey, requiresDirectorKey, stopRefusedReads])

  const run = useCallback(async (harness: MailActionHarness, mode: MailActionMode) => {
    const action = ACTIONS[harness][mode]
    const key = getOperatorToken()
    try {
      const next = await action.run()
      setStatus(isCompleteInstallStatus(next) ? next : null)
      await load()
      toast.success(action.label)
    } catch (error) {
      if (error instanceof ApiHttpError && (error.status === 401 || error.status === 403)) {
        await stopRefusedReads(error, key, true)
      }
      toast.error(error instanceof Error ? error.message : 'Install action failed')
      throw error
    }
  }, [load, stopRefusedReads])

  return { status, snippets, loading, needsKey, recommendKey: directorKeyConfigured === false, enterKey, tokenDialog, reload: load, loadSnippets, run }
}

export type AgentMailSetup = ReturnType<typeof useAgentMailSetup>
