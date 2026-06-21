import {
  AlertCircle,
  Bot,
  CheckCircle2,
  LayoutDashboard,
  Terminal,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { useNavigate } from "react-router-dom";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { useDashboard } from "@/contexts/DashboardContext";
import { useProjectContext } from "@/contexts/ProjectContext";
import { useProviderContext } from "@/contexts/ProviderContext";
import { getRelativeTime } from "@/features/usage/utils";

export function DashboardPage() {
  const { stats, loading, error, lastFetched, refreshDashboard } = useDashboard(
    { autoFetch: true },
  );
  const { projects } = useProjectContext();
  const {
    providers,
    selectedProviderId,
    selectedProvider,
    setSelectedProviderId,
  } = useProviderContext();
  const navigate = useNavigate();
  const installedProviderCount = providers.filter(
    (provider) => provider.installed,
  ).length;
  const providerStats = stats?.providerId === selectedProviderId ? stats : null;
  const selectedProviderName =
    selectedProvider?.display_name ??
    (selectedProviderId === "codex-cli"
      ? "Codex"
      : selectedProviderId === "copilot-cli"
        ? "GitHub Copilot CLI"
        : selectedProviderId === "opencode-cli"
          ? "OpenCode CLI"
          : "Claude Code");
  const isCodex = selectedProviderId === "codex-cli";

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

      {loading && !providerStats && (
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

      {providerStats && providerStats.warnings.length > 0 && (
        <Card className="border-amber-500/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-amber-600 dark:text-amber-400">
              Partial {selectedProviderName} data
            </CardTitle>
            <CardDescription>
              Some provider-specific checks could not be loaded.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 text-xs text-muted-foreground">
              {providerStats.warnings.map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {providerStats && (
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
                  const isSelected = provider.id === selectedProviderId;
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      onClick={() => setSelectedProviderId(provider.id)}
                      className={`rounded-md border p-4 text-left transition-colors hover:bg-accent ${
                        isSelected
                          ? "border-primary bg-primary/5"
                          : "border-border"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Terminal className="h-4 w-4 shrink-0" />
                            <p className="font-medium">
                              {provider.display_name}
                            </p>
                            {isSelected && (
                              <Badge variant="secondary">Selected</Badge>
                            )}
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {provider.binary_path ??
                              provider.config_paths.home ??
                              "Binary not found"}
                          </p>
                        </div>
                        <Badge
                          variant={
                            provider.installed ? "outline" : "destructive"
                          }
                          className={
                            provider.installed
                              ? "text-green-600 dark:text-green-400"
                              : undefined
                          }
                        >
                          {provider.installed ? (
                            <CheckCircle2 className="mr-1 h-3 w-3" />
                          ) : (
                            <AlertCircle className="mr-1 h-3 w-3" />
                          )}
                          {provider.installed
                            ? (provider.version ?? "Installed")
                            : "Missing"}
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
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {isCodex ? (
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Codex Config</CardDescription>
                <CardTitle className="text-3xl">
                  {providerStats.settingsKeys}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Safe config entries, profiles, projects, and feature settings
                </p>
                <Button
                  variant="link"
                  className="p-0 h-auto mt-2"
                  onClick={() => navigate("/config")}
                >
                  View Codex config →
                </Button>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Projects</CardDescription>
                <CardTitle className="text-3xl">{projects.length}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Tracked Claude Code projects
                </p>
              </CardContent>
            </Card>
          )}

          {/* Tier 2: Core Configuration */}
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>
                {selectedProviderName} MCP Servers
              </CardDescription>
              <CardTitle className="text-3xl">
                {providerStats.mcpServerCount}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Configured MCP servers
              </p>
              <Button
                variant="link"
                className="p-0 h-auto mt-2"
                onClick={() => navigate("/mcp")}
              >
                Manage MCP servers →
              </Button>
            </CardContent>
          </Card>

          {!isCodex && (
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Claude Commands</CardDescription>
                <CardTitle className="text-3xl">
                  {providerStats.commandCount}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Claude slash commands available
                </p>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>{selectedProviderName} Plugins</CardDescription>
              <CardTitle className="text-3xl">
                {providerStats.pluginCount ?? 0}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                {isCodex
                  ? "Codex CLI plugin inventory rows"
                  : `Installed ${selectedProviderName} plugins`}
              </p>
              <Button
                variant="link"
                className="p-0 h-auto mt-2"
                onClick={() => navigate("/plugins")}
              >
                {isCodex ? "Open Codex plugins →" : "View plugins →"}
              </Button>
            </CardContent>
          </Card>

          {isCodex && (
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Codex Feature Flags</CardDescription>
                <CardTitle className="text-3xl">
                  {providerStats.featureFlagCount ?? 0}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  {providerStats.enabledFeatureFlagCount ?? 0} enabled
                </p>
                <Button
                  variant="link"
                  className="p-0 h-auto mt-2"
                  onClick={() => navigate("/config#codex-features")}
                >
                  Manage feature flags →
                </Button>
              </CardContent>
            </Card>
          )}

          {!isCodex && (
            <>
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription>Claude Hooks</CardDescription>
                  <CardTitle className="text-3xl">
                    {providerStats.hookCount}
                  </CardTitle>
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
                  <CardTitle className="text-3xl">
                    {providerStats.permissionCount}
                  </CardTitle>
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
                  <CardTitle className="text-3xl">
                    {providerStats.agentCount}
                  </CardTitle>
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
                  <CardTitle className="text-3xl">
                    {providerStats.skillCount}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Available skills
                  </p>
                </CardContent>
              </Card>
            </>
          )}

          {/* Tier 3: Customization */}
          {!isCodex && (
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Claude Output Styles</CardDescription>
                <CardTitle className="text-3xl">
                  {providerStats.outputStyleCount}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Custom output formats
                </p>
              </CardContent>
            </Card>
          )}

          {/* Tier 4: Monitoring */}
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>
                {providerStats.sessionMetricKind === "live"
                  ? `${selectedProviderName} Live Sessions`
                  : "Claude Session History"}
              </CardDescription>
              <CardTitle className="text-3xl">
                {providerStats.sessionCount}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {providerStats.sessionMetricKind === "live" ? (
                <p className="text-xs text-muted-foreground">
                  Sessions currently visible through Agent Bridge
                </p>
              ) : (
                <div className="text-xs text-muted-foreground space-y-1">
                  <p>{providerStats.sessionsToday} today</p>
                  <p>{providerStats.sessionsThisWeek} this week</p>
                  {providerStats.mostActiveProject && (
                    <p className="text-primary">
                      Most active: {providerStats.mostActiveProject}
                    </p>
                  )}
                </div>
              )}
              <Button
                variant="link"
                className="p-0 h-auto mt-2"
                onClick={() =>
                  navigate(
                    providerStats.sessionMetricKind === "live"
                      ? "/agent-bridge"
                      : "/sessions",
                  )
                }
              >
                {providerStats.sessionMetricKind === "live"
                  ? "View live sessions →"
                  : "View all sessions →"}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>
                {isCodex ? "Plan Snapshots" : "Plans"}
              </CardDescription>
              <CardTitle className="text-3xl">
                {providerStats.planCount}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                {isCodex ? "Codex update_plan snapshots" : "Execution plans"}
              </p>
              <Button
                variant="link"
                className="p-0 h-auto mt-2"
                onClick={() => navigate("/plans")}
              >
                View all plans →
              </Button>
            </CardContent>
          </Card>

          {!isCodex && (
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Claude Context Window</CardDescription>
                <CardTitle className="text-3xl">
                  {providerStats.contextActiveCount &&
                  providerStats.contextActiveCount > 0
                    ? `${(providerStats.contextHighestPct ?? 0).toFixed(0)}%`
                    : "--"}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {providerStats.contextActiveCount &&
                providerStats.contextActiveCount > 0 ? (
                  <div className="space-y-2">
                    <Progress
                      value={providerStats.contextHighestPct ?? 0}
                      className={`h-2 ${
                        (providerStats.contextHighestPct ?? 0) >= 95
                          ? "[&>div]:bg-red-500"
                          : (providerStats.contextHighestPct ?? 0) >= 80
                            ? "[&>div]:bg-orange-500"
                            : (providerStats.contextHighestPct ?? 0) >= 50
                              ? "[&>div]:bg-yellow-500"
                              : "[&>div]:bg-green-500"
                      }`}
                    />
                    <p className="text-xs text-muted-foreground">
                      {providerStats.contextActiveCount} active session
                      {providerStats.contextActiveCount !== 1 ? "s" : ""}
                      {providerStats.contextHighestProject &&
                        ` - ${providerStats.contextHighestProject}`}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No active sessions
                  </p>
                )}
                <Button
                  variant="link"
                  className="p-0 h-auto mt-2"
                  onClick={() => navigate("/context")}
                >
                  View context →
                </Button>
              </CardContent>
            </Card>
          )}

          {isCodex && providerStats.unsupportedFeatures.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Not shown for Codex</CardDescription>
                <CardTitle className="text-base">
                  Claude Code-only surfaces
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {providerStats.unsupportedFeatures.map((feature) => (
                    <Badge key={feature} variant="secondary">
                      {feature}
                    </Badge>
                  ))}
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  These cards are hidden because Codex does not expose
                  equivalent data through Claude Deck yet.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {providerStats && (
        <Card>
          <CardHeader>
            <CardTitle>Quick Status</CardTitle>
            <CardDescription>
              {selectedProviderName} configuration health indicators
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isCodex ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span>Config entries:</span>
                  <span className="font-medium">
                    {providerStats.settingsKeys}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span>MCP servers:</span>
                  <span className="font-medium">
                    {providerStats.mcpServerCount}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span>Plugins:</span>
                  <span className="font-medium">
                    {providerStats.pluginCount ?? 0}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span>Enabled features:</span>
                  <span className="font-medium">
                    {providerStats.enabledFeatureFlagCount ?? 0}
                  </span>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span>Settings keys:</span>
                  <span className="font-medium">
                    {providerStats.settingsKeys} configured
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span>Allow rules:</span>
                  <span className="font-medium text-success">
                    {providerStats.allowRules}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span>Deny rules:</span>
                  <span className="font-medium text-destructive">
                    {providerStats.denyRules}
                  </span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
