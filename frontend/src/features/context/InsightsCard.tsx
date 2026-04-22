import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { AlertTriangle, AlertCircle, Info } from 'lucide-react'
import type { ContextInsight, InsightSeverity } from '@/types/context'

interface InsightsCardProps {
  insights: ContextInsight[]
  showHelp?: boolean
}

const SEVERITY_STYLES: Record<InsightSeverity, { border: string; bg: string; text: string; Icon: typeof Info }> = {
  info: {
    border: 'border-blue-500/30',
    bg: 'bg-blue-500/5',
    text: 'text-blue-600 dark:text-blue-400',
    Icon: Info,
  },
  warning: {
    border: 'border-amber-500/40',
    bg: 'bg-amber-500/5',
    text: 'text-amber-600 dark:text-amber-400',
    Icon: AlertTriangle,
  },
  critical: {
    border: 'border-red-500/40',
    bg: 'bg-red-500/5',
    text: 'text-red-600 dark:text-red-400',
    Icon: AlertCircle,
  },
}

export function InsightsCard({ insights, showHelp }: InsightsCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Insights</CardTitle>
        {showHelp && (
          <CardDescription>
            Heuristic observations about this session — repeated reads, dominant files, tool-result bloat, near-limit warnings.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        {insights.length === 0 ? (
          <p className="text-sm text-muted-foreground">No issues detected.</p>
        ) : (
          insights.map((insight) => {
            const style = SEVERITY_STYLES[insight.severity]
            const Icon = style.Icon
            return (
              <div
                key={insight.rule_id}
                className={`flex gap-3 rounded-md border p-3 text-sm ${style.border} ${style.bg}`}
              >
                <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${style.text}`} />
                <p className="leading-relaxed">{insight.message}</p>
              </div>
            )
          })
        )}
        <p className="text-[11px] text-muted-foreground pt-2 leading-relaxed">
          Estimates based on JSONL content; token counts are approximate. Reflects what the
          session has fed the model — not necessarily what&apos;s in context right now after
          compaction.
        </p>
      </CardContent>
    </Card>
  )
}
