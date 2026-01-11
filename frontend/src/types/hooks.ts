// Hook TypeScript types matching backend schemas

export type HookEvent =
  | "PreToolUse"
  | "PostToolUse"
  | "PermissionRequest"
  | "Stop"
  | "SubagentStop"
  | "Notification"
  | "UserPromptSubmit"
  | "SessionStart"
  | "PreCompact";

export type HookType = "command" | "prompt";

export interface Hook {
  id: string;
  event: HookEvent;
  matcher?: string;
  type: HookType;
  command?: string;
  prompt?: string;
  timeout?: number;
  scope: "user" | "project";
}

export interface HookCreate {
  event: HookEvent;
  matcher?: string;
  type: HookType;
  command?: string;
  prompt?: string;
  timeout?: number;
  scope: "user" | "project";
}

export interface HookUpdate {
  event?: HookEvent;
  matcher?: string;
  type?: HookType;
  command?: string;
  prompt?: string;
  timeout?: number;
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
    name: "PermissionRequest",
    label: "Permission Request",
    description: "Triggered when Claude requests user permission",
    icon: "🔐",
  },
  {
    name: "Stop",
    label: "Stop",
    description: "Triggered when a session stops",
    icon: "🛑",
  },
  {
    name: "SubagentStop",
    label: "Subagent Stop",
    description: "Triggered when a subagent stops",
    icon: "🤖",
  },
  {
    name: "Notification",
    label: "Notification",
    description: "Triggered on notifications",
    icon: "🔔",
  },
  {
    name: "UserPromptSubmit",
    label: "User Prompt Submit",
    description: "Triggered when user submits a prompt",
    icon: "💬",
  },
  {
    name: "SessionStart",
    label: "Session Start",
    description: "Triggered when a session starts",
    icon: "🚀",
  },
  {
    name: "PreCompact",
    label: "Pre-Compact",
    description: "Triggered before context compaction",
    icon: "📦",
  },
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
  timeout?: number;
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
];
