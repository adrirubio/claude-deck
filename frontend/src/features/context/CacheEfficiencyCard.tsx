import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import type { CacheEfficiency } from '@/types/context'

interface CacheEfficiencyCardProps {
  cache: CacheEfficiency
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

export function CacheEfficiencyCard({ cache }: CacheEfficiencyCardProps) {
  const hitPct = Math.round(cache.hit_ratio * 100)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Cache Efficiency</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-muted-foreground">Hit Ratio</span>
            <span className="font-medium">{hitPct}%</span>
          </div>
          <Progress value={hitPct} className="h-2" />
        </div>
        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          <div>
            <div className="font-medium">{formatTokens(cache.total_cache_read)}</div>
            <div className="text-muted-foreground">Cache Read</div>
          </div>
          <div>
            <div className="font-medium">{formatTokens(cache.total_cache_creation)}</div>
            <div className="text-muted-foreground">Cache Write</div>
          </div>
          <div>
            <div className="font-medium">{formatTokens(cache.total_uncached)}</div>
            <div className="text-muted-foreground">Uncached</div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
