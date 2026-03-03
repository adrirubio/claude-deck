/**
 * Dashboard Context — caches dashboard stats across navigation.
 * Data is fetched lazily on first dashboard visit, re-fetched on project change or manual refresh.
 */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
} from 'react';
import { useProjectContext } from '@/contexts/ProjectContext';
import { useSessionsApi } from '@/hooks/useSessionsApi';
import { useContextApi } from '@/hooks/useContextApi';
import { usePlansApi } from '@/hooks/usePlansApi';
import { apiClient, buildEndpoint } from '@/lib/api';
import type { MergedConfig } from '@/types/config';
import type { AgentListResponse, SkillListResponse } from '@/types/agents';
import type { OutputStyleListResponse } from '@/types/output-styles';
import type { PluginListResponse } from '@/types/plugins';
import type { MCPServerListResponse } from '@/types/mcp';
import type { HookListResponse } from '@/types/hooks';
import type { PermissionListResponse } from '@/types/permissions';
import type { SlashCommandListResponse } from '@/types/commands';
import type { ActiveSessionsResponse, ActiveSessionContext } from '@/types/context';

export interface DashboardStats {
  mcpServerCount: number;
  commandCount: number;
  agentCount: number;
  skillCount: number;
  hookCount: number;
  pluginCount: number;
  permissionCount: number;
  outputStyleCount: number;
  allowRules: number;
  denyRules: number;
  settingsKeys: number;
  sessionCount: number;
  sessionsToday: number;
  sessionsThisWeek: number;
  mostActiveProject?: string;
  totalMessages: number;
  contextHighestPct: number;
  contextHighestProject?: string;
  contextActiveCount: number;
  planCount: number;
}

interface DashboardContextType {
  stats: DashboardStats | null;
  loading: boolean;
  error: string | null;
  lastFetched: Date | null;
  refreshDashboard: () => Promise<void>;
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const { activeProject } = useProjectContext();
  const { getDashboardStats } = useSessionsApi();
  const { getActiveSessions } = useContextApi();
  const { getStats: getPlanStats } = usePlansApi();

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const prevProjectPath = useRef<string | undefined>(undefined);
  const fetchId = useRef(0);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    const currentFetchId = ++fetchId.current;
    try {
      const params = { project_path: activeProject?.path };

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
        contextData,
        planStatsData,
      ] = await Promise.all([
        apiClient<MergedConfig>(buildEndpoint('config', params)),
        apiClient<MCPServerListResponse>(buildEndpoint('mcp/servers', params)),
        apiClient<AgentListResponse>(buildEndpoint('agents', params)),
        apiClient<SkillListResponse>(buildEndpoint('agents/skills', params)),
        apiClient<PluginListResponse>(buildEndpoint('plugins', params)),
        apiClient<HookListResponse>(buildEndpoint('hooks', params)),
        apiClient<PermissionListResponse>(buildEndpoint('permissions', params)),
        apiClient<SlashCommandListResponse>(buildEndpoint('commands', params)),
        apiClient<OutputStyleListResponse>(buildEndpoint('output-styles', params)),
        getDashboardStats(),
        getActiveSessions().catch((): ActiveSessionsResponse => ({ sessions: [] })),
        getPlanStats().catch(() => ({ total_plans: 0 })),
      ]);

      // Guard against stale responses from rapid project switches
      if (currentFetchId !== fetchId.current) return;

      const allowRules = permissionsData.rules.filter(r => r.type === 'allow').length;
      const denyRules = permissionsData.rules.filter(r => r.type === 'deny').length;

      const activeSessions = contextData.sessions.filter((s: ActiveSessionContext) => s.is_active);
      const highestCtx = contextData.sessions.length > 0
        ? contextData.sessions.reduce((max: ActiveSessionContext, s: ActiveSessionContext) =>
            s.context_percentage > max.context_percentage ? s : max, contextData.sessions[0])
        : null;

      setStats({
        mcpServerCount: mcpData.servers.length,
        commandCount: commandsData.commands.length,
        agentCount: agentsData.agents.length,
        skillCount: skillsData.skills.length,
        hookCount: hooksData.hooks.length,
        pluginCount: pluginsData.plugins.length,
        permissionCount: allowRules + denyRules,
        outputStyleCount: outputStylesData?.output_styles?.length || 0,
        allowRules,
        denyRules,
        settingsKeys: Object.keys(configData.settings || {}).length,
        sessionCount: sessionStatsData.total_sessions,
        sessionsToday: sessionStatsData.sessions_today,
        sessionsThisWeek: sessionStatsData.sessions_this_week,
        mostActiveProject: sessionStatsData.most_active_project,
        totalMessages: sessionStatsData.total_messages,
        contextHighestPct: highestCtx?.context_percentage ?? 0,
        contextHighestProject: highestCtx?.project_name,
        contextActiveCount: activeSessions.length,
        planCount: planStatsData.total_plans,
      });
      setLastFetched(new Date());
    } catch (err) {
      if (currentFetchId !== fetchId.current) return;
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
    } finally {
      if (currentFetchId === fetchId.current) {
        setLoading(false);
      }
    }
  // getDashboardStats and getActiveSessions have stable refs (empty deps).
  // getPlanStats changes with activeProject?.path but we handle project changes separately.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProject?.path]);

  // Re-fetch when active project changes (but not on initial mount)
  useEffect(() => {
    const currentPath = activeProject?.path;
    if (prevProjectPath.current !== undefined && prevProjectPath.current !== currentPath) {
      fetchStats();
    }
    prevProjectPath.current = currentPath;
  }, [activeProject?.path, fetchStats]);

  return (
    <DashboardContext.Provider
      value={{
        stats,
        loading,
        error,
        lastFetched,
        refreshDashboard: fetchStats,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useDashboard(options?: { autoFetch?: boolean }) {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error('useDashboard must be used within a DashboardProvider');
  }
  const { autoFetch = false } = options ?? {};
  const hasFetchedRef = useRef(false);

  useEffect(() => {
    if (autoFetch && !hasFetchedRef.current && !context.stats) {
      hasFetchedRef.current = true;
      context.refreshDashboard();
    }
  }, [autoFetch, context]);

  return context;
}
