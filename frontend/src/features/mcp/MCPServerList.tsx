import type { MCPServer } from "@/types/mcp";
import { MCPServerCard } from "./MCPServerCard";

interface MCPServerListProps {
  servers: MCPServer[];
  loading: boolean;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string, scope: string) => void;
  onTestComplete: () => void;
}

export function MCPServerList({ servers, loading, onEdit, onDelete, onTestComplete }: MCPServerListProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-muted-foreground">Loading MCP servers...</p>
      </div>
    );
  }

  if (servers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <p className="text-muted-foreground mb-2">No MCP servers configured</p>
        <p className="text-sm text-muted-foreground">
          Click "Add Server" to configure your first MCP server
        </p>
      </div>
    );
  }

  // Group servers by scope
  const userServers = servers.filter(s => s.scope === "user");
  const projectServers = servers.filter(s => s.scope === "project");
  const pluginServers = servers.filter(s => s.scope === "plugin");

  return (
    <div className="space-y-6">
      {userServers.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-3">User Servers</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {userServers.map((server) => (
              <MCPServerCard
                key={`${server.scope}-${server.name}`}
                server={server}
                onEdit={onEdit}
                onDelete={onDelete}
                onTestComplete={onTestComplete}
              />
            ))}
          </div>
        </div>
      )}

      {projectServers.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-3">Project Servers</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projectServers.map((server) => (
              <MCPServerCard
                key={`${server.scope}-${server.name}`}
                server={server}
                onEdit={onEdit}
                onDelete={onDelete}
                onTestComplete={onTestComplete}
              />
            ))}
          </div>
        </div>
      )}

      {pluginServers.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-3">Plugin Servers</h3>
          <p className="text-xs text-muted-foreground mb-3">
            These servers are provided by installed plugins and cannot be edited directly.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {pluginServers.map((server) => (
              <MCPServerCard
                key={`${server.scope}-${server.name}`}
                server={server}
                onEdit={onEdit}
                onDelete={onDelete}
                onTestComplete={onTestComplete}
                readOnly
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
