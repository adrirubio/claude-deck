import { Package, Globe, GitBranch, Download } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CLICKABLE_CARD } from '@/lib/constants'
import type { RegistryServer } from '@/types/registry'
import { getDisplayName } from '@/types/registry'

interface MCPRegistryCardProps {
  server: RegistryServer
  onSelect: (server: RegistryServer) => void
  onInstall: (server: RegistryServer) => void
}

function getPackageTypeBadges(server: RegistryServer) {
  const badges: { label: string; variant: 'default' | 'secondary' | 'outline' }[] = []
  const seen = new Set<string>()

  server.packages?.forEach((pkg) => {
    if (!seen.has(pkg.registryType)) {
      seen.add(pkg.registryType)
      badges.push({ label: pkg.registryType, variant: 'secondary' })
    }
  })

  server.remotes?.forEach((remote) => {
    const type = remote.type === 'streamable-http' ? 'http' : remote.type
    if (!seen.has(type)) {
      seen.add(type)
      badges.push({ label: type, variant: 'outline' })
    }
  })

  return badges
}

function shortenRepoUrl(url: string): string {
  try {
    const parsed = new URL(url)
    return parsed.pathname.replace(/^\//, '').replace(/\.git$/, '')
  } catch {
    return url
  }
}

export function MCPRegistryCard({ server, onSelect, onInstall }: MCPRegistryCardProps) {
  const displayName = getDisplayName(server)
  const typeBadges = getPackageTypeBadges(server)

  return (
    <Card
      className={CLICKABLE_CARD}
      tabIndex={0}
      onClick={() => onSelect(server)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect(server)
        }
      }}
      role="button"
      aria-label={`View details for ${displayName}`}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-base truncate">{displayName}</CardTitle>
            <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">
              {server.name}
            </p>
          </div>
          <Badge variant="outline" className="text-xs shrink-0">
            v{server.version}
          </Badge>
        </div>
        <CardDescription className="line-clamp-2 mt-1">
          {server.description}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-3">
          {/* Package type badges */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {typeBadges.map((badge) => (
              <Badge key={badge.label} variant={badge.variant} className="text-xs gap-1">
                <Package className="h-3 w-3" />
                {badge.label}
              </Badge>
            ))}
          </div>

          {/* Repository link + install button */}
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0 flex-1">
              {server.repository?.url && (
                <span
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground truncate"
                  title={server.repository.url}
                >
                  <GitBranch className="h-3 w-3 shrink-0" />
                  <span className="truncate">{shortenRepoUrl(server.repository.url)}</span>
                </span>
              )}
              {!server.repository?.url && server.websiteUrl && (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground truncate">
                  <Globe className="h-3 w-3 shrink-0" />
                  <span className="truncate">{server.websiteUrl}</span>
                </span>
              )}
            </div>
            <Button
              size="sm"
              variant="default"
              onClick={(e) => {
                e.stopPropagation()
                onInstall(server)
              }}
              className="shrink-0"
            >
              <Download className="h-3.5 w-3.5 mr-1" />
              Install
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
