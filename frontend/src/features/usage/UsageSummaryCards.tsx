import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { UsageSummary } from '@/types/usage'
import { formatTokens, formatCost } from './utils'

interface UsageSummaryCardsProps {
  summary: UsageSummary | null
  loading: boolean
}

export function UsageSummaryCards({ summary, loading }: UsageSummaryCardsProps) {
  if (loading && !summary) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <CardDescription>Loading...</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">-</div>
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  if (!summary) return null

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Total Cost</CardDescription>
          <CardTitle className="text-3xl">{formatCost(summary.total_cost)}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            {summary.date_range_start && summary.date_range_end
              ? `${summary.date_range_start} to ${summary.date_range_end}`
              : 'All time'}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Total Tokens</CardDescription>
          <CardTitle className="text-3xl">{formatTokens(summary.total_tokens)}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted-foreground space-y-1">
            <p>Input: {formatTokens(summary.total_input_tokens)}</p>
            <p>Output: {formatTokens(summary.total_output_tokens)}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Cache Tokens</CardDescription>
          <CardTitle className="text-3xl">{formatTokens(summary.total_cache_read_tokens)}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted-foreground space-y-1">
            <p>Created: {formatTokens(summary.total_cache_creation_tokens)}</p>
            <p>Read: {formatTokens(summary.total_cache_read_tokens)}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Activity</CardDescription>
          <CardTitle className="text-3xl">{summary.session_count}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted-foreground space-y-1">
            <p>{summary.project_count} projects</p>
            <p>{summary.models_used.length} models used</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
