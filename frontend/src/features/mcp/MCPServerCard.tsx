import { useState, useEffect } from "react";
import {
  Edit2,
  Trash2,
  Play,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Circle,
  X,
  Wrench,
  FileText,
  MessageSquare,
  Shield,
  AlertTriangle,
  KeyRound,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Switch } from "@/components/ui/switch";
import type { MCPServer, MCPTestConnectionResponse } from "@/types/mcp";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { CLICKABLE_CARD } from "@/lib/constants";
import { getServerStatus } from "./mcpStatus";

interface MCPServerCardProps {
  server: MCPServer;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string, scope: string) => void;
  onTestComplete: () => void;
  onViewDetail: (server: MCPServer) => void;
  onToggle: (server: MCPServer, enabled: boolean) => void;
  readOnly?: boolean;
  approvalOverride?: string | null;
}

function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? singular + 's');
}

function getTransportSummary(server: MCPServer): string {
  if (server.type === "stdio") {
    const cmd = server.command || "";
    const args = server.args?.join(" ") || "";
    return `stdio · ${cmd}${args ? " " + args : ""}`;
  }
  return `${server.type} · ${server.url || ""}`;
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

const STATUS_ICONS = {
  connected: <CheckCircle2 className="h-4 w-4 text-green-500" />,
  failed: <XCircle className="h-4 w-4 text-red-500" />,
  "needs-auth": <AlertTriangle className="h-4 w-4 text-amber-500" />,
  "not-tested": <Circle className="h-4 w-4 text-muted-foreground" />,
} as const;

const STATUS_COLORS = {
  connected: "text-green-600 dark:text-green-400",
  failed: "text-red-600 dark:text-red-400",
  "needs-auth": "text-amber-600 dark:text-amber-400",
  "not-tested": "text-muted-foreground",
} as const;

export function MCPServerCard({
  server,
  onEdit,
  onDelete,
  onTestComplete,
  onViewDetail,
  onToggle,
  readOnly = false,
  approvalOverride,
}: MCPServerCardProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<MCPTestConnectionResponse | null>(null);

  // Auto-clear success results after 5 seconds
  useEffect(() => {
    if (testResult?.success) {
      const timer = setTimeout(() => setTestResult(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [testResult]);

  const toolCount = testResult?.tools?.length || server.tool_count || 0;
  const resourceCount = testResult?.resource_count || server.resource_count || 0;
  const promptCount = testResult?.prompt_count || server.prompt_count || 0;

  // Connection status
  const status = getServerStatus(server, testResult);

  const handleTest = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setTesting(true);
    setTestResult(null);
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

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm(`Are you sure you want to delete the MCP server "${server.name}"?`)) {
      onDelete(server.name, server.scope);
    }
  };

  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    onEdit(server);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onViewDetail(server);
    }
  };

  return (
    <Card
      className={`${CLICKABLE_CARD}${server.disabled ? " opacity-50" : ""}`}
      tabIndex={0}
      onClick={() => onViewDetail(server)}
      onKeyDown={handleKeyDown}
      role="button"
      aria-label={`View details for ${server.name}`}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-lg truncate flex-1 min-w-0">
            {server.name}
          </CardTitle>
          <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
            {approvalOverride && (
              <Badge variant="outline" className="text-xs gap-1">
                <Shield className="h-3 w-3" />
                {approvalOverride === "always-allow" ? "allow" :
                 approvalOverride === "always-deny" ? "deny" : "ask"}
              </Badge>
            )}
            <Badge variant={getScopeBadgeVariant(server.scope)}>
              {getScopeLabel(server.scope, server.source)}
            </Badge>
            <Switch
              checked={!server.disabled}
              onCheckedChange={(checked) => onToggle(server, checked)}
              aria-label={`${server.disabled ? "Enable" : "Disable"} ${server.name}`}
            />
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap mt-1">
          <span className="inline-flex items-center gap-1">
            {STATUS_ICONS[status.status]}
            <span className={`text-xs font-medium ${STATUS_COLORS[status.status]}`}>
              {status.label}
            </span>
          </span>
          {toolCount > 0 && (
            <Badge variant="secondary" className="text-xs gap-1">
              <Wrench className="h-3 w-3" />
              {toolCount}
            </Badge>
          )}
          {resourceCount > 0 && (
            <Badge variant="secondary" className="text-xs gap-1">
              <FileText className="h-3 w-3" />
              {resourceCount}
            </Badge>
          )}
          {promptCount > 0 && (
            <Badge variant="secondary" className="text-xs gap-1">
              <MessageSquare className="h-3 w-3" />
              {promptCount}
            </Badge>
          )}
        </div>
        <CardDescription className="truncate mt-1">
          {getTransportSummary(server)}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-3">
          {/* Supplementary details */}
          {(server.mcp_server_version || (server.env && Object.keys(server.env).length > 0) || server.last_tested_at) && (
            <div className="text-sm text-muted-foreground space-y-1">
              {server.mcp_server_version && (
                <div>Version {server.mcp_server_version}</div>
              )}
              {server.env && Object.keys(server.env).length > 0 && (
                <div>
                  {Object.keys(server.env).length} env {pluralize(Object.keys(server.env).length, 'variable')}
                </div>
              )}
              {server.last_tested_at && (
                <div>
                  Tested {new Date(server.last_tested_at).toLocaleString()}
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            {status.status === "needs-auth" ? (
              <Button
                size="sm"
                variant="outline"
                onClick={(e) => {
                  e.stopPropagation();
                  onViewDetail(server);
                }}
                className="flex-1"
              >
                <KeyRound className="h-4 w-4 mr-2" />
                Authenticate
              </Button>
            ) : (
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
            )}
            {!readOnly && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleEdit}
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
            <div className="mt-3">
              {status.status === "needs-auth" ? (
                <Alert
                  className="relative border-amber-500/50 bg-amber-50/50 dark:bg-amber-950/20 text-amber-800 dark:text-amber-200"
                >
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                  <AlertDescription className="pr-6">
                    <div className="font-mono text-xs break-all">
                      {testResult.message}
                    </div>
                  </AlertDescription>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="absolute top-1 right-1 h-6 w-6 p-0"
                    onClick={(e) => {
                      e.stopPropagation();
                      setTestResult(null);
                    }}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </Alert>
              ) : (
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
                  </AlertDescription>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="absolute top-1 right-1 h-6 w-6 p-0"
                    onClick={(e) => {
                      e.stopPropagation();
                      setTestResult(null);
                    }}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </Alert>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
