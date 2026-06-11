import { useState, useEffect, useCallback } from 'react'
import { apiClient } from '@/lib/api'
import type { InstanceIdentity, SystemStatusResponse } from '@/types/status'

interface SystemStatus {
  claudeCodeVersion: string | null
  activeSessions: number
  providers: SystemStatusResponse['providers']
  instance: InstanceIdentity | null
}

function parseStatus(res: SystemStatusResponse): SystemStatus {
  return {
    claudeCodeVersion: res.claude_code_version,
    activeSessions: res.active_sessions,
    providers: res.providers ?? {},
    instance: res.instance ?? null,
  }
}

const POLL_INTERVAL_MS = 30_000 // 30 seconds — much cheaper than a permanent WebSocket

export function useSystemStatus() {
  const [status, setStatus] = useState<SystemStatus | null>(null)

  const fetchStatus = useCallback(() => {
    apiClient<SystemStatusResponse>('status').then((res) => {
      setStatus(parseStatus(res))
    }).catch(() => {
      setStatus(null)
    })
  }, [])

  useEffect(() => {
    fetchStatus()
    const timer = setInterval(fetchStatus, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [fetchStatus])

  return status
}
