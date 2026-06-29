import { useCallback, useEffect, useState } from 'react'
import { apiClient } from '@/lib/api'
import type {
  AgentProviderId,
  AgentProviderStatus,
  CodexConfigUpdateRequest,
  CodexFeatureInventoryResponse,
  CodexMcpAddRequest,
  CodexMcpInventoryResponse,
  CodexMcpMutationResponse,
  CodexPluginInventoryResponse,
  CodexPluginMutationRequest,
  CodexPluginMutationResponse,
  ProviderDoctorResponse,
  ProviderLaunchOptionsResponse,
  ProvidersResponse,
} from '@/types/providers'

const POLL_INTERVAL_MS = 60_000

export function useProviders() {
  const [providers, setProviders] = useState<AgentProviderStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await apiClient<ProvidersResponse>('providers')
      setProviders(data.providers)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load providers')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [refresh])

  return { providers, loading, error, refresh }
}

export async function fetchProviderDoctor(providerId: AgentProviderId): Promise<ProviderDoctorResponse> {
  return apiClient<ProviderDoctorResponse>(`providers/${providerId}/doctor`)
}

export async function fetchProviderLaunchOptions(
  providerId: AgentProviderId
): Promise<ProviderLaunchOptionsResponse> {
  return apiClient<ProviderLaunchOptionsResponse>(`providers/${providerId}/launch-options`)
}

export async function updateCodexConfig(request: CodexConfigUpdateRequest): Promise<unknown> {
  return apiClient('codex-config', {
    method: 'PATCH',
    body: JSON.stringify(request),
  })
}

export async function fetchCodexMcpInventory(): Promise<CodexMcpInventoryResponse> {
  return apiClient<CodexMcpInventoryResponse>('providers/codex-cli/mcp')
}

export async function addCodexMcpServer(request: CodexMcpAddRequest): Promise<CodexMcpMutationResponse> {
  return apiClient<CodexMcpMutationResponse>('providers/codex-cli/mcp', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function removeCodexMcpServer(name: string): Promise<CodexMcpMutationResponse> {
  return apiClient<CodexMcpMutationResponse>(`providers/codex-cli/mcp/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}

export async function fetchCodexPluginInventory(): Promise<CodexPluginInventoryResponse> {
  return apiClient<CodexPluginInventoryResponse>('providers/codex-cli/plugins')
}

export async function fetchCodexFeatureInventory(): Promise<CodexFeatureInventoryResponse> {
  return apiClient<CodexFeatureInventoryResponse>('providers/codex-cli/features')
}

export async function installCodexPlugin(request: CodexPluginMutationRequest): Promise<CodexPluginMutationResponse> {
  return apiClient<CodexPluginMutationResponse>('providers/codex-cli/plugins', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function removeCodexPlugin(name: string): Promise<CodexPluginMutationResponse> {
  return apiClient<CodexPluginMutationResponse>(`providers/codex-cli/plugins/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}
