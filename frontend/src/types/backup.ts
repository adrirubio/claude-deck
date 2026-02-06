// Backup TypeScript types matching backend schemas

export type BackupScope = "full" | "user" | "project";

export interface Backup {
  id: number;
  name: string;
  description?: string | null;
  scope: BackupScope;
  file_path: string;
  project_id?: number | null;
  created_at: string;
  size_bytes: number;
  // Extended fields from manifest
  has_dependencies?: boolean;
  skill_count?: number;
  plugin_count?: number;
  mcp_server_count?: number;
}

export interface BackupCreate {
  name: string;
  description?: string;
  scope: BackupScope;
  project_path?: string;
  project_id?: number;
}

export interface BackupListResponse {
  backups: Backup[];
}

export interface BackupContentsResponse {
  files: string[];
}

// Manifest types

export interface BackupSkillDependency {
  kind: "npm" | "pip" | "bin" | "script";
  name: string;
  version?: string;
}

export interface BackupSkillInfo {
  name: string;
  path: string;
  has_package_json: boolean;
  has_requirements_txt: boolean;
  has_install_script: boolean;
  dependencies: BackupSkillDependency[];
}

export interface BackupPluginInfo {
  name: string;
  version?: string;
  source?: string;
  install_command?: string;
  marketplace?: string;
}

export interface BackupMCPServerInfo {
  name: string;
  type: "stdio" | "http" | "sse";
  scope: string;
  command?: string;
  args?: string[];
  url?: string;
  requires_npm_install: boolean;
}

export interface BackupManifestContents {
  files: string[];
  skills: BackupSkillInfo[];
  plugins: BackupPluginInfo[];
  mcp_servers: BackupMCPServerInfo[];
  agents: string[];
  commands: string[];
}

export interface BackupManifest {
  version: string;
  created_at: string;
  claude_code_version?: string;
  platform: string;
  scope: string;
  contents: BackupManifestContents;
}

// Restore types

export interface RestoreOptions {
  selective_restore?: string[];
  install_dependencies?: boolean;
  dry_run?: boolean;
  skip_plugins?: boolean;
  skip_skills?: boolean;
  skip_mcp_servers?: boolean;
}

export interface DependencyInstallStatus {
  name: string;
  kind: "npm" | "pip" | "plugin" | "skill" | "mcp_npm";
  success: boolean;
  message?: string;
}

export interface RestorePlanDependency {
  kind: "npm" | "pip" | "plugin" | "mcp_npm";
  name: string;
  version?: string;
  source?: string;
  install_command?: string;
}

export interface RestorePlanWarning {
  type: "platform" | "version" | "missing_tool";
  message: string;
  severity: "warning" | "error";
}

export interface RestorePlan {
  backup_id: number;
  backup_name: string;
  created_at: string;
  scope: string;
  platform_current: string;
  platform_backup: string;
  platform_compatible: boolean;

  files_to_restore: string[];
  skills_to_restore: BackupSkillInfo[];
  plugins_to_restore: BackupPluginInfo[];
  mcp_servers_to_restore: BackupMCPServerInfo[];

  dependencies: RestorePlanDependency[];
  has_dependencies: boolean;

  warnings: RestorePlanWarning[];
  manual_steps: string[];
}

export interface RestoreResult {
  success: boolean;
  message: string;
  files_restored: number;
  files_skipped: number;
  dry_run: boolean;
  dependency_results: DependencyInstallStatus[];
  manual_steps: string[];
}

export interface DependencyInstallRequest {
  install_npm?: boolean;
  install_pip?: boolean;
  install_plugins?: boolean;
  skill_names?: string[];
  plugin_names?: string[];
}

export interface DependencyInstallResult {
  success: boolean;
  message: string;
  installed: DependencyInstallStatus[];
  failed: DependencyInstallStatus[];
  logs: string;
}

export interface ValidationResponse {
  valid: boolean;
  issues: string[];
}

export interface ExportRequest {
  paths: string[];
  name?: string;
}

export interface ExportResponse {
  file_path: string;
  size_bytes: number;
}

// Helper function to format bytes
export function formatBytes(bytes: number, decimals = 2): string {
  if (bytes === 0) return "0 Bytes";

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];

  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
}

// Helper function to format date
export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Scope display info
export const BACKUP_SCOPES = [
  {
    value: "full" as BackupScope,
    label: "Complete",
    description: "User and project configurations",
  },
  {
    value: "user" as BackupScope,
    label: "User",
    description: "Settings in ~/.claude/",
  },
  {
    value: "project" as BackupScope,
    label: "Project",
    description: "Settings in .claude/",
  },
];

// Platform display names
export const PLATFORM_NAMES: Record<string, string> = {
  linux: "Linux",
  darwin: "macOS",
  win32: "Windows",
};

// Dependency kind display
export const DEPENDENCY_KINDS: Record<string, { label: string; color: string }> = {
  npm: { label: "npm", color: "bg-red-100 text-red-800" },
  pip: { label: "pip", color: "bg-blue-100 text-blue-800" },
  plugin: { label: "Plugin", color: "bg-purple-100 text-purple-800" },
  mcp_npm: { label: "MCP (npm)", color: "bg-orange-100 text-orange-800" },
  skill: { label: "Skill", color: "bg-green-100 text-green-800" },
};
