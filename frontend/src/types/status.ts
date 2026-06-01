import type { AgentProviderStatus } from './providers'

export interface SystemStatusResponse {
  claude_code_version: string | null
  active_sessions: number
  providers?: Record<string, AgentProviderStatus>
}
