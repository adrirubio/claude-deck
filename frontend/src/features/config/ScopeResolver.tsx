import { useState, useEffect, useCallback } from 'react'
import { Shield, User, Folder, FileCode, Copy, Lock, ChevronRight, ChevronDown, RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { apiClient, buildEndpoint } from '@/lib/api'
import { useProjectContext } from '@/contexts/ProjectContext'
import { toast } from 'sonner'
import type { ConfigValue, ResolvedConfigResponse, ResolvedSettingValue } from '@/types/config'

const SCOPE_ICONS = {
  managed: Shield,
  user: User,
  project: Folder,
  local: FileCode,
}

const SCOPE_COLORS = {
  managed: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
  user: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
  project: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
  local: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300',
}

const SCOPE_LABELS = {
  managed: 'Managed (Admin)',
  user: 'User',
  project: 'Project',
  local: 'Local',
}

interface ScopeBadgeProps {
  scope: 'managed' | 'local' | 'project' | 'user'
  isSource?: boolean
}

function ScopeBadge({ scope, isSource }: ScopeBadgeProps) {
  const Icon = SCOPE_ICONS[scope]
  return (
    <Badge 
      variant="secondary" 
      className={`${SCOPE_COLORS[scope]} ${isSource ? 'ring-2 ring-offset-1 ring-primary' : ''} flex items-center gap-1`}
      title={isSource ? 'Active value source' : undefined}
    >
      <Icon className="h-3 w-3" />
      {SCOPE_LABELS[scope]}
      {scope === 'managed' && <Lock className="h-3 w-3 ml-1" />}
    </Badge>
  )
}

interface ResolvedSettingRowProps {
  settingKey: string
  value: ResolvedSettingValue
  onOverride?: (key: string, value: ConfigValue) => void
}

function ResolvedSettingRow({ settingKey, value, onOverride }: ResolvedSettingRowProps) {
  const [isOpen, setIsOpen] = useState(false)
  const hasMultipleValues = Object.keys(value.values_by_scope).length > 1
  const isManaged = value.source_scope === 'managed'

  const formatValue = (val: ConfigValue) => {
    if (val === null) return 'null'
    if (val === undefined) return 'undefined'
    if (typeof val === 'boolean') return val ? 'true' : 'false'
    if (typeof val === 'object') return JSON.stringify(val, null, 2)
    return String(val)
  }

  const handleCopyToLocal = () => {
    if (onOverride) {
      onOverride(settingKey, value.effective_value)
      toast.success(`Setting "${settingKey}" copied to local scope`)
    }
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div className="border rounded-lg p-3 mb-2 bg-card">
        <CollapsibleTrigger asChild>
          <div className="flex items-center justify-between cursor-pointer hover:bg-accent/50 -m-3 p-3 rounded-lg transition-colors">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              {hasMultipleValues ? (
                isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />
              ) : (
                <div className="w-4" />
              )}
              <code className="text-sm font-mono truncate">{settingKey}</code>
            </div>
            <div className="flex items-center gap-2">
              <ScopeBadge scope={value.source_scope} isSource />
              {!isManaged && onOverride && (
                <Button 
                  variant="ghost" 
                  size="sm"
                  title="Override in local scope"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleCopyToLocal()
                  }}
                >
                  <Copy className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        </CollapsibleTrigger>

        <div className="mt-2 pl-6">
          <div className="text-sm">
            <span className="text-muted-foreground">Effective value: </span>
            <code className="bg-muted px-1 py-0.5 rounded text-xs">
              {formatValue(value.effective_value)}
            </code>
          </div>
        </div>

        {hasMultipleValues && (
          <CollapsibleContent>
            <div className="mt-3 pl-6 border-l-2 border-muted ml-2 space-y-2">
              <p className="text-xs text-muted-foreground mb-2">Values by scope (highest priority first):</p>
              {(['managed', 'local', 'project', 'user'] as const).map(scope => {
                if (!(scope in value.values_by_scope)) return null
                const scopeValue = value.values_by_scope[scope]
                const isActive = scope === value.source_scope
                return (
                  <div 
                    key={scope} 
                    className={`flex items-center gap-2 p-2 rounded ${isActive ? 'bg-primary/10 border border-primary/20' : 'bg-muted/50'}`}
                  >
                    <ScopeBadge scope={scope} isSource={isActive} />
                    <code className="text-xs flex-1 truncate">{formatValue(scopeValue)}</code>
                    {!isActive && (
                      <span className="text-xs text-muted-foreground">(overridden)</span>
                    )}
                  </div>
                )
              })}
            </div>
          </CollapsibleContent>
        )}

        {isManaged && (
          <div className="mt-2 pl-6 flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
            <Lock className="h-3 w-3" />
            <span>Enforced by administrator - cannot be overridden</span>
          </div>
        )}
      </div>
    </Collapsible>
  )
}

interface ScopeTabContentProps {
  scope: 'managed' | 'user' | 'project' | 'local'
  data: ResolvedConfigResponse | null
}

function ScopeTabContent({ scope, data }: ScopeTabContentProps) {
  if (!data) return null
  
  const scopeInfo = data.scopes[scope]
  const Icon = SCOPE_ICONS[scope]
  
  if (!scopeInfo.exists) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <Icon className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>No {SCOPE_LABELS[scope].toLowerCase()} settings file found</p>
        <p className="text-xs mt-2">{scopeInfo.path || 'Path not available'}</p>
      </div>
    )
  }

  const settings = scopeInfo.settings
  const settingKeys = Object.keys(settings)

  if (settingKeys.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <Icon className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>No settings defined in {SCOPE_LABELS[scope].toLowerCase()} scope</p>
        <p className="text-xs mt-2">{scopeInfo.path}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{scopeInfo.path}</p>
        {scopeInfo.readonly && (
          <Badge variant="outline" className="flex items-center gap-1">
            <Lock className="h-3 w-3" />
            Read-only
          </Badge>
        )}
      </div>
      <pre className="bg-muted p-4 rounded-lg overflow-auto max-h-96 text-sm">
        {JSON.stringify(settings, null, 2)}
      </pre>
    </div>
  )
}

interface ScopeResolverProps {
  onOverride?: (key: string, value: ConfigValue) => void
}

export function ScopeResolver({ onOverride }: ScopeResolverProps) {
  const { activeProject } = useProjectContext()
  const [data, setData] = useState<ResolvedConfigResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'resolved' | 'managed' | 'user' | 'project' | 'local'>('resolved')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const endpoint = buildEndpoint('config/resolved', { project_path: activeProject?.path })
      const response = await apiClient<ResolvedConfigResponse>(endpoint)
      setData(response)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load resolved config'
      setError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [activeProject?.path])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const resolvedKeys = data ? Object.keys(data.resolved).sort() : []

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              Settings Scope Resolver
            </CardTitle>
            <CardDescription>
              View effective settings and their source scopes. Priority: Managed → Local → Project → User
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={fetchData} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="text-destructive mb-4 p-3 bg-destructive/10 rounded-lg">
            {error}
          </div>
        )}

        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
          <TabsList className="mb-4">
            <TabsTrigger value="resolved" className="flex items-center gap-2">
              Resolved
            </TabsTrigger>
            <TabsTrigger value="managed" className="flex items-center gap-1">
              <Shield className="h-3 w-3" />
              Managed
            </TabsTrigger>
            <TabsTrigger value="user" className="flex items-center gap-1">
              <User className="h-3 w-3" />
              User
            </TabsTrigger>
            <TabsTrigger value="project" className="flex items-center gap-1">
              <Folder className="h-3 w-3" />
              Project
            </TabsTrigger>
            <TabsTrigger value="local" className="flex items-center gap-1">
              <FileCode className="h-3 w-3" />
              Local
            </TabsTrigger>
          </TabsList>

          <TabsContent value="resolved">
            {loading && !data ? (
              <div className="text-center py-8 text-muted-foreground">
                <RefreshCw className="h-8 w-8 mx-auto mb-4 animate-spin opacity-50" />
                <p>Loading resolved settings...</p>
              </div>
            ) : resolvedKeys.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <p>No settings found in any scope</p>
              </div>
            ) : (
              <div className="space-y-2">
                {resolvedKeys.map(key => (
                  <ResolvedSettingRow
                    key={key}
                    settingKey={key}
                    value={data!.resolved[key]}
                    onOverride={onOverride}
                  />
                ))}
              </div>
            )}
          </TabsContent>

          <TabsContent value="managed">
            <ScopeTabContent scope="managed" data={data} />
          </TabsContent>

          <TabsContent value="user">
            <ScopeTabContent scope="user" data={data} />
          </TabsContent>

          <TabsContent value="project">
            <ScopeTabContent scope="project" data={data} />
          </TabsContent>

          <TabsContent value="local">
            <ScopeTabContent scope="local" data={data} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
