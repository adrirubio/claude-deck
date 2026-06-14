import { CheckCircle2, Clipboard, Plug, RefreshCw, ShieldCheck, Terminal, Trash2, Unplug } from 'lucide-react'
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
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import type { AgentMailInstallStatus, AgentMailSnippets } from '@/types/agentMail'
import { useState } from 'react'

type InstallActionKey =
  | 'claude-apply'
  | 'claude-uninstall'
  | 'codex-apply'
  | 'codex-uninstall'

interface InstallTabProps {
  status: AgentMailInstallStatus | null
  snippets: AgentMailSnippets | null
  loading: boolean
  onRefresh: () => Promise<void>
  onApplyClaudeCode: () => Promise<void>
  onUninstallClaudeCode: () => Promise<void>
  onApplyCodex: () => Promise<void>
  onUninstallCodex: () => Promise<void>
}

function InstalledBadge({
  installed,
  installedLabel = 'installed',
  missingLabel = 'not installed',
}: {
  installed: boolean
  installedLabel?: string
  missingLabel?: string
}) {
  return installed ? (
    <Badge variant="outline" className="border-emerald-300 text-emerald-700">
      {installedLabel}
    </Badge>
  ) : (
    <Badge variant="outline">{missingLabel}</Badge>
  )
}

function PathLine({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="min-w-0 text-sm">
      <span className="text-muted-foreground">{label}: </span>
      <code className="break-all rounded bg-muted px-1 py-0.5 text-xs">{value || 'unavailable'}</code>
    </div>
  )
}

export function InstallTab({
  status,
  snippets,
  loading,
  onRefresh,
  onApplyClaudeCode,
  onUninstallClaudeCode,
  onApplyCodex,
  onUninstallCodex,
}: InstallTabProps) {
  const [confirming, setConfirming] = useState<InstallActionKey | null>(null)
  const [running, setRunning] = useState(false)

  const copyText = async (text: string, label: string) => {
    await navigator.clipboard.writeText(text)
    toast.success(`${label} copied`)
  }

  const actionDetails = (() => {
    if (!status || !confirming) return null
    if (confirming === 'claude-apply') {
      return {
        title: 'Install Agent Mail for Claude Code',
        description: 'A backup is attempted before these user-scope config changes are made.',
        mutations: [
          `${status.claude_settings_path || '~/.claude/settings.json'}: add four Agent Mail curl command hooks`,
          `${status.claude_mcp_config_path || '~/.claude.json'}: add user MCP server ${'claude-deck-mail'}`,
        ],
        run: onApplyClaudeCode,
      }
    }
    if (confirming === 'claude-uninstall') {
      return {
        title: 'Remove Agent Mail from Claude Code',
        description: 'A backup is attempted before the managed hooks and MCP server are removed.',
        mutations: [
          `${status.claude_settings_path || '~/.claude/settings.json'}: remove Agent Mail hook commands`,
          `${status.claude_mcp_config_path || '~/.claude.json'}: remove MCP server ${'claude-deck-mail'}`,
        ],
        run: onUninstallClaudeCode,
      }
    }
    if (confirming === 'codex-apply') {
      return {
        title: 'Install Agent Mail for Codex',
        description: 'A backup is attempted before Claude Deck installs the Codex MCP server and lifecycle hooks.',
        mutations: [
          'Codex CLI: run `codex mcp add --env CLAUDE_DECK_URL=... --env CLAUDE_DECK_PROVIDER=codex-cli claude-deck-mail -- ...`',
          `${status.codex_hooks_path || '~/.codex/hooks.json'}: add Agent Mail SessionStart and UserPromptSubmit hooks`,
          `MCP server command: ${status.python_path} ${status.shim_path}`,
        ],
        run: onApplyCodex,
      }
    }
    return {
      title: 'Remove Agent Mail from Codex',
      description: 'A backup is attempted before Claude Deck removes the managed MCP server and hooks.',
      mutations: [
        'Codex CLI: run `codex mcp remove claude-deck-mail`',
        `${status.codex_hooks_path || '~/.codex/hooks.json'}: remove Agent Mail hook commands`,
      ],
      run: onUninstallCodex,
    }
  })()

  const runConfirmed = async () => {
    if (!actionDetails) return
    setRunning(true)
    try {
      await actionDetails.run()
      setConfirming(null)
    } finally {
      setRunning(false)
    }
  }

  if (!status) {
    return (
      <Card className="rounded-lg border-dashed">
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          {loading ? 'Loading install status...' : 'Install status unavailable.'}
        </CardContent>
      </Card>
    )
  }

  const claudeInstalled = status.claude_code_hooks_missing.length === 0 && status.claude_code_mcp_installed
  const claudeHooksInstalled = status.claude_code_hooks_missing.length === 0
  const codexHooksInstalled = status.codex_hooks_missing.length === 0
  const codexInstalled = status.codex_mcp_installed && codexHooksInstalled

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="rounded-lg">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Plug className="h-5 w-5" />
                  Claude Code
                </CardTitle>
                <CardDescription>Hooks deliver state into context; MCP tools send and read mail.</CardDescription>
              </div>
              <InstalledBadge installed={claudeInstalled} />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {claudeInstalled && (
              <Alert className="border-emerald-300 bg-emerald-50/60 dark:bg-emerald-950/20">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                <AlertTitle>Claude Code integration installed</AlertTitle>
                <AlertDescription>
                  Hooks and MCP are configured. Restart or resume Claude Code sessions so the MCP server and hooks are loaded.
                </AlertDescription>
              </Alert>
            )}
            <div className="space-y-2">
              <PathLine label="Hooks file" value={status.claude_settings_path} />
              <PathLine label="MCP file" value={status.claude_mcp_config_path} />
              <PathLine label="Shim" value={status.shim_path} />
              <PathLine label="Deck URL" value={status.deck_url} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant={status.curl_available ? 'secondary' : 'destructive'}>
                curl {status.curl_available ? 'available' : 'missing'}
              </Badge>
              <Badge
                variant="outline"
                className={claudeHooksInstalled ? 'border-emerald-300 text-emerald-700' : ''}
              >
                hooks {claudeHooksInstalled ? 'installed' : `${status.claude_code_hooks.length}/4 installed`}
              </Badge>
              <Badge
                variant="outline"
                className={status.claude_code_mcp_installed ? 'border-emerald-300 text-emerald-700' : ''}
              >
                MCP {status.claude_code_mcp_installed ? 'installed' : 'not installed'}
              </Badge>
              {status.claude_code_hooks_missing.length > 0 && (
                <Badge variant="outline" className="border-amber-300 text-amber-700">
                  missing {status.claude_code_hooks_missing.length}
                </Badge>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setConfirming('claude-apply')} disabled={claudeInstalled}>
                <ShieldCheck className="mr-2 h-4 w-4" />
                Install
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setConfirming('claude-uninstall')}
                disabled={!claudeInstalled}
              >
                <Unplug className="mr-2 h-4 w-4" />
                Uninstall
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-lg">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Terminal className="h-5 w-5" />
                  Codex CLI
                </CardTitle>
                <CardDescription>MCP tools read mail; hooks remind Codex at turn boundaries.</CardDescription>
              </div>
              <InstalledBadge
                installed={codexInstalled}
                installedLabel="installed"
                missingLabel="not installed"
              />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {codexInstalled && (
              <Alert className="border-blue-300 bg-blue-50/60 dark:bg-blue-950/20">
                <Terminal className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                <AlertTitle>Codex integration installed</AlertTitle>
                <AlertDescription>
                  MCP and lifecycle hooks are configured. Restart or resume Codex sessions so hooks and the MCP server are loaded.
                </AlertDescription>
              </Alert>
            )}
            <div className="space-y-2">
              <PathLine label="Hooks file" value={status.codex_hooks_path} />
              <PathLine label="Shim" value={status.shim_path} />
              <PathLine label="Python" value={status.python_path} />
              <PathLine label="Deck URL" value={status.deck_url} />
            </div>
            <Badge variant={status.codex_cli_available ? 'secondary' : 'destructive'}>
              Codex CLI {status.codex_cli_available ? 'available' : 'missing'}
            </Badge>
            <Badge
              variant="outline"
              className={status.codex_mcp_installed ? 'border-emerald-300 text-emerald-700' : ''}
            >
              MCP {status.codex_mcp_installed ? 'installed' : 'not installed'}
            </Badge>
            <Badge
              variant="outline"
              className={codexHooksInstalled ? 'border-emerald-300 text-emerald-700' : ''}
            >
              hooks {codexHooksInstalled ? 'installed' : `${status.codex_hooks.length}/2 installed`}
            </Badge>
            {status.codex_hooks_missing.length > 0 && (
              <Badge variant="outline" className="border-amber-300 text-amber-700">
                missing {status.codex_hooks_missing.length}
              </Badge>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => setConfirming('codex-apply')}
                disabled={!status.codex_cli_available || codexInstalled}
              >
                <ShieldCheck className="mr-2 h-4 w-4" />
                Install
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setConfirming('codex-uninstall')}
                disabled={!status.codex_cli_available || (!status.codex_mcp_installed && !codexHooksInstalled)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Remove
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {snippets && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card className="rounded-lg">
            <CardHeader>
              <CardTitle>Codex config snippet</CardTitle>
              <CardDescription>Manual fallback for MCP setup.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea value={snippets.codex_config_toml} readOnly rows={8} className="font-mono text-xs" />
              <Button size="sm" variant="outline" onClick={() => copyText(snippets.codex_config_toml, 'Config snippet')}>
                <Clipboard className="mr-2 h-4 w-4" />
                Copy
              </Button>
            </CardContent>
          </Card>
          <Card className="rounded-lg">
            <CardHeader>
              <CardTitle>AGENTS.md snippet</CardTitle>
              <CardDescription>Suggested instruction block for Codex projects.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea value={snippets.codex_agents_md} readOnly rows={8} className="font-mono text-xs" />
              <Button size="sm" variant="outline" onClick={() => copyText(snippets.codex_agents_md, 'AGENTS.md snippet')}>
                <Clipboard className="mr-2 h-4 w-4" />
                Copy
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      <AlertDialog open={Boolean(confirming)} onOpenChange={(open) => !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{actionDetails?.title}</AlertDialogTitle>
            <AlertDialogDescription>{actionDetails?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 rounded-lg border bg-muted/40 p-3 text-sm">
            {actionDetails?.mutations.map((mutation) => (
              <div key={mutation} className="break-words">
                {mutation}
              </div>
            ))}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={running}>Cancel</AlertDialogCancel>
            <Button onClick={runConfirmed} disabled={running}>
              {running ? 'Applying...' : 'Confirm'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
