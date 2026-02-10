import { useCallback } from 'react'
import { apiClient, buildEndpoint } from '@/lib/api'
import { useProjectContext } from '@/contexts/ProjectContext'
import type {
  RegistrySearchResponse,
  RegistryInstallRequest,
  RegistryInstallResponse,
} from '@/types/registry'

export function useMCPRegistryApi() {
  const { activeProject } = useProjectContext()

  const searchServers = useCallback(
    async (query?: string, limit?: number, cursor?: string) => {
      const endpoint = buildEndpoint('mcp/registry/search', {
        q: query || undefined,
        limit,
        cursor,
      })
      return apiClient<RegistrySearchResponse>(endpoint)
    },
    []
  )

  const getServerDetail = useCallback(async (serverName: string, version = 'latest') => {
    return apiClient<Record<string, unknown>>(
      `mcp/registry/servers/${encodeURIComponent(serverName)}/versions/${version}`
    )
  }, [])

  const getServerVersions = useCallback(async (serverName: string) => {
    return apiClient<Record<string, unknown>>(
      `mcp/registry/servers/${encodeURIComponent(serverName)}/versions`
    )
  }, [])

  const installServer = useCallback(
    async (request: RegistryInstallRequest) => {
      const endpoint = buildEndpoint('mcp/registry/install', {
        project_path: activeProject?.path,
      })
      return apiClient<RegistryInstallResponse>(endpoint, {
        method: 'POST',
        body: JSON.stringify(request),
      })
    },
    [activeProject?.path]
  )

  return { searchServers, getServerDetail, getServerVersions, installServer }
}
