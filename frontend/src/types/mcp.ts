/**
 * TypeScript types for MCP Server management
 * Matches backend schemas from app/models/schemas.py
 */

export interface MCPServer {
  name: string;
  type: "stdio" | "http" | "sse";
  scope: "user" | "project" | "plugin";
  command?: string;
  args?: string[];
  url?: string;
  headers?: Record<string, string>;
  env?: Record<string, string>;
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
}

export interface MCPTestConnectionResponse {
  success: boolean;
  message: string;
  server_name?: string;
  server_version?: string;
  tools?: MCPTool[];
}
