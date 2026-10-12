import { Navigate, useLocation } from 'react-router-dom'
import { useProviderContext } from '@/contexts/ProviderContext'

/**
 * Old unlisted native routes (/config, /mcp, /sessions/... and others) open the matching
 * Harnesses page. The harness is the saved preference when it is a known harness, else the
 * first installed one, else the first listed one. The path is built only from a harness id in
 * the harness list. The path, the query string (?project=) and the hash are kept.
 */
export function LegacyNativeRedirect() {
  const { providers, loading, selectedProviderId } = useProviderContext()
  const { pathname, search, hash } = useLocation()

  if (loading) return <p role="status">Loading harness registry…</p>
  const target = providers.find((provider) => provider.id === selectedProviderId)
    ?? providers.find((provider) => provider.installed)
    ?? providers[0]
  if (!target) {
    return (
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">No harness available</h2>
        <p>Deck found no harness for <code>{pathname}</code>. Open Harnesses to see what is installed.</p>
      </section>
    )
  }
  return <Navigate replace to={`/harnesses/${encodeURIComponent(target.id)}${pathname}${search}${hash}`} />
}
