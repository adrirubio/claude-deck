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

// Plugin Update Types
export interface PluginUpdateInfo {
  name: string;
  installed_version?: string;
  latest_version?: string;
  has_update: boolean;
  source?: string;
}

export interface PluginUpdatesResponse {
  plugins: PluginUpdateInfo[];
  outdated_count: number;
}

export interface PluginValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface AvailablePluginsResponse {
  plugins: MarketplacePlugin[];
}

export interface PluginUpdateResponse {
  success: boolean;
  message: string;
  stdout?: string;
  stderr?: string;
}

export interface PluginUpdateAllResponse {
  success: boolean;
  message: string;
  updated_count: number;
  failed_count: number;
  results: PluginUpdateResponse[];
}

// Plugin with status (combines Plugin with update info)
export interface PluginWithStatus extends Plugin {
  updateInfo?: PluginUpdateInfo;
}

// UI-specific types
export type PluginTab = "installed" | "marketplace" | "available";
export type PluginScope = "user" | "project" | "local";
export type PluginStatusFilter = "all" | "enabled" | "disabled";
export type PluginUpdateFilter = "all" | "updates-available" | "up-to-date";

export interface PluginCardProps {
  plugin: Plugin;
  updateInfo?: PluginUpdateInfo;
  onDetails: (plugin: Plugin) => void;
  onUninstall: (name: string) => void;
  onUpdate?: (name: string) => void;
}

export interface MarketplacePluginCardProps {
  plugin: MarketplacePlugin;
  isInstalled?: boolean;
  onInstall: (plugin: MarketplacePlugin) => void;
}
