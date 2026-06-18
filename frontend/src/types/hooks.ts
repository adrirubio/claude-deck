// Hook TypeScript types matching backend schemas

export type HookEvent =
  | "PreToolUse"
  | "PostToolUse"
  | "PostToolUseFailure"
  | "Stop"
  | "StopFailure"
  | "SessionStart"
  | "SessionEnd"
  | "UserPromptSubmit"
  | "PermissionRequest"
  | "PermissionDenied"
  | "Notification"
  | "SubagentStart"
  | "SubagentStop"
  | "TeammateIdle"
  | "TaskCreated"
  | "TaskCompleted"
  | "PreCompact"
  | "PostCompact"
  | "InstructionsLoaded"
  | "ConfigChange"
  | "CwdChanged"
  | "FileChanged"
  | "WorktreeCreate"
  | "WorktreeRemove"
  | "Elicitation"
  | "ElicitationResult";

export type HookType = "command" | "prompt" | "agent" | "http";

export interface Hook {
  id: string;
  event: HookEvent;
  matcher?: string;
  if?: string;  // Permission rule filter
  type: HookType;
  command?: string;
  prompt?: string;
  model?: string;
  async_?: boolean;  // Run in background (JSON field: "async")
  shell?: "bash" | "powershell";
  statusMessage?: string;
  once?: boolean;
  timeout?: number;
  url?: string;
  headers?: Record<string, string>;
  allowedEnvVars?: string[];
  scope: "user" | "project";
}

export interface HookCreate {
  event: HookEvent;
  matcher?: string;
  type: HookType;
  command?: string;
  prompt?: string;
  model?: string;
  async_?: boolean;
  statusMessage?: string;
  once?: boolean;
  timeout?: number;
  url?: string;
  headers?: Record<string, string>;
  allowedEnvVars?: string[];
  scope: "user" | "project";
}

export interface HookUpdate {
  event?: HookEvent;
  matcher?: string;
  type?: HookType;
  command?: string;
  prompt?: string;
  model?: string;
  async_?: boolean;
  statusMessage?: string;
  once?: boolean;
  timeout?: number;
  url?: string;
  headers?: Record<string, string>;
  allowedEnvVars?: string[];
}

export interface HookListResponse {
  hooks: Hook[];
}

// UI-specific types
export interface HookCardProps {
  hook: Hook;
  onEdit: (hook: Hook) => void;
  onDelete: (hookId: string, scope: "user" | "project") => void;
}

export interface HookListProps {
  hooks: Hook[];
  onEdit: (hook: Hook) => void;
  onDelete: (hookId: string, scope: "user" | "project") => void;
}

// Event type metadata for UI
export interface HookEventMetadata {
  name: HookEvent;
  label: string;
  description: string;
  icon: string;
}

export const HOOK_EVENTS: HookEventMetadata[] = [
  {
    name: "PreToolUse",
    label: "Pre-Tool Use",
    description: "Triggered before Claude executes a tool",
    icon: "🔧",
  },
  {
    name: "PostToolUse",
    label: "Post-Tool Use",
    description: "Triggered after Claude executes a tool",
    icon: "✅",
  },
  {
    name: "PostToolUseFailure",
    label: "Post-Tool Use Failure",
    description: "Triggered when a tool execution fails",
    icon: "❌",
  },
  {
    name: "Stop",
    label: "Stop",
    description: "Triggered after Claude responds",
    icon: "🛑",
  },
  {
    name: "StopFailure",
    label: "Stop Failure",
    description: "Triggered on API error during a turn",
    icon: "💥",
  },
  {
    name: "SessionStart",
    label: "Session Start",
    description: "Triggered when a session starts",
    icon: "🚀",
  },
  {
    name: "SessionEnd",
    label: "Session End",
    description: "Triggered when a session ends",
    icon: "🏁",
  },
  {
    name: "UserPromptSubmit",
    label: "User Prompt Submit",
    description: "Triggered when user submits a prompt",
    icon: "💬",
  },
  {
    name: "PermissionRequest",
    label: "Permission Request",
    description: "Triggered when a permission dialog appears",
    icon: "🔐",
  },
  {
    name: "PermissionDenied",
    label: "Permission Denied",
    description: "Triggered when auto mode denies a tool",
    icon: "🚫",
  },
  {
    name: "Notification",
    label: "Notification",
    description: "Triggered on notifications",
    icon: "🔔",
  },
  {
    name: "SubagentStart",
    label: "Subagent Start",
    description: "Triggered when a subagent starts",
    icon: "🤖",
  },
  {
    name: "SubagentStop",
    label: "Subagent Stop",
    description: "Triggered when a subagent finishes",
    icon: "🤖",
  },
  {
    name: "TeammateIdle",
    label: "Teammate Idle",
    description: "Triggered when a team member becomes idle",
    icon: "💤",
  },
  {
    name: "TaskCreated",
    label: "Task Created",
    description: "Triggered when a task is created via TaskCreate",
    icon: "📋",
  },
  {
    name: "TaskCompleted",
    label: "Task Completed",
    description: "Triggered when a task is marked complete",
    icon: "✔️",
  },
  {
    name: "PreCompact",
    label: "Pre-Compact",
    description: "Triggered before context compaction",
    icon: "📦",
  },
  {
    name: "PostCompact",
    label: "Post-Compact",
    description: "Triggered after context compaction",
    icon: "📦",
  },
  {
    name: "InstructionsLoaded",
    label: "Instructions Loaded",
    description: "Triggered when CLAUDE.md or rules are loaded",
    icon: "📄",
  },
  {
    name: "ConfigChange",
    label: "Config Change",
    description: "Triggered when a settings file changes",
    icon: "⚙️",
  },
  {
    name: "CwdChanged",
    label: "CWD Changed",
    description: "Triggered when the working directory changes",
    icon: "📂",
  },
  {
    name: "FileChanged",
    label: "File Changed",
    description: "Triggered when a watched file changes",
    icon: "📝",
  },
  {
    name: "WorktreeCreate",
    label: "Worktree Create",
    description: "Triggered when a git worktree is created",
    icon: "🌳",
  },
  {
    name: "WorktreeRemove",
    label: "Worktree Remove",
    description: "Triggered when a git worktree is removed",
    icon: "🌳",
  },
  {
    name: "Elicitation",
    label: "Elicitation",
    description: "Triggered on MCP elicitation input",
    icon: "❓",
  },
  {
    name: "ElicitationResult",
    label: "Elicitation Result",
    description: "Triggered when MCP elicitation result arrives",
    icon: "❓",
  },
];

// Model options for agent hooks
export const AGENT_MODELS = [
  { value: "haiku", label: "Haiku (Fast)" },
  { value: "sonnet", label: "Sonnet (Balanced)" },
  { value: "opus", label: "Opus (Powerful)" },
];

// Matcher pattern examples
export const MATCHER_EXAMPLES = [
  { pattern: "Write(*.py)", description: "Matches Write tool on Python files" },
  { pattern: "Bash", description: "Matches any Bash tool use" },
  { pattern: "Edit|Write", description: "Matches Edit OR Write tool" },
  { pattern: "Read(*.md)", description: "Matches Read tool on Markdown files" },
  { pattern: "*", description: "Matches all tools" },
];

// Environment variables available in hooks
export const HOOK_ENV_VARS = [
  {
    name: "$CLAUDE_FILE_PATHS",
    description: "File paths involved in the tool use",
  },
  { name: "$CLAUDE_TOOL_NAME", description: "Name of the tool being executed" },
  {
    name: "$CLAUDE_TOOL_ARGS",
    description: "Arguments passed to the tool (JSON)",
  },
  { name: "$CLAUDE_PROJECT_PATH", description: "Current project directory path" },
  { name: "$CLAUDE_USER_HOME", description: "User's home directory" },
];

// Hook templates for quick creation
export interface HookTemplate {
  name: string;
  description: string;
  event: HookEvent;
  type: HookType;
  matcher?: string;
  command?: string;
  prompt?: string;
  model?: string;
  async_?: boolean;
  statusMessage?: string;
  once?: boolean;
  timeout?: number;
  url?: string;
}

export const HOOK_TEMPLATES: HookTemplate[] = [
  {
    name: "Blank Hook",
    description: "Start from scratch",
    event: "PreToolUse",
    type: "command",
    command: "",
  },
  {
    name: "Python File Linter",
    description: "Run linter before writing Python files",
    event: "PreToolUse",
    type: "command",
    matcher: "Write(*.py)",
    command: "python -m pylint $CLAUDE_FILE_PATHS",
    timeout: 10,
  },
  {
    name: "Git Auto-commit",
    description: "Commit changes after file writes",
    event: "PostToolUse",
    type: "command",
    matcher: "Write|Edit",
    command: 'git add $CLAUDE_FILE_PATHS && git commit -m "Auto-commit: $CLAUDE_TOOL_NAME"',
    timeout: 5,
  },
  {
    name: "Security Reminder",
    description: "Remind about security when reading config files",
    event: "PreToolUse",
    type: "prompt",
    matcher: "Read(*.env|*.json)",
    prompt:
      "Remember to mask any sensitive data like API keys, tokens, or passwords when displaying file contents to the user.",
  },
  {
    name: "Session Start Logger",
    description: "Log session start time",
    event: "SessionStart",
    type: "command",
    command: 'echo "Session started at $(date)" >> ~/.claude/session.log',
    timeout: 2,
  },
  {
    name: "Code Review Agent",
    description: "Use an agent to review code changes",
    event: "PostToolUse",
    type: "agent",
    matcher: "Write(*.ts|*.tsx|*.js|*.jsx)",
    prompt: "Review this code change for best practices, potential bugs, and security issues. Provide brief feedback.",
    model: "haiku",
    async_: true,
    statusMessage: "Reviewing code...",
  },
  {
    name: "Session Summary Agent",
    description: "Generate session summary on end",
    event: "SessionEnd",
    type: "agent",
    prompt: "Summarize the key accomplishments and changes made during this session.",
    model: "haiku",
    once: true,
  },
];
