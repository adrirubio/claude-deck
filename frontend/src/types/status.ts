import type { AgentProviderStatus, RuntimeEnvironmentStatus } from './providers'

export type InstanceAccent =
  | 'blue'
  | 'green'
  | 'purple'
  | 'orange'
  | 'red'
  | 'pink'
  | 'cyan'
  | 'slate'

export interface InstanceIdentity {
  id: string
  name: string
  // True only when the operator set CLAUDE_DECK_INSTANCE_NAME.
  name_configured?: boolean
  hostname: string
  short_hostname: string
  accent: InstanceAccent
  started_at: string
}

export interface SystemStatusResponse {
  claude_code_version: string | null
  active_sessions: number
  providers?: Record<string, AgentProviderStatus>
  instance?: InstanceIdentity
  environment?: RuntimeEnvironmentStatus
}
