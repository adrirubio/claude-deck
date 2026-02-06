export interface ConfigFile {
  path: string
  scope: 'user' | 'project' | 'managed'
  exists: boolean
  content?: Record<string, any>
}

export interface ConfigFileListResponse {
  files: ConfigFile[]
}

export interface MergedConfig {
  settings: Record<string, any>
  mcp_servers: Record<string, any>
  hooks: Record<string, any[]>
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
  settings: Record<string, any>
  project_path?: string
}

export interface SettingsUpdateResponse {
  success: boolean
  message: string
  path: string
}

export interface ScopedSettingsResponse {
  settings: Record<string, any>
  scope: SettingsScope
}

// Resolved config types for scope management
export interface ResolvedSettingValue {
  effective_value: any
  source_scope: 'managed' | 'local' | 'project' | 'user'
  values_by_scope: Record<string, any>
}

export interface ScopeInfo {
  settings: Record<string, any>
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
    managed: Record<string, any>
    user: Record<string, any>
    project: Record<string, any>
    local: Record<string, any>
  }
}
