import { useMemo } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts'
import type { DailyUsage } from '@/types/usage'
import { formatDate, formatCost, formatTokens } from './utils'

interface DailyUsageChartProps {
  data: DailyUsage[]
  loading: boolean
}

const chartConfig = {
  input_tokens: {
    label: 'Input',
    color: 'hsl(var(--chart-1))',
  },
  output_tokens: {
    label: 'Output',
    color: 'hsl(var(--chart-2))',
  },
  cache_read_tokens: {
    label: 'Cache Read',
    color: 'hsl(var(--chart-3))',
  },
} satisfies ChartConfig

export function DailyUsageChart({ data, loading }: DailyUsageChartProps) {
  const chartData = useMemo(() => {
    // Sort ascending for chart (oldest first)
    return [...data]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map(d => ({
        date: formatDate(d.date),
        fullDate: d.date,
        input_tokens: d.input_tokens,
        output_tokens: d.output_tokens,
        cache_read_tokens: d.cache_read_tokens,
        total_cost: d.total_cost,
      }))
  }, [data])

  if (loading && chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Daily Usage</CardTitle>
          <CardDescription>Loading...</CardDescription>
        </CardHeader>
        <CardContent className="h-[300px] flex items-center justify-center text-muted-foreground">
          Loading chart data...
        </CardContent>
      </Card>
    )
  }

  if (chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Daily Usage</CardTitle>
          <CardDescription>Token usage by day</CardDescription>
        </CardHeader>
        <CardContent className="h-[300px] flex items-center justify-center text-muted-foreground">
          No usage data available
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Daily Usage</CardTitle>
        <CardDescription>
          Token usage by day ({chartData.length} days)
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[300px] w-full">
          <BarChart data={chartData} accessibilityLayer>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="date"
              tickLine={false}
              tickMargin={10}
              axisLine={false}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => formatTokens(value)}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(label, payload) => {
                    const item = payload?.[0]?.payload
                    return (
                      <div>
                        <div>{item?.fullDate || label}</div>
                        <div className="text-xs text-muted-foreground">
                          Cost: {formatCost(item?.total_cost || 0)}
                        </div>
                      </div>
                    )
                  }}
                />
              }
            />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar
              dataKey="input_tokens"
              stackId="tokens"
              fill="var(--color-input_tokens)"
              radius={[0, 0, 0, 0]}
            />
            <Bar
              dataKey="output_tokens"
              stackId="tokens"
              fill="var(--color-output_tokens)"
              radius={[0, 0, 0, 0]}
            />
            <Bar
              dataKey="cache_read_tokens"
              stackId="tokens"
              fill="var(--color-cache_read_tokens)"
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
