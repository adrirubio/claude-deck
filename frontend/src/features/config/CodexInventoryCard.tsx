import { ChevronRight, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { CodexMcpInventoryResponse, CodexPluginInventoryResponse } from '@/types/providers'

interface CodexInventoryCardProps {
  mcp: CodexMcpInventoryResponse | null
  plugins: CodexPluginInventoryResponse | null
  mcpError: string | null
  pluginError: string | null
  loading: boolean
  onRefresh: () => void
}

function countMcpServers(servers: unknown): number | null {
  if (!servers || typeof servers !== 'object') return null
  if (Array.isArray(servers)) return servers.length
  const objectValue = servers as Record<string, unknown>
  if (objectValue.servers && typeof objectValue.servers === 'object') {
    return Array.isArray(objectValue.servers)
      ? objectValue.servers.length
      : Object.keys(objectValue.servers as Record<string, unknown>).length
  }
  return Object.keys(objectValue).length
}

function InventoryError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
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
  const mcpCount = countMcpServers(mcp?.servers)
  const pluginCount = plugins?.plugins.length ?? null

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Codex Inventory</CardTitle>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onRefresh}
          disabled={loading}
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
            {plugins?.stderr && (
              <p className="mt-2 text-xs text-muted-foreground">{plugins.stderr}</p>
            )}
          </div>
        </div>

        <InventoryError message={mcpError} />
        <InventoryError message={pluginError} />

        {plugins?.plugins && plugins.plugins.length > 0 && (
          <div className="rounded-md border">
            {plugins.plugins.map((plugin) => (
              <div key={`${plugin.status ?? 'unknown'}:${plugin.name}`} className="border-b p-3 last:border-b-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium">{plugin.name}</p>
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
