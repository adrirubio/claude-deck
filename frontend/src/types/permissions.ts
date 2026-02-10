// Permission TypeScript types matching backend schemas

export type PermissionType = "allow" | "deny" | "ask";
export type PermissionScope = "user" | "project";
export type PermissionMode = "default" | "acceptEdits" | "dontAsk" | "plan" | "bypassPermissions" | "delegate";

export interface PermissionRule {
  id: string;
  type: PermissionType;
  pattern: string; // Tool(pattern), Tool:subcommand, WebFetch(domain:...), MCP(server:tool), etc.
  scope: PermissionScope;
}

export interface PermissionRuleCreate {
  type: PermissionType;
  pattern: string;
  scope: PermissionScope;
}

export interface PermissionRuleUpdate {
  type?: PermissionType;
  pattern?: string;
}

export interface PermissionSettings {
  defaultMode?: PermissionMode;
  additionalDirectories?: string[];
  disableBypassPermissionsMode?: boolean;
}

export interface PermissionSettingsUpdate {
  defaultMode?: PermissionMode;
  additionalDirectories?: string[];
  disableBypassPermissionsMode?: boolean;
}

export interface PermissionListResponse {
  rules: PermissionRule[];
  settings?: PermissionSettings;
}

// UI-specific types
export interface RuleListProps {
  rules: PermissionRule[];
  type: PermissionType;
  onEdit: (rule: PermissionRule) => void;
  onDelete: (ruleId: string, scope: PermissionScope) => void;
}

// Permission tool type
export interface PermissionTool {
  name: string;
  description: string;
  hint?: string;
}

// Available tools for permission patterns
export const PERMISSION_TOOLS: PermissionTool[] = [
  { name: "Bash", description: "Shell command execution" },
  { name: "Read", description: "File reading" },
  { name: "Write", description: "File creation" },
  { name: "Edit", description: "File editing" },
  { name: "Glob", description: "File pattern matching" },
  { name: "Grep", description: "Content searching" },
  { name: "WebFetch", description: "Web requests", hint: "domain:example.com" },
  { name: "Task", description: "Subagent tasks", hint: "* or task-name" },
  { name: "Skill", description: "Skills/prompts", hint: "skill-name" },
  { name: "MCP", description: "MCP server tools", hint: "server:tool or server:*" },
  { name: "TodoWrite", description: "Todo list updates" },
  { name: "NotebookEdit", description: "Jupyter notebook editing" },
];

// Pattern examples for UI help - expanded with new syntax
export const PATTERN_EXAMPLES = [
  { pattern: "Bash(npm run *)", description: "Allow npm run commands" },
  { pattern: "Bash(git *)", description: "Allow git commands" },
  { pattern: "Read(~/.zshrc)", description: "Read specific file" },
  { pattern: "Write(*.py)", description: "Write Python files" },
  { pattern: "Edit(/etc/*)", description: "Edit files in /etc" },
  { pattern: "Bash(rm *)", description: "Remove commands (dangerous)" },
  { pattern: "WebFetch(*)", description: "All web requests" },
  { pattern: "WebFetch(domain:github.com)", description: "Fetch from GitHub" },
  { pattern: "WebFetch(domain:*.anthropic.com)", description: "Fetch from Anthropic domains" },
  { pattern: "MCP(filesystem:*)", description: "All filesystem MCP tools" },
  { pattern: "MCP(postgres:query)", description: "Specific MCP tool" },
  { pattern: "Task(*)", description: "All subagent tasks" },
  { pattern: "Task:explore", description: "Explore task type" },
  { pattern: "Skill(code-review)", description: "Specific skill" },
  { pattern: "Skill(*)", description: "All skills" },
];

// Permission mode descriptions
export const PERMISSION_MODES: { value: PermissionMode; label: string; description: string }[] = [
  {
    value: "default",
    label: "Default",
    description: "Ask for permission on unmatched operations",
  },
  {
    value: "acceptEdits",
    label: "Accept Edits",
    description: "Auto-approve file edits, ask for other operations",
  },
  {
    value: "dontAsk",
    label: "Don't Ask",
    description: "Auto-approve all operations (use with caution)",
  },
  {
    value: "plan",
    label: "Plan Mode",
    description: "Claude will propose changes without executing",
  },
  {
    value: "bypassPermissions",
    label: "Bypass Permissions",
    description: "Auto-approve all operations including dangerous ones",
  },
  {
    value: "delegate",
    label: "Delegate",
    description: "Run as a sub-agent with limited permissions",
  },
];

// Pattern syntax help
export const PATTERN_SYNTAX_HELP = `
**Permission Pattern Syntax:**

- \`Tool\` - Match any use of the tool
- \`Tool(pattern)\` - Match tool with argument pattern
- \`Tool:subcommand\` - Match specific subcommand (for Bash)
- \`Tool(prefix *)\` - Match tool with prefix and wildcard

**Extended Patterns:**

- \`WebFetch(domain:example.com)\` - Web fetch by domain
- \`WebFetch(domain:*.github.com)\` - Domain with wildcard
- \`MCP(server:tool)\` - MCP server tool
- \`MCP(server:*)\` - All tools from MCP server
- \`Task(*)\` - All subagent tasks
- \`Task:explore\` - Specific task type
- \`Skill(skill-name)\` - Specific skill

**Wildcards:**
- \`*\` - Match any characters

**Examples:**
- \`Bash(npm run *)\` - Any npm run command
- \`Read(*.env)\` - Read .env files
- \`Write(/tmp/*)\` - Write to /tmp directory
`;
