import { useState, useEffect } from "react";
import { Edit2, Trash2, Play, AlertCircle, CheckCircle2, X, Wrench, ChevronDown, ChevronUp } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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

export function MCPServerCard({ server, onEdit, onDelete, onTestComplete: _onTestComplete, readOnly = false }: MCPServerCardProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<MCPTestConnectionResponse | null>(null);
  const [showTools, setShowTools] = useState(false);
  const [selectedTool, setSelectedTool] = useState<MCPTool | null>(null);

  // Auto-clear success results after 30 seconds (longer to allow viewing tools)
  useEffect(() => {
    if (testResult?.success && !testResult.tools?.length) {
      const timer = setTimeout(() => setTestResult(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [testResult]);

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
          const toolCount = response.tools?.length || 0;
          toast.success(`Connected! ${toolCount} tool${toolCount !== 1 ? 's' : ''} available`);
          if (toolCount > 0) {
            setShowTools(true);
          }
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
          <div>
            <CardTitle className="text-lg">{server.name}</CardTitle>
            <CardDescription className="mt-1">
              Type: {server.type === "stdio" ? "Standard I/O" : server.type === "sse" ? "Server-Sent Events" : "HTTP"}
            </CardDescription>
          </div>
          <Badge variant={server.scope === "user" ? "default" : server.scope === "plugin" ? "secondary" : "outline"}>
            {server.scope}
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
            {server.type === "http" && (
              <div>
                <span className="font-medium">URL:</span>{" "}
                <span className="text-muted-foreground font-mono break-all">{server.url}</span>
              </div>
            )}
            {server.env && Object.keys(server.env).length > 0 && (
              <div>
                <span className="font-medium">Environment:</span>{" "}
                <span className="text-muted-foreground">
                  {Object.keys(server.env).length} variable(s)
                </span>
              </div>
            )}
          </div>

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
              {testing ? "Testing..." : "Test"}
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
                      {testResult.tools.length} tool{testResult.tools.length !== 1 ? 's' : ''}
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
                    <button
                      key={index}
                      className="w-full text-left bg-background rounded p-2 text-sm hover:bg-accent transition-colors cursor-pointer"
                      onClick={() => setSelectedTool(tool)}
                    >
                      <div className="font-medium font-mono text-xs">{tool.name}</div>
                      {tool.description && (
                        <div className="text-xs text-muted-foreground mt-1 line-clamp-1">
                          {tool.description}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>

      {/* Tool Details Modal */}
      <Dialog open={!!selectedTool} onOpenChange={(open) => !open && setSelectedTool(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="font-mono">{selectedTool?.name}</DialogTitle>
          </DialogHeader>
          <DialogDescription className="text-sm whitespace-pre-wrap">
            {selectedTool?.description || "No description available"}
          </DialogDescription>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
