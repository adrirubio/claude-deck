import { BarChart, Bar, ResponsiveContainer } from 'recharts'

interface ActivitySparklineProps {
  buckets: number[]
}

export function ActivitySparkline({ buckets }: ActivitySparklineProps) {
  const data = buckets.map((value, i) => ({ i, v: value }))

  return (
    <div className="h-5 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <Bar
            dataKey="v"
            fill="hsl(var(--primary) / 0.5)"
            radius={[1, 1, 0, 0]}
            isAnimationActive={false}
            maxBarSize={8}
            background={{ fill: 'hsl(var(--muted) / 0.3)', radius: [1, 1, 0, 0] as unknown as number }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
