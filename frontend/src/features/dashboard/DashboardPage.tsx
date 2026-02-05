import { useEffect, useState, useCallback } from 'react'
import { LayoutDashboard } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { useProjectContext } from '@/contexts/ProjectContext'
import { useNavigate } from 'react-router-dom'
import { apiClient, buildEndpoint } from '@/lib/api'
import type { MergedConfig } from '@/types/config'
import type { AgentListResponse, SkillListResponse } from '@/types/agents'
import type { OutputStyleListResponse } from '@/types/output-styles'
import { useSessionsApi } from '@/hooks/useSessionsApi'

interface PluginListResponse {
  plugins: unknown[];
}

interface MCPServerListResponse {
  servers: unknown[];
}

interface HookListResponse {
  hooks: unknown[];
}

interface PermissionListResponse {
  rules: { type: string }[];
}

interface CommandListResponse {
  commands: unknown[];
}

export function DashboardPage() {
  const { projects, activeProject } = useProjectContext()
  const { getDashboardStats } = useSessionsApi()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [stats, setStats] = useState<{
    mcpServerCount: number;
    commandCount: number;
    agentCount: number;
    skillCount: number;
    hookCount: number;
    pluginCount: number;
    permissionCount: number;
    projectCount: number;
    outputStyleCount: number;
    allowRules: number;
    denyRules: number;
    settingsKeys: number;
    sessionCount: number;
    sessionsToday: number;
    sessionsThisWeek: number;
    mostActiveProject?: string;
    totalMessages: number;
  } | null>(null)

  const fetchStats = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { project_path: activeProject?.path }

      // Fetch all data in parallel using dedicated endpoints for accurate counts
      const [
        configData,
        mcpData,
        agentsData,
        skillsData,
        pluginsData,
        hooksData,
        permissionsData,
        commandsData,
        outputStylesData,
        sessionStatsData,
      ] = await Promise.all([
        apiClient<MergedConfig>(buildEndpoint('config', params)),
        apiClient<MCPServerListResponse>(buildEndpoint('mcp/servers', params)),
        apiClient<AgentListResponse>(buildEndpoint('agents', params)),
        apiClient<SkillListResponse>(buildEndpoint('agents/skills', params)),
        apiClient<PluginListResponse>(buildEndpoint('plugins', params)),
        apiClient<HookListResponse>(buildEndpoint('hooks', params)),
        apiClient<PermissionListResponse>(buildEndpoint('permissions', params)),
        apiClient<CommandListResponse>(buildEndpoint('commands', params)),
        apiClient<OutputStyleListResponse>(buildEndpoint('output-styles', params)),
        getDashboardStats(),
      ])

      const allowRules = permissionsData.rules.filter(r => r.type === 'allow').length
      const denyRules = permissionsData.rules.filter(r => r.type === 'deny').length

      setStats({
        mcpServerCount: mcpData.servers.length,
        commandCount: commandsData.commands.length,
        agentCount: agentsData.agents.length,
        skillCount: skillsData.skills.length,
        hookCount: hooksData.hooks.length,
        pluginCount: pluginsData.plugins.length,
        permissionCount: allowRules + denyRules,
        projectCount: projects.length,
        outputStyleCount: outputStylesData?.output_styles?.length || 0,
        allowRules,
        denyRules,
        settingsKeys: Object.keys(configData.settings || {}).length,
        sessionCount: sessionStatsData.total_sessions,
        sessionsToday: sessionStatsData.sessions_today,
        sessionsThisWeek: sessionStatsData.sessions_this_week,
        mostActiveProject: sessionStatsData.most_active_project,
        totalMessages: sessionStatsData.total_messages,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data')
    } finally {
      setLoading(false)
    }
  }, [activeProject?.path, projects.length, getDashboardStats])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <LayoutDashboard className="h-8 w-8" />
            Dashboard
          </h1>
          <p className="text-muted-foreground">
            Overview of your Claude Code configuration
          </p>
        </div>
        <RefreshButton onClick={fetchStats} loading={loading} />
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
              <CardDescription>Commands</CardDescription>
              <CardTitle className="text-3xl">{stats.commandCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Slash commands available
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Plugins</CardDescription>
              <CardTitle className="text-3xl">{stats.pluginCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Installed plugins
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Agents</CardDescription>
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
              <CardDescription>Skills</CardDescription>
              <CardTitle className="text-3xl">{stats.skillCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Available skills
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Hooks</CardDescription>
              <CardTitle className="text-3xl">{stats.hookCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Automation hooks configured
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Permissions</CardDescription>
              <CardTitle className="text-3xl">{stats.permissionCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Permission rules
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Projects</CardDescription>
              <CardTitle className="text-3xl">{stats.projectCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Tracked projects
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Output Styles</CardDescription>
              <CardTitle className="text-3xl">{stats.outputStyleCount}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Custom output formats
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Sessions</CardDescription>
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
        </div>
      )}

      {stats && (
        <Card>
          <CardHeader>
            <CardTitle>Quick Status</CardTitle>
            <CardDescription>Configuration health indicators</CardDescription>
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
