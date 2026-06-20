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
import { useProviderContext } from '@/contexts/ProviderContext';
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
import type {
  AgentProviderId,
  CodexConfigResponse,
  CodexFeatureInventoryResponse,
  CodexMcpInventoryResponse,
  CodexPluginInventoryResponse,
} from '@/types/providers';

export interface DashboardStats {
  providerId: AgentProviderId;
  providerDisplayName: string;
  mcpServerCount: number;
  commandCount: number | null;
  agentCount: number | null;
  skillCount: number | null;
  hookCount: number | null;
  pluginCount: number | null;
  permissionCount: number | null;
  outputStyleCount: number | null;
  allowRules: number | null;
  denyRules: number | null;
  settingsKeys: number;
  sessionCount: number;
  sessionMetricKind: 'transcript' | 'live';
  sessionsToday: number | null;
  sessionsThisWeek: number | null;
  mostActiveProject?: string;
  totalMessages: number | null;
  contextHighestPct: number | null;
  contextHighestProject?: string;
  contextActiveCount: number | null;
  planCount: number;
  featureFlagCount: number | null;
  enabledFeatureFlagCount: number | null;
  unsupportedFeatures: string[];
  warnings: string[];
}

interface DashboardContextType {
  stats: DashboardStats | null;
  loading: boolean;
  error: string | null;
  lastFetched: Date | null;
  refreshDashboard: () => Promise<void>;
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined);

interface AgentBridgeSessionsResponse {
  sessions: unknown[];
  count: number;
}

function countCollection(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === 'object') return Object.keys(value).length;
  return 0;
}

function countCodexConfigEntries(config: CodexConfigResponse): number {
  return Object.entries(config.summary ?? {}).reduce((total, [, value]) => {
    if (value == null) return total;
    if (Array.isArray(value)) return total + value.length;
    if (typeof value === 'object') return total + Object.keys(value).length;
    return total + 1;
  }, 0);
}

async function safeFetch<T>(
  request: Promise<T>,
  fallback: T,
  warning: string,
  warnings: string[],
): Promise<T> {
  try {
    return await request;
  } catch (err) {
    warnings.push(err instanceof Error ? `${warning}: ${err.message}` : warning);
    return fallback;
  }
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const { activeProject } = useProjectContext();
  const { selectedProviderId, selectedProvider } = useProviderContext();
  const { getDashboardStats } = useSessionsApi();
  const { getActiveSessions } = useContextApi();
  const { getStats: getPlanStats } = usePlansApi();

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const prevProjectPath = useRef<string | undefined>(undefined);
  const prevProviderId = useRef<string | undefined>(undefined);
  const fetchId = useRef(0);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    const currentFetchId = ++fetchId.current;
    try {
      const providerId = selectedProviderId;
      const providerDisplayName = selectedProvider?.display_name ?? (
        providerId === 'codex-cli' ? 'Codex' : 'Claude Code'
      );
      const params = { project_path: activeProject?.path };

      if (providerId === 'codex-cli') {
        const warnings: string[] = [];
        const [
          configData,
          mcpData,
          pluginsData,
          featuresData,
          bridgeSessionsData,
          planStatsData,
        ] = await Promise.all([
          safeFetch(
            apiClient<CodexConfigResponse>('codex-config'),
            {
              provider: 'codex-cli',
              path: '',
              exists: false,
              parse_error: null,
              summary: {
                projects: {},
                profiles: {},
                features: {},
              },
              profile_resolution: null,
            },
            'Codex config unavailable',
            warnings,
          ),
          safeFetch(
            apiClient<CodexMcpInventoryResponse>('providers/codex-cli/mcp'),
            {
              provider: 'codex-cli',
              provider_display_name: 'Codex',
              exit_code: 1,
              servers: null,
              parse_error: null,
              stderr: '',
              raw_stdout: '',
            },
            'Codex MCP inventory unavailable',
            warnings,
          ),
          safeFetch(
            apiClient<CodexPluginInventoryResponse>('providers/codex-cli/plugins'),
            {
              provider: 'codex-cli',
              provider_display_name: 'Codex',
              exit_code: 1,
              plugins: [],
              mutation_capabilities: {
                install: { state: 'unsupported', reason: 'Unavailable' },
                remove: { state: 'unsupported', reason: 'Unavailable' },
                enable: { state: 'unsupported', reason: 'Unavailable' },
                disable: { state: 'unsupported', reason: 'Unavailable' },
              },
              stderr: '',
              raw_stdout: '',
            },
            'Codex plugin inventory unavailable',
            warnings,
          ),
          safeFetch(
            apiClient<CodexFeatureInventoryResponse>('providers/codex-cli/features'),
            {
              provider: 'codex-cli',
              provider_display_name: 'Codex',
              exit_code: 1,
              features: [],
              stderr: '',
              raw_stdout: '',
            },
            'Codex feature inventory unavailable',
            warnings,
          ),
          safeFetch(
            apiClient<AgentBridgeSessionsResponse>(
              buildEndpoint('agent-bridge/sessions', { provider: providerId }),
            ),
            { sessions: [], count: 0 },
            'Codex live sessions unavailable',
            warnings,
          ),
          getPlanStats().catch(() => ({ total_plans: 0 })),
        ]);

        if (currentFetchId !== fetchId.current) return;

        setStats({
          providerId,
          providerDisplayName,
          mcpServerCount: countCollection(mcpData.servers),
          commandCount: null,
          agentCount: null,
          skillCount: null,
          hookCount: null,
          pluginCount: pluginsData.plugins.length,
          permissionCount: null,
          outputStyleCount: null,
          allowRules: null,
          denyRules: null,
          settingsKeys: countCodexConfigEntries(configData),
          sessionCount: bridgeSessionsData.count ?? bridgeSessionsData.sessions.length,
          sessionMetricKind: 'live',
          sessionsToday: null,
          sessionsThisWeek: null,
          mostActiveProject: undefined,
          totalMessages: null,
          contextHighestPct: null,
          contextHighestProject: undefined,
          contextActiveCount: null,
          planCount: planStatsData.total_plans,
          featureFlagCount: featuresData.features.length,
          enabledFeatureFlagCount: featuresData.features.filter((feature) => feature.enabled).length,
          unsupportedFeatures: [
            'Slash commands',
            'Agents',
            'Skills',
            'Hooks',
            'Permissions',
            'Output styles',
            'Transcript context',
          ],
          warnings,
        });
        setLastFetched(new Date());
        return;
      }

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
        providerId,
        providerDisplayName,
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
        sessionMetricKind: 'transcript',
        sessionsToday: sessionStatsData.sessions_today,
        sessionsThisWeek: sessionStatsData.sessions_this_week,
        mostActiveProject: sessionStatsData.most_active_project,
        totalMessages: sessionStatsData.total_messages,
        contextHighestPct: highestCtx?.context_percentage ?? 0,
        contextHighestProject: highestCtx?.project_name,
        contextActiveCount: activeSessions.length,
        planCount: planStatsData.total_plans,
        featureFlagCount: null,
        enabledFeatureFlagCount: null,
        unsupportedFeatures: [],
        warnings: [],
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
  // getPlanStats changes with activeProject?.path and selectedProviderId; those are handled below.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProject?.path, selectedProvider?.display_name, selectedProviderId]);

  // Re-fetch when active project or provider changes (but not on initial mount)
  useEffect(() => {
    const currentPath = activeProject?.path;
    const currentProvider = selectedProviderId;
    const projectChanged = prevProjectPath.current !== undefined && prevProjectPath.current !== currentPath;
    const providerChanged = prevProviderId.current !== undefined && prevProviderId.current !== currentProvider;
    if (projectChanged || providerChanged) {
      fetchStats();
    }
    prevProjectPath.current = currentPath;
    prevProviderId.current = currentProvider;
  }, [activeProject?.path, selectedProviderId, fetchStats]);

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
