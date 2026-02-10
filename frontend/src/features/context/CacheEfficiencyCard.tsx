import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Info } from 'lucide-react'
import type { CacheEfficiency } from '@/types/context'

interface CacheEfficiencyCardProps {
  cache: CacheEfficiency
  showHelp?: boolean
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

export function CacheEfficiencyCard({ cache, showHelp }: CacheEfficiencyCardProps) {
  const hitPct = Math.round(cache.hit_ratio * 100)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Cache Efficiency</CardTitle>
        {showHelp && (
          <CardDescription>
            Shows how effectively Claude reuses cached content instead of re-processing it each turn.
          </CardDescription>
        )}
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
        {showHelp && (
          <div className="bg-muted p-3 rounded text-xs space-y-1 mt-3">
            <p className="font-medium flex items-center gap-1.5">
              <Info className="h-3.5 w-3.5" />
              Cache Terminology
            </p>
            <p><span className="font-medium">Cache Read</span> — tokens served from cache (fast, cheap).</p>
            <p><span className="font-medium">Cache Write</span> — tokens written to cache for future reuse.</p>
            <p><span className="font-medium">Uncached</span> — tokens processed from scratch each turn.</p>
            <p>A higher hit ratio means lower latency and cost.</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
