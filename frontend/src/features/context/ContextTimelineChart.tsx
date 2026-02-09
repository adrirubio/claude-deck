import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ReferenceLine,
  CartesianGrid,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import type { ContextSnapshot } from '@/types/context'

interface ContextTimelineChartProps {
  snapshots: ContextSnapshot[]
  maxTokens: number
}

const chartConfig = {
  cache_read_tokens: {
    label: 'Cache Read',
    color: 'hsl(142, 71%, 45%)',
  },
  cache_creation_tokens: {
    label: 'Cache Creation',
    color: 'hsl(47, 100%, 50%)',
  },
  input_tokens: {
    label: 'Input Tokens',
    color: 'hsl(217, 91%, 60%)',
  },
} satisfies ChartConfig

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

export function ContextTimelineChart({ snapshots, maxTokens }: ContextTimelineChartProps) {
  if (snapshots.length === 0) {
    return null
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Context Window Over Time</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="aspect-[2/1] w-full">
          <AreaChart data={snapshots} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="turn_number"
              label={{ value: 'Turn', position: 'insideBottom', offset: -5 }}
              fontSize={11}
            />
            <YAxis
              tickFormatter={formatTokens}
              fontSize={11}
              width={50}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(value) => `Turn ${value}`}
                />
              }
            />
            <ReferenceLine
              y={maxTokens}
              stroke="hsl(0, 84%, 60%)"
              strokeDasharray="6 3"
              label={{ value: 'Limit', position: 'right', fontSize: 10 }}
            />
            <Area
              type="monotone"
              dataKey="cache_read_tokens"
              stackId="1"
              fill="var(--color-cache_read_tokens)"
              stroke="var(--color-cache_read_tokens)"
              fillOpacity={0.6}
            />
            <Area
              type="monotone"
              dataKey="cache_creation_tokens"
              stackId="1"
              fill="var(--color-cache_creation_tokens)"
              stroke="var(--color-cache_creation_tokens)"
              fillOpacity={0.6}
            />
            <Area
              type="monotone"
              dataKey="input_tokens"
              stackId="1"
              fill="var(--color-input_tokens)"
              stroke="var(--color-input_tokens)"
              fillOpacity={0.6}
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
