import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface ProjectionsCardProps {
  avgTokensPerTurn: number
  estimatedTurnsRemaining: number
  contextZone: string
  totalTurns: number
  showHelp?: boolean
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

function getZoneBadge(zone: string) {
  const variants: Record<string, { label: string; className: string }> = {
    green: { label: 'Plenty of room', className: 'bg-green-500/10 text-green-600 border-green-500/30' },
    yellow: { label: 'Moderate usage', className: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/30' },
    orange: { label: 'Getting full', className: 'bg-orange-500/10 text-orange-600 border-orange-500/30' },
    red: { label: 'Near limit', className: 'bg-red-500/10 text-red-600 border-red-500/30' },
  }
  const v = variants[zone] || variants.green
  return <Badge variant="outline" className={v.className}>{v.label}</Badge>
}

export function ProjectionsCard({ avgTokensPerTurn, estimatedTurnsRemaining, contextZone, totalTurns, showHelp }: ProjectionsCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Projections</CardTitle>
          {getZoneBadge(contextZone)}
        </div>
        {showHelp && (
          <CardDescription>
            Estimates how many more conversation turns remain before the context window fills up, based on average token growth per turn.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <div className="text-2xl font-bold">{totalTurns}</div>
            <div className="text-xs text-muted-foreground">Turns Used</div>
          </div>
          <div>
            <div className="text-2xl font-bold">{formatTokens(avgTokensPerTurn)}</div>
            <div className="text-xs text-muted-foreground">Avg/Turn</div>
          </div>
          <div>
            <div className="text-2xl font-bold">~{estimatedTurnsRemaining}</div>
            <div className="text-xs text-muted-foreground">Turns Left</div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
