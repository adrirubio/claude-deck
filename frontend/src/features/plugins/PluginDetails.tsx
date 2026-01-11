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
import { Package, User, Tag, Box, Globe, BookOpen, Lightbulb, FileText } from "lucide-react";

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

// Helper to determine if plugin is local (can be uninstalled)
const isLocalPlugin = (plugin: Plugin) => {
  return plugin.source === 'local' || plugin.source === 'local-project';
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 flex-wrap">
              <Package className="h-5 w-5" />
              <DialogTitle>{plugin.name}</DialogTitle>
              {plugin.version && (
                <Badge variant="outline">v{plugin.version}</Badge>
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

        <div className="space-y-6">
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

          {/* Components */}
          {plugin.components && plugin.components.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Box className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-semibold text-sm">Components</h3>
                <Badge variant="outline">{plugin.components.length}</Badge>
              </div>
              <div className="border rounded-lg p-4 space-y-2">
                {plugin.components.map((component, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2 rounded bg-muted/50"
                  >
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{component.type}</Badge>
                      <span className="text-sm font-mono">{component.name}</span>
                    </div>
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
        </div>

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
