export type RemainingWork = {
  state: 'current' | 'historical' | 'unavailable'
  remaining: string | null
  estimate: string | null
  next_action: string | null
  reported_at: string | null
  reported_by: string | null
  source_sha: string | null
  reason: string | null
  source_url: string | null
  completed?: string | null
  assumptions?: string | null
}

export function validRemainingWork(value: unknown): value is RemainingWork {
  if (!value || typeof value !== 'object') return false
  const data = value as RemainingWork
  return ['current', 'historical', 'unavailable'].includes(data.state)
    && [data.remaining, data.estimate, data.next_action, data.reported_by]
      .every((text) => text === null || typeof text === 'string' && text.length <= 300)
    && (data.source_sha === null || typeof data.source_sha === 'string' && /^[a-f0-9]{40}$/.test(data.source_sha))
    && (data.reported_at === null || typeof data.reported_at === 'string' && Number.isFinite(Date.parse(data.reported_at)))
    && (data.state !== 'current' || Boolean(data.remaining && data.estimate && data.next_action && data.reported_at))
    && [data.completed, data.assumptions].every((text) => text === undefined || text === null || typeof text === 'string' && text.length <= 200)
}

