import { useEffect, useMemo, useState } from 'react'
import type { AgentActivityObservation } from '@/types/agentTeams'
import { fetchAgentTeamActivity } from './api'

type Snapshot = { presetId: number; expiresAt: number; slots: AgentActivityObservation[] }

/** One shared poll per selected team. A cached working state never lives forever. */
export function useAgentActivity(presetId: number | null) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [snapshotSelection, setSnapshotSelection] = useState(presetId)
  const [now, setNow] = useState(() => performance.now())
  // Reset during selection reconciliation, before committing a new view. This
  // also invalidates A's cache for an A -> B -> A switch before B replies.
  if (snapshotSelection !== presetId) {
    setSnapshotSelection(presetId)
    setSnapshot(null)
  }

  useEffect(() => {
    if (presetId === null) return
    let disposed = false
    let request: AbortController | null = null
    const poll = async () => {
      if (disposed || document.visibilityState !== 'visible' || request) return
      const controller = new AbortController()
      request = controller
      const timeout = window.setTimeout(() => controller.abort(), 4_000)
      try {
        const response = await fetchAgentTeamActivity(presetId, controller.signal)
        if (disposed || controller.signal.aborted) return
        const remaining = Date.parse(response.valid_until) - Date.now()
        if (response.preset_id !== presetId || !Number.isFinite(remaining) || remaining <= 0) {
          throw new Error('Activity observation expired')
        }
        setSnapshot({ presetId, expiresAt: performance.now() + Math.min(remaining, 15_000), slots: response.slots })
        setNow(performance.now())
      } catch {
        if (!disposed) setSnapshot(null)
      } finally {
        window.clearTimeout(timeout)
        if (request === controller) request = null
      }
    }
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') {
        request?.abort()
        setSnapshot(null)
      } else {
        void poll()
      }
    }
    void poll()
    const interval = window.setInterval(() => { void poll() }, 5_000)
    const expiry = window.setInterval(() => setNow(performance.now()), 1_000)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      disposed = true
      request?.abort()
      window.clearInterval(interval)
      window.clearInterval(expiry)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [presetId])

  return useMemo(() => {
    if (snapshotSelection !== presetId || !snapshot || snapshot.presetId !== presetId || now >= snapshot.expiresAt) {
      return new Map<number, AgentActivityObservation>()
    }
    return new Map(snapshot.slots.map((slot) => [slot.slot_id, slot]))
  }, [now, presetId, snapshot, snapshotSelection])
}
