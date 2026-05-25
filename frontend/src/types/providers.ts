export type AgentProviderId = 'claude-code' | 'codex-cli'

export interface AgentProviderCapabilities {
  sessions: boolean
  spawn: boolean
  resume: boolean
  fork: boolean
  mcp: boolean
  plugins: boolean
  commands: boolean
  agents: boolean
  skills: boolean
  hooks: boolean
  memory: boolean
  usage: boolean
  context: boolean
  doctor: boolean
}

export interface AgentProviderStatus {
  id: AgentProviderId
  display_name: string
  binary_name: string
  installed: boolean
  binary_path: string | null
  version: string | null
  capabilities: AgentProviderCapabilities
  config_paths: Record<string, string>
}

export interface ProvidersResponse {
  providers: AgentProviderStatus[]
  count: number
}

export type ProviderDoctorStatus = 'ok' | 'warn' | 'error' | 'unknown' | string

export interface ProviderDoctorCheck {
  id: string
  category: string
  status: ProviderDoctorStatus
  summary: string
  details?: Record<string, unknown>
  remediation?: string | null
  durationMs?: number
}

export interface ProviderDoctorReport {
  schemaVersion?: number
  generatedAt?: string
  overallStatus?: ProviderDoctorStatus
  codexVersion?: string
  checks?: Record<string, ProviderDoctorCheck>
}

export interface ProviderDoctorResponse {
  provider: AgentProviderId
  provider_display_name: string
  exit_code: number
  report: ProviderDoctorReport | null
  parse_error: string | null
  stderr: string
}
