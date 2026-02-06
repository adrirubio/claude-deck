export interface ConfigFile {
  path: string
  scope: 'user' | 'project'
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

export type SettingsScope = 'user' | 'user_local' | 'project' | 'local'

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
