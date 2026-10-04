import { updateNativeMetadata, updateNativeCatalog, clearNativeCatalogs } from '@/features/native-settings/surfaceRegistry'
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { providerOperationKeys } from '@/types/providers'
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
  ProviderOperations,
} from '@/types/providers'

const POLL_INTERVAL_MS = 60_000
const CATALOG_REQUEST_DEADLINE_MS = 10_000

type CatalogState = { state: 'idle' | 'loading' | 'ready' | 'error'; catalog: ProviderOperations | null; refreshing: boolean }
type CatalogEntry = { snapshot: CatalogState; updated: number; flight?: Promise<void>; deadline?: number; retire?: () => void; expiryTimer?: ReturnType<typeof setTimeout> }
const emptyCatalog: CatalogState = { state: 'idle', catalog: null, refreshing: false }
const catalogs = new Map<AgentProviderId, CatalogEntry>()
const catalogListeners = new Set<() => void>()
const subscribeCatalog = (listener: () => void) => { catalogListeners.add(listener); return () => { catalogListeners.delete(listener) } }
const notifyCatalog = () => catalogListeners.forEach(listener => listener())
const object = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const strings = (value: unknown) => Array.isArray(value) && value.every(v => typeof v === 'string')
const stateIn = (value: unknown, states: string[]) => typeof value === 'string' && states.includes(value)
const date = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value))

// Runtime validation prevents partial, stale-schema or foreign provider data
// from becoming permissions. Native access also checks every requested adapter.
export function isProviderOperations(value: unknown, provider: AgentProviderId): value is ProviderOperations {
  if (!object(value) || value.schema_version !== 1 || value.provider !== provider || typeof value.provider_display_name !== 'string' ||
      !object(value.operations) || !object(value.native_surfaces) || !object(value.native_capabilities) || !object(value.readiness)) return false
  const operations = value.operations
  if (Object.keys(operations).length !== providerOperationKeys.length || !providerOperationKeys.every(key => {
    const op = operations[key]
    return object(op) && stateIn(op.state, ['supported', 'conditional', 'unsupported', 'unknown']) && typeof op.reason === 'string' && strings(op.conditions) && strings(op.evidence)
  })) return false
  if (!Object.values(value.native_surfaces).every(s => object(s) && typeof s.reason === 'string' && strings(s.conditions) &&
      (s.state === 'available' ? typeof s.adapter_id === 'string' && stateIn(s.access, ['read_only', 'read_write']) :
       stateIn(s.state, ['unavailable', 'unknown']) && s.adapter_id === null && s.access === 'none'))) return false
  if (!Object.values(value.native_capabilities).every(c => object(c) && stateIn(c.state, ['supported', 'read_only', 'write_capable', 'unsupported', 'unknown']) && typeof c.label === 'string')) return false
  const r = value.readiness
  if (!object(r.configuration) || !stateIn(r.configuration.state, ['ready', 'blocked', 'unknown']) || !Array.isArray(r.configuration.checks) ||
      !r.configuration.checks.every(c => object(c) && stateIn(c.state, ['ready', 'blocked', 'unknown']) && typeof c.reason === 'string' && typeof c.code === 'string' && typeof c.source === 'string') ||
      !object(r.credentials) || !stateIn(r.credentials.state, ['ready', 'blocked', 'unknown']) || typeof r.credentials.reason !== 'string' ||
      !object(r.session) || !stateIn(r.session.state, ['bound', 'offline', 'ambiguous', 'unknown']) || typeof r.session.reason !== 'string' ||
      !stateIn(r.probe_state, ['observed', 'pending', 'failed']) || !date(r.observed_at) || !(r.observation_started_at === null || date(r.observation_started_at))) return false
  // This hook reads a generic provider card, never a team/slot binding claim.
  return r.session.state === 'unknown' && ['team_id', 'slot_id', 'member_id', 'session_id', 'observed_provider'].every(key => r.session && object(r.session) && r.session[key] === null) &&
    ['cache_ttl_seconds', 'request_wait_seconds', 'aggregate_probe_seconds'].every(key => typeof r[key] === 'number' && Number.isFinite(r[key]) && r[key] > 0)
}

export function resetProviderOperations() {
  const entries = [...catalogs.values()]
  catalogs.clear() // Retire generations before aborting; late responses cannot reinstall.
  for (const entry of entries) { clearTimeout(entry.expiryTimer); entry.retire?.() }
  clearNativeCatalogs()
  notifyCatalog()
}

export function refreshProviderOperations(provider: AgentProviderId, force = true): Promise<void> {
  const current = catalogs.get(provider)
  // Wall-clock checks cover suspended tabs whose deadline timer has not run.
  if (current?.flight && Date.now() >= (current.deadline ?? 0)) current.retire?.()
  if (current?.flight) return current.flight
  if (!force && current?.snapshot.state === 'ready' && Date.now() - current.updated < POLL_INTERVAL_MS) return Promise.resolve()
  // Preserve unsaved editor state during healthy revalidation. Only an actual
  // still-valid catalog can be retained; errors and expiry revoke it outright.
  const retain = current?.snapshot.state === 'ready' && Date.now() - current.updated < POLL_INTERVAL_MS
  const entry: CatalogEntry = {
    snapshot: retain ? { ...current.snapshot, refreshing: true } : { state: 'loading', catalog: null, refreshing: true },
    updated: retain ? current.updated : 0,
  }
  clearTimeout(current?.expiryTimer)
  catalogs.set(provider, entry)
  if (!retain) updateNativeCatalog(provider)
  const expire = () => {
    clearTimeout(entry.expiryTimer)
    entry.expiryTimer = setTimeout(() => {
      if (catalogs.get(provider) === entry) notifyCatalog()
    }, Math.max(1, entry.updated + POLL_INTERVAL_MS - Date.now()))
  }
  if (retain) expire()
  const controller = new AbortController()
  entry.deadline = Date.now() + CATALOG_REQUEST_DEADLINE_MS
  let active = true
  let settled = false
  let resolveFlight!: () => void
  const flight = new Promise<void>(resolve => { resolveFlight = resolve })
  entry.flight = flight
  const finish = () => {
    if (settled) return
    settled = true
    clearTimeout(deadlineTimer)
    entry.retire = undefined
    if (catalogs.get(provider) === entry) { entry.flight = undefined; notifyCatalog() }
    resolveFlight()
  }
  const retire = () => {
    active = false // Abort is best effort; logical retirement rejects ignored/late aborts.
    controller.abort()
    clearTimeout(entry.expiryTimer)
    if (catalogs.get(provider) === entry) {
      updateNativeCatalog(provider)
      entry.updated = Date.now()
      entry.snapshot = { state: 'error', catalog: null, refreshing: false }
    }
    finish()
  }
  entry.retire = retire
  const deadlineTimer = setTimeout(retire, CATALOG_REQUEST_DEADLINE_MS)
  notifyCatalog()
  void apiClient<unknown>(`providers/${provider}/operations`, { signal: controller.signal }).then(value => {
    if (!active || catalogs.get(provider) !== entry) return
    // A timer may be throttled: never give an overdue response a new receipt TTL.
    if (Date.now() >= (entry.deadline ?? 0)) { retire(); return }
    if (!isProviderOperations(value, provider)) throw new Error('Invalid operating catalog')
    entry.updated = Date.now()
    updateNativeCatalog(provider, value) // Publish guards before children can mount/fetch.
    entry.snapshot = { state: 'ready', catalog: value, refreshing: false }
    active = false
    expire()
  }).catch(() => {
    if (active && catalogs.get(provider) === entry) retire()
  }).finally(finish)
  return flight
}

export function useProviderOperations(provider?: AgentProviderId) {
  const snapshot = useCallback(() => {
    const entry = provider ? catalogs.get(provider) : undefined
    return entry?.snapshot.state === 'ready' && Date.now() - entry.updated >= POLL_INTERVAL_MS ? emptyCatalog : entry?.snapshot ?? emptyCatalog
  }, [provider])
  const state = useSyncExternalStore(subscribeCatalog, snapshot, snapshot)
  useEffect(() => {
    if (!provider) return
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      const current = catalogs.get(provider)
      if (current?.flight && Date.now() >= (current.deadline ?? 0)) current.retire?.()
      notifyCatalog()
    }
    document.addEventListener('visibilitychange', onVisible)
    let timer: ReturnType<typeof setTimeout> | undefined
    if (state.state === 'idle') void refreshProviderOperations(provider, false)
    else if (state.state === 'error') timer = setTimeout(() => { void refreshProviderOperations(provider) }, POLL_INTERVAL_MS)
    else if (state.state === 'ready' && !state.refreshing) {
      const updated = catalogs.get(provider)?.updated ?? 0
      timer = setTimeout(() => {
        const current = catalogs.get(provider)
        if (current && Date.now() - current.updated >= POLL_INTERVAL_MS - 5_000) void refreshProviderOperations(provider)
      }, Math.max(1, updated + POLL_INTERVAL_MS - 5_000 - Date.now()))
    }
    return () => { clearTimeout(timer); document.removeEventListener('visibilitychange', onVisible) }
  }, [provider, state])
  const refresh = useCallback(() => provider ? refreshProviderOperations(provider) : Promise.resolve(), [provider])
  return { ...state, refresh }
}

export function useProviders() {
  const [providers, setProviders] = useState<AgentProviderStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await apiClient<ProvidersResponse>('providers')
      updateNativeMetadata(data.providers)
      setProviders(data.providers)
      setError(null)
    } catch (err) {
      updateNativeMetadata([])
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
