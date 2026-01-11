import { useState, useEffect } from "react";
import type { MarketplacePlugin, MarketplaceResponse, Plugin } from "@/types/plugins";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Download, Search, Store, AlertCircle, Trash2, CheckCircle } from "lucide-react";

interface MarketplaceBrowserProps {
  marketplaces: MarketplaceResponse[];
  installedPlugins: Plugin[];
  onInstall: (plugin: MarketplacePlugin, marketplaceName: string) => void;
  onUninstall: (name: string) => void;
}

export function MarketplaceBrowser({ marketplaces, installedPlugins, onInstall, onUninstall }: MarketplaceBrowserProps) {
  const [selectedMarketplace, setSelectedMarketplace] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<MarketplacePlugin[]>([]);
  const [filteredPlugins, setFilteredPlugins] = useState<MarketplacePlugin[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check if a plugin is already installed
  const isInstalled = (pluginName: string) => {
    return installedPlugins?.some((p) => p.name === pluginName) ?? false;
  };

  // Select first marketplace by default
  useEffect(() => {
    if (marketplaces.length > 0 && selectedMarketplace === null) {
      setSelectedMarketplace(marketplaces[0].name);
    }
  }, [marketplaces, selectedMarketplace]);

  // Fetch marketplace plugins when marketplace changes
  useEffect(() => {
    if (selectedMarketplace === null) {
      return;
    }

    const marketplace = marketplaces.find((m) => m.name === selectedMarketplace);
    if (!marketplace) {
      return;
    }

    setLoading(true);
    setError(null);

    fetch(`/api/v1/plugins/marketplace/${selectedMarketplace}/browse`)
      .then((res) => {
        if (!res.ok) {
          throw new Error("Failed to load marketplace");
        }
        return res.json();
      })
      .then((data) => {
        setPlugins(data.plugins || []);
        setFilteredPlugins(data.plugins || []);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [selectedMarketplace, marketplaces]);

  // Filter plugins based on search query
  useEffect(() => {
    if (!searchQuery.trim()) {
      setFilteredPlugins(plugins);
      return;
    }

    const query = searchQuery.toLowerCase();
    const filtered = plugins.filter(
      (plugin) =>
        plugin.name.toLowerCase().includes(query) ||
        (plugin.description?.toLowerCase().includes(query) ?? false)
    );
    setFilteredPlugins(filtered);
  }, [searchQuery, plugins]);

  if (marketplaces.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Store className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
          <p className="text-lg font-medium text-muted-foreground mb-2">No custom marketplaces configured</p>
          <p className="text-sm text-muted-foreground mb-4 max-w-md mx-auto">
            The Marketplace tab is for discovering plugins from external sources.
            Official Claude plugins from Anthropic are shown in the Installed tab when enabled in your settings.
          </p>
          <p className="text-sm text-muted-foreground">
            Click "Manage Marketplaces" above to add a custom plugin repository.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Marketplace selector and search */}
      <div className="flex gap-4">
        <select
          className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          value={selectedMarketplace || ""}
          onChange={(e) => setSelectedMarketplace(e.target.value)}
        >
          {marketplaces.map((marketplace) => (
            <option key={marketplace.name} value={marketplace.name}>
              {marketplace.name}
              {marketplace.last_updated && ` (updated ${new Date(marketplace.last_updated).toLocaleDateString()})`}
            </option>
          ))}
        </select>

        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search plugins..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="text-center py-12 text-muted-foreground">
          Loading marketplace plugins...
        </div>
      )}

      {/* Error state */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="py-6 flex items-center gap-2 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <span>Error: {error}</span>
          </CardContent>
        </Card>
      )}

      {/* Plugin grid */}
      {!loading && !error && filteredPlugins.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            {searchQuery ? "No plugins match your search" : "No plugins available in this marketplace"}
          </CardContent>
        </Card>
      )}

      {!loading && !error && filteredPlugins.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredPlugins.map((plugin) => {
            const installed = isInstalled(plugin.name);
            return (
              <Card key={plugin.name} className="hover:border-primary/50 transition-colors">
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    {installed ? (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                    {plugin.name}
                    {installed && (
                      <Badge variant="secondary" className="ml-auto">
                        Installed
                      </Badge>
                    )}
                  </CardTitle>
                  {plugin.version && (
                    <CardDescription>v{plugin.version}</CardDescription>
                  )}
                </CardHeader>
                <CardContent>
                  {plugin.description && (
                    <p className="text-sm text-muted-foreground mb-4 line-clamp-3">
                      {plugin.description}
                    </p>
                  )}
                  {installed ? (
                    <Button
                      className="w-full"
                      variant="destructive"
                      onClick={() => onUninstall(plugin.name)}
                    >
                      <Trash2 className="h-4 w-4 mr-2" />
                      Uninstall
                    </Button>
                  ) : (
                    <Button
                      className="w-full"
                      onClick={() => selectedMarketplace && onInstall(plugin, selectedMarketplace)}
                    >
                      <Download className="h-4 w-4 mr-2" />
                      Install
                    </Button>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
