/**
 * TypeScript types for the MCP Registry API.
 * Matches the official MCP Registry v0.1 response shapes.
 */

export interface RegistryServer {
  $schema?: string
  name: string // Reverse-DNS format: "io.github.user/server-name"
  description: string
  version: string
  title?: string // Human-readable name
  icons?: RegistryIcon[]
  packages?: RegistryPackage[]
  remotes?: RegistryRemote[]
  repository?: { url: string; source: string; subfolder?: string }
  websiteUrl?: string
}

export interface RegistryIcon {
  src: string
  sizes?: string
  theme?: 'light' | 'dark'
  mimeType?: string
}

export interface RegistryPackage {
  registryType: 'npm' | 'pypi' | 'oci' | 'nuget' | 'mcpb'
  identifier: string
  version?: string
  transport: { type: 'stdio' | 'streamable-http' | 'sse' }
  runtimeHint?: string
  runtimeArguments?: RegistryArgument[]
  packageArguments?: RegistryArgument[]
  environmentVariables?: RegistryEnvVar[]
}

export interface RegistryRemote {
  type: 'streamable-http' | 'sse'
  url: string
  headers?: RegistryEnvVar[]
  variables?: Record<string, RegistryInput>
}

export interface RegistryEnvVar {
  name: string
  description?: string
  isRequired?: boolean
  isSecret?: boolean
  default?: string
  value?: string // Template value like "Bearer {api_key}"
  format?: string
  choices?: string[]
}

export interface RegistryArgument {
  type: 'positional' | 'named'
  name?: string
  value?: string
  description?: string
  isRequired?: boolean
  default?: string
  format?: string
}

export interface RegistryInput {
  description?: string
  default?: string
}

export interface RegistryMeta {
  'io.modelcontextprotocol.registry/official'?: {
    status: string
    publishedAt: string
    updatedAt: string
    isLatest: boolean
  }
}

export interface RegistryServerEntry {
  server: RegistryServer
  _meta: RegistryMeta
}

export interface RegistrySearchResponse {
  servers: RegistryServerEntry[]
  metadata: { count: number; nextCursor?: string }
}

export interface RegistryInstallRequest {
  server_name: string
  scope: 'user' | 'project'
  package_registry_type?: string
  package_identifier?: string
  package_version?: string
  package_runtime_hint?: string
  package_arguments?: Record<string, string>
  remote_type?: string
  remote_url?: string
  remote_headers?: Record<string, string>
  env_values?: Record<string, string>
}

export interface RegistryInstallResponse {
  success: boolean
  server_name: string
  config: Record<string, unknown>
  scope: string
}

/** Extract a short display name from a registry server name. */
export function getDisplayName(server: RegistryServer): string {
  if (server.title) return server.title
  const parts = server.name.split('/')
  return parts[parts.length - 1]
}

/** Get available transport options for a registry server. */
export interface TransportOption {
  kind: 'package' | 'remote'
  label: string
  description: string
  packageIndex?: number
  remoteIndex?: number
}

export function getTransportOptions(server: RegistryServer): TransportOption[] {
  const options: TransportOption[] = []

  server.packages?.forEach((pkg, i) => {
    const runtime = pkg.runtimeHint || pkg.registryType
    options.push({
      kind: 'package',
      label: `${pkg.registryType} (${runtime})`,
      description: `${pkg.identifier}${pkg.version ? `@${pkg.version}` : ''} via ${runtime}`,
      packageIndex: i,
    })
  })

  server.remotes?.forEach((remote, i) => {
    const type = remote.type === 'streamable-http' ? 'HTTP' : 'SSE'
    options.push({
      kind: 'remote',
      label: `Remote (${type})`,
      description: remote.url,
      remoteIndex: i,
    })
  })

  return options
}
