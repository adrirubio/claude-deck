import { ExternalLink, Package, Globe, GitBranch, Download, Key, Terminal } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { MODAL_SIZES } from '@/lib/constants'
import type { RegistryServer } from '@/types/registry'
import { getDisplayName } from '@/types/registry'

interface MCPRegistryDetailDialogProps {
  server: RegistryServer | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onInstall: (server: RegistryServer) => void
}

export function MCPRegistryDetailDialog({
  server,
  open,
  onOpenChange,
  onInstall,
}: MCPRegistryDetailDialogProps) {
  if (!server) return null

  const displayName = getDisplayName(server)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.LG}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {displayName}
            <Badge variant="outline" className="text-xs">v{server.version}</Badge>
          </DialogTitle>
          <DialogDescription className="text-xs font-mono">
            {server.name}
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh]">
          <div className="space-y-6 pr-4">
            {/* Description */}
            <p className="text-sm">{server.description}</p>

            {/* Links */}
            <div className="flex items-center gap-3 flex-wrap">
              {server.repository?.url && (
                <a
                  href={server.repository.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  <GitBranch className="h-3.5 w-3.5" />
                  Repository
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
              {server.websiteUrl && (
                <a
                  href={server.websiteUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Globe className="h-3.5 w-3.5" />
                  Website
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>

            {/* Packages */}
            {server.packages && server.packages.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold flex items-center gap-1.5">
                  <Package className="h-4 w-4" />
                  Packages
                </h3>
                {server.packages.map((pkg, i) => (
                  <div key={i} className="border rounded-lg p-3 space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant="secondary">{pkg.registryType}</Badge>
                      <span className="text-sm font-mono">{pkg.identifier}</span>
                      {pkg.version && (
                        <Badge variant="outline" className="text-xs">v{pkg.version}</Badge>
                      )}
                    </div>
                    {pkg.runtimeHint && (
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <Terminal className="h-3 w-3" />
                        Runtime: {pkg.runtimeHint}
                      </div>
                    )}
                    {pkg.packageArguments && pkg.packageArguments.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-medium">Arguments:</p>
                        {pkg.packageArguments.map((arg, j) => (
                          <div key={j} className="text-xs text-muted-foreground pl-2">
                            <span className="font-mono">--{arg.name}</span>
                            {arg.isRequired && <Badge variant="destructive" className="text-[10px] ml-1 px-1 py-0">required</Badge>}
                            {arg.description && <span className="ml-1">— {arg.description}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                    {pkg.environmentVariables && pkg.environmentVariables.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-medium flex items-center gap-1">
                          <Key className="h-3 w-3" />
                          Environment Variables:
                        </p>
                        {pkg.environmentVariables.map((env, j) => (
                          <div key={j} className="text-xs text-muted-foreground pl-2">
                            <span className="font-mono">{env.name}</span>
                            {env.isRequired && <Badge variant="destructive" className="text-[10px] ml-1 px-1 py-0">required</Badge>}
                            {env.isSecret && <Badge variant="outline" className="text-[10px] ml-1 px-1 py-0">secret</Badge>}
                            {env.description && <span className="ml-1">— {env.description}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Remotes */}
            {server.remotes && server.remotes.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold flex items-center gap-1.5">
                  <Globe className="h-4 w-4" />
                  Remote Transports
                </h3>
                {server.remotes.map((remote, i) => (
                  <div key={i} className="border rounded-lg p-3 space-y-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">
                        {remote.type === 'streamable-http' ? 'HTTP' : 'SSE'}
                      </Badge>
                      <span className="text-sm font-mono break-all">{remote.url}</span>
                    </div>
                    {remote.headers && remote.headers.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-medium flex items-center gap-1">
                          <Key className="h-3 w-3" />
                          Required Headers:
                        </p>
                        {remote.headers.map((header, j) => (
                          <div key={j} className="text-xs text-muted-foreground pl-2">
                            <span className="font-mono">{header.name}</span>
                            {header.isRequired && <Badge variant="destructive" className="text-[10px] ml-1 px-1 py-0">required</Badge>}
                            {header.description && <span className="ml-1">— {header.description}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </ScrollArea>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button onClick={() => onInstall(server)}>
            <Download className="h-4 w-4 mr-2" />
            Install
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
