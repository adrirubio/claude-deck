/**
 * Utility functions for usage display formatting
 */

/**
 * Format a number with appropriate suffix (K, M, B)
 */
export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000_000) {
    return `${(tokens / 1_000_000_000).toFixed(1)}B`
  }
  if (tokens >= 1_000_000) {
    return `${(tokens / 1_000_000).toFixed(1)}M`
  }
  if (tokens >= 1_000) {
    return `${(tokens / 1_000).toFixed(1)}K`
  }
  return tokens.toLocaleString()
}

/**
 * Format cost as USD with appropriate precision
 */
export function formatCost(cost: number): string {
  if (cost >= 1000) {
    return `$${cost.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }
  if (cost >= 100) {
    return `$${cost.toFixed(2)}`
  }
  if (cost >= 1) {
    return `$${cost.toFixed(3)}`
  }
  return `$${cost.toFixed(4)}`
}

/**
 * Format date string (YYYY-MM-DD) to a more readable format
 */
export function formatDate(dateStr: string): string {
  const date = new Date(dateStr + 'T00:00:00')
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  })
}

/**
 * Format month string (YYYY-MM) to a more readable format
 */
export function formatMonth(monthStr: string): string {
  const [year, month] = monthStr.split('-')
  const date = new Date(parseInt(year), parseInt(month) - 1)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    year: 'numeric',
  })
}

/**
 * Format ISO timestamp to readable date/time
 */
export function formatTimestamp(isoString: string): string {
  const date = new Date(isoString)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/**
 * Get relative time string (e.g., "2 hours ago")
 */
export function getRelativeTime(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (days > 0) return `${days}d ago`
  if (hours > 0) return `${hours}h ago`
  if (minutes > 0) return `${minutes}m ago`
  return 'just now'
}

/**
 * Model colors for consistent chart coloring
 */
export const MODEL_COLORS: Record<string, string> = {
  'claude-sonnet-4-20250514': 'hsl(var(--chart-1))',
  'claude-opus-4-20250514': 'hsl(var(--chart-2))',
  'claude-3-5-sonnet-20241022': 'hsl(var(--chart-3))',
  'claude-3-5-haiku-20241022': 'hsl(var(--chart-4))',
  'claude-3-opus-20240229': 'hsl(var(--chart-5))',
  default: 'hsl(var(--muted-foreground))',
}

export function getModelColor(model: string): string {
  return MODEL_COLORS[model] || MODEL_COLORS.default
}

/**
 * Shorten model name for display
 */
export function shortenModelName(model: string): string {
  return model
    .replace('claude-', '')
    .replace('-20250514', '')
    .replace('-20241022', '')
    .replace('-20240229', '')
}
