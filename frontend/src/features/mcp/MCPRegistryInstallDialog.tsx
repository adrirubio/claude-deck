import { useState, useMemo, useEffect } from 'react'
import { Download } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { MODAL_SIZES } from '@/lib/constants'
import { useMCPRegistryApi } from '@/hooks/useMCPRegistryApi'
import { toast } from 'sonner'
import type { RegistryServer, RegistryInstallRequest } from '@/types/registry'
import { getDisplayName, getTransportOptions, type TransportOption } from '@/types/registry'

interface MCPRegistryInstallDialogProps {
  server: RegistryServer | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onInstallComplete: () => void
}

export function MCPRegistryInstallDialog({
  server,
  open,
  onOpenChange,
  onInstallComplete,
}: MCPRegistryInstallDialogProps) {
  const { installServer } = useMCPRegistryApi()
  const [step, setStep] = useState(1)
  const [installing, setInstalling] = useState(false)

  // Form state
  const [selectedTransportIdx, setSelectedTransportIdx] = useState(0)
  const [serverName, setServerName] = useState('')
  const [scope, setScope] = useState<'user' | 'project'>('user')
  const [envValues, setEnvValues] = useState<Record<string, string>>({})
  const [argValues, setArgValues] = useState<Record<string, string>>({})
  const [headerValues, setHeaderValues] = useState<Record<string, string>>({})

  const transportOptions = useMemo(
    () => (server ? getTransportOptions(server) : []),
    [server]
  )

  const selectedTransport: TransportOption | undefined = transportOptions[selectedTransportIdx]

  // Reset state when dialog opens with a new server
  useEffect(() => {
    if (open && server) {
      setStep(1)
      setSelectedTransportIdx(0)
      setEnvValues({})
      setArgValues({})
      setHeaderValues({})
      setInstalling(false)
      const parts = server.name.split('/')
      const defaultName = server.title || parts[parts.length - 1]
      setServerName(defaultName.toLowerCase().replace(/\s+/g, '-'))
    }
  }, [open, server])

  // Get env vars and args for selected transport
  const getSelectedEnvVars = () => {
    if (!server || !selectedTransport) return []
    if (selectedTransport.kind === 'package' && selectedTransport.packageIndex !== undefined) {
      return server.packages?.[selectedTransport.packageIndex]?.environmentVariables || []
    }
    return []
  }

  const getSelectedArgs = () => {
    if (!server || !selectedTransport) return []
    if (selectedTransport.kind === 'package' && selectedTransport.packageIndex !== undefined) {
      return server.packages?.[selectedTransport.packageIndex]?.packageArguments || []
    }
    return []
  }

  const getSelectedHeaders = () => {
    if (!server || !selectedTransport) return []
    if (selectedTransport.kind === 'remote' && selectedTransport.remoteIndex !== undefined) {
      return server.remotes?.[selectedTransport.remoteIndex]?.headers || []
    }
    return []
  }

  const envVars = getSelectedEnvVars()
  const args = getSelectedArgs()
  const headers = getSelectedHeaders()

  // Determine total steps (skip transport selection if only one option)
  const hasTransportChoice = transportOptions.length > 1
  const totalSteps = hasTransportChoice ? 4 : 3
  const effectiveStep = hasTransportChoice ? step : step + 1 // Map to 4-step numbering

  // Validation
  const canProceed = () => {
    switch (effectiveStep) {
      case 1: // Transport selection
        return selectedTransport !== undefined
      case 2: // Configure
        if (!serverName.trim()) return false
        // Check required env vars
        for (const env of envVars) {
          if (env.isRequired && !envValues[env.name]?.trim()) return false
        }
        // Check required args
        for (const arg of args) {
          if (arg.isRequired && arg.name && !argValues[arg.name]?.trim()) return false
        }
        // Check required headers
        for (const header of headers) {
          if (header.isRequired && !headerValues[header.name]?.trim()) return false
        }
        return true
      case 3: // Scope
        return true
      case 4: // Review
        return true
      default:
        return false
    }
  }

  // Build install request
  const buildRequest = (): RegistryInstallRequest | null => {
    if (!server || !selectedTransport) return null

    const request: RegistryInstallRequest = {
      server_name: serverName,
      scope,
    }

    // Filter out empty env values
    const filteredEnv: Record<string, string> = {}
    for (const [k, v] of Object.entries(envValues)) {
      if (v.trim()) filteredEnv[k] = v
    }
    if (Object.keys(filteredEnv).length > 0) {
      request.env_values = filteredEnv
    }

    if (selectedTransport.kind === 'package' && selectedTransport.packageIndex !== undefined) {
      const pkg = server.packages![selectedTransport.packageIndex]
      request.package_registry_type = pkg.registryType
      request.package_identifier = pkg.identifier
      request.package_version = pkg.version
      request.package_runtime_hint = pkg.runtimeHint

      const filteredArgs: Record<string, string> = {}
      for (const [k, v] of Object.entries(argValues)) {
        if (v.trim()) filteredArgs[k] = v
      }
      if (Object.keys(filteredArgs).length > 0) {
        request.package_arguments = filteredArgs
      }
    } else if (selectedTransport.kind === 'remote' && selectedTransport.remoteIndex !== undefined) {
      const remote = server.remotes![selectedTransport.remoteIndex]
      request.remote_type = remote.type
      request.remote_url = remote.url

      const filteredHeaders: Record<string, string> = {}
      for (const [k, v] of Object.entries(headerValues)) {
        if (v.trim()) filteredHeaders[k] = v
      }
      if (Object.keys(filteredHeaders).length > 0) {
        request.remote_headers = filteredHeaders
      }
    }

    return request
  }

  // Generate preview config (client-side approximation)
  const getPreviewConfig = (): Record<string, unknown> => {
    if (!server || !selectedTransport) return {}

    if (selectedTransport.kind === 'package' && selectedTransport.packageIndex !== undefined) {
      const pkg = server.packages![selectedTransport.packageIndex]
      const args: string[] = []
      const command = pkg.runtimeHint || (pkg.registryType === 'npm' ? 'npx' : pkg.registryType === 'pypi' ? 'uvx' : 'docker')

      if (pkg.registryType === 'npm') {
        if (command === 'npx') args.push('-y')
        args.push(pkg.version ? `${pkg.identifier}@${pkg.version}` : pkg.identifier)
      } else if (pkg.registryType === 'pypi') {
        args.push(pkg.identifier)
      } else if (pkg.registryType === 'oci') {
        args.push('run', '-i', '--rm', pkg.identifier)
      }

      // Add user-provided args
      for (const [name, value] of Object.entries(argValues)) {
        if (value.trim()) args.push(`--${name}`, value)
      }

      const config: Record<string, unknown> = { type: 'stdio', command, args }

      const filteredEnv: Record<string, string> = {}
      for (const [k, v] of Object.entries(envValues)) {
        if (v.trim()) filteredEnv[k] = v
      }
      if (Object.keys(filteredEnv).length > 0) config.env = filteredEnv

      return config
    }

    if (selectedTransport.kind === 'remote' && selectedTransport.remoteIndex !== undefined) {
      const remote = server.remotes![selectedTransport.remoteIndex]
      const configType = remote.type === 'streamable-http' ? 'http' : remote.type
      const config: Record<string, unknown> = { type: configType, url: remote.url }

      const filteredHeaders: Record<string, string> = {}
      for (const [k, v] of Object.entries(headerValues)) {
        if (v.trim()) filteredHeaders[k] = v
      }
      if (Object.keys(filteredHeaders).length > 0) config.headers = filteredHeaders

      return config
    }

    return {}
  }

  const handleInstall = async () => {
    const request = buildRequest()
    if (!request) return

    setInstalling(true)
    try {
      await installServer(request)
      toast.success(`Server "${serverName}" installed successfully`)
      onOpenChange(false)
      onInstallComplete()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to install server')
    } finally {
      setInstalling(false)
    }
  }

  if (!server) return null

  const displayName = getDisplayName(server)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.MD}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Download className="h-5 w-5" />
            Install {displayName}
          </DialogTitle>
          <DialogDescription>
            Step {step} of {totalSteps}
          </DialogDescription>
        </DialogHeader>

        {/* Progress bar */}
        <div className="flex items-center gap-2">
          {Array.from({ length: totalSteps }, (_, i) => (
            <div
              key={i}
              className={`h-2 flex-1 rounded ${i < step ? 'bg-primary' : 'bg-muted'}`}
            />
          ))}
        </div>

        <div className="space-y-4 py-2">
          {/* Step 1: Transport selection (only if multiple options) */}
          {effectiveStep === 1 && hasTransportChoice && (
            <div className="space-y-3">
              <p className="text-sm font-medium">Choose how to run this server:</p>
              {transportOptions.map((opt, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setSelectedTransportIdx(i)}
                  className={`w-full p-3 border rounded-lg text-left transition-colors ${
                    selectedTransportIdx === i
                      ? 'border-primary bg-primary/5'
                      : 'border-input hover:bg-muted/50'
                  }`}
                >
                  <div className="font-medium text-sm">{opt.label}</div>
                  <div className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                    {opt.description}
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Step 2: Configure */}
          {effectiveStep === 2 && (
            <div className="space-y-4">
              <div>
                <Label htmlFor="server-name">Server Name *</Label>
                <Input
                  id="server-name"
                  value={serverName}
                  onChange={(e) => setServerName(e.target.value)}
                  placeholder="e.g., github, filesystem"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  This name identifies the server in your Claude Code config
                </p>
              </div>

              {/* Environment variables */}
              {envVars.length > 0 && (
                <div className="space-y-3">
                  <p className="text-sm font-medium">Environment Variables</p>
                  {envVars.map((env) => (
                    <div key={env.name}>
                      <Label htmlFor={`env-${env.name}`} className="flex items-center gap-1">
                        {env.name}
                        {env.isRequired && <span className="text-destructive">*</span>}
                      </Label>
                      <Input
                        id={`env-${env.name}`}
                        type={env.isSecret ? 'password' : 'text'}
                        value={envValues[env.name] || ''}
                        onChange={(e) =>
                          setEnvValues((prev) => ({ ...prev, [env.name]: e.target.value }))
                        }
                        placeholder={env.default || env.description || ''}
                      />
                      {env.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">{env.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Package arguments */}
              {args.length > 0 && (
                <div className="space-y-3">
                  <p className="text-sm font-medium">Arguments</p>
                  {args.map((arg) => (
                    <div key={arg.name}>
                      <Label htmlFor={`arg-${arg.name}`} className="flex items-center gap-1">
                        --{arg.name}
                        {arg.isRequired && <span className="text-destructive">*</span>}
                      </Label>
                      <Input
                        id={`arg-${arg.name}`}
                        value={argValues[arg.name || ''] || ''}
                        onChange={(e) =>
                          setArgValues((prev) => ({ ...prev, [arg.name || '']: e.target.value }))
                        }
                        placeholder={arg.default || arg.description || ''}
                      />
                      {arg.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">{arg.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Remote headers */}
              {headers.length > 0 && (
                <div className="space-y-3">
                  <p className="text-sm font-medium">Headers</p>
                  {headers.map((header) => (
                    <div key={header.name}>
                      <Label htmlFor={`header-${header.name}`} className="flex items-center gap-1">
                        {header.name}
                        {header.isRequired && <span className="text-destructive">*</span>}
                      </Label>
                      <Input
                        id={`header-${header.name}`}
                        type={header.isSecret ? 'password' : 'text'}
                        value={headerValues[header.name] || ''}
                        onChange={(e) =>
                          setHeaderValues((prev) => ({ ...prev, [header.name]: e.target.value }))
                        }
                        placeholder={header.value || header.description || ''}
                      />
                      {header.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">{header.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {envVars.length === 0 && args.length === 0 && headers.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No additional configuration required for this transport.
                </p>
              )}
            </div>
          )}

          {/* Step 3: Scope */}
          {effectiveStep === 3 && (
            <div className="space-y-4">
              <p className="text-sm font-medium">Where should this server be saved?</p>
              <Select value={scope} onValueChange={(v: 'user' | 'project') => setScope(v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">User (~/.claude.json)</SelectItem>
                  <SelectItem value="project">Project (.mcp.json)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                <strong>User:</strong> Available in all projects.{' '}
                <strong>Project:</strong> Only available in this project.
              </p>
            </div>
          )}

          {/* Step 4: Review & Install */}
          {effectiveStep === 4 && (
            <div className="space-y-4">
              <div className="border rounded-lg p-4 space-y-3 bg-muted/30">
                <div>
                  <div className="text-sm font-medium">Server Name</div>
                  <div className="text-sm text-muted-foreground font-mono">{serverName}</div>
                </div>
                <div>
                  <div className="text-sm font-medium">Scope</div>
                  <div className="text-sm text-muted-foreground capitalize">{scope}</div>
                </div>
                <div>
                  <div className="text-sm font-medium">Transport</div>
                  <div className="text-sm text-muted-foreground">
                    {selectedTransport?.label}
                  </div>
                </div>
              </div>

              <div>
                <p className="text-sm font-medium mb-2">Generated Config</p>
                <pre className="text-xs font-mono bg-muted p-3 rounded-lg overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify({ [serverName]: getPreviewConfig() }, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex justify-between pt-2">
          <Button
            variant="outline"
            onClick={() => {
              if (step === 1) {
                onOpenChange(false)
              } else {
                setStep(step - 1)
              }
            }}
          >
            {step === 1 ? 'Cancel' : 'Back'}
          </Button>

          <div className="flex gap-2">
            {step < totalSteps && (
              <Button onClick={() => setStep(step + 1)} disabled={!canProceed()}>
                Next
              </Button>
            )}
            {step === totalSteps && (
              <Button onClick={handleInstall} disabled={installing || !canProceed()}>
                {installing ? 'Installing...' : 'Install'}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
