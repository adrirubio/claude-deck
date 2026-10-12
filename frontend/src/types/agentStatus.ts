/** Display facts from the backend. They grant no authority. */
export interface AgentStatus {
  session_state: 'online' | 'offline' | 'unknown'
  activity_state: 'working' | 'idle' | 'stopped' | 'unknown'
  activity_reason: string
  wake_state: 'can_wake' | 'cannot_wake' | 'unknown'
  wake_reason: string | null
  idle_since: string | null
  checked_at: string
  valid_until: string
}
