import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import type { ContentCategory } from '@/types/context'

interface ContentBreakdownChartProps {
  categories: ContentCategory[]
}

const chartConfig = {
  estimated_tokens: {
    label: 'Estimated Tokens',
    color: 'hsl(217, 91%, 60%)',
  },
} satisfies ChartConfig

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

export function ContentBreakdownChart({ categories }: ContentBreakdownChartProps) {
  if (categories.length === 0) {
    return null
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Content Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="aspect-[2/1] w-full">
          <BarChart
            data={categories}
            layout="vertical"
            margin={{ top: 5, right: 10, left: 10, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" tickFormatter={formatTokens} fontSize={11} />
            <YAxis
              type="category"
              dataKey="category"
              width={120}
              fontSize={11}
              tickLine={false}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  formatter={(value) => formatTokens(Number(value))}
                />
              }
            />
            <Bar
              dataKey="estimated_tokens"
              fill="var(--color-estimated_tokens)"
              radius={[0, 4, 4, 0]}
            />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
