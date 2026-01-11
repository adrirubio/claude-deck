import { useMemo } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid } from 'recharts'
import type { DailyUsage } from '@/types/usage'
import { formatDate, formatCost } from './utils'

interface CostChartProps {
  data: DailyUsage[]
  loading: boolean
}

const chartConfig = {
  cost: {
    label: 'Daily Cost',
    color: 'hsl(var(--chart-1))',
  },
} satisfies ChartConfig

export function CostChart({ data, loading }: CostChartProps) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map(d => ({
        date: formatDate(d.date),
        fullDate: d.date,
        cost: d.total_cost,
      }))
  }, [data])

  // Calculate total and average
  const stats = useMemo(() => {
    if (chartData.length === 0) return { total: 0, avg: 0, max: 0 }
    const total = chartData.reduce((sum, d) => sum + d.cost, 0)
    const max = Math.max(...chartData.map(d => d.cost))
    return {
      total,
      avg: total / chartData.length,
      max,
    }
  }, [chartData])

  if (loading && chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Cost Over Time</CardTitle>
          <CardDescription>Loading...</CardDescription>
        </CardHeader>
        <CardContent className="h-[250px] flex items-center justify-center text-muted-foreground">
          Loading chart data...
        </CardContent>
      </Card>
    )
  }

  if (chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Cost Over Time</CardTitle>
          <CardDescription>Daily cost trend</CardDescription>
        </CardHeader>
        <CardContent className="h-[250px] flex items-center justify-center text-muted-foreground">
          No usage data available
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cost Over Time</CardTitle>
        <CardDescription>
          Total: {formatCost(stats.total)} | Avg: {formatCost(stats.avg)}/day | Peak: {formatCost(stats.max)}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[250px] w-full">
          <AreaChart data={chartData} accessibilityLayer>
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
              tickFormatter={(value) => formatCost(value)}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(label, payload) => {
                    const item = payload?.[0]?.payload
                    return item?.fullDate || label
                  }}
                  formatter={(value) => formatCost(value as number)}
                />
              }
            />
            <Area
              type="monotone"
              dataKey="cost"
              stroke="var(--color-cost)"
              fill="var(--color-cost)"
              fillOpacity={0.3}
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
