import { useEffect, useRef, useState, useCallback } from 'react'
import type { PresenceSession, PresenceWsMessage } from '@/types/presence'
import { buildPresenceWsUrl } from '@/features/presence/api'

interface UsePresenceWebSocketOptions {
  onSessionUpdate: (session: PresenceSession) => void
  onSessionRemove: (sessionId: string) => void
  onSessionsCleared?: () => void
  enabled: boolean
}

export function usePresenceWebSocket(options: UsePresenceWebSocketOptions) {
  const { onSessionUpdate, onSessionRemove, onSessionsCleared, enabled } = options
  const [connected, setConnected] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1000)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const url = buildPresenceWsUrl()
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setReconnecting(false)
      backoffRef.current = 1000
    }

    ws.onmessage = (event) => {
      try {
        const msg: PresenceWsMessage = JSON.parse(event.data)
        if (msg.type === 'session_update') {
          onSessionUpdate(msg.session)
        } else if (msg.type === 'session_remove') {
          onSessionRemove(msg.session_id)
        } else if (msg.type === 'sessions_cleared') {
          onSessionsCleared?.()
        }
      } catch {
        // Ignore non-JSON messages
      }
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
    }

    ws.onerror = () => {
      // onclose will fire after onerror
    }
  }, [onSessionUpdate, onSessionRemove, onSessionsCleared])

  useEffect(() => {
    if (!enabled) return

    connect()

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      setConnected(false)
      setReconnecting(false)
    }
  }, [enabled, connect])

  // Reconnection logic in a separate effect watching `connected`
  useEffect(() => {
    if (!enabled || connected) return

    // Set reconnecting state and schedule reconnect
    setReconnecting(true)
    const delay = Math.min(backoffRef.current, 30000)
    reconnectTimerRef.current = setTimeout(() => {
      backoffRef.current = delay * 2
      connect()
    }, delay)

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
    }
  }, [enabled, connected, connect])

  return { connected, reconnecting }
}
