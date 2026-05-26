export type AgentProviderId = 'claude-code' | 'codex-cli'

export interface AgentProviderCapabilities {
  config: boolean
  sessions: boolean
  spawn: boolean
  resume: boolean
  fork: boolean
  mcp: boolean
  plugins: boolean
  permissions: boolean
  commands: boolean
  agents: boolean
  skills: boolean
  hooks: boolean
  memory: boolean
  output_styles: boolean
  statusline: boolean
  usage: boolean
  context: boolean
  doctor: boolean
  backup: boolean
}

export type AgentProviderCapabilityState = 'supported' | 'read_only' | 'write_capable' | 'unsupported' | 'unknown'

export interface AgentProviderCapabilityDetail {
  state: AgentProviderCapabilityState
  label: string
  reason?: string
}

export interface AgentProviderStatus {
  id: AgentProviderId
  display_name: string
  binary_name: string
  installed: boolean
  binary_path: string | null
  version: string | null
  capabilities: AgentProviderCapabilities
  capability_matrix: Partial<Record<keyof AgentProviderCapabilities, AgentProviderCapabilityDetail>>
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

export interface CodexConfigSummary {
  model?: string
  model_reasoning_effort?: string
  profile?: string
  sandbox_mode?: string
  approval_policy?: string
  search?: boolean
  strict_config?: boolean
  no_alt_screen?: boolean
  projects: Record<string, { trust_level?: string }>
  profiles: Record<string, unknown>
  features: Record<string, boolean>
}

export interface CodexConfigResponse {
  provider: 'codex-cli'
  path: string
  exists: boolean
  parse_error: string | null
  summary: CodexConfigSummary
}

export interface CodexConfigUpdateRequest {
  settings?: Record<string, string | boolean | null>
  features?: Record<string, boolean | null>
}

export interface CodexMcpInventoryResponse {
  provider: 'codex-cli'
  provider_display_name: string
  exit_code: number
  servers: unknown
  parse_error: string | null
  stderr: string
  raw_stdout: string
}

export interface CodexMcpAddRequest {
  name: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  bearer_token_env_var?: string
}

export interface CodexMcpMutationResponse {
  provider: 'codex-cli'
  provider_display_name: string
  name: string
  stdout: string
  stderr: string
  exit_code: number
}

export interface CodexPluginInventoryRow {
  name: string
  status?: string
  version?: string
  path?: string
}

export interface CodexPluginInventoryResponse {
  provider: 'codex-cli'
  provider_display_name: string
  exit_code: number
  plugins: CodexPluginInventoryRow[]
  stderr: string
  raw_stdout: string
}
