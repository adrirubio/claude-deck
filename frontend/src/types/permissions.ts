// Permission TypeScript types matching backend schemas

export type PermissionType = "allow" | "deny";
export type PermissionScope = "user" | "project";

export interface PermissionRule {
  id: string;
  type: PermissionType;
  pattern: string; // Tool(pattern) or Tool:subcommand
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

export interface PermissionListResponse {
  rules: PermissionRule[];
}

// UI-specific types
export interface RuleListProps {
  rules: PermissionRule[];
  type: PermissionType;
  onEdit: (rule: PermissionRule) => void;
  onDelete: (ruleId: string, scope: PermissionScope) => void;
}

// Available tools for permission patterns
export const PERMISSION_TOOLS = [
  { name: "Bash", description: "Shell command execution" },
  { name: "Read", description: "File reading" },
  { name: "Write", description: "File creation" },
  { name: "Edit", description: "File editing" },
  { name: "Glob", description: "File pattern matching" },
  { name: "Grep", description: "Content searching" },
  { name: "WebFetch", description: "Web requests" },
  { name: "Task", description: "Subagent tasks" },
  { name: "TodoWrite", description: "Todo list updates" },
  { name: "NotebookEdit", description: "Jupyter notebook editing" },
  { name: "mcp", description: "MCP server tools" },
] as const;

// Pattern examples for UI help
export const PATTERN_EXAMPLES = [
  { pattern: "Bash(npm:*)", description: "Allow npm commands" },
  { pattern: "Bash(git:*)", description: "Allow git commands" },
  { pattern: "Read(~/.zshrc)", description: "Read specific file" },
  { pattern: "Write(*.py)", description: "Write Python files" },
  { pattern: "Edit(/etc/*)", description: "Edit files in /etc" },
  { pattern: "Bash(rm:*)", description: "Remove commands (dangerous)" },
  { pattern: "WebFetch(*)", description: "All web requests" },
];

// Pattern syntax help
export const PATTERN_SYNTAX_HELP = `
**Permission Pattern Syntax:**

- \`Tool\` - Match any use of the tool
- \`Tool(pattern)\` - Match tool with argument pattern
- \`Tool:subcommand\` - Match specific subcommand (for Bash)
- \`Tool(prefix:*)\` - Prefix matching with colon

**Wildcards:**
- \`*\` - Match any characters
- Use \`:*\` for prefix matching in Bash commands

**Examples:**
- \`Bash(npm:*)\` - Any npm command
- \`Read(*.env)\` - Read .env files
- \`Write(/tmp/*)\` - Write to /tmp directory
`;
