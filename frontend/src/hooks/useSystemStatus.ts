import { useState, useEffect, useRef, useCallback } from 'react'
import { apiClient } from '@/lib/api'
import { usePresenceWebSocket } from '@/hooks/usePresenceWebSocket'
import type { SystemStatusResponse } from '@/types/status'

interface SystemStatus {
  claudeCodeVersion: string | null
  activeSessions: number
}

function parseStatus(res: SystemStatusResponse): SystemStatus {
  return {
    claudeCodeVersion: res.claude_code_version,
    activeSessions: res.active_sessions,
  }
}

const DEBOUNCE_MS = 500

export function useSystemStatus() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchStatus = useCallback(() => {
    apiClient<SystemStatusResponse>('status').then((res) => {
      setStatus(parseStatus(res))
    }).catch(() => { /* badges just won't show */ })
  }, [])

  const debouncedFetch = useCallback(() => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(fetchStatus, DEBOUNCE_MS)
  }, [fetchStatus])

  const onSessionUpdate = useCallback(() => debouncedFetch(), [debouncedFetch])
  const onSessionRemove = useCallback(() => debouncedFetch(), [debouncedFetch])
  const onSessionsCleared = useCallback(() => { debouncedFetch() }, [debouncedFetch])

  usePresenceWebSocket({
    onSessionUpdate,
    onSessionRemove,
    onSessionsCleared,
    enabled: true,
  })

  useEffect(() => {
    fetchStatus()
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    }
  }, [fetchStatus])

  return status
}
