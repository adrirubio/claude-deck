import { useState, useEffect, useCallback } from 'react'
import { Search, Loader2, Globe } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { useMCPRegistryApi } from '@/hooks/useMCPRegistryApi'
import { MCPRegistryCard } from './MCPRegistryCard'
import { MCPRegistryDetailDialog } from './MCPRegistryDetailDialog'
import { MCPRegistryInstallDialog } from './MCPRegistryInstallDialog'
import type { RegistryServer, RegistryServerEntry } from '@/types/registry'

interface MCPRegistryBrowserProps {
  onInstallComplete: () => void
}

export function MCPRegistryBrowser({ onInstallComplete }: MCPRegistryBrowserProps) {
  const { searchServers } = useMCPRegistryApi()

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<RegistryServerEntry[]>([])
  const [nextCursor, setNextCursor] = useState<string | undefined>()
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Dialog state
  const [selectedServer, setSelectedServer] = useState<RegistryServer | null>(null)
  const [showDetail, setShowDetail] = useState(false)
  const [installingServer, setInstallingServer] = useState<RegistryServer | null>(null)
  const [showInstall, setShowInstall] = useState(false)

  const doSearch = useCallback(
    async (searchQuery: string, cursor?: string) => {
      const isLoadMore = !!cursor
      if (isLoadMore) {
        setLoadingMore(true)
      } else {
        setLoading(true)
        setError(null)
      }

      try {
        const response = await searchServers(searchQuery || undefined, 21, cursor)
        if (isLoadMore) {
          setResults((prev) => [...prev, ...response.servers])
        } else {
          setResults(response.servers)
        }
        setNextCursor(response.metadata.nextCursor)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to search registry')
      } finally {
        setLoading(false)
        setLoadingMore(false)
      }
    },
    [searchServers]
  )

  // Initial load
  useEffect(() => {
    doSearch('')
  }, [doSearch])

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      doSearch(query)
    }, 300)
    return () => clearTimeout(timer)
  }, [query, doSearch])

  const handleLoadMore = () => {
    if (nextCursor) {
      doSearch(query, nextCursor)
    }
  }

  const handleSelect = (server: RegistryServer) => {
    setSelectedServer(server)
    setShowDetail(true)
  }

  const handleInstall = (server: RegistryServer) => {
    setShowDetail(false)
    setInstallingServer(server)
    setShowInstall(true)
  }

  const handleInstallComplete = () => {
    setShowInstall(false)
    setInstallingServer(null)
    onInstallComplete()
  }

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search MCP servers..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-10"
          />
        </div>
        {results.length > 0 && !loading && (
          <Badge variant="secondary">{results.length} results</Badge>
        )}
      </div>

      {/* Info */}
      {!query && (
        <p className="text-sm text-muted-foreground flex items-center gap-1">
          <Globe className="h-4 w-4" />
          Browsing servers from the{" "}
          <a
            href="https://registry.modelcontextprotocol.io"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-foreground transition-colors"
          >
            MCP Registry
          </a>
        </p>
      )}

      {/* Error */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="py-4">
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Searching registry...</span>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && results.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <p className="text-muted-foreground mb-2">No servers found</p>
          <p className="text-sm text-muted-foreground">
            {query ? 'Try a different search term' : 'The registry appears to be empty'}
          </p>
        </div>
      )}

      {/* Results grid */}
      {!loading && results.length > 0 && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {results.map((entry) => (
              <MCPRegistryCard
                key={entry.server.name + entry.server.version}
                server={entry.server}
                onSelect={handleSelect}
                onInstall={handleInstall}
              />
            ))}
          </div>

          {/* Load More */}
          {nextCursor && (
            <div className="flex justify-center pt-4">
              <Button
                variant="outline"
                onClick={handleLoadMore}
                disabled={loadingMore}
              >
                {loadingMore ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Loading...
                  </>
                ) : (
                  'Load More'
                )}
              </Button>
            </div>
          )}
        </>
      )}

      {/* Detail Dialog */}
      <MCPRegistryDetailDialog
        server={selectedServer}
        open={showDetail}
        onOpenChange={(open) => {
          setShowDetail(open)
          if (!open) setSelectedServer(null)
        }}
        onInstall={handleInstall}
      />

      {/* Install Dialog */}
      <MCPRegistryInstallDialog
        server={installingServer}
        open={showInstall}
        onOpenChange={(open) => {
          setShowInstall(open)
          if (!open) setInstallingServer(null)
        }}
        onInstallComplete={handleInstallComplete}
      />
    </div>
  )
}
