import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { SessionUsage } from '@/types/usage'
import { formatTokens, formatCost, shortenModelName } from './utils'

interface SessionUsageTableProps {
  data: SessionUsage[]
  loading: boolean
  totalCost: number
}

export function SessionUsageTable({ data, loading, totalCost }: SessionUsageTableProps) {
  if (loading && data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Sessions</CardTitle>
          <CardDescription>Loading...</CardDescription>
        </CardHeader>
        <CardContent className="h-[200px] flex items-center justify-center text-muted-foreground">
          Loading session data...
        </CardContent>
      </Card>
    )
  }

  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Sessions</CardTitle>
          <CardDescription>Usage by session</CardDescription>
        </CardHeader>
        <CardContent className="h-[200px] flex items-center justify-center text-muted-foreground">
          No session data available
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sessions</CardTitle>
        <CardDescription>
          {data.length} sessions | Total: {formatCost(totalCost)}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="relative overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-muted-foreground uppercase bg-muted/50">
              <tr>
                <th className="px-3 py-2">Project</th>
                <th className="px-3 py-2 text-right">Tokens</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2">Models</th>
                <th className="px-3 py-2">Last Activity</th>
              </tr>
            </thead>
            <tbody>
              {data.slice(0, 20).map((session) => (
                <tr
                  key={session.session_id}
                  className="border-b border-border/50 hover:bg-muted/30"
                >
                  <td className="px-3 py-2 font-medium">
                    <div className="truncate max-w-[200px]" title={session.project_path}>
                      {session.project_path.split('/').pop() || session.project_path}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono">
                      {session.session_id.slice(0, 8)}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <div>{formatTokens(session.input_tokens + session.output_tokens)}</div>
                    <div className="text-xs text-muted-foreground">
                      {formatTokens(session.input_tokens)} / {formatTokens(session.output_tokens)}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-medium">
                    {formatCost(session.total_cost)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {session.models_used.slice(0, 2).map((model) => (
                        <span
                          key={model}
                          className="px-1.5 py-0.5 text-xs bg-muted rounded"
                        >
                          {shortenModelName(model)}
                        </span>
                      ))}
                      {session.models_used.length > 2 && (
                        <span className="px-1.5 py-0.5 text-xs bg-muted rounded">
                          +{session.models_used.length - 2}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {session.last_activity}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.length > 20 && (
            <div className="text-center py-2 text-xs text-muted-foreground">
              Showing 20 of {data.length} sessions
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
