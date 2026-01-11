import type { Plugin } from "@/types/plugins";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Package, Info } from "lucide-react";

interface InstalledPluginsProps {
  plugins: Plugin[];
  loading: boolean;
  onViewDetails: (plugin: Plugin) => void;
  onUninstall: (name: string) => void;
  onToggle: (plugin: Plugin, enabled: boolean) => void;
}

export function InstalledPlugins({ plugins, loading, onViewDetails, onUninstall, onToggle }: InstalledPluginsProps) {
  if (loading) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        Loading installed plugins...
      </div>
    );
  }

  if (plugins.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Package className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
          <p className="text-muted-foreground mb-2">No plugins installed</p>
          <p className="text-sm text-muted-foreground">
            Browse the marketplace to discover and install plugins
          </p>
        </CardContent>
      </Card>
    );
  }

  // Helper to determine if plugin is local (can be uninstalled)
  const isLocalPlugin = (plugin: Plugin) => {
    return plugin.source === 'local' || plugin.source === 'local-project';
  };

  // Helper to format source name
  const formatSource = (source?: string) => {
    if (!source) return 'Unknown';
    if (source === 'local') return 'Local';
    if (source === 'local-project') return 'Project';
    // Format names like "anthropic-agent-skills" -> "Anthropic"
    if (source.includes('anthropic')) return 'Anthropic';
    if (source.includes('claude-plugins-official')) return 'Official';
    return source;
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {plugins.map((plugin) => (
        <Card
          key={`${plugin.name}-${plugin.source}`}
          className={`hover:border-primary/50 transition-colors ${plugin.enabled === false ? 'opacity-60' : ''}`}
        >
          <CardHeader>
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Package className="h-4 w-4" />
                  {plugin.name}
                </CardTitle>
                <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                  {plugin.version && <span>v{plugin.version}</span>}
                  {plugin.source && (
                    <Badge variant="secondary" className="text-xs">
                      {formatSource(plugin.source)}
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {plugin.category && (
                  <Badge variant="outline">
                    {plugin.category}
                  </Badge>
                )}
                {!isLocalPlugin(plugin) && plugin.enabled !== undefined && (
                  <Switch
                    checked={plugin.enabled}
                    onCheckedChange={(checked) => onToggle(plugin, checked)}
                    aria-label={`${plugin.enabled ? 'Disable' : 'Enable'} ${plugin.name}`}
                  />
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {plugin.description && (
              <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
                {plugin.description}
              </p>
            )}
            {plugin.author && (
              <p className="text-xs text-muted-foreground mb-4">
                by {plugin.author}
              </p>
            )}
            {plugin.components.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-4">
                {plugin.components.map((component, idx) => (
                  <Badge key={idx} variant="secondary">
                    {component.type}: {component.name}
                  </Badge>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() => onViewDetails(plugin)}
              >
                <Info className="h-4 w-4 mr-2" />
                Details
              </Button>
              {isLocalPlugin(plugin) && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => {
                    if (confirm(`Uninstall ${plugin.name}?`)) {
                      onUninstall(plugin.name);
                    }
                  }}
                >
                  Uninstall
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
