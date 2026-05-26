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

export interface CodexConfigSummary {
  model?: string
  model_reasoning_effort?: string
  profile?: string
  profile_v2?: string
  sandbox_mode?: string
  approval_policy?: string
  search?: boolean
  strict_config?: boolean
  no_alt_screen?: boolean
  projects: Record<string, { trust_level?: string }>
  profiles: Record<string, unknown>
  features: Record<string, boolean>
}

export interface CodexProfileOverride {
  key: string
  base?: unknown
  value: unknown
}

export interface CodexProfileSource {
  name: string
  source: 'inline' | 'file' | string
  path: string | null
  exists: boolean
  parse_error: string | null
  summary: Record<string, unknown>
  overrides: CodexProfileOverride[]
}

export interface CodexMissingProfileReference {
  name: string
  reference: 'profile' | 'profile_v2' | string
  expected_file: string | null
  unsafe_reference: boolean
}

export interface CodexMalformedProfile {
  name: string
  path: string | null
  parse_error: string
}

export interface CodexProfileResolution {
  active_profile: string | null
  active_profile_v2: string | null
  resolution_order: string[]
  base_summary: Record<string, unknown>
  profiles: CodexProfileSource[]
  active_sources: CodexProfileSource[]
  missing_references: CodexMissingProfileReference[]
  malformed_profiles: CodexMalformedProfile[]
  effective_summary: Record<string, unknown>
}

export interface CodexConfigResponse {
  provider: 'codex-cli'
  path: string
  exists: boolean
  parse_error: string | null
  summary: CodexConfigSummary
  profile_resolution: CodexProfileResolution | null
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
