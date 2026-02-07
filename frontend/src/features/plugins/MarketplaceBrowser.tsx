import { useState, useEffect } from "react";
import type { MarketplacePlugin, MarketplaceResponse, Plugin } from "@/types/plugins";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Download, Search, Store, AlertCircle, Trash2, CheckCircle, Info, ExternalLink, Loader2, Terminal, Bot, Puzzle, Server } from "lucide-react";

interface MarketplaceBrowserProps {
  marketplaces: MarketplaceResponse[];
  installedPlugins: Plugin[];
  onInstall: (plugin: MarketplacePlugin, marketplaceName: string) => void;
  onUninstall: (name: string) => void;
}

interface PluginDetails {
  name: string;
  description?: string;
  version?: string;
  author?: { name: string; email?: string } | string;
  category?: string;
  homepage?: string;
  github_url?: string;
  readme?: string;
  components?: { type: string; name: string }[];
  has_mcp?: boolean;
  has_lsp?: boolean;
}

export function MarketplaceBrowser({ marketplaces, installedPlugins, onInstall, onUninstall }: MarketplaceBrowserProps) {
  const [selectedMarketplace, setSelectedMarketplace] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<MarketplacePlugin[]>([]);
  const [filteredPlugins, setFilteredPlugins] = useState<MarketplacePlugin[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Preview dialog state
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewPlugin, setPreviewPlugin] = useState<MarketplacePlugin | null>(null);
  const [previewDetails, setPreviewDetails] = useState<PluginDetails | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

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

  // Handle preview dialog
  const handlePreview = async (plugin: MarketplacePlugin) => {
    setPreviewPlugin(plugin);
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewDetails(null);
    
    try {
      const response = await fetch(
        `/api/v1/plugins/marketplace/${selectedMarketplace}/plugin/${plugin.name}`
      );
      if (response.ok) {
        const details = await response.json();
        setPreviewDetails(details);
      }
    } catch {
      // Silently fail - we still show basic info
    } finally {
      setPreviewLoading(false);
    }
  };

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
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handlePreview(plugin)}
                    >
                      <Info className="h-4 w-4 mr-1" />
                      Info
                    </Button>
                    {installed ? (
                      <Button
                        className="flex-1"
                        variant="destructive"
                        size="sm"
                        onClick={() => onUninstall(plugin.name)}
                      >
                        <Trash2 className="h-4 w-4 mr-1" />
                        Uninstall
                      </Button>
                    ) : (
                      <Button
                        className="flex-1"
                        size="sm"
                        onClick={() => selectedMarketplace && onInstall(plugin, selectedMarketplace)}
                      >
                        <Download className="h-4 w-4 mr-1" />
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

      {/* Plugin Preview Dialog */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="sm:max-w-[700px] max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Puzzle className="h-5 w-5" />
              {previewPlugin?.name}
            </DialogTitle>
            <DialogDescription>
              {previewDetails?.category && (
                <Badge variant="outline" className="mr-2">{previewDetails.category}</Badge>
              )}
              {previewDetails?.version && `v${previewDetails.version}`}
            </DialogDescription>
          </DialogHeader>

          {previewLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <ScrollArea className="max-h-[60vh]">
              <div className="space-y-4 pr-4">
                {/* Description */}
                <p className="text-sm text-muted-foreground">
                  {previewDetails?.description || previewPlugin?.description}
                </p>

                {/* Author */}
                {previewDetails?.author && (
                  <div className="text-sm">
                    <span className="font-medium">Author: </span>
                    {typeof previewDetails.author === "string"
                      ? previewDetails.author
                      : previewDetails.author.name}
                  </div>
                )}

                {/* Components */}
                {previewDetails?.components && previewDetails.components.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium mb-2">Included Components</h4>
                    <div className="flex flex-wrap gap-2">
                      {previewDetails.components.map((c, i) => (
                        <Badge key={i} variant="secondary" className="flex items-center gap-1">
                          {c.type === "command" && <Terminal className="h-3 w-3" />}
                          {c.type === "agent" && <Bot className="h-3 w-3" />}
                          {c.type === "skill" && <Puzzle className="h-3 w-3" />}
                          {c.name}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Features */}
                {(previewDetails?.has_mcp || previewDetails?.has_lsp) && (
                  <div className="flex gap-2">
                    {previewDetails.has_mcp && (
                      <Badge variant="outline" className="flex items-center gap-1">
                        <Server className="h-3 w-3" />
                        MCP Server
                      </Badge>
                    )}
                    {previewDetails.has_lsp && (
                      <Badge variant="outline" className="flex items-center gap-1">
                        <Terminal className="h-3 w-3" />
                        LSP Server
                      </Badge>
                    )}
                  </div>
                )}

                {/* README */}
                {previewDetails?.readme && (
                  <div>
                    <h4 className="text-sm font-medium mb-2">README</h4>
                    <div className="text-sm text-muted-foreground bg-muted/50 rounded-lg p-3 whitespace-pre-wrap font-mono text-xs max-h-[300px] overflow-auto">
                      {previewDetails.readme}
                    </div>
                  </div>
                )}
              </div>
            </ScrollArea>
          )}

          <DialogFooter className="flex-col sm:flex-row gap-2">
            {previewDetails?.homepage && (
              <a
                href={previewDetails.homepage}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-10 px-4 py-2 w-full sm:w-auto"
              >
                <ExternalLink className="h-4 w-4" />
                View on GitHub
              </a>
            )}
            {previewPlugin && !isInstalled(previewPlugin.name) && (
              <Button
                className="w-full sm:w-auto"
                onClick={() => {
                  if (selectedMarketplace && previewPlugin) {
                    onInstall(previewPlugin, selectedMarketplace);
                    setPreviewOpen(false);
                  }
                }}
              >
                <Download className="h-4 w-4 mr-2" />
                Install Plugin
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
