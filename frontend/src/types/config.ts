export type ConfigValue = string | number | boolean | null | ConfigValue[] | { [key: string]: ConfigValue }

export interface ConfigFile {
  path: string
  scope: 'user' | 'project' | 'managed'
  exists: boolean
  content?: Record<string, ConfigValue>
}

export interface ConfigFileListResponse {
  files: ConfigFile[]
}

export interface MergedConfig {
  settings: Record<string, ConfigValue>
  mcp_servers: Record<string, Record<string, ConfigValue>>
  hooks: Record<string, Record<string, ConfigValue>[]>
  permissions: {
    allow: string[]
    deny: string[]
  }
  commands: string[]
  agents: string[]
}

export interface RawFileContent {
  path: string
  content: string
  exists: boolean
}

export interface DashboardStats {
  configFileCount: number
  mcpServerCount: number
  commandCount: number
  agentCount: number
}

export type SettingsScope = 'user' | 'user_local' | 'project' | 'local' | 'managed'

export interface SettingsUpdateRequest {
  scope: SettingsScope
  settings: Record<string, ConfigValue>
  project_path?: string
}

export interface SettingsUpdateResponse {
  success: boolean
  message: string
  path: string
}

export interface ScopedSettingsResponse {
  settings: Record<string, ConfigValue>
  scope: SettingsScope
}

// Resolved config types for scope management
export interface ResolvedSettingValue {
  effective_value: ConfigValue
  source_scope: 'managed' | 'local' | 'project' | 'user'
  values_by_scope: Record<string, ConfigValue>
}

export interface ScopeInfo {
  settings: Record<string, ConfigValue>
  path: string | null
  exists: boolean
  readonly: boolean
}

export interface ResolvedConfigResponse {
  resolved: Record<string, ResolvedSettingValue>
  scopes: {
    managed: ScopeInfo
    user: ScopeInfo
    project: ScopeInfo
    local: ScopeInfo
  }
}

export interface AllScopedSettingsResponse {
  scopes: {
    managed: Record<string, ConfigValue>
    user: Record<string, ConfigValue>
    project: Record<string, ConfigValue>
    local: Record<string, ConfigValue>
  }
}
