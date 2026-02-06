import { useState, useEffect } from "react";
import { Edit2, Trash2, Play, AlertCircle, CheckCircle2, X, Wrench, ChevronDown, ChevronUp, Search } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { MCPServer, MCPTestConnectionResponse, MCPTool } from "@/types/mcp";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

interface MCPServerCardProps {
  server: MCPServer;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string, scope: string) => void;
  onTestComplete: () => void;
  readOnly?: boolean;
}

function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? singular + 's');
}

function getServerTypeLabel(type: string): string {
  switch (type) {
    case "stdio": return "Standard I/O";
    case "sse": return "Server-Sent Events";
    default: return "HTTP";
  }
}

function getScopeBadgeVariant(scope: string): "default" | "secondary" | "outline" | "destructive" {
  switch (scope) {
    case "managed": return "destructive";
    case "user": return "default";
    case "plugin": return "secondary";
    case "project": return "outline";
    default: return "outline";
  }
}

function getScopeLabel(scope: string, source?: string): string {
  switch (scope) {
    case "managed": return "enforced";
    case "plugin": return source ? `plugin:${source}` : "plugin";
    default: return scope;
  }
}

interface ToolListItemProps {
  tool: MCPTool;
  onClick: () => void;
}

function ToolListItem({ tool, onClick }: ToolListItemProps) {
  return (
    <button
      className="w-full text-left bg-background rounded p-2 text-sm hover:bg-accent transition-colors cursor-pointer"
      onClick={onClick}
    >
      <div className="font-medium font-mono text-xs">{tool.name}</div>
      {tool.description && (
        <div className="text-xs text-muted-foreground mt-1 line-clamp-1">
          {tool.description}
        </div>
      )}
    </button>
  );
}

export function MCPServerCard({ server, onEdit, onDelete, onTestComplete, readOnly = false }: MCPServerCardProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<MCPTestConnectionResponse | null>(null);
  const [showTools, setShowTools] = useState(false);
  const [selectedTool, setSelectedTool] = useState<MCPTool | null>(null);
  const [toolFilter, setToolFilter] = useState("");

  // Auto-clear success results after 30 seconds (longer to allow viewing tools)
  useEffect(() => {
    if (testResult?.success && !testResult.tools?.length) {
      const timer = setTimeout(() => setTestResult(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [testResult]);

  // Get tools to display (from test result or cached data)
  const displayTools = testResult?.tools || server.tools || null;
  const toolCount = testResult?.tools?.length || server.tool_count || 0;

  // Filter tools based on search
  const filteredTools = displayTools?.filter(
    (tool) =>
      tool.name.toLowerCase().includes(toolFilter.toLowerCase()) ||
      tool.description?.toLowerCase().includes(toolFilter.toLowerCase())
  );

  // Connection status indicator
  function getConnectionInfo(): { icon: string; label: string } {
    const isConnected = testResult?.success ?? server.is_connected;
    if (isConnected === true) {
      return { icon: "🟢", label: "Connected" };
    }
    if (isConnected === false) {
      return { icon: "🔴", label: "Failed" };
    }
    return { icon: "⚪", label: "Not tested" };
  }

  const connectionInfo = getConnectionInfo();

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    setShowTools(false);
    try {
      const response = await apiClient<MCPTestConnectionResponse>(
        `mcp/servers/${encodeURIComponent(server.name)}/test?scope=${server.scope}`,
        { method: "POST" }
      );

      if (response && typeof response.success === "boolean") {
        setTestResult(response);
        if (response.success) {
          const responseToolCount = response.tools?.length || 0;
          toast.success(`Connected! ${responseToolCount} ${pluralize(responseToolCount, 'tool')} available`);
          if (responseToolCount > 0) {
            setShowTools(true);
          }
          onTestComplete();
        } else {
          toast.error("Connection failed");
        }
      } else {
        setTestResult({ success: false, message: "Invalid response from server" });
        toast.error("Invalid response from server");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTestResult({ success: false, message: `Failed to test connection: ${message}` });
      toast.error(`Test failed: ${message}`);
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = () => {
    if (confirm(`Are you sure you want to delete the MCP server "${server.name}"?`)) {
      onDelete(server.name, server.scope);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-lg">{server.name}</CardTitle>
              <span className="text-xs" title={connectionInfo.label}>
                {connectionInfo.icon}
              </span>
              {toolCount > 0 && (
                <Badge variant="secondary" className="text-xs">
                  {toolCount} {pluralize(toolCount, 'tool')}
                </Badge>
              )}
            </div>
            <CardDescription className="mt-1">
              Type: {getServerTypeLabel(server.type)}
              {server.last_tested_at && (
                <span className="ml-2 text-xs">
                  • Tested {new Date(server.last_tested_at).toLocaleString()}
                </span>
              )}
            </CardDescription>
          </div>
          <Badge variant={getScopeBadgeVariant(server.scope)}>
            {getScopeLabel(server.scope, server.source)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {/* Server Details */}
          <div className="text-sm space-y-1">
            {server.type === "stdio" && (
              <>
                <div>
                  <span className="font-medium">Command:</span>{" "}
                  <span className="text-muted-foreground font-mono">{server.command}</span>
                </div>
                {server.args && server.args.length > 0 && (
                  <div>
                    <span className="font-medium">Args:</span>{" "}
                    <span className="text-muted-foreground font-mono">
                      {server.args.join(" ")}
                    </span>
                  </div>
                )}
              </>
            )}
            {(server.type === "http" || server.type === "sse") && (
              <div>
                <span className="font-medium">URL:</span>{" "}
                <span className="text-muted-foreground font-mono break-all">{server.url}</span>
              </div>
            )}
            {server.env && Object.keys(server.env).length > 0 && (
              <div>
                <span className="font-medium">Environment:</span>{" "}
                <span className="text-muted-foreground">
                  {Object.keys(server.env).length} {pluralize(Object.keys(server.env).length, 'variable')}
                </span>
              </div>
            )}
          </div>

          {/* Cached Tools Display */}
          {!testResult && displayTools && displayTools.length > 0 && (
            <div className="bg-muted/30 rounded-md p-3">
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-between h-auto py-2"
                onClick={() => setShowTools(!showTools)}
              >
                <div className="flex items-center gap-2">
                  <Wrench className="h-4 w-4" />
                  <span className="text-sm font-medium">
                    {toolCount} cached {pluralize(toolCount, 'tool')}
                  </span>
                </div>
                {showTools ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </Button>
              {showTools && (
                <div className="mt-2 space-y-2">
                  {toolCount > 5 && (
                    <div className="relative">
                      <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        placeholder="Filter tools..."
                        value={toolFilter}
                        onChange={(e) => setToolFilter(e.target.value)}
                        className="pl-8 h-8 text-sm"
                      />
                    </div>
                  )}
                  <div className="space-y-1 max-h-60 overflow-y-auto">
                    {filteredTools?.map((tool, index) => (
                      <ToolListItem
                        key={index}
                        tool={tool}
                        onClick={() => setSelectedTool(tool)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <Button
              size="sm"
              variant="outline"
              onClick={handleTest}
              disabled={testing}
              className="flex-1"
            >
              <Play className="h-4 w-4 mr-2" />
              {testing ? "Testing..." : "Re-test"}
            </Button>
            {!readOnly && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onEdit(server)}
                >
                  <Edit2 className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleDelete}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>

          {/* Test Result Display */}
          {testResult && (
            <div className="mt-3 space-y-2">
              <Alert
                variant={testResult.success ? "default" : "destructive"}
                className="relative"
              >
                {testResult.success ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <AlertCircle className="h-4 w-4" />
                )}
                <AlertDescription className="pr-6">
                  <div className="font-mono text-xs break-all">
                    {testResult.message}
                  </div>
                  {testResult.success && testResult.tools && testResult.tools.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mt-2 h-6 px-2 text-xs"
                      onClick={() => setShowTools(!showTools)}
                    >
                      <Wrench className="h-3 w-3 mr-1" />
                      {testResult.tools.length} {pluralize(testResult.tools.length, 'tool')}
                      {showTools ? (
                        <ChevronUp className="h-3 w-3 ml-1" />
                      ) : (
                        <ChevronDown className="h-3 w-3 ml-1" />
                      )}
                    </Button>
                  )}
                </AlertDescription>
                <Button
                  size="sm"
                  variant="ghost"
                  className="absolute top-1 right-1 h-6 w-6 p-0"
                  onClick={() => setTestResult(null)}
                >
                  <X className="h-3 w-3" />
                </Button>
              </Alert>

              {/* Tools List */}
              {showTools && testResult.success && testResult.tools && (
                <div className="bg-muted/50 rounded-md p-3 space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">Available Tools</div>
                  {testResult.tools.map((tool, index) => (
                    <ToolListItem
                      key={index}
                      tool={tool}
                      onClick={() => setSelectedTool(tool)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>

      {/* Tool Details Modal */}
      <Dialog open={!!selectedTool} onOpenChange={(open) => !open && setSelectedTool(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono">{selectedTool?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <h4 className="text-sm font-medium mb-2">Description</h4>
              <DialogDescription className="text-sm whitespace-pre-wrap">
                {selectedTool?.description || "No description available"}
              </DialogDescription>
            </div>
            {selectedTool?.inputSchema && (
              <div>
                <h4 className="text-sm font-medium mb-2">Input Schema</h4>
                <div className="bg-muted rounded-md p-3 space-y-2">
                  {selectedTool.inputSchema.properties && (
                    <div>
                      <div className="text-xs font-medium text-muted-foreground mb-2">Parameters</div>
                      {Object.entries(selectedTool.inputSchema.properties).map(([key, prop]) => (
                        <div key={key} className="text-sm mb-1">
                          <span className="font-mono font-medium">{key}</span>
                          {selectedTool.inputSchema?.required?.includes(key) && (
                            <span className="text-red-500 ml-1">*</span>
                          )}
                          <span className="text-muted-foreground ml-2">({prop.type})</span>
                          {prop.description && (
                            <div className="text-xs text-muted-foreground ml-4 mt-1">
                              {prop.description}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                      View raw schema
                    </summary>
                    <pre className="mt-2 bg-background rounded p-2 overflow-x-auto">
                      {JSON.stringify(selectedTool.inputSchema, null, 2)}
                    </pre>
                  </details>
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
