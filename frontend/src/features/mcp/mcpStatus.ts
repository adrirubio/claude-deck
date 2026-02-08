import type { MCPServer, MCPTestConnectionResponse } from "@/types/mcp";

export type MCPConnectionStatus = "connected" | "failed" | "needs-auth" | "not-tested";

export interface MCPStatusInfo {
  status: MCPConnectionStatus;
  label: string;
}

const AUTH_ERROR_PATTERNS = [
  "auth",
  "unauthorized",
  "401",
  "403",
  "oauth",
  "token",
  "credential",
  "login",
  "permission denied",
  "access denied",
  "needs authentication",
];

function isAuthError(error: string | null | undefined): boolean {
  if (!error) return false;
  const lower = error.toLowerCase();
  return AUTH_ERROR_PATTERNS.some((pattern) => lower.includes(pattern));
}

/**
 * Determine the connection status of an MCP server,
 * matching the Claude Code `/mcp` interface states:
 * - connected (green check)
 * - failed (red X)
 * - needs authentication (amber triangle)
 * - not tested (gray circle)
 */
export function getServerStatus(
  server: MCPServer,
  testResult?: MCPTestConnectionResponse | null
): MCPStatusInfo {
  const isConnected = testResult?.success ?? server.is_connected;
  const errorMessage = testResult?.message ?? server.last_error;

  if (isConnected === true) {
    return { status: "connected", label: "connected" };
  }

  if (isConnected === false) {
    if (isAuthError(errorMessage)) {
      return { status: "needs-auth", label: "needs authentication" };
    }
    return { status: "failed", label: "failed" };
  }

  return { status: "not-tested", label: "not tested" };
}
