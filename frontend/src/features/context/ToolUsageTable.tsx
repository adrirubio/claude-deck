import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import type { ToolConsumption } from '@/types/context'

interface ToolUsageTableProps {
  tools: ToolConsumption[]
  showHelp?: boolean
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

export function ToolUsageTable({ tools, showHelp }: ToolUsageTableProps) {
  if (tools.length === 0) {
    return null
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Tool Usage</CardTitle>
        {showHelp && (
          <CardDescription>
            Per-tool call counts and the estimated token cost of their results. Tools with large average result sizes (Bash, Grep, WebFetch) can fill the context fast — narrower queries help.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="pb-2 font-medium text-muted-foreground">Tool</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Calls</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Total Tokens</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Avg / Call</th>
              </tr>
            </thead>
            <tbody>
              {tools.slice(0, 20).map((tool) => (
                <tr key={tool.tool_name} className="border-b border-border/50">
                  <td className="py-1.5 font-mono text-xs" title={tool.tool_name}>
                    {tool.tool_name}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{tool.call_count}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatTokens(tool.total_result_tokens)}</td>
                  <td className="py-1.5 text-right tabular-nums text-muted-foreground">{formatTokens(tool.avg_result_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
