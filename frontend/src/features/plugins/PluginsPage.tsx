import { useState, useEffect, useCallback, useMemo } from "react";
import type {
  Plugin,
  MarketplacePlugin,
  MarketplaceResponse,
  PluginTab,
  PluginUpdateInfo,
} from "@/types/plugins";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, Package, Store, Settings, Globe, ArrowUpCircle } from "lucide-react";
import { InstalledPlugins } from "./InstalledPlugins";
import { PluginDetails } from "./PluginDetails";
import { MarketplaceBrowser } from "./MarketplaceBrowser";
import { PluginInstallWizard } from "./PluginInstallWizard";
import { MarketplaceManager } from "./MarketplaceManager";
import { AllAvailablePlugins } from "./AllAvailablePlugins";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";

export function PluginsPage() {
  const { activeProject } = useProjectContext();
  const [activeTab, setActiveTab] = useState<PluginTab>("installed");
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [marketplaces, setMarketplaces] = useState<MarketplaceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Update tracking
  const [updateInfo, setUpdateInfo] = useState<Map<string, PluginUpdateInfo>>(new Map());
  const [checkingUpdates, setCheckingUpdates] = useState(false);

  // Search state (shared across tabs)
  const [searchQuery, setSearchQuery] = useState("");

  // Plugin details dialog
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  // Install wizard
  const [pluginToInstall, setPluginToInstall] = useState<MarketplacePlugin | null>(null);
  const [installMarketplaceName, setInstallMarketplaceName] = useState<string | null>(null);
  const [installWizardOpen, setInstallWizardOpen] = useState(false);

  // Show marketplace manager
  const [showMarketplaceManager, setShowMarketplaceManager] = useState(false);

  // Count updates available
  const updatesCount = useMemo(() => {
    let count = 0;
    updateInfo.forEach((info) => {
      if (info.has_update) count++;
    });
    return count;
  }, [updateInfo]);

  const fetchPlugins = useCallback(async () => {
    try {
      const endpoint = buildEndpoint("plugins", { project_path: activeProject?.path });
      const data = await apiClient<{ plugins: Plugin[] }>(endpoint);
      setPlugins(data.plugins || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load plugins");
    }
  }, [activeProject?.path]);

  const fetchMarketplaces = useCallback(async () => {
    try {
      const endpoint = buildEndpoint("plugins/marketplaces", { project_path: activeProject?.path });
      const data = await apiClient<{ marketplaces: MarketplaceResponse[] }>(endpoint);
      setMarketplaces(data.marketplaces || []);
    } catch (err) {
      console.error("Failed to load marketplaces:", err);
    }
  }, [activeProject?.path]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    await Promise.all([fetchPlugins(), fetchMarketplaces()]);
    setLoading(false);
  }, [fetchPlugins, fetchMarketplaces]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCheckUpdates = useCallback(async () => {
    setCheckingUpdates(true);
    try {
      const data = await apiClient<{ plugins: PluginUpdateInfo[]; outdated_count: number }>(
        "plugins/updates"
      );
      const newUpdateInfo = new Map<string, PluginUpdateInfo>();
      data.plugins.forEach((info) => {
        newUpdateInfo.set(info.name, info);
      });
      setUpdateInfo(newUpdateInfo);
      if (data.outdated_count > 0) {
        toast.info(`${data.outdated_count} plugin(s) have updates available`);
      } else {
        toast.success("All plugins are up to date");
      }
    } catch {
      toast.error("Failed to check for updates");
    } finally {
      setCheckingUpdates(false);
    }
  }, []);

  const handleUpdatePlugin = useCallback(async (name: string) => {
    try {
      const data = await apiClient<{ success: boolean; message: string }>(
        `/api/v1/plugins/${name}/update`,
        { method: "POST" }
      );
      if (data.success) {
        toast.success(`Plugin "${name}" updated successfully`);
        // Refresh plugins and clear update info for this plugin
        fetchPlugins();
        setUpdateInfo((prev) => {
          const newMap = new Map(prev);
          newMap.delete(name);
          return newMap;
        });
      } else {
        toast.error(data.message);
      }
    } catch {
      toast.error(`Failed to update plugin "${name}"`);
    }
  }, [fetchPlugins]);

  const handleUpdateAll = useCallback(async () => {
    try {
      const data = await apiClient<{
        success: boolean;
        message: string;
        updated_count: number;
        failed_count: number;
}>("plugins/update-all", { method: "POST" });
      
      if (data.updated_count > 0) {
        toast.success(`Updated ${data.updated_count} plugin(s)`);
      }
      if (data.failed_count > 0) {
        toast.error(`${data.failed_count} plugin(s) failed to update`);
      }
      
      // Refresh plugins and clear update info
      fetchPlugins();
      setUpdateInfo(new Map());
    } catch {
      toast.error("Failed to update plugins");
    }
  }, [fetchPlugins]);

  const handleEnableAll = useCallback(async () => {
    let successCount = 0;
    for (const plugin of plugins) {
      if (plugin.enabled === false && plugin.source !== "local" && plugin.source !== "local-project") {
        try {
          await apiClient(`/api/v1/plugins/${plugin.name}/toggle`, {
            method: "POST",
            body: JSON.stringify({ enabled: true, source: plugin.source }),
          });
          successCount++;
        } catch {
          // Continue with other plugins
        }
      }
    }
    if (successCount > 0) {
      toast.success(`Enabled ${successCount} plugin(s)`);
      fetchPlugins();
    }
  }, [plugins, fetchPlugins]);

  const handleDisableAll = useCallback(async () => {
    let successCount = 0;
    for (const plugin of plugins) {
      if (plugin.enabled !== false && plugin.source !== "local" && plugin.source !== "local-project") {
        try {
          await apiClient(`/api/v1/plugins/${plugin.name}/toggle`, {
            method: "POST",
            body: JSON.stringify({ enabled: false, source: plugin.source }),
          });
          successCount++;
        } catch {
          // Continue with other plugins
        }
      }
    }
    if (successCount > 0) {
      toast.success(`Disabled ${successCount} plugin(s)`);
      fetchPlugins();
    }
  }, [plugins, fetchPlugins]);

  const handleViewDetails = (plugin: Plugin) => {
    setSelectedPlugin(plugin);
    setDetailsOpen(true);
  };

  const handleUninstall = async (name: string) => {
    try {
      const endpoint = buildEndpoint(`plugins/${name}`, { project_path: activeProject?.path });
      await apiClient(endpoint, { method: "DELETE" });

      toast.success(`Plugin "${name}" uninstalled successfully`);
      fetchPlugins();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to uninstall plugin");
    }
  };

  const handleInstall = (plugin: MarketplacePlugin, marketplaceName: string) => {
    setPluginToInstall(plugin);
    setInstallMarketplaceName(marketplaceName);
    setInstallWizardOpen(true);
  };

  const handleInstallComplete = () => {
    fetchPlugins();
  };

  const handleToggle = async (plugin: Plugin, enabled: boolean) => {
    try {
      const endpoint = buildEndpoint(`plugins/${plugin.name}/toggle`, { project_path: activeProject?.path });
      const data = await apiClient<{ message: string }>(endpoint, {
        method: "POST",
        body: JSON.stringify({
          enabled,
          source: plugin.source,
        }),
      });

      toast.success(data.message);
      fetchPlugins();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to toggle plugin");
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Package className="h-8 w-8" />
            Plugins
          </h1>
          <p className="text-muted-foreground mt-2">
            Manage Claude Code plugins and browse marketplace
          </p>
        </div>
        {updatesCount > 0 && (
          <Button variant="default" onClick={handleUpdateAll} className="bg-orange-500 hover:bg-orange-600">
            <ArrowUpCircle className="h-4 w-4 mr-2" />
            Update All ({updatesCount})
          </Button>
        )}
      </div>

      {/* Error display */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="py-4">
            <p className="text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <Button onClick={fetchData} variant="outline" disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
        <Button
          variant="outline"
          onClick={() => setShowMarketplaceManager(!showMarketplaceManager)}
        >
          <Settings className="h-4 w-4 mr-2" />
          {showMarketplaceManager ? "Hide" : "Manage"} Marketplaces
        </Button>
      </div>

      {/* Marketplace Manager */}
      {showMarketplaceManager && (
        <MarketplaceManager marketplaces={marketplaces} onRefresh={fetchMarketplaces} />
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as PluginTab)}>
        <TabsList>
          <TabsTrigger value="installed" className="flex items-center gap-2">
            <Package className="h-4 w-4" />
            Installed ({plugins.length})
            {updatesCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 text-xs bg-orange-500 text-white rounded-full">
                {updatesCount}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="marketplace" className="flex items-center gap-2">
            <Store className="h-4 w-4" />
            Marketplace
          </TabsTrigger>
          <TabsTrigger value="available" className="flex items-center gap-2">
            <Globe className="h-4 w-4" />
            All Available
          </TabsTrigger>
        </TabsList>

        <TabsContent value="installed">
          <InstalledPlugins
            plugins={plugins}
            loading={loading}
            updateInfo={updateInfo}
            checkingUpdates={checkingUpdates}
            onViewDetails={handleViewDetails}
            onUninstall={handleUninstall}
            onToggle={handleToggle}
            onUpdate={handleUpdatePlugin}
            onCheckUpdates={handleCheckUpdates}
            onUpdateAll={handleUpdateAll}
            onEnableAll={handleEnableAll}
            onDisableAll={handleDisableAll}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
          />
        </TabsContent>

        <TabsContent value="marketplace">
          <MarketplaceBrowser
            marketplaces={marketplaces}
            installedPlugins={plugins}
            onInstall={handleInstall}
            onUninstall={handleUninstall}
          />
        </TabsContent>

        <TabsContent value="available">
          <AllAvailablePlugins
            installedPlugins={plugins}
            onInstall={handleInstall}
            onViewDetails={handleViewDetails}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
          />
        </TabsContent>
      </Tabs>

      {/* Plugin Details Dialog */}
      <PluginDetails
        plugin={selectedPlugin}
        open={detailsOpen}
        onOpenChange={setDetailsOpen}
        onUninstall={handleUninstall}
        onToggle={handleToggle}
      />

      {/* Install Wizard Dialog */}
      <PluginInstallWizard
        plugin={pluginToInstall}
        marketplaceName={installMarketplaceName}
        open={installWizardOpen}
        onOpenChange={setInstallWizardOpen}
        onComplete={handleInstallComplete}
      />
    </div>
  );
}
