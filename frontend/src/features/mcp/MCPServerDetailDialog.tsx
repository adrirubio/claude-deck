import { useState, useEffect, useRef, useCallback } from "react";
import {
  CheckCircle2,
  XCircle,
  Circle,
  AlertTriangle,
  Play,
  Search,
  Edit2,
  Trash2,
  Wrench,
  FileText,
  MessageSquare,
  AlertCircle,
  KeyRound,
  Loader2,
  ExternalLink,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { MODAL_SIZES } from "@/lib/constants";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { getServerStatus, type MCPConnectionStatus } from "./mcpStatus";
import type {
  MCPServer,
  MCPTestConnectionResponse,
  MCPTool,
  MCPResource,
  MCPPrompt,
  MCPServerApprovalSettings,
  MCPAuthStatus,
  MCPAuthStartResponse,
} from "@/types/mcp";

interface MCPServerDetailDialogProps {
  server: MCPServer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string, scope: string) => void;
  onTestComplete: () => void;
  approvalSettings: MCPServerApprovalSettings | null;
  onApprovalChange: (serverName: string, mode: string | null) => void;
  readOnly?: boolean;
}

function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? singular + "s");
}

function getServerTypeLabel(type: string): string {
  switch (type) {
    case "stdio":
      return "Standard I/O";
    case "sse":
      return "Server-Sent Events";
    default:
      return "HTTP";
  }
}

function getScopeBadgeVariant(
  scope: string
): "default" | "secondary" | "outline" | "destructive" {
  switch (scope) {
    case "managed":
      return "destructive";
    case "user":
      return "default";
    case "plugin":
      return "secondary";
    case "project":
      return "outline";
    default:
      return "outline";
  }
}

function getScopeLabel(scope: string, source?: string): string {
  switch (scope) {
    case "managed":
      return "enforced";
    case "plugin":
      return source ? `plugin:${source}` : "plugin";
    default:
      return scope;
  }
}

const STATUS_ICONS_LG = {
  connected: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  failed: <XCircle className="h-5 w-5 text-red-500" />,
  "needs-auth": <AlertTriangle className="h-5 w-5 text-amber-500" />,
  "not-tested": <Circle className="h-5 w-5 text-muted-foreground" />,
} as const;

const STATUS_COLORS = {
  connected: "text-green-600 dark:text-green-400",
  failed: "text-red-600 dark:text-red-400",
  "needs-auth": "text-amber-600 dark:text-amber-400",
  "not-tested": "text-muted-foreground",
} as const;

// --- Tool Detail Section ---
function ToolDetailView({ tool }: { tool: MCPTool }) {
  const [showRaw, setShowRaw] = useState(false);
  return (
    <div className="border rounded-md p-3 space-y-2 bg-muted/30">
      <div className="font-mono text-sm font-medium">{tool.name}</div>
      {tool.description && (
        <p className="text-sm text-muted-foreground">{tool.description}</p>
      )}
      {tool.inputSchema?.properties && (
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-1">
            Parameters
          </div>
          {Object.entries(tool.inputSchema.properties).map(([key, prop]) => (
            <div key={key} className="text-sm mb-1">
              <span className="font-mono font-medium">{key}</span>
              {tool.inputSchema?.required?.includes(key) && (
                <span className="text-red-500 ml-1">*</span>
              )}
              <span className="text-muted-foreground ml-2">({prop.type})</span>
              {prop.description && (
                <div className="text-xs text-muted-foreground ml-4 mt-0.5">
                  {prop.description}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {tool.inputSchema && (
        <div>
          <button
            className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            onClick={() => setShowRaw(!showRaw)}
          >
            {showRaw ? "Hide" : "View"} raw schema
          </button>
          {showRaw && (
            <pre className="mt-1 bg-background rounded p-2 overflow-x-auto text-xs">
              {JSON.stringify(tool.inputSchema, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// --- Authentication Section (HTTP/SSE servers only) ---
function AuthSection({
  server,
  serverStatus,
  onAuthComplete,
}: {
  server: MCPServer;
  serverStatus: MCPConnectionStatus;
  onAuthComplete: () => void;
}) {
  const [authStatus, setAuthStatus] = useState<MCPAuthStatus | null>(null);
  const [authenticating, setAuthenticating] = useState(false);
  const [loading, setLoading] = useState(true);
  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAuthStatus = useCallback(async () => {
    try {
      const status = await apiClient<MCPAuthStatus>(
        `mcp/servers/${encodeURIComponent(server.name)}/auth-status?scope=${server.scope}`
      );
      setAuthStatus(status);
      return status;
    } catch {
      setAuthStatus(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, [server.name, server.scope]);

  useEffect(() => {
    fetchAuthStatus();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchAuthStatus]);

  // Listen for postMessage from OAuth callback popup
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === "mcp-oauth-complete") {
        setAuthenticating(false);
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        fetchAuthStatus().then(() => onAuthComplete());
        toast.success("Authentication successful!");
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [fetchAuthStatus, onAuthComplete]);

  const handleAuthenticate = async () => {
    setAuthenticating(true);
    try {
      const response = await apiClient<MCPAuthStartResponse>(
        `mcp/servers/${encodeURIComponent(server.name)}/auth/start?scope=${server.scope}`,
        { method: "POST" }
      );

      // Open OAuth URL in popup
      popupRef.current = window.open(
        response.auth_url,
        "mcp-oauth",
        "width=600,height=700,popup=yes"
      );

      // Poll auth status as fallback (in case postMessage doesn't work)
      pollRef.current = setInterval(async () => {
        const status = await fetchAuthStatus();
        if (status?.has_token && !status.expired) {
          setAuthenticating(false);
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          if (popupRef.current && !popupRef.current.closed) {
            popupRef.current.close();
          }
          onAuthComplete();
          toast.success("Authentication successful!");
        }
        // Also stop if popup was closed without completing
        if (popupRef.current?.closed) {
          setAuthenticating(false);
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          fetchAuthStatus();
        }
      }, 2000);
    } catch (error) {
      setAuthenticating(false);
      const message = error instanceof Error ? error.message : String(error);
      toast.error(`OAuth failed: ${message}`);
    }
  };

  if (loading) {
    return (
      <div className="space-y-2">
        <h4 className="text-sm font-medium">Authentication</h4>
        <div className="bg-muted/30 rounded-md p-3 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Checking auth status...
        </div>
      </div>
    );
  }

  const hasToken = authStatus?.has_token ?? false;
  const expired = authStatus?.expired ?? false;
  const hasClientReg = authStatus?.has_client_registration ?? false;

  // If the server status says "needs-auth" despite having a stored token,
  // the token is invalid/revoked. Also handle "connected" as truly authenticated.
  const tokenInvalid = hasToken && serverStatus === "needs-auth";
  const isConnected = serverStatus === "connected";

  // Determine display state
  let statusIcon: React.ReactNode;
  let statusText: string;
  let needsAuth: boolean;

  if (isConnected && hasToken) {
    statusIcon = <CheckCircle2 className="h-4 w-4 text-green-500" />;
    statusText = "Authenticated";
    needsAuth = false;
  } else if (tokenInvalid) {
    statusIcon = <XCircle className="h-4 w-4 text-red-500" />;
    statusText = "Token not working";
    needsAuth = true;
  } else if (hasToken && expired) {
    statusIcon = <AlertTriangle className="h-4 w-4 text-amber-500" />;
    statusText = "Token expired";
    needsAuth = true;
  } else if (hasToken && !expired) {
    statusIcon = <CheckCircle2 className="h-4 w-4 text-green-500" />;
    statusText = "Token stored";
    needsAuth = false;
  } else if (hasClientReg) {
    statusIcon = <KeyRound className="h-4 w-4 text-amber-500" />;
    statusText = "Registered, needs login";
    needsAuth = true;
  } else {
    statusIcon = <KeyRound className="h-4 w-4 text-muted-foreground" />;
    statusText = "Not authenticated";
    needsAuth = true;
  }

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Authentication</h4>
      <div className="bg-muted/30 rounded-md p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            {statusIcon}
            <span className={
              isConnected && hasToken ? "text-green-700 dark:text-green-400 font-medium" :
              tokenInvalid ? "text-red-700 dark:text-red-400 font-medium" :
              expired ? "text-amber-700 dark:text-amber-400 font-medium" :
              hasToken ? "text-green-700 dark:text-green-400 font-medium" :
              hasClientReg ? "text-amber-700 dark:text-amber-400 font-medium" :
              "text-muted-foreground"
            }>
              {statusText}
            </span>
          </div>
          <Button
            size="sm"
            variant={needsAuth ? "default" : "outline"}
            onClick={handleAuthenticate}
            disabled={authenticating}
          >
            {authenticating ? (
              <>
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                Waiting...
              </>
            ) : (
              <>
                <ExternalLink className="h-3 w-3 mr-1" />
                {needsAuth ? "Authenticate" : "Re-authenticate"}
              </>
            )}
          </Button>
        </div>
        {authenticating && (
          <p className="text-xs text-muted-foreground">
            Complete authentication in the popup window. This page will update automatically.
          </p>
        )}
      </div>
    </div>
  );
}

// --- Overview Tab ---
function OverviewTab({
  server,
  testResult,
  testing,
  onTest,
  onAuthComplete,
  approvalSettings,
  onApprovalChange,
}: {
  server: MCPServer;
  testResult: MCPTestConnectionResponse | null;
  testing: boolean;
  onTest: () => void;
  onAuthComplete: () => void;
  approvalSettings: MCPServerApprovalSettings | null;
  onApprovalChange: (serverName: string, mode: string | null) => void;
}) {
  const currentOverride = approvalSettings?.server_overrides.find(
    (o) => o.server_name === server.name
  );
  const currentMode = currentOverride?.mode ?? "default";

  const defaultLabel =
    approvalSettings?.default_mode === "always-allow"
      ? "Auto-approve"
      : approvalSettings?.default_mode === "always-deny"
        ? "Always deny"
        : "Ask each time";

  // Check capabilities for resource/prompt support info
  const capabilities = testResult?.capabilities ?? server.capabilities;
  const hasResources = !!capabilities?.resources;
  const hasPrompts = !!capabilities?.prompts;

  const status = getServerStatus(server, testResult);

  return (
    <ScrollArea className="h-[60vh]">
      <div className="space-y-4 pr-4">
        {/* Config display */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium">Configuration</h4>
          <div className="text-sm space-y-1 bg-muted/30 rounded-md p-3">
            <div>
              <span className="font-medium">Type:</span>{" "}
              <span className="text-muted-foreground">
                {getServerTypeLabel(server.type)}
              </span>
            </div>
            {server.type === "stdio" && (
              <>
                <div>
                  <span className="font-medium">Command:</span>{" "}
                  <span className="text-muted-foreground font-mono">
                    {server.command}
                  </span>
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
                <span className="text-muted-foreground font-mono break-all">
                  {server.url}
                </span>
              </div>
            )}
            {server.env && Object.keys(server.env).length > 0 && (
              <div>
                <span className="font-medium">Environment:</span>{" "}
                <span className="text-muted-foreground">
                  {Object.entries(server.env).map(([k, v]) => (
                    <span key={k} className="font-mono text-xs mr-2">
                      {k}={v}
                    </span>
                  ))}
                </span>
              </div>
            )}
            {server.headers && Object.keys(server.headers).length > 0 && (
              <div>
                <span className="font-medium">Headers:</span>{" "}
                <span className="text-muted-foreground">
                  {Object.keys(server.headers).length}{" "}
                  {pluralize(Object.keys(server.headers).length, "header")}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Connection info */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium">Connection</h4>
          <div className="text-sm space-y-1 bg-muted/30 rounded-md p-3">
            {server.last_tested_at && (
              <div>
                <span className="font-medium">Last tested:</span>{" "}
                <span className="text-muted-foreground">
                  {new Date(server.last_tested_at).toLocaleString()}
                </span>
              </div>
            )}
            {server.mcp_server_name && (
              <div>
                <span className="font-medium">Server:</span>{" "}
                <span className="text-muted-foreground">
                  {server.mcp_server_name}
                  {server.mcp_server_version &&
                    ` v${server.mcp_server_version}`}
                </span>
              </div>
            )}
            {capabilities && (
              <div>
                <span className="font-medium">Capabilities:</span>{" "}
                <span className="text-muted-foreground">
                  {Object.keys(capabilities).join(", ") || "none"}
                </span>
              </div>
            )}
            {!capabilities && !server.last_tested_at && (
              <div className="text-muted-foreground text-xs">
                Not yet tested. Click Test to discover capabilities.
              </div>
            )}
            {capabilities && !hasResources && !hasPrompts && (
              <div className="text-muted-foreground text-xs mt-1">
                Server does not advertise resource or prompt support.
              </div>
            )}
          </div>
        </div>

        {/* Authentication (HTTP/SSE servers only) */}
        {(server.type === "http" || server.type === "sse") && (
          <AuthSection server={server} serverStatus={status.status} onAuthComplete={onAuthComplete} />
        )}

        {/* Per-server approval override */}
        {approvalSettings && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium">Approval Override</h4>
            <div className="bg-muted/30 rounded-md p-3">
              <Label htmlFor="server-approval" className="text-sm">
                Tool approval mode for this server
              </Label>
              <Select
                value={currentMode}
                onValueChange={(value) =>
                  onApprovalChange(
                    server.name,
                    value === "default" ? null : value
                  )
                }
              >
                <SelectTrigger id="server-approval" className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">
                    Use default ({defaultLabel})
                  </SelectItem>
                  <SelectItem value="always-allow">Always allow</SelectItem>
                  <SelectItem value="always-deny">Always deny</SelectItem>
                  <SelectItem value="ask-every-time">
                    Ask every time
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        {/* Test Connection */}
        <div className="space-y-2">
          <Button
            onClick={onTest}
            disabled={testing}
            variant="outline"
            className="w-full"
          >
            <Play className="h-4 w-4 mr-2" />
            {testing ? "Testing..." : "Test Connection"}
          </Button>

          {testResult && (
            status.status === "needs-auth" ? (
              <Alert className="border-amber-500/50 bg-amber-50/50 dark:bg-amber-950/20 text-amber-800 dark:text-amber-200">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <AlertDescription>
                  <div className="font-mono text-xs break-all">
                    {testResult.message}
                  </div>
                </AlertDescription>
              </Alert>
            ) : (
              <Alert variant={testResult.success ? "default" : "destructive"}>
                {testResult.success ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <AlertCircle className="h-4 w-4" />
                )}
                <AlertDescription>
                  <div className="font-mono text-xs break-all">
                    {testResult.message}
                  </div>
                </AlertDescription>
              </Alert>
            )
          )}
        </div>
      </div>
    </ScrollArea>
  );
}

// --- Tools Tab ---
function ToolsTab({
  server,
  testResult,
}: {
  server: MCPServer;
  testResult: MCPTestConnectionResponse | null;
}) {
  const [filter, setFilter] = useState("");
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  const tools = testResult?.tools || server.tools || [];
  const toolCount =
    testResult?.tools?.length ??
    server.tool_count ??
    tools.length;
  const totalCount = toolCount;
  const isTruncated = totalCount > tools.length;

  const filteredTools = tools.filter(
    (tool) =>
      tool.name.toLowerCase().includes(filter.toLowerCase()) ||
      tool.description?.toLowerCase().includes(filter.toLowerCase())
  );

  if (tools.length === 0) {
    return (
      <div className="h-[60vh] flex flex-col items-center justify-center text-center">
        <Wrench className="h-8 w-8 text-muted-foreground mb-2" />
        <p className="text-muted-foreground">
          {server.last_tested_at
            ? "No tools discovered."
            : "Click Test in the Overview tab to discover tools."}
        </p>
      </div>
    );
  }

  return (
    <div className="h-[60vh] flex flex-col gap-3">
      {tools.length > 5 && (
        <div className="relative shrink-0">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filter tools..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="pl-8 h-9"
          />
        </div>
      )}
      {isTruncated && (
        <p className="text-xs text-muted-foreground shrink-0">
          Showing {tools.length} of {totalCount} tools
        </p>
      )}
      <ScrollArea className="flex-1 min-h-0">
        <div className="space-y-2 pr-4">
          {filteredTools.map((tool) => (
            <div key={tool.name}>
              <button
                className="w-full text-left bg-background rounded p-2.5 text-sm hover:bg-accent transition-colors cursor-pointer border"
                onClick={() =>
                  setExpandedTool(
                    expandedTool === tool.name ? null : tool.name
                  )
                }
              >
                <div className="font-medium font-mono text-xs">
                  {tool.name}
                </div>
                {tool.description && (
                  <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {tool.description}
                  </div>
                )}
              </button>
              {expandedTool === tool.name && (
                <div className="ml-2 mt-1">
                  <ToolDetailView tool={tool} />
                </div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}

// --- Resources Tab ---
function ResourcesTab({
  server,
  testResult,
}: {
  server: MCPServer;
  testResult: MCPTestConnectionResponse | null;
}) {
  const resources: MCPResource[] = testResult?.resources || server.resources || [];
  const resourceCount =
    testResult?.resource_count ?? server.resource_count ?? resources.length;
  const isTruncated = resourceCount > resources.length;
  const capabilities = testResult?.capabilities ?? server.capabilities;
  const hasResourceCapability = !!capabilities?.resources;

  if (resources.length === 0) {
    let message: string;
    if (!server.last_tested_at && !testResult) {
      message = "Test connection to discover resources.";
    } else if (capabilities && !hasResourceCapability) {
      message = "This server does not expose resources.";
    } else {
      message = "No resources found.";
    }

    return (
      <div className="h-[60vh] flex flex-col items-center justify-center text-center">
        <FileText className="h-8 w-8 text-muted-foreground mb-2" />
        <p className="text-muted-foreground">{message}</p>
      </div>
    );
  }

  return (
    <div className="h-[60vh] flex flex-col gap-3">
      {isTruncated && (
        <p className="text-xs text-muted-foreground shrink-0">
          Showing {resources.length} of {resourceCount} resources
        </p>
      )}
      <ScrollArea className="flex-1 min-h-0">
        <div className="space-y-2 pr-4">
          {resources.map((resource, i) => (
            <div
              key={i}
              className="bg-background rounded p-2.5 text-sm border"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{resource.name}</div>
                  <div className="font-mono text-xs text-muted-foreground truncate">
                    {resource.uri}
                  </div>
                  {resource.description && (
                    <div className="text-xs text-muted-foreground mt-1">
                      {resource.description}
                    </div>
                  )}
                </div>
                {resource.mimeType && (
                  <Badge variant="outline" className="text-xs shrink-0">
                    {resource.mimeType}
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}

// --- Prompts Tab ---
function PromptsTab({
  server,
  testResult,
}: {
  server: MCPServer;
  testResult: MCPTestConnectionResponse | null;
}) {
  const prompts: MCPPrompt[] = testResult?.prompts || server.prompts || [];
  const promptCount =
    testResult?.prompt_count ?? server.prompt_count ?? prompts.length;
  const isTruncated = promptCount > prompts.length;
  const capabilities = testResult?.capabilities ?? server.capabilities;
  const hasPromptCapability = !!capabilities?.prompts;

  if (prompts.length === 0) {
    let message: string;
    if (!server.last_tested_at && !testResult) {
      message = "Test connection to discover prompts.";
    } else if (capabilities && !hasPromptCapability) {
      message = "This server does not expose prompts.";
    } else {
      message = "No prompts found.";
    }

    return (
      <div className="h-[60vh] flex flex-col items-center justify-center text-center">
        <MessageSquare className="h-8 w-8 text-muted-foreground mb-2" />
        <p className="text-muted-foreground">{message}</p>
      </div>
    );
  }

  return (
    <div className="h-[60vh] flex flex-col gap-3">
      {isTruncated && (
        <p className="text-xs text-muted-foreground shrink-0">
          Showing {prompts.length} of {promptCount} prompts
        </p>
      )}
      <ScrollArea className="flex-1 min-h-0">
        <div className="space-y-2 pr-4">
          {prompts.map((prompt, i) => (
            <div
              key={i}
              className="bg-background rounded p-2.5 text-sm border"
            >
              <div className="font-medium">{prompt.name}</div>
              {prompt.description && (
                <div className="text-xs text-muted-foreground mt-1">
                  {prompt.description}
                </div>
              )}
              {prompt.arguments && prompt.arguments.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="text-xs font-medium text-muted-foreground">
                    Arguments
                  </div>
                  {prompt.arguments.map((arg, j) => (
                    <div key={j} className="flex items-center gap-1.5 text-xs">
                      <span className="font-mono">{arg.name}</span>
                      {arg.required && (
                        <Badge
                          variant="destructive"
                          className="text-[10px] px-1 py-0"
                        >
                          required
                        </Badge>
                      )}
                      {arg.description && (
                        <span className="text-muted-foreground">
                          - {arg.description}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}

// --- Main Dialog ---
export function MCPServerDetailDialog({
  server,
  open,
  onOpenChange,
  onEdit,
  onDelete,
  onTestComplete,
  approvalSettings,
  onApprovalChange,
  readOnly = false,
}: MCPServerDetailDialogProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] =
    useState<MCPTestConnectionResponse | null>(null);

  if (!server) return null;

  const isEditable =
    !readOnly &&
    server.scope !== "plugin" &&
    server.scope !== "managed";

  const toolCount = server.tool_count ?? server.tools?.length ?? 0;
  const resourceCount = server.resource_count ?? server.resources?.length ?? 0;
  const promptCount = server.prompt_count ?? server.prompts?.length ?? 0;

  const handleTest = async () => {
    if (!server) return;
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
          toast.success(
            `Connected! ${responseToolCount} ${pluralize(responseToolCount, "tool")} available`
          );
          onTestComplete();
        } else {
          toast.error("Connection failed");
        }
      } else {
        setTestResult({
          success: false,
          message: "Invalid response from server",
        });
        toast.error("Invalid response from server");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTestResult({
        success: false,
        message: `Failed to test connection: ${message}`,
      });
      toast.error(`Test failed: ${message}`);
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = () => {
    if (
      confirm(
        `Are you sure you want to delete the MCP server "${server.name}"?`
      )
    ) {
      onDelete(server.name, server.scope);
      onOpenChange(false);
    }
  };

  // Merge test result counts with server counts for tab badges
  const displayToolCount =
    testResult?.tools?.length ?? toolCount;
  const displayResourceCount =
    testResult?.resource_count ?? resourceCount;
  const displayPromptCount =
    testResult?.prompt_count ?? promptCount;

  const status = getServerStatus(server, testResult);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setTestResult(null);
        onOpenChange(o);
      }}
    >
      <DialogContent className={`${MODAL_SIZES.LG} flex flex-col`}>
        <DialogHeader>
          <div className="flex items-center gap-3">
            {STATUS_ICONS_LG[status.status]}
            <div className="flex-1 min-w-0">
              <DialogTitle className="text-lg truncate">
                {server.name}
              </DialogTitle>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-muted-foreground">
                  {getServerTypeLabel(server.type)}
                </span>
                <Badge variant={getScopeBadgeVariant(server.scope)} className="text-xs">
                  {getScopeLabel(server.scope, server.source)}
                </Badge>
                <span className={`text-xs font-medium ${STATUS_COLORS[status.status]}`}>
                  {status.label}
                </span>
              </div>
            </div>
          </div>
        </DialogHeader>

        <Tabs defaultValue="overview" className="flex-1">
          <TabsList className="w-full justify-start">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="tools" className="gap-1.5">
              Tools
              {displayToolCount > 0 && (
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 ml-1">
                  {displayToolCount}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="resources" className="gap-1.5">
              Resources
              {displayResourceCount > 0 && (
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 ml-1">
                  {displayResourceCount}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="prompts" className="gap-1.5">
              Prompts
              {displayPromptCount > 0 && (
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 ml-1">
                  {displayPromptCount}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <OverviewTab
              server={server}
              testResult={testResult}
              testing={testing}
              onTest={handleTest}
              onAuthComplete={() => {
                handleTest();
              }}
              approvalSettings={approvalSettings}
              onApprovalChange={onApprovalChange}
            />
          </TabsContent>

          <TabsContent value="tools">
            <ToolsTab server={server} testResult={testResult} />
          </TabsContent>

          <TabsContent value="resources">
            <ResourcesTab server={server} testResult={testResult} />
          </TabsContent>

          <TabsContent value="prompts">
            <PromptsTab server={server} testResult={testResult} />
          </TabsContent>
        </Tabs>

        {/* Footer */}
        <div className="flex justify-between pt-4 border-t">
          <div className="flex gap-2">
            {isEditable && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    onEdit(server);
                    onOpenChange(false);
                  }}
                >
                  <Edit2 className="h-4 w-4 mr-1" />
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="text-destructive hover:text-destructive"
                  onClick={handleDelete}
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  Delete
                </Button>
              </>
            )}
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
