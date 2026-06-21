import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useProviders } from '@/hooks/useProviders'
import type { AgentProviderId, AgentProviderStatus } from '@/types/providers'

interface ProviderContextValue {
  providers: AgentProviderStatus[]
  loading: boolean
  error: string | null
  selectedProviderId: AgentProviderId
  selectedProvider: AgentProviderStatus | null
  setSelectedProviderId: (providerId: AgentProviderId) => void
  refreshProviders: () => void
}

const DEFAULT_PROVIDER: AgentProviderId = 'claude-code'
const STORAGE_KEY = 'claude-deck:selected-provider'

const ProviderContext = createContext<ProviderContextValue | undefined>(undefined)

function readStoredProvider(): AgentProviderId {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'codex-cli' || stored === 'claude-code' || stored === 'copilot-cli'
    ? stored
    : DEFAULT_PROVIDER
}

export function ProviderProvider({ children }: { children: ReactNode }) {
  const { providers, loading, error, refresh } = useProviders()
  const [selectedProviderId, setSelectedProviderIdState] = useState<AgentProviderId>(readStoredProvider)

  useEffect(() => {
    if (providers.length === 0) return

    const installed = providers.filter((provider) => provider.installed)
    const selectedExists = providers.some((provider) => provider.id === selectedProviderId)
    if (!selectedExists) {
      setSelectedProviderIdState(DEFAULT_PROVIDER)
      return
    }
    if (installed.length === 1 && selectedProviderId !== installed[0].id) {
      setSelectedProviderIdState(installed[0].id)
    }
  }, [providers, selectedProviderId])

  const setSelectedProviderId = useCallback((providerId: AgentProviderId) => {
    window.localStorage.setItem(STORAGE_KEY, providerId)
    setSelectedProviderIdState(providerId)
  }, [])

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedProviderId) ?? null,
    [providers, selectedProviderId],
  )

  const value = useMemo<ProviderContextValue>(() => ({
    providers,
    loading,
    error,
    selectedProviderId,
    selectedProvider,
    setSelectedProviderId,
    refreshProviders: refresh,
  }), [providers, loading, error, selectedProviderId, selectedProvider, setSelectedProviderId, refresh])

  return (
    <ProviderContext.Provider value={value}>
      {children}
    </ProviderContext.Provider>
  )
}

export function useProviderContext() {
  const context = useContext(ProviderContext)
  if (!context) {
    throw new Error('useProviderContext must be used within ProviderProvider')
  }
  return context
}
