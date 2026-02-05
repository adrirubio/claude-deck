/**
 * Types for memory management (CLAUDE.md, rules, etc.)
 */

export interface MemoryHierarchyItem {
  path: string;
  scope: "managed" | "user" | "project" | "local" | "rules";
  type: "claude_md" | "rule";
  exists: boolean;
  readonly: boolean;
  description: string;
  name?: string;
  relative_path?: string;
}

export interface MemoryHierarchyResponse {
  files: MemoryHierarchyItem[];
}

export interface MemoryFileResponse {
  path: string;
  exists: boolean;
  content: string | null;
  imports: string[];
  frontmatter: Record<string, unknown>;
  error?: string;
}

export interface RuleInfo {
  name: string;
  path: string;
  relative_path: string;
  frontmatter: Record<string, unknown>;
  scoped_paths: string[];
  description: string;
  content_preview: string;
}

export interface RulesListResponse {
  rules: RuleInfo[];
  rules_dir: string;
}

export interface SaveMemoryResponse {
  success: boolean;
  path: string;
  error?: string;
}

export interface ImportTreeNode {
  path: string;
  exists: boolean;
  cycle: boolean;
  imports: ImportTreeNode[];
  error?: string;
}

export interface ImportTreeResponse {
  tree: ImportTreeNode;
}
