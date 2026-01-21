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

export interface RestoreRequest {
  project_path?: string;
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
