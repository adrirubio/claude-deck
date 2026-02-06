import type { Plugin } from "@/types/plugins";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Package,
  User,
  Tag,
  Box,
  Globe,
  BookOpen,
  Lightbulb,
  FileText,
  Zap,
  Bot,
  Terminal,
  Server,
  Code,
  FolderOpen,
} from "lucide-react";

interface PluginDetailsProps {
  plugin: Plugin | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUninstall: (name: string) => void;
  onToggle?: (plugin: Plugin, enabled: boolean) => void;
}

// Helper to format source name
const formatSource = (source?: string) => {
  if (!source) return 'Unknown';
  if (source === 'local') return 'Local Installation';
  if (source === 'local-project') return 'Project Installation';
  if (source.includes('anthropic')) return 'Anthropic Official';
  if (source.includes('claude-plugins-official')) return 'Claude Official';
  return source;
};

// Helper to format scope
const formatScope = (scope?: string) => {
  if (!scope) return null;
  const scopeMap: Record<string, { label: string; variant: "default" | "secondary" | "outline" }> = {
    user: { label: "User", variant: "default" },
    project: { label: "Project", variant: "secondary" },
    local: { label: "Local", variant: "outline" },
  };
  return scopeMap[scope];
};

// Helper to determine if plugin is local (can be uninstalled)
const isLocalPlugin = (plugin: Plugin) => {
  return plugin.source === 'local' || plugin.source === 'local-project';
};

// Component type icon mapping
const getComponentIcon = (type: string) => {
  switch (type) {
    case 'skill':
    case 'command':
      return <Terminal className="h-4 w-4" />;
    case 'agent':
      return <Bot className="h-4 w-4" />;
    case 'hook':
      return <Zap className="h-4 w-4" />;
    case 'mcp':
      return <Server className="h-4 w-4" />;
    case 'lsp':
      return <Code className="h-4 w-4" />;
    default:
      return <Box className="h-4 w-4" />;
  }
};

export function PluginDetails({ plugin, open, onOpenChange, onUninstall, onToggle }: PluginDetailsProps) {
  if (!plugin) {
    return null;
  }

  const handleUninstall = () => {
    if (confirm(`Are you sure you want to uninstall ${plugin.name}?`)) {
      onUninstall(plugin.name);
      onOpenChange(false);
    }
  };

  const scopeInfo = formatScope(plugin.scope);

  // Calculate component totals
  const hasComponents = plugin.components && plugin.components.length > 0;
  const hasHooks = plugin.hooks && plugin.hooks.length > 0;
  const hasLSP = plugin.lsp_configs && plugin.lsp_configs.length > 0;
  const hasComponentBreakdown = (plugin.skill_count || 0) + (plugin.agent_count || 0) +
    (plugin.hook_count || 0) + (plugin.mcp_count || 0) + (plugin.lsp_count || 0) > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 flex-wrap">
              <Package className="h-5 w-5" />
              <DialogTitle>{plugin.name}</DialogTitle>
              {plugin.version && (
                <Badge variant="outline">v{plugin.version}</Badge>
              )}
              {scopeInfo && (
                <Badge variant={scopeInfo.variant}>
                  <FolderOpen className="h-3 w-3 mr-1" />
                  {scopeInfo.label}
                </Badge>
              )}
            </div>
            {!isLocalPlugin(plugin) && plugin.enabled !== undefined && onToggle && (
              <div className="flex items-center gap-2">
                <Label htmlFor="plugin-enabled" className="text-sm text-muted-foreground">
                  {plugin.enabled ? 'Enabled' : 'Disabled'}
                </Label>
                <Switch
                  id="plugin-enabled"
                  checked={plugin.enabled}
                  onCheckedChange={(checked) => onToggle(plugin, checked)}
                />
              </div>
            )}
          </div>
          <DialogDescription>
            {plugin.description || 'No description available'}
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="overview" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="components">Components</TabsTrigger>
            <TabsTrigger value="hooks" disabled={!hasHooks}>Hooks</TabsTrigger>
            <TabsTrigger value="lsp" disabled={!hasLSP}>LSP</TabsTrigger>
          </TabsList>

          {/* Overview Tab */}
          <TabsContent value="overview" className="space-y-6">
            {/* Metadata */}
            <div className="space-y-3 border rounded-lg p-4 bg-muted/30">
              <h3 className="font-semibold text-sm mb-3">Plugin Information</h3>

              {/* Source */}
              <div className="flex items-center gap-2 text-sm">
                <Globe className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Source:</span>
                <span className="font-medium">{formatSource(plugin.source)}</span>
                {plugin.source && !isLocalPlugin(plugin) && (
                  <Badge variant="secondary" className="text-xs ml-1">
                    {plugin.source}
                  </Badge>
                )}
              </div>

              {plugin.author && (
                <div className="flex items-center gap-2 text-sm">
                  <User className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Author:</span>
                  <span className="font-medium">{plugin.author}</span>
                </div>
              )}

              {plugin.category && (
                <div className="flex items-center gap-2 text-sm">
                  <Tag className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Category:</span>
                  <span className="font-medium">{plugin.category}</span>
                </div>
              )}

              {plugin.version && (
                <div className="flex items-center gap-2 text-sm">
                  <Package className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Version:</span>
                  <span className="font-medium">{plugin.version}</span>
                </div>
              )}
            </div>

            {/* Component Summary */}
            {hasComponentBreakdown && (
              <div className="space-y-3">
                <h3 className="font-semibold text-sm">Component Summary</h3>
                <div className="grid grid-cols-5 gap-2">
                  <div className="border rounded-lg p-3 text-center bg-muted/30">
                    <Terminal className="h-5 w-5 mx-auto mb-1 text-blue-500" />
                    <div className="text-2xl font-bold">{plugin.skill_count || 0}</div>
                    <div className="text-xs text-muted-foreground">Skills</div>
                  </div>
                  <div className="border rounded-lg p-3 text-center bg-muted/30">
                    <Bot className="h-5 w-5 mx-auto mb-1 text-purple-500" />
                    <div className="text-2xl font-bold">{plugin.agent_count || 0}</div>
                    <div className="text-xs text-muted-foreground">Agents</div>
                  </div>
                  <div className="border rounded-lg p-3 text-center bg-muted/30">
                    <Zap className="h-5 w-5 mx-auto mb-1 text-yellow-500" />
                    <div className="text-2xl font-bold">{plugin.hook_count || 0}</div>
                    <div className="text-xs text-muted-foreground">Hooks</div>
                  </div>
                  <div className="border rounded-lg p-3 text-center bg-muted/30">
                    <Server className="h-5 w-5 mx-auto mb-1 text-green-500" />
                    <div className="text-2xl font-bold">{plugin.mcp_count || 0}</div>
                    <div className="text-xs text-muted-foreground">MCP</div>
                  </div>
                  <div className="border rounded-lg p-3 text-center bg-muted/30">
                    <Code className="h-5 w-5 mx-auto mb-1 text-orange-500" />
                    <div className="text-2xl font-bold">{plugin.lsp_count || 0}</div>
                    <div className="text-xs text-muted-foreground">LSP</div>
                  </div>
                </div>
              </div>
            )}

            {/* Usage Instructions */}
            {plugin.usage && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-semibold text-sm">How to Use</h3>
                </div>
                <div className="border rounded-lg p-4 bg-muted/30">
                  <p className="text-sm">{plugin.usage}</p>
                </div>
              </div>
            )}

            {/* Examples */}
            {plugin.examples && plugin.examples.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Lightbulb className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-semibold text-sm">Examples</h3>
                </div>
                <div className="border rounded-lg p-4 space-y-2">
                  {plugin.examples.map((example, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-2 p-2 rounded bg-muted/50"
                    >
                      <span className="text-muted-foreground mt-0.5">•</span>
                      <span className="text-sm font-mono">{example}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* README Content (for local plugins) */}
            {plugin.readme && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-semibold text-sm">Documentation</h3>
                </div>
                <div className="border rounded-lg p-4 bg-muted/30 max-h-64 overflow-y-auto">
                  <pre className="text-sm whitespace-pre-wrap font-mono">{plugin.readme}</pre>
                </div>
              </div>
            )}

            {/* Info for settings-based plugins */}
            {!isLocalPlugin(plugin) && (
              <div className="text-sm text-muted-foreground bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                <p className="font-medium text-blue-700 dark:text-blue-300 mb-1">Official Plugin</p>
                <p>
                  This plugin's state is managed via the <code className="mx-1 px-1 py-0.5 bg-blue-100 dark:bg-blue-900 rounded text-xs">enabledPlugins</code> setting
                  in <code className="mx-1 px-1 py-0.5 bg-blue-100 dark:bg-blue-900 rounded text-xs">~/.claude/settings.json</code>.
                  Use the toggle above to enable or disable it.
                </p>
              </div>
            )}
          </TabsContent>

          {/* Components Tab */}
          <TabsContent value="components" className="space-y-4">
            {hasComponents ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Box className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-semibold text-sm">Plugin Components</h3>
                  <Badge variant="outline">{plugin.components.length}</Badge>
                </div>
                <div className="border rounded-lg divide-y">
                  {plugin.components.map((component, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between p-3"
                    >
                      <div className="flex items-center gap-3">
                        <div className="p-2 rounded-md bg-muted">
                          {getComponentIcon(component.type)}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm">{component.name}</span>
                            <Badge variant="secondary" className="text-xs capitalize">
                              {component.type}
                            </Badge>
                          </div>
                          {component.description && (
                            <p className="text-xs text-muted-foreground mt-0.5">
                              {component.description}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <Box className="h-12 w-12 mx-auto mb-3 opacity-50" />
                <p>No components defined in plugin.json</p>
                <p className="text-sm">Components are discovered from plugin directories</p>
              </div>
            )}
          </TabsContent>

          {/* Hooks Tab */}
          <TabsContent value="hooks" className="space-y-4">
            {hasHooks && plugin.hooks ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-semibold text-sm">Plugin-Defined Hooks</h3>
                  <Badge variant="outline">{plugin.hooks.length}</Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  These hooks are defined by the plugin and are read-only.
                </p>
                <div className="border rounded-lg divide-y">
                  {plugin.hooks.map((hook, idx) => (
                    <div key={idx} className="p-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <Badge variant="default">{hook.event}</Badge>
                        <Badge variant="secondary">{hook.type}</Badge>
                        {hook.matcher && (
                          <code className="text-xs bg-muted px-1.5 py-0.5 rounded">
                            {hook.matcher}
                          </code>
                        )}
                      </div>
                      {hook.command && (
                        <div className="text-sm font-mono bg-muted rounded p-2">
                          {hook.command}
                        </div>
                      )}
                      {hook.prompt && (
                        <div className="text-sm bg-muted rounded p-2">
                          {hook.prompt}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <Zap className="h-12 w-12 mx-auto mb-3 opacity-50" />
                <p>No hooks defined for this plugin</p>
              </div>
            )}
          </TabsContent>

          {/* LSP Tab */}
          <TabsContent value="lsp" className="space-y-4">
            {hasLSP && plugin.lsp_configs ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Code className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-semibold text-sm">LSP Server Configurations</h3>
                  <Badge variant="outline">{plugin.lsp_configs.length}</Badge>
                </div>
                <div className="border rounded-lg divide-y">
                  {plugin.lsp_configs.map((config, idx) => (
                    <div key={idx} className="p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{config.name}</span>
                          <Badge variant="outline">{config.language}</Badge>
                        </div>
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm">
                          <span className="text-muted-foreground">Command: </span>
                          <code className="bg-muted px-1.5 py-0.5 rounded">
                            {config.command}
                          </code>
                        </div>
                        {config.args && config.args.length > 0 && (
                          <div className="text-sm">
                            <span className="text-muted-foreground">Args: </span>
                            <code className="bg-muted px-1.5 py-0.5 rounded">
                              {config.args.join(' ')}
                            </code>
                          </div>
                        )}
                        {config.env && Object.keys(config.env).length > 0 && (
                          <div className="text-sm">
                            <span className="text-muted-foreground">Environment:</span>
                            <div className="mt-1 bg-muted rounded p-2 font-mono text-xs">
                              {Object.entries(config.env).map(([key, value]) => (
                                <div key={key}>
                                  {key}={value}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <Code className="h-12 w-12 mx-auto mb-3 opacity-50" />
                <p>No LSP configurations for this plugin</p>
              </div>
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          {isLocalPlugin(plugin) && (
            <Button variant="destructive" onClick={handleUninstall}>
              Uninstall Plugin
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
