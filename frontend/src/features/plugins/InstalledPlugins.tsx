import { useState, useMemo } from "react";
import type { Plugin, PluginUpdateInfo, PluginStatusFilter, PluginUpdateFilter } from "@/types/plugins";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Package,
  Info,
  Search,
  RefreshCw,
  Power,
  PowerOff,
  ArrowUpCircle,
} from "lucide-react";

interface InstalledPluginsProps {
  plugins: Plugin[];
  loading: boolean;
  updateInfo: Map<string, PluginUpdateInfo>;
  checkingUpdates: boolean;
  onViewDetails: (plugin: Plugin) => void;
  onUninstall: (name: string) => void;
  onToggle: (plugin: Plugin, enabled: boolean) => void;
  onUpdate: (name: string) => void;
  onCheckUpdates: () => void;
  onUpdateAll: () => void;
  onEnableAll: () => void;
  onDisableAll: () => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export function InstalledPlugins({
  plugins,
  loading,
  updateInfo,
  checkingUpdates,
  onViewDetails,
  onUninstall,
  onToggle,
  onUpdate,
  onCheckUpdates,
  onUpdateAll,
  onEnableAll,
  onDisableAll,
  searchQuery,
  onSearchChange,
}: InstalledPluginsProps) {
  const [statusFilter, setStatusFilter] = useState<PluginStatusFilter>("all");
  const [updateFilter, setUpdateFilter] = useState<PluginUpdateFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  // Get unique sources for filter dropdown
  const sources = useMemo(() => {
    const uniqueSources = new Set<string>();
    plugins.forEach((p) => {
      if (p.source) uniqueSources.add(p.source);
    });
    return Array.from(uniqueSources).sort();
  }, [plugins]);

  // Count updates available
  const updatesAvailable = useMemo(() => {
    return plugins.filter((p) => updateInfo.get(p.name)?.has_update).length;
  }, [plugins, updateInfo]);

  // Filter plugins
  const filteredPlugins = useMemo(() => {
    return plugins.filter((plugin) => {
      // Search filter
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const matchesName = plugin.name.toLowerCase().includes(query);
        const matchesDesc = plugin.description?.toLowerCase().includes(query);
        if (!matchesName && !matchesDesc) return false;
      }

      // Status filter
      if (statusFilter === "enabled" && plugin.enabled === false) return false;
      if (statusFilter === "disabled" && plugin.enabled !== false) return false;

      // Update filter
      const hasUpdate = updateInfo.get(plugin.name)?.has_update;
      if (updateFilter === "updates-available" && !hasUpdate) return false;
      if (updateFilter === "up-to-date" && hasUpdate) return false;

      // Source filter
      if (sourceFilter !== "all" && plugin.source !== sourceFilter) return false;

      return true;
    });
  }, [plugins, searchQuery, statusFilter, updateFilter, sourceFilter, updateInfo]);

  // Helper to determine if plugin is local (can be uninstalled)
  const isLocalPlugin = (plugin: Plugin) => {
    return plugin.source === "local" || plugin.source === "local-project";
  };

  // Helper to format source name
  const formatSource = (source?: string) => {
    if (!source) return "Unknown";
    if (source === "local") return "Local";
    if (source === "local-project") return "Project";
    if (source.includes("anthropic")) return "Anthropic";
    if (source.includes("claude-plugins-official")) return "Official";
    return source;
  };

  if (loading) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        Loading installed plugins...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search and Filters Bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search plugins..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as PluginStatusFilter)}>
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="enabled">Enabled</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
        <Select value={updateFilter} onValueChange={(v) => setUpdateFilter(v as PluginUpdateFilter)}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Updates" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Updates</SelectItem>
            <SelectItem value="updates-available">Has Updates</SelectItem>
            <SelectItem value="up-to-date">Up to Date</SelectItem>
          </SelectContent>
        </Select>
        {sources.length > 1 && (
          <Select value={sourceFilter} onValueChange={setSourceFilter}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="Source" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Sources</SelectItem>
              {sources.map((source) => (
                <SelectItem key={source} value={source}>
                  {formatSource(source)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Bulk Actions Bar */}
      <div className="flex flex-wrap items-center gap-2 p-3 bg-muted/50 rounded-lg">
        <span className="text-sm text-muted-foreground mr-2">
          {filteredPlugins.length} of {plugins.length} plugins
        </span>
        <Button size="sm" variant="outline" onClick={onCheckUpdates} disabled={checkingUpdates}>
          <RefreshCw className={`h-4 w-4 mr-2 ${checkingUpdates ? "animate-spin" : ""}`} />
          Check Updates
        </Button>
        {updatesAvailable > 0 && (
          <Button size="sm" variant="default" onClick={onUpdateAll}>
            <ArrowUpCircle className="h-4 w-4 mr-2" />
            Update All ({updatesAvailable})
          </Button>
        )}
        <div className="flex-1" />
        <Button size="sm" variant="outline" onClick={onEnableAll}>
          <Power className="h-4 w-4 mr-2" />
          Enable All
        </Button>
        <Button size="sm" variant="outline" onClick={onDisableAll}>
          <PowerOff className="h-4 w-4 mr-2" />
          Disable All
        </Button>
      </div>

      {/* Plugin List */}
      {filteredPlugins.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Package className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
            {plugins.length === 0 ? (
              <>
                <p className="text-muted-foreground mb-2">No plugins installed</p>
                <p className="text-sm text-muted-foreground">
                  Browse the marketplace to discover and install plugins
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">No plugins match your filters</p>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredPlugins.map((plugin) => {
            const pluginUpdate = updateInfo.get(plugin.name);
            const hasUpdate = pluginUpdate?.has_update;

            return (
              <Card
                key={`${plugin.name}-${plugin.source}`}
                className={`hover:border-primary/50 transition-colors ${
                  plugin.enabled === false ? "opacity-60" : ""
                } ${hasUpdate ? "border-orange-500/50" : ""}`}
              >
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <CardTitle className="text-lg flex items-center gap-2">
                        <Package className="h-4 w-4" />
                        {plugin.name}
                        {hasUpdate && (
                          <Badge variant="default" className="bg-orange-500 text-xs">
                            Update
                          </Badge>
                        )}
                      </CardTitle>
                      <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground flex-wrap">
                        {plugin.version && (
                          <span className="flex items-center gap-1">
                            v{plugin.version}
                            {hasUpdate && pluginUpdate?.latest_version && (
                              <span className="text-orange-500">
                                → v{pluginUpdate.latest_version}
                              </span>
                            )}
                          </span>
                        )}
                        {plugin.source && (
                          <Badge variant="secondary" className="text-xs">
                            {formatSource(plugin.source)}
                          </Badge>
                        )}
                        {plugin.scope && (
                          <Badge variant="outline" className="text-xs">
                            {plugin.scope}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {plugin.category && (
                        <Badge variant="outline">{plugin.category}</Badge>
                      )}
                      {!isLocalPlugin(plugin) && plugin.enabled !== undefined && (
                        <Switch
                          checked={plugin.enabled}
                          onCheckedChange={(checked) => onToggle(plugin, checked)}
                          aria-label={`${plugin.enabled ? "Disable" : "Enable"} ${plugin.name}`}
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
                      {plugin.components.slice(0, 3).map((component, idx) => (
                        <Badge key={idx} variant="secondary">
                          {component.type}: {component.name}
                        </Badge>
                      ))}
                      {plugin.components.length > 3 && (
                        <Badge variant="secondary">+{plugin.components.length - 3}</Badge>
                      )}
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
                    {hasUpdate && (
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => onUpdate(plugin.name)}
                        className="bg-orange-500 hover:bg-orange-600"
                      >
                        <ArrowUpCircle className="h-4 w-4 mr-2" />
                        Update
                      </Button>
                    )}
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
            );
          })}
        </div>
      )}
    </div>
  );
}
