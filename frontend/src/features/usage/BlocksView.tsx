import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import type { SessionBlock } from '@/types/usage'
import { formatTokens, formatCost, formatTimestamp, getRelativeTime } from './utils'

interface BlocksViewProps {
  blocks: SessionBlock[]
  activeBlock?: SessionBlock
  loading: boolean
  totalCost: number
}

export function BlocksView({ blocks, activeBlock, loading, totalCost }: BlocksViewProps) {
  if (loading && blocks.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Billing Blocks</CardTitle>
          <CardDescription>Loading...</CardDescription>
        </CardHeader>
        <CardContent className="h-[200px] flex items-center justify-center text-muted-foreground">
          Loading block data...
        </CardContent>
      </Card>
    )
  }

  // Filter out gap blocks for display
  const activityBlocks = blocks.filter(b => !b.is_gap)

  if (activityBlocks.length === 0 && !activeBlock) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Billing Blocks</CardTitle>
          <CardDescription>5-hour billing windows</CardDescription>
        </CardHeader>
        <CardContent className="h-[200px] flex items-center justify-center text-muted-foreground">
          No billing blocks available
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Active Block */}
      {activeBlock && (
        <Card className="border-success/50 bg-success/5">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                Active Block
                <Badge variant="default" className="bg-success text-success-foreground">LIVE</Badge>
              </CardTitle>
              <span className="text-sm text-muted-foreground">
                {activeBlock.remaining_minutes} min remaining
              </span>
            </div>
            <CardDescription>
              Started {formatTimestamp(activeBlock.start_time)}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {/* Progress bar */}
              <div className="space-y-1">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Block Progress</span>
                  <span>{Math.round(((300 - (activeBlock.remaining_minutes || 0)) / 300) * 100)}%</span>
                </div>
                <Progress
                  value={((300 - (activeBlock.remaining_minutes || 0)) / 300) * 100}
                  className="h-2"
                />
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">Current Cost</p>
                  <p className="text-lg font-bold">{formatCost(activeBlock.cost_usd)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Projected</p>
                  <p className="text-lg font-bold text-muted-foreground">
                    {formatCost(activeBlock.projected_total_cost || activeBlock.cost_usd)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Burn Rate</p>
                  <p className="text-lg font-bold">
                    {activeBlock.burn_rate_cost_per_hour
                      ? `${formatCost(activeBlock.burn_rate_cost_per_hour)}/hr`
                      : '-'}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Tokens</p>
                  <p className="text-lg font-bold">
                    {formatTokens(activeBlock.input_tokens + activeBlock.output_tokens)}
                  </p>
                </div>
              </div>

              {activeBlock.models.length > 0 && (
                <div className="flex gap-1 flex-wrap">
                  {activeBlock.models.map(model => (
                    <Badge key={model} variant="outline" className="text-xs">
                      {model.replace('claude-', '').replace(/-20\d{6}$/, '')}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Blocks */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Blocks</CardTitle>
          <CardDescription>
            {activityBlocks.length} blocks | Total: {formatCost(totalCost)}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {activityBlocks.slice(0, 10).map((block) => (
              <div
                key={block.id}
                className="flex items-center justify-between p-3 rounded-lg border bg-card hover:bg-muted/50 transition-colors"
              >
                <div className="space-y-1">
                  <div className="font-medium">
                    {formatTimestamp(block.start_time)}
                    <span className="text-xs text-muted-foreground ml-2">
                      ({getRelativeTime(block.start_time)})
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {block.actual_end_time
                      ? `Active for ${Math.round((new Date(block.actual_end_time).getTime() - new Date(block.start_time).getTime()) / 60000)} min`
                      : 'No activity recorded'}
                  </div>
                </div>
                <div className="text-right space-y-1">
                  <div className="font-bold tabular-nums">{formatCost(block.cost_usd)}</div>
                  <div className="text-xs text-muted-foreground tabular-nums">
                    {formatTokens(block.input_tokens + block.output_tokens)} tokens
                  </div>
                </div>
              </div>
            ))}
          </div>
          {activityBlocks.length > 10 && (
            <div className="text-center pt-4 text-xs text-muted-foreground">
              Showing 10 of {activityBlocks.length} blocks
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
