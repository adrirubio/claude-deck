import { useMemo, useState } from 'react'
import { ChevronRight, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { addCodexMcpServer, installCodexPlugin, removeCodexMcpServer, removeCodexPlugin } from '@/hooks/useProviders'
import { cn } from '@/lib/utils'
import type { CodexMcpAddRequest, CodexMcpInventoryResponse, CodexPluginInventoryResponse } from '@/types/providers'

interface CodexInventoryCardProps {
  mcp: CodexMcpInventoryResponse | null
  plugins: CodexPluginInventoryResponse | null
  mcpError: string | null
  pluginError: string | null
  loading: boolean
  onRefresh: () => void | Promise<void>
}

type McpMode = 'command' | 'url'

interface McpServerRow {
  name: string
  details: unknown
}

function getMcpServerMap(servers: unknown): Record<string, unknown> | null {
  if (!servers || typeof servers !== 'object' || Array.isArray(servers)) return null
  const objectValue = servers as Record<string, unknown>
  if (objectValue.servers && typeof objectValue.servers === 'object' && !Array.isArray(objectValue.servers)) {
    return objectValue.servers as Record<string, unknown>
  }
  return objectValue
}

function getMcpServerRows(servers: unknown): McpServerRow[] {
  if (Array.isArray(servers)) {
    return servers.flatMap((server, index) => {
      if (!server || typeof server !== 'object') return []
      const objectValue = server as Record<string, unknown>
      const name = typeof objectValue.name === 'string' ? objectValue.name : `server-${index + 1}`
      return [{ name, details: server }]
    })
  }
  const map = getMcpServerMap(servers)
  if (!map) return []
  return Object.entries(map).map(([name, details]) => ({ name, details }))
}

function countMcpServers(servers: unknown): number | null {
  if (!servers || typeof servers !== 'object') return null
  if (Array.isArray(servers)) return servers.length
  const map = getMcpServerMap(servers)
  return map ? Object.keys(map).length : null
}

function parseLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function parseEnv(value: string): Record<string, string> {
  const env: Record<string, string> = {}
  for (const line of parseLines(value)) {
    const separatorIndex = line.indexOf('=')
    if (separatorIndex <= 0) {
      throw new Error('Environment variables must use KEY=VALUE format')
    }
    env[line.slice(0, separatorIndex).trim()] = line.slice(separatorIndex + 1)
  }
  return env
}

function InventoryError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      {message}
    </p>
  )
}

function InventoryMessage({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p className="rounded-md border border-primary/30 bg-primary/10 p-3 text-sm text-primary">
      {message}
    </p>
  )
}

function RawDetails({ label, content }: { label: string; content: unknown }) {
  return (
    <details className="group rounded-md border">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium">
        <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" />
        {label}
      </summary>
      <pre className="max-h-72 overflow-auto border-t bg-muted p-3 text-xs">
        {typeof content === 'string' ? content || '(empty)' : JSON.stringify(content, null, 2)}
      </pre>
    </details>
  )
}

export function CodexInventoryCard({
  mcp,
  plugins,
  mcpError,
  pluginError,
  loading,
  onRefresh,
}: CodexInventoryCardProps) {
  const [mode, setMode] = useState<McpMode>('command')
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [argsText, setArgsText] = useState('')
  const [envText, setEnvText] = useState('')
  const [url, setUrl] = useState('')
  const [bearerTokenEnvVar, setBearerTokenEnvVar] = useState('')
  const [pluginName, setPluginName] = useState('')
  const [pluginMarketplace, setPluginMarketplace] = useState('')
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [mutationMessage, setMutationMessage] = useState<string | null>(null)
  const [mutating, setMutating] = useState(false)

  const mcpRows = useMemo(() => getMcpServerRows(mcp?.servers), [mcp?.servers])
  const mcpCount = countMcpServers(mcp?.servers)
  const pluginCount = plugins?.plugins.length ?? null
  const pluginCapabilities = plugins?.mutation_capabilities
  const canInstallPlugins = pluginCapabilities?.install.state === 'supported'
  const canRemovePlugins = pluginCapabilities?.remove.state === 'supported'
  const pluginToggleUnsupported = [
    pluginCapabilities?.enable.reason,
    pluginCapabilities?.disable.reason,
  ].filter(Boolean).join(' ')

  const resetForm = () => {
    setName('')
    setCommand('')
    setArgsText('')
    setEnvText('')
    setUrl('')
    setBearerTokenEnvVar('')
  }

  const resetPluginForm = () => {
    setPluginName('')
    setPluginMarketplace('')
  }

  const handleAddMcp = async () => {
    setMutationError(null)
    setMutationMessage(null)
    try {
      const trimmedName = name.trim()
      if (!trimmedName) throw new Error('Server name is required')
      const request: CodexMcpAddRequest = mode === 'url'
        ? {
            name: trimmedName,
            url: url.trim(),
            ...(bearerTokenEnvVar.trim() && { bearer_token_env_var: bearerTokenEnvVar.trim() }),
          }
        : {
            name: trimmedName,
            command: command.trim(),
            args: parseLines(argsText),
            env: parseEnv(envText),
          }
      if (mode === 'url' && !request.url) throw new Error('URL is required')
      if (mode === 'command' && !request.command) throw new Error('Command is required')

      setMutating(true)
      const result = await addCodexMcpServer(request)
      if (result.exit_code !== 0) {
        throw new Error(result.stderr || result.stdout || `codex mcp add exited with ${result.exit_code}`)
      }
      const message = `MCP server "${trimmedName}" added`
      setMutationMessage(message)
      toast.success(message)
      resetForm()
      await onRefresh()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to add MCP server'
      setMutationError(message)
      toast.error(message)
    } finally {
      setMutating(false)
    }
  }

  const handleRemoveMcp = async (serverName: string) => {
    setMutationError(null)
    setMutationMessage(null)
    setMutating(true)
    try {
      const result = await removeCodexMcpServer(serverName)
      if (result.exit_code !== 0) {
        throw new Error(result.stderr || result.stdout || `codex mcp remove exited with ${result.exit_code}`)
      }
      const message = `MCP server "${serverName}" removed`
      setMutationMessage(message)
      toast.success(message)
      await onRefresh()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to remove MCP server'
      setMutationError(message)
      toast.error(message)
    } finally {
      setMutating(false)
    }
  }

  const handleInstallPlugin = async () => {
    setMutationError(null)
    setMutationMessage(null)
    try {
      const trimmedName = pluginName.trim()
      const trimmedMarketplace = pluginMarketplace.trim()
      if (!trimmedName) throw new Error('Plugin name is required')
      if (!canInstallPlugins) {
        throw new Error(pluginCapabilities?.install.reason || 'Codex plugin install is not supported')
      }

      setMutating(true)
      const result = await installCodexPlugin({
        name: trimmedName,
        ...(trimmedMarketplace && { marketplace: trimmedMarketplace }),
      })
      if (result.exit_code !== 0) {
        throw new Error(result.stderr || result.stdout || `codex plugin add exited with ${result.exit_code}`)
      }
      const message = `Plugin "${trimmedName}" installed`
      setMutationMessage(message)
      toast.success(message)
      resetPluginForm()
      await onRefresh()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to install Codex plugin'
      setMutationError(message)
      toast.error(message)
    } finally {
      setMutating(false)
    }
  }

  const handleRemovePlugin = async (nameToRemove: string) => {
    setMutationError(null)
    setMutationMessage(null)
    if (!canRemovePlugins) {
      const message = pluginCapabilities?.remove.reason || 'Codex plugin remove is not supported'
      setMutationError(message)
      toast.error(message)
      return
    }

    setMutating(true)
    try {
      const result = await removeCodexPlugin(nameToRemove)
      if (result.exit_code !== 0) {
        throw new Error(result.stderr || result.stdout || `codex plugin remove exited with ${result.exit_code}`)
      }
      const message = `Plugin "${nameToRemove}" removed`
      setMutationMessage(message)
      toast.success(message)
      await onRefresh()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to remove Codex plugin'
      setMutationError(message)
      toast.error(message)
    } finally {
      setMutating(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Codex Inventory</CardTitle>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onRefresh}
          disabled={loading || mutating}
          title="Refresh inventory"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-md border p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">MCP Servers</p>
              <Badge variant={mcp?.exit_code === 0 ? 'default' : 'outline'}>
                exit {mcp?.exit_code ?? 'n/a'}
              </Badge>
            </div>
            <p className="mt-1 text-2xl font-semibold">{mcpCount ?? 'Unknown'}</p>
            {mcp?.parse_error && (
              <p className="mt-2 text-xs text-destructive">{mcp.parse_error}</p>
            )}
            {mcp?.stderr && (
              <p className="mt-2 text-xs text-muted-foreground">{mcp.stderr}</p>
            )}
          </div>

          <div className="rounded-md border p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">Plugins</p>
              <Badge variant={plugins?.exit_code === 0 ? 'default' : 'outline'}>
                exit {plugins?.exit_code ?? 'n/a'}
              </Badge>
            </div>
            <p className="mt-1 text-2xl font-semibold">{pluginCount ?? 'Unknown'}</p>
            {pluginCapabilities && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant={canInstallPlugins ? 'default' : 'outline'}>install</Badge>
                <Badge variant={canRemovePlugins ? 'default' : 'outline'}>remove</Badge>
                <Badge variant="outline">enable unsupported</Badge>
                <Badge variant="outline">disable unsupported</Badge>
              </div>
            )}
            {plugins?.stderr && (
              <p className="mt-2 text-xs text-muted-foreground">{plugins.stderr}</p>
            )}
          </div>
        </div>

        <InventoryError message={mcpError} />
        <InventoryError message={pluginError} />
        <InventoryError message={mutationError} />
        <InventoryMessage message={mutationMessage} />

        <div className="rounded-md border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">Add MCP Server</p>
            <div className="flex rounded-md border p-0.5">
              <Button
                type="button"
                variant={mode === 'command' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7"
                onClick={() => setMode('command')}
              >
                Command
              </Button>
              <Button
                type="button"
                variant={mode === 'url' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7"
                onClick={() => setMode('url')}
              >
                URL
              </Button>
            </div>
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="codex-mcp-name">Name</Label>
              <Input
                id="codex-mcp-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="linear"
                disabled={mutating}
              />
            </div>
            {mode === 'url' ? (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="codex-mcp-url">URL</Label>
                  <Input
                    id="codex-mcp-url"
                    value={url}
                    onChange={(event) => setUrl(event.target.value)}
                    placeholder="https://example.com/mcp"
                    disabled={mutating}
                  />
                </div>
                <div className="space-y-1.5 md:col-span-2">
                  <Label htmlFor="codex-mcp-bearer-env">Bearer Token Env Var</Label>
                  <Input
                    id="codex-mcp-bearer-env"
                    value={bearerTokenEnvVar}
                    onChange={(event) => setBearerTokenEnvVar(event.target.value)}
                    placeholder="MCP_TOKEN"
                    disabled={mutating}
                  />
                </div>
              </>
            ) : (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="codex-mcp-command">Command</Label>
                  <Input
                    id="codex-mcp-command"
                    value={command}
                    onChange={(event) => setCommand(event.target.value)}
                    placeholder="npx"
                    disabled={mutating}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="codex-mcp-args">Arguments</Label>
                  <Textarea
                    id="codex-mcp-args"
                    value={argsText}
                    onChange={(event) => setArgsText(event.target.value)}
                    placeholder={'-y\n@linear/mcp'}
                    disabled={mutating}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="codex-mcp-env">Environment</Label>
                  <Textarea
                    id="codex-mcp-env"
                    value={envText}
                    onChange={(event) => setEnvText(event.target.value)}
                    placeholder="LINEAR_API_KEY=value"
                    disabled={mutating}
                  />
                </div>
              </>
            )}
          </div>
          <div className="mt-3 flex justify-end">
            <Button onClick={handleAddMcp} disabled={mutating} className="gap-2">
              <Plus className="h-4 w-4" />
              Add Server
            </Button>
          </div>
        </div>

        <div className="rounded-md border p-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-sm font-medium">Install Plugin</p>
              {pluginToggleUnsupported && (
                <p className="mt-1 text-xs text-muted-foreground">{pluginToggleUnsupported}</p>
              )}
            </div>
            {pluginCapabilities?.install.command && (
              <Badge variant="outline">{pluginCapabilities.install.command}</Badge>
            )}
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="codex-plugin-name">Plugin</Label>
              <Input
                id="codex-plugin-name"
                value={pluginName}
                onChange={(event) => setPluginName(event.target.value)}
                placeholder="linear or linear@openai-curated"
                disabled={mutating || !canInstallPlugins}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="codex-plugin-marketplace">Marketplace</Label>
              <Input
                id="codex-plugin-marketplace"
                value={pluginMarketplace}
                onChange={(event) => setPluginMarketplace(event.target.value)}
                placeholder="openai-curated"
                disabled={mutating || !canInstallPlugins}
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <Button onClick={handleInstallPlugin} disabled={mutating || !canInstallPlugins} className="gap-2">
              <Plus className="h-4 w-4" />
              Install Plugin
            </Button>
          </div>
        </div>

        {mcpRows.length > 0 && (
          <div className="rounded-md border">
            {mcpRows.map((server) => (
              <div key={server.name} className="flex items-start justify-between gap-3 border-b p-3 last:border-b-0">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{server.name}</p>
                  <code className="mt-1 block max-w-full truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                    {JSON.stringify(server.details)}
                  </code>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-destructive hover:text-destructive"
                      disabled={mutating}
                      title={`Remove ${server.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Remove MCP Server</AlertDialogTitle>
                      <AlertDialogDescription>
                        Remove "{server.name}" from Codex MCP configuration? This uses codex mcp remove and cannot be undone from this screen.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => handleRemoveMcp(server.name)}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        Remove
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ))}
          </div>
        )}

        {plugins?.plugins && plugins.plugins.length > 0 && (
          <div className="rounded-md border">
            {plugins.plugins.map((plugin) => (
              <div key={`${plugin.status ?? 'unknown'}:${plugin.name}`} className="border-b p-3 last:border-b-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium">{plugin.name}</p>
                      {plugin.status && <Badge variant="outline">{plugin.status}</Badge>}
                    </div>
                    {(plugin.version || plugin.path) && (
                      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {plugin.version && <span>v{plugin.version}</span>}
                        {plugin.path && (
                          <code className="max-w-full truncate rounded bg-muted px-1.5 py-0.5 font-mono">
                            {plugin.path}
                          </code>
                        )}
                      </div>
                    )}
                  </div>
                  {plugin.status === 'installed' && (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0 text-destructive hover:text-destructive"
                          disabled={mutating || !canRemovePlugins}
                          title={`Remove ${plugin.name}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Remove Codex Plugin</AlertDialogTitle>
                          <AlertDialogDescription>
                            Remove "{plugin.name}" using codex plugin remove? This updates Codex local plugin config and cache.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => handleRemovePlugin(plugin.name)}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          >
                            Remove
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="grid gap-3 lg:grid-cols-2">
          <RawDetails label="MCP JSON" content={mcp?.servers ?? null} />
          <RawDetails label="Plugin output" content={plugins?.raw_stdout ?? ''} />
        </div>
      </CardContent>
    </Card>
  )
}
