import { useState, useEffect, useCallback, useRef } from 'react'
import type { AgentProviderId } from '@/types/providers'
import type { CCSession } from './types'
import { fetchCCSessions } from './api'

const POLL_INTERVAL = 5000

export function useCCSessions(provider?: AgentProviderId) {
  const [sessions, setSessions] = useState<CCSession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await fetchCCSessions(provider)
      setSessions(data.sessions)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch sessions')
    } finally {
      setLoading(false)
    }
  }, [provider])

  useEffect(() => {
    refresh()
    intervalRef.current = setInterval(refresh, POLL_INTERVAL)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [refresh])

  return { sessions, loading, error, refresh }
}
