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
