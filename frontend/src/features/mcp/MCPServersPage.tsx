import { useState, useEffect, useCallback } from "react";
import { Plus, Server } from "lucide-react";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { MCPServerList } from "./MCPServerList";
import { MCPServerWizard } from "./MCPServerWizard";
import { MCPServerForm } from "./MCPServerForm";
import { RefreshButton } from "@/components/shared/RefreshButton";
import type { MCPServer, MCPServerCreate, MCPServerUpdate, MCPServerListResponse } from "@/types/mcp";
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

  useEffect(() => {
    fetchServers();
  }, [fetchServers]);

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

      {/* Server List */}
      <MCPServerList
        servers={servers}
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
