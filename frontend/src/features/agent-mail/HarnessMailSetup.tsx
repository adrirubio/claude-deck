import { useEffect, useState } from 'react'
import { Clipboard } from 'lucide-react'
import { toast } from 'sonner'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { AgentMailSnippets } from '@/types/agentMail'
import type { AgentProviderId } from '@/types/providers'
import {
  HARNESS_NAMES,
  hasMailAction,
  mailConfirm,
  mailSetupActions,
  mailSetupLine,
  mailSetupState,
  mailTechnicalLines,
  type MailActionMode,
} from './mailSetup'
import type { AgentMailSetup } from './useAgentMailSetup'

function snippetsFor(providerId: AgentProviderId, snippets: AgentMailSnippets): Array<{ label: string; text: string }> {
  if (providerId === 'codex-cli') {
    return [
      { label: 'Config snippet', text: snippets.codex_config_toml },
      { label: 'AGENTS.md snippet', text: snippets.codex_agents_md },
    ]
  }
  if (providerId === 'copilot-cli') {
    return [{ label: 'Copilot fallback', text: `${snippets.copilot_mcp_command}\n\n${snippets.copilot_hooks_json}` }]
  }
  if (providerId === 'opencode-cli') {
    return [{ label: 'OpenCode fallback', text: `${snippets.opencode_config_json}\n\n${snippets.opencode_plugin_js}` }]
  }
  return []
}

interface HarnessMailSetupProps {
  providerId: AgentProviderId
  /** False when the harness itself is not installed on this machine. */
  harnessInstalled: boolean
  setup: AgentMailSetup
}

/**
 * #531: the Agent Mail state of one harness and its Set up and Remove action.
 * The line names no path. Paths, counts and the fallback snippets are under
 * "Technical details".
 */
export function HarnessMailSetup({ providerId, harnessInstalled, setup }: HarnessMailSetupProps) {
  const { status, loading, run } = setup
  const [confirming, setConfirming] = useState<MailActionMode | null>(null)
  const [running, setRunning] = useState(false)

  if (!harnessInstalled) {
    return (
      <section aria-label="Agent Mail" className="rounded-lg border bg-card p-3 text-sm">
        <span className="font-medium">Agent Mail:</span> Install the harness first.
      </section>
    )
  }
  if (!status) {
    return (
      <section aria-label="Agent Mail" className="rounded-lg border bg-card p-3 text-sm">
        <span className="font-medium">Agent Mail:</span>{' '}
        {loading ? 'Checking the setup…' : 'The setup state is unavailable.'}
        {setup.recommendKey && <p>Set a Director key to protect Director actions.</p>}
        {!loading && setup.enterKey && (
          <Button size="sm" variant="outline" onClick={() => void setup.enterKey()}>{setup.recommendKey ? 'Retry' : 'Enter the Director key'}</Button>
        )}
        {setup.tokenDialog}
      </section>
    )
  }

  const state = mailSetupState(providerId, status)
  const actions = mailSetupActions(state)
  const managed = hasMailAction(providerId)
  const confirm = managed && confirming ? mailConfirm(providerId, confirming, status) : null

  const runConfirmed = async () => {
    if (!managed || !confirming) return
    setRunning(true)
    try {
      await run(providerId, confirming)
      setConfirming(null)
    } catch {
      // The hook already showed the error. Keep the dialog open.
    } finally {
      setRunning(false)
    }
  }

  return (
    <section aria-label="Agent Mail" className="space-y-3 rounded-lg border bg-card p-3">
      {setup.tokenDialog}
      {setup.recommendKey && <p className="text-sm">Set a Director key to protect Director actions.</p>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          <span className="font-medium">Agent Mail:</span>{' '}
          {/* data-plain: "Restart sessions" is a plain phrase, not a code name (see the harness page checks). */}
          <span data-plain="mail-state">{mailSetupLine(state)}</span>
        </p>
        {setup.needsKey && setup.enterKey && (
          <Button size="sm" variant="outline" onClick={() => void setup.enterKey()}>Enter the Director key</Button>
        )}
        {managed && !setup.needsKey && (
          <div className="flex flex-wrap gap-2">
            {actions.setUp && (
              <Button size="sm" onClick={() => setConfirming('setup')}>Set up</Button>
            )}
            {actions.remove && (
              <Button size="sm" variant="outline" onClick={() => setConfirming('remove')}>Remove</Button>
            )}
          </div>
        )}
      </div>
      <AlertDialog open={Boolean(confirm)} onOpenChange={(open) => !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirm?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 rounded-lg border bg-muted/40 p-3 text-sm">
            {confirm?.mutations.map((mutation) => (
              <div key={mutation} className="wrap-break-word">{mutation}</div>
            ))}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={running}>Cancel</AlertDialogCancel>
            <Button onClick={() => void runConfirmed()} disabled={running}>
              {running ? 'Applying...' : 'Confirm'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

interface HarnessMailDetailsProps {
  providerId: AgentProviderId
  setup: AgentMailSetup
}

/** The Agent Mail technical lines and fallback snippets. The harness page puts them inside its one "Technical details". */
export function HarnessMailDetails({ providerId, setup }: HarnessMailDetailsProps) {
  const { status, snippets, loadSnippets } = setup
  const name = HARNESS_NAMES[providerId]
  const needsSnippets = hasMailAction(providerId) && providerId !== 'claude-code'

  useEffect(() => {
    if (needsSnippets) void loadSnippets()
  }, [needsSnippets, loadSnippets])

  if (!status) return null

  const copy = async (text: string, label: string) => {
    await navigator.clipboard.writeText(text)
    toast.success(`${label} copied`)
  }

  return (
    <section aria-label={`${name} Agent Mail details`} className="space-y-3">
      <p className="font-medium">Agent Mail</p>
      <dl className="space-y-1 text-sm">
        {mailTechnicalLines(providerId, status).map((line) => (
          <div key={line.label} className="min-w-0">
            <dt className="inline text-muted-foreground">{line.label}: </dt>
            <dd className="inline break-all">
              <code className="rounded bg-muted px-1 py-0.5 text-xs">{line.value}</code>
            </dd>
          </div>
        ))}
      </dl>
      {snippets && snippetsFor(providerId, snippets).map((snippet) => (
        <div key={snippet.label} className="space-y-2">
          <p className="text-sm font-medium">{name} {snippet.label.toLowerCase()} (manual setup)</p>
          <Textarea value={snippet.text} readOnly rows={8} className="font-mono text-xs" />
          <Button size="sm" variant="outline" onClick={() => void copy(snippet.text, snippet.label)}>
            <Clipboard className="mr-2 h-4 w-4" />
            Copy
          </Button>
        </div>
      ))}
    </section>
  )
}
