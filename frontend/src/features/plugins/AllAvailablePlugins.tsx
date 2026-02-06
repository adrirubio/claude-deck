import { useState, useEffect, useMemo } from "react";
import type { MarketplacePlugin, Plugin } from "@/types/plugins";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Package, Download, Search, CheckCircle, Loader2 } from "lucide-react";

interface AllAvailablePluginsProps {
  installedPlugins: Plugin[];
  onInstall: (plugin: MarketplacePlugin, marketplaceName: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export function AllAvailablePlugins({
  installedPlugins,
  onInstall,
  searchQuery,
  onSearchChange,
}: AllAvailablePluginsProps) {
  const [plugins, setPlugins] = useState<MarketplacePlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Set of installed plugin names for quick lookup
  const installedNames = useMemo(() => {
    return new Set(installedPlugins.map((p) => p.name));
  }, [installedPlugins]);

  // Fetch all available plugins
  useEffect(() => {
    const fetchPlugins = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch("/api/v1/plugins/available");
        if (!response.ok) {
          throw new Error("Failed to fetch available plugins");
        }
        const data = await response.json();
        setPlugins(data.plugins || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load plugins");
      } finally {
        setLoading(false);
      }
    };

    fetchPlugins();
  }, []);

  // Filter plugins by search query
  const filteredPlugins = useMemo(() => {
    if (!searchQuery) return plugins;
    
    const query = searchQuery.toLowerCase();
    return plugins.filter((plugin) => {
      const matchesName = plugin.name.toLowerCase().includes(query);
      const matchesDesc = plugin.description?.toLowerCase().includes(query);
      return matchesName || matchesDesc;
    });
  }, [plugins, searchQuery]);

  if (loading) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
        Loading available plugins...
      </div>
    );
  }

  if (error) {
    return (
      <Card className="border-destructive">
        <CardContent className="py-12 text-center">
          <p className="text-destructive">{error}</p>
          <Button
            variant="outline"
            className="mt-4"
            onClick={() => window.location.reload()}
          >
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search Bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search all available plugins..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Stats */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>{filteredPlugins.length} plugins available</span>
        <span>•</span>
        <span>{installedNames.size} installed</span>
      </div>

      {/* Plugin Grid */}
      {filteredPlugins.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Package className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
            {plugins.length === 0 ? (
              <>
                <p className="text-muted-foreground mb-2">No plugins available</p>
                <p className="text-sm text-muted-foreground">
                  Add a marketplace to browse available plugins
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">
                No plugins match your search
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredPlugins.map((plugin) => {
            const isInstalled = installedNames.has(plugin.name);

            return (
              <Card
                key={plugin.name}
                className={`hover:border-primary/50 transition-colors ${
                  isInstalled ? "border-green-500/30 bg-green-500/5" : ""
                }`}
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
                        {isInstalled && (
                          <Badge variant="default" className="bg-green-500 text-xs">
                            <CheckCircle className="h-3 w-3 mr-1" />
                            Installed
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {plugin.description && (
                    <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
                      {plugin.description}
                    </p>
                  )}
                  <div className="flex gap-2">
                    {isInstalled ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1"
                        disabled
                      >
                        <CheckCircle className="h-4 w-4 mr-2 text-green-500" />
                        Installed
                      </Button>
                    ) : (
                      <Button
                        variant="default"
                        size="sm"
                        className="flex-1"
                        onClick={() => onInstall(plugin, "")}
                      >
                        <Download className="h-4 w-4 mr-2" />
                        Install
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
