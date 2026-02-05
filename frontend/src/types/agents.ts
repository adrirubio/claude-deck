// Agent and Skill TypeScript types matching backend schemas

export type AgentScope = "user" | "project";

export interface Agent {
  name: string;
  scope: AgentScope;
  description?: string | null;
  tools?: string[] | null;
  model?: string | null;
  prompt: string;
}

export interface AgentCreate {
  name: string;
  scope: AgentScope;
  description?: string;
  tools?: string[];
  model?: string;
  prompt: string;
}

export interface AgentUpdate {
  description?: string;
  tools?: string[];
  model?: string;
  prompt?: string;
}

export interface AgentListResponse {
  agents: Agent[];
}

export interface SkillDependency {
  kind: "bin" | "npm" | "pip" | "script";
  name: string;
  installed: boolean;
  version?: string | null;
  installed_version?: string | null;
}

export interface SkillDependencyStatus {
  skill_name: string;
  all_satisfied: boolean;
  dependencies: SkillDependency[];
  has_install_script: boolean;
  install_script_path?: string | null;
}

export interface SkillInstallResult {
  success: boolean;
  message: string;
  installed: string[];
  failed: string[];
  logs: string;
}

export interface SkillSupportingFile {
  name: string;
  path: string;
  size_bytes: number;
  is_script: boolean;
}

export interface Skill {
  name: string;
  description?: string | null;
  location: string; // "user", "project", or plugin path
  content?: string | null; // Full markdown content (optional)
  dependency_status?: SkillDependencyStatus | null;
  supporting_files?: SkillSupportingFile[] | null;
}

export interface SkillListResponse {
  skills: Skill[];
}

// Available tools for agent configuration
export const AGENT_TOOLS = [
  { name: "Read", description: "Read file contents" },
  { name: "Write", description: "Create new files" },
  { name: "Edit", description: "Edit existing files" },
  { name: "Bash", description: "Execute shell commands" },
  { name: "Glob", description: "Find files by pattern" },
  { name: "Grep", description: "Search file contents" },
  { name: "WebFetch", description: "Fetch web content" },
  { name: "Task", description: "Launch subagents" },
  { name: "TodoWrite", description: "Manage todo lists" },
  { name: "NotebookEdit", description: "Edit Jupyter notebooks" },
  { name: "LSP", description: "Language server operations" },
] as const;

// Available model options
export const AGENT_MODELS = [
  { value: "sonnet", label: "Claude Sonnet", description: "Fast and capable" },
  { value: "opus", label: "Claude Opus", description: "Most capable" },
  { value: "haiku", label: "Claude Haiku", description: "Fastest, lightweight" },
] as const;

// Model type from the constants
export type AgentModel = typeof AGENT_MODELS[number]["value"];
