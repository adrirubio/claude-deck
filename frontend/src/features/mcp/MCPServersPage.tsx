import { useState, useEffect, useCallback } from "react";
import { Plus, Server, Shield, Info } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { MCPServerList } from "./MCPServerList";
import { MCPServerWizard } from "./MCPServerWizard";
import { MCPServerForm } from "./MCPServerForm";
import { RefreshButton } from "@/components/shared/RefreshButton";
import type { MCPServer, MCPServerCreate, MCPServerUpdate, MCPServerListResponse, MCPServerApprovalSettings } from "@/types/mcp";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";

export function MCPServersPage() {
  const { activeProject } = useProjectContext();
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showWizard, setShowWizard] = useState(false);
  const [editingServer, setEditingServer] = useState<MCPServer | null>(null);
  const [approvalSettingsOpen, setApprovalSettingsOpen] = useState(false);
  const [approvalSettings, setApprovalSettings] = useState<MCPServerApprovalSettings | null>(null);

  // Separate managed servers from editable ones
  const managedServers = servers.filter(s => s.scope === "managed");
  const editableServers = servers.filter(s => s.scope !== "managed");

  const fetchServers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = buildEndpoint("mcp/servers", { project_path: activeProject?.path });
      const response = await apiClient<MCPServerListResponse>(endpoint);
      setServers(response.servers);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load MCP servers";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  const fetchApprovalSettings = useCallback(async () => {
    try {
      const response = await apiClient<MCPServerApprovalSettings>("mcp/approval-settings");
      setApprovalSettings(response);
    } catch {
      // Silently fail - approval settings are optional
    }
  }, []);

  useEffect(() => {
    fetchServers();
    fetchApprovalSettings();
  }, [fetchServers, fetchApprovalSettings]);

  const handleApprovalSettingsChange = async (defaultMode: string) => {
    try {
      const updated = await apiClient<MCPServerApprovalSettings>("mcp/approval-settings", {
        method: "PUT",
        body: JSON.stringify({
          default_mode: defaultMode,
          server_overrides: approvalSettings?.server_overrides || [],
        }),
      });
      setApprovalSettings(updated);
      toast.success("Approval settings updated");
    } catch {
      toast.error("Failed to update approval settings");
    }
  };

  const handleAddServer = async (server: MCPServerCreate) => {
    try {
      const endpoint = buildEndpoint("mcp/servers", { project_path: activeProject?.path });
      await apiClient<MCPServer>(endpoint, {
        method: "POST",
        body: JSON.stringify(server),
      });

      toast.success(`MCP server "${server.name}" added successfully`);
      setShowWizard(false);
      await fetchServers();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to add server";
      toast.error(message);
      throw err; // Re-throw to let the wizard handle the error state
    }
  };

  const handleUpdateServer = async (name: string, scope: string, updates: MCPServerUpdate) => {
    try {
      const endpoint = buildEndpoint(`mcp/servers/${name}`, {
        scope,
        project_path: activeProject?.path,
      });
      await apiClient<MCPServer>(endpoint, {
        method: "PUT",
        body: JSON.stringify(updates),
      });

      toast.success(`MCP server "${name}" updated successfully`);
      setEditingServer(null);
      await fetchServers();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to update server";
      toast.error(message);
      throw err;
    }
  };

  const handleDeleteServer = async (name: string, scope: string) => {
    try {
      const endpoint = buildEndpoint(`mcp/servers/${name}`, {
        scope,
        project_path: activeProject?.path,
      });
      await apiClient(endpoint, {
        method: "DELETE",
      });

      toast.success(`MCP server "${name}" removed successfully`);
      await fetchServers();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to remove server";
      toast.error(message);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Server className="h-8 w-8" />
            MCP Servers
          </h1>
          <p className="text-muted-foreground mt-1">
            Manage Model Context Protocol server configurations
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onClick={fetchServers} loading={loading} />
          <Button onClick={() => setShowWizard(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add Server
          </Button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Managed Servers Section */}
      {managedServers.length > 0 && (
        <Card className="border-amber-500/50 bg-amber-50/50 dark:bg-amber-950/20">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-amber-600" />
              <CardTitle className="text-lg">Managed Servers</CardTitle>
              <Badge variant="outline" className="text-amber-600 border-amber-600">
                Enterprise
              </Badge>
            </div>
            <CardDescription>
              These servers are configured by your organization and cannot be modified.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <MCPServerList
              servers={managedServers}
              loading={false}
              onEdit={() => {}}
              onDelete={() => {}}
              onTestComplete={fetchServers}
              readOnly
            />
          </CardContent>
        </Card>
      )}

      {/* Approval Settings Panel */}
      <Collapsible open={approvalSettingsOpen} onOpenChange={setApprovalSettingsOpen}>
        <Card>
          <CollapsibleTrigger asChild>
            <CardHeader className="cursor-pointer hover:bg-muted/50 transition-colors">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Info className="h-5 w-5" />
                  <CardTitle className="text-lg">Server Approval Settings</CardTitle>
                </div>
                <Badge variant="outline">
                  {approvalSettings?.default_mode === "always-allow" ? "Auto-approve" :
                   approvalSettings?.default_mode === "always-deny" ? "Always deny" : "Ask each time"}
                </Badge>
              </div>
              <CardDescription>
                Control how MCP tool calls are approved
              </CardDescription>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className="pt-0">
              <div className="space-y-4">
                <div>
                  <Label htmlFor="default-approval">Default Approval Mode</Label>
                  <Select
                    value={approvalSettings?.default_mode || "ask-every-time"}
                    onValueChange={handleApprovalSettingsChange}
                  >
                    <SelectTrigger id="default-approval" className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ask-every-time">Ask every time</SelectItem>
                      <SelectItem value="always-allow">Always allow (trust all servers)</SelectItem>
                      <SelectItem value="always-deny">Always deny</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-2">
                    This controls whether Claude Code asks for permission before using MCP tools.
                  </p>
                </div>
              </div>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>

      {/* Server List */}
      <MCPServerList
        servers={editableServers}
        loading={loading}
        onEdit={setEditingServer}
        onDelete={handleDeleteServer}
        onTestComplete={fetchServers}
      />

      {/* Add Server Wizard Dialog */}
      <Dialog open={showWizard} onOpenChange={setShowWizard}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add MCP Server</DialogTitle>
            <DialogDescription>
              Configure a new Model Context Protocol server
            </DialogDescription>
          </DialogHeader>
          <MCPServerWizard
            onSave={handleAddServer}
            onCancel={() => setShowWizard(false)}
          />
        </DialogContent>
      </Dialog>

      {/* Edit Server Dialog */}
      <Dialog open={!!editingServer} onOpenChange={(open) => !open && setEditingServer(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit MCP Server</DialogTitle>
            <DialogDescription>
              Update the configuration for {editingServer?.name}
            </DialogDescription>
          </DialogHeader>
          {editingServer && (
            <MCPServerForm
              server={editingServer}
              onSave={handleUpdateServer}
              onCancel={() => setEditingServer(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
