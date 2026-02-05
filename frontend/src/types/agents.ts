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

export interface SkillFrontmatter {
  // Identity
  name?: string | null;
  description?: string | null;
  version?: string | null;
  license?: string | null;

  // Execution context
  context?: string | null; // "fork" to run in a subagent
  agent?: string | null; // Subagent type: "Explore", "Plan", custom
  model?: string | null; // Override model

  // Tool control
  allowed_tools?: string[] | null;

  // Visibility
  user_invocable?: boolean | null; // Show in / menu
  disable_model_invocation?: boolean | null; // Prevent auto-loading

  // UX
  argument_hint?: string | null; // Autocomplete hint

  // Hooks & metadata
  hooks?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
}

export interface Skill {
  name: string;
  description?: string | null;
  location: string; // "user", "project", or plugin path
  content?: string | null; // Full markdown content (optional)
  frontmatter?: SkillFrontmatter | null;
  dependency_status?: SkillDependencyStatus | null;
  supporting_files?: SkillSupportingFile[] | null;
}

export interface SkillListResponse {
  skills: Skill[];
}

// Registry Skills (skills.sh)

export interface RegistrySkill {
  skill_id: string;
  name: string;
  source: string; // GitHub repo path (e.g. "vercel-labs/agent-skills")
  installs: number;
  registry_id: string;
  url: string; // skills.sh detail page URL
  github_url: string; // GitHub repo URL
  installed: boolean;
}

export interface RegistrySearchResponse {
  skills: RegistrySkill[];
  total: number;
  cached: boolean;
}

export interface RegistryInstallRequest {
  source: string;
  skill_names?: string[];
  global_install: boolean;
}

export interface RegistryInstallResponse {
  success: boolean;
  message: string;
  logs: string;
  source: string;
  skill_names?: string[];
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
