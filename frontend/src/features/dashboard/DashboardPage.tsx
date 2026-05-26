import { AlertCircle, Bot, CheckCircle2, LayoutDashboard, Terminal } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { useNavigate } from 'react-router-dom'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { useDashboard } from '@/contexts/DashboardContext'
import { useProjectContext } from '@/contexts/ProjectContext'
import { useProviderContext } from '@/contexts/ProviderContext'
import { getRelativeTime } from '@/features/usage/utils'

export function DashboardPage() {
  const { stats, loading, error, lastFetched, refreshDashboard } = useDashboard({ autoFetch: true })
  const { projects } = useProjectContext()
  const { providers, selectedProviderId, setSelectedProviderId } = useProviderContext()
  const navigate = useNavigate()
  const installedProviderCount = providers.filter((provider) => provider.installed).length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <LayoutDashboard className="h-8 w-8" />
            Dashboard
          </h1>
          <p className="text-muted-foreground">
            Overview of your local agent workspace
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastFetched && (
            <span className="text-xs text-muted-foreground">
              Updated {getRelativeTime(lastFetched.toISOString())}
            </span>
          )}
          <RefreshButton onClick={refreshDashboard} loading={loading} />
        </div>
      </div>

      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{error}</p>
          </CardContent>
        </Card>
      )}

      {loading && !stats && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(9)].map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <CardDescription>Loading...</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">-</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {stats && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {/* Order matches sidebar navigation */}

          {/* Tier 1: Overview & Setup */}
          <Card className="md:col-span-2 lg:col-span-3">
            <CardHeader>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Bot className="h-5 w-5" />
                    Agent Providers
                  </CardTitle>
                  <CardDescription>
                    Claude Code and Codex CLI availability on this machine
                  </CardDescription>
                </div>
                <Badge variant="outline">
                  {installedProviderCount}/{providers.length} installed
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2">
                {providers.map((provider) => {
                  const isSelected = provider.id === selectedProviderId
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      onClick={() => setSelectedProviderId(provider.id)}
                      className={`rounded-md border p-4 text-left transition-colors hover:bg-accent ${
                        isSelected ? 'border-primary bg-primary/5' : 'border-border'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Terminal className="h-4 w-4 shrink-0" />
                            <p className="font-medium">{provider.display_name}</p>
                            {isSelected && <Badge variant="secondary">Selected</Badge>}
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {provider.binary_path ?? provider.config_paths.home ?? 'Binary not found'}
                          </p>
                        </div>
                        <Badge
                          variant={provider.installed ? 'outline' : 'destructive'}
                          className={provider.installed ? 'text-green-600 dark:text-green-400' : undefined}
                        >
                          {provider.installed ? (
                            <CheckCircle2 className="mr-1 h-3 w-3" />
                          ) : (
                            <AlertCircle className="mr-1 h-3 w-3" />
                          )}
                          {provider.installed ? provider.version ?? 'Installed' : 'Missing'}
                        </Badge>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {Object.entries(provider.capabilities)
                          .filter(([, enabled]) => enabled)
                          .slice(0, 7)
                          .map(([capability]) => (
                            <span
                              key={capability}
                              className="rounded border bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground"
                            >
                              {capability}
                            </span>
                          ))}
                      </div>
                    </button>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Projects</CardDescription>
              <CardTitle className="text-3xl">{projects.length}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Tracked projects
              </p>
            </CardContent>
          </Card>

          {/* Tier 2: Core Configuration */}
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>MCP Servers</CardDescription>
              <CardTitle className="text-3xl">{stats.mcpServerCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Configured MCP servers
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Commands</CardDescription>
              <CardTitle className="text-3xl">{stats.commandCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Claude slash commands available
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Plugins</CardDescription>
              <CardTitle className="text-3xl">{stats.pluginCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Installed Claude plugins
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Hooks</CardDescription>
              <CardTitle className="text-3xl">{stats.hookCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Claude automation hooks configured
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Permissions</CardDescription>
              <CardTitle className="text-3xl">{stats.permissionCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Claude permission rules
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Agents</CardDescription>
              <CardTitle className="text-3xl">{stats.agentCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Custom agents (user, project, plugin)
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Skills</CardDescription>
              <CardTitle className="text-3xl">{stats.skillCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Available skills
              </p>
            </CardContent>
          </Card>

          {/* Tier 3: Customization */}
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Output Styles</CardDescription>
              <CardTitle className="text-3xl">{stats.outputStyleCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Custom output formats
              </p>
            </CardContent>
          </Card>

          {/* Tier 4: Monitoring */}
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Session History</CardDescription>
              <CardTitle className="text-3xl">{stats.sessionCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-xs text-muted-foreground space-y-1">
                <p>{stats.sessionsToday} today</p>
                <p>{stats.sessionsThisWeek} this week</p>
                {stats.mostActiveProject && (
                  <p className="text-primary">Most active: {stats.mostActiveProject}</p>
                )}
              </div>
              <Button
                variant="link"
                className="p-0 h-auto mt-2"
                onClick={() => navigate('/sessions')}
              >
                View all sessions →
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Plans</CardDescription>
              <CardTitle className="text-3xl">{stats.planCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">Execution plans</p>
              <Button
                variant="link"
                className="p-0 h-auto mt-2"
                onClick={() => navigate('/plans')}
              >
                View all plans →
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Claude Context Window</CardDescription>
              <CardTitle className="text-3xl">
                {stats.contextActiveCount > 0 ? `${stats.contextHighestPct.toFixed(0)}%` : '--'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {stats.contextActiveCount > 0 ? (
                <div className="space-y-2">
                  <Progress
                    value={stats.contextHighestPct}
                    className={`h-2 ${
                      stats.contextHighestPct >= 95 ? '[&>div]:bg-red-500' :
                      stats.contextHighestPct >= 80 ? '[&>div]:bg-orange-500' :
                      stats.contextHighestPct >= 50 ? '[&>div]:bg-yellow-500' :
                      '[&>div]:bg-green-500'
                    }`}
                  />
                  <p className="text-xs text-muted-foreground">
                    {stats.contextActiveCount} active session{stats.contextActiveCount !== 1 ? 's' : ''}
                    {stats.contextHighestProject && ` - ${stats.contextHighestProject}`}
                  </p>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No active sessions</p>
              )}
              <Button
                variant="link"
                className="p-0 h-auto mt-2"
                onClick={() => navigate('/context')}
              >
                View context →
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {stats && (
        <Card>
          <CardHeader>
            <CardTitle>Quick Status</CardTitle>
            <CardDescription>Claude Code configuration health indicators</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span>Settings keys:</span>
                <span className="font-medium">
                  {stats.settingsKeys} configured
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span>Allow rules:</span>
                <span className="font-medium text-success">
                  {stats.allowRules}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span>Deny rules:</span>
                <span className="font-medium text-destructive">
                  {stats.denyRules}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
