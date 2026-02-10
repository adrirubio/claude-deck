interface ContextGaugeProps {
  percentage: number
  currentTokens: number
  maxTokens: number
  model: string
  showHelp?: boolean
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

function getColor(pct: number): string {
  if (pct >= 95) return '#ef4444'  // red
  if (pct >= 80) return '#f97316'  // orange
  if (pct >= 50) return '#eab308'  // yellow
  return '#22c55e'  // green
}

export function ContextGauge({ percentage, currentTokens, maxTokens, model, showHelp }: ContextGaugeProps) {
  const clampedPct = Math.min(100, Math.max(0, percentage))
  const color = getColor(clampedPct)

  // SVG semicircular arc
  const cx = 100
  const cy = 90
  const r = 70
  const startAngle = Math.PI
  const endAngle = 0
  const sweepAngle = startAngle - (startAngle - endAngle) * (clampedPct / 100)

  const bgStartX = cx + r * Math.cos(startAngle)
  const bgStartY = cy - r * Math.sin(startAngle)
  const bgEndX = cx + r * Math.cos(endAngle)
  const bgEndY = cy - r * Math.sin(endAngle)

  const arcEndX = cx + r * Math.cos(sweepAngle)
  const arcEndY = cy - r * Math.sin(sweepAngle)

  // Semicircular gauge: filled arc is at most 180°, so large-arc is always 0
  const largeArc = 0

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 110" className="w-full max-w-[240px]">
        {/* Background arc */}
        <path
          d={`M ${bgStartX} ${bgStartY} A ${r} ${r} 0 1 1 ${bgEndX} ${bgEndY}`}
          fill="none"
          stroke="currentColor"
          strokeWidth="12"
          strokeLinecap="round"
          className="text-muted/30"
        />
        {/* Value arc */}
        {clampedPct > 0 && (
          <path
            d={`M ${bgStartX} ${bgStartY} A ${r} ${r} 0 ${largeArc} 1 ${arcEndX} ${arcEndY}`}
            fill="none"
            stroke={color}
            strokeWidth="12"
            strokeLinecap="round"
          />
        )}
        {/* Center text */}
        <text x={cx} y={cy - 10} textAnchor="middle" className="fill-foreground text-2xl font-bold" fontSize="24">
          {clampedPct.toFixed(0)}%
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" className="fill-muted-foreground" fontSize="10">
          {formatTokens(currentTokens)} / {formatTokens(maxTokens)}
        </text>
      </svg>
      <span className="text-xs text-muted-foreground mt-1">{model}</span>
      {showHelp && (
        <p className="text-xs text-muted-foreground mt-2 text-center max-w-[240px]">
          How much of the model's memory is used. Green is healthy; red means the session may need to compact or reset soon.
        </p>
      )}
    </div>
  )
}
