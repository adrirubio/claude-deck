import { useCallback, useEffect, useState } from 'react'
import { apiClient } from '@/lib/api'
import type {
  AgentProviderId,
  AgentProviderStatus,
  CodexConfigUpdateRequest,
  ProviderDoctorResponse,
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

export async function updateCodexConfig(request: CodexConfigUpdateRequest): Promise<unknown> {
  return apiClient('codex-config', {
    method: 'PATCH',
    body: JSON.stringify(request),
  })
}
