// Plugin TypeScript types matching backend schemas

export interface PluginComponent {
  type: "command" | "agent" | "hook" | "mcp";
  name: string;
}

export interface Plugin {
  name: string;
  version?: string;
  description?: string;
  author?: string;
  category?: string;
  source?: string;  // e.g., "anthropic-agent-skills", "claude-plugins-official", "local"
  enabled?: boolean;
  components: PluginComponent[];
  // Extended information
  usage?: string;  // Usage instructions
  examples?: string[];  // Example use cases
  readme?: string;  // README content (for local plugins)
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
}

export interface MarketplaceListResponse {
  marketplaces: MarketplaceResponse[];
}

export interface PluginInstallRequest {
  name: string;
  marketplace_name?: string;
}

export interface PluginInstallResponse {
  success: boolean;
  message: string;
  stdout?: string;
  stderr?: string;
}

// UI-specific types
export type PluginTab = "installed" | "marketplace";

export interface PluginCardProps {
  plugin: Plugin;
  onDetails: (plugin: Plugin) => void;
  onUninstall: (name: string) => void;
}

export interface MarketplacePluginCardProps {
  plugin: MarketplacePlugin;
  onInstall: (plugin: MarketplacePlugin) => void;
}
