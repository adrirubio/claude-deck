export interface FileChange {
  path: string
  op: 'created' | 'modified'
}

export interface PresenceSession {
  session_id: string
  label?: string
  project_path?: string
  status: 'active' | 'idle' | 'error' | 'stopped'
  status_text?: string
  last_narrative?: string
  last_narrative_at?: string
  modified_files?: (string | FileChange)[]
  last_user_prompt?: string
  last_command?: string
  last_command_exit?: number | null
  activity_buckets?: number[]
  total_events: number
  error_count: number
  started_at: string
  last_event_at: string
  ended_at?: string
}

export interface PresenceSessionList {
  sessions: PresenceSession[]
  total: number
  active: number
  error: number
}

export type PresenceWsMessage =
  | { type: 'session_update'; session: PresenceSession }
  | { type: 'session_remove'; session_id: string }
  | { type: 'sessions_cleared' }

export interface PresenceConfigSnippet {
  snippet: Record<string, unknown>
  instructions: string
}
