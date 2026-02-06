// Plugin TypeScript types matching backend schemas

export interface PluginComponent {
  type: "command" | "agent" | "hook" | "mcp" | "lsp" | "skill";
  name: string;
  description?: string;
}

export interface PluginHook {
  event: string;  // PreToolUse, PostToolUse, etc.
  type: "command" | "prompt" | "agent";
  matcher?: string;
  command?: string;
  prompt?: string;
}

export interface PluginLSPConfig {
  name: string;
  language: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

export interface Plugin {
  name: string;
  version?: string;
  description?: string;
  author?: string;
  category?: string;
  source?: string;  // e.g., "anthropic-agent-skills", "claude-plugins-official", "local"
  enabled?: boolean;
  scope?: "user" | "project" | "local";  // Installation scope
  components: PluginComponent[];
  // Component counts
  skill_count?: number;
  agent_count?: number;
  hook_count?: number;
  mcp_count?: number;
  lsp_count?: number;
  // Extended information
  usage?: string;  // Usage instructions
  examples?: string[];  // Example use cases
  readme?: string;  // README content (for local plugins)
  // Plugin-defined hooks (read-only)
  hooks?: PluginHook[];
  // LSP configurations
  lsp_configs?: PluginLSPConfig[];
}

export interface PluginListResponse {
  plugins: Plugin[];
}

export interface MarketplacePlugin {
  name: string;
  description?: string;
  version?: string;
  install_command: string;
}

export interface MarketplacePluginListResponse {
  plugins: MarketplacePlugin[];
}

export interface MarketplaceCreate {
  name?: string;  // Optional - derived from input if not provided
  url?: string;   // Optional - derived from input if not provided
  input?: string; // Accepts "owner/repo" or full URL
}

export interface MarketplaceResponse {
  name: string;
  repo: string;
  install_location: string;
  last_updated?: string;
  plugin_count: number;
  auto_update: boolean;  // Per-marketplace auto-update setting
}

export interface MarketplaceListResponse {
  marketplaces: MarketplaceResponse[];
}

export interface PluginInstallRequest {
  name: string;
  marketplace_name?: string;
  scope?: "user" | "project" | "local";  // Installation scope
}

export interface PluginInstallResponse {
  success: boolean;
  message: string;
  stdout?: string;
  stderr?: string;
}

// UI-specific types
export type PluginTab = "installed" | "marketplace";
export type PluginScope = "user" | "project" | "local";

export interface PluginCardProps {
  plugin: Plugin;
  onDetails: (plugin: Plugin) => void;
  onUninstall: (name: string) => void;
}

export interface MarketplacePluginCardProps {
  plugin: MarketplacePlugin;
  onInstall: (plugin: MarketplacePlugin) => void;
}
