/**
 * TypeScript types for MCP Server management
 * Matches backend schemas from app/models/schemas.py
 */

export interface MCPServer {
  name: string;
  type: "stdio" | "http" | "sse";
  scope: "user" | "project" | "plugin" | "managed";
  source?: string; // Original source (e.g., plugin name, "enterprise")
  disabled?: boolean;
  command?: string;
  args?: string[];
  url?: string;
  headers?: Record<string, string>;
  env?: Record<string, string>;
  // Cache fields
  is_connected?: boolean | null;
  last_tested_at?: string | null;
  last_error?: string | null;
  mcp_server_name?: string | null;
  mcp_server_version?: string | null;
  tools?: MCPTool[] | null;
  tool_count?: number;
  resources?: MCPResource[] | null;
  prompts?: MCPPrompt[] | null;
  resource_count?: number;
  prompt_count?: number;
  capabilities?: Record<string, unknown> | null;
}

export interface MCPServerCreate {
  name: string;
  type: "stdio" | "http" | "sse";
  scope: "user" | "project";
  command?: string;
  args?: string[];
  url?: string;
  headers?: Record<string, string>;
  env?: Record<string, string>;
}

export interface MCPServerUpdate {
  type?: "stdio" | "http" | "sse";
  command?: string;
  args?: string[];
  url?: string;
  headers?: Record<string, string>;
  env?: Record<string, string>;
}

export interface MCPServerListResponse {
  servers: MCPServer[];
}

export interface MCPTestConnectionRequest {
  name: string;
  scope: string;
}

export interface MCPTool {
  name: string;
  description?: string;
  inputSchema?: {
    type: string;
    properties?: Record<string, { type: string; description?: string }>;
    required?: string[];
  };
}

export interface MCPResource {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

export interface MCPPromptArgument {
  name: string;
  description?: string;
  required?: boolean;
}

export interface MCPPrompt {
  name: string;
  description?: string;
  arguments?: MCPPromptArgument[];
}

export interface MCPTestConnectionResponse {
  success: boolean;
  message: string;
  server_name?: string;
  server_version?: string;
  tools?: MCPTool[];
  resources?: MCPResource[];
  prompts?: MCPPrompt[];
  resource_count?: number;
  prompt_count?: number;
  capabilities?: Record<string, unknown>;
}

export interface MCPTestAllResult {
  server_name: string;
  scope: string;
  success: boolean;
  message: string;
  tool_count?: number;
  resource_count?: number;
  prompt_count?: number;
}

export interface MCPTestAllResponse {
  results: MCPTestAllResult[];
}

// OAuth Authentication

export interface MCPAuthStatus {
  has_token: boolean;
  expired: boolean;
  server_url?: string;
  has_client_registration?: boolean;
}

export interface MCPAuthStartResponse {
  auth_url: string;
  state: string;
}

// Server Approval Settings

export interface MCPServerApprovalMode {
  server_name: string;
  mode: "always-allow" | "always-deny" | "ask-every-time";
}

export interface MCPServerApprovalSettings {
  default_mode: "always-allow" | "always-deny" | "ask-every-time";
  server_overrides: MCPServerApprovalMode[];
}
