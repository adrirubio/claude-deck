// TypeScript types for slash commands

export interface SlashCommand {
  name: string;
  path: string;
  scope: 'user' | 'project';
  description?: string;
  allowed_tools?: string[];
  content: string;
}

export interface SlashCommandCreate {
  name: string;
  scope: 'user' | 'project';
  description?: string;
  allowed_tools?: string[];
  content: string;
}

export interface SlashCommandUpdate {
  description?: string;
  allowed_tools?: string[];
  content?: string;
}

export interface SlashCommandListResponse {
  commands: SlashCommand[];
}

// Namespace-aware command representation
export interface CommandTreeNode {
  name: string;
  path: string;
  scope: 'user' | 'project';
  isNamespace: boolean;
  children?: CommandTreeNode[];
  command?: SlashCommand;
}

// Command templates
export interface CommandTemplate {
  name: string;
  description: string;
  defaultContent: string;
  defaultAllowedTools?: string[];
}

export const COMMAND_TEMPLATES: CommandTemplate[] = [
  {
    name: 'blank',
    description: 'Start with a blank command',
    defaultContent: 'Your command instructions here.\n\nUsage: /command-name <args>',
  },
  {
    name: 'review',
    description: 'Code review command',
    defaultContent: `Review the code in: $ARGUMENTS

Please analyze the code for:
- Bugs and logic errors
- Security vulnerabilities
- Performance issues
- Code quality and best practices
- Readability and maintainability

Provide specific, actionable feedback.`,
    defaultAllowedTools: ['Read', 'Grep', 'Glob'],
  },
  {
    name: 'test',
    description: 'Test generation command',
    defaultContent: `Generate comprehensive tests for: $ARGUMENTS

Create tests that cover:
- Happy path scenarios
- Edge cases
- Error handling
- Input validation

Use the appropriate testing framework for the language.`,
    defaultAllowedTools: ['Read', 'Write', 'Grep'],
  },
  {
    name: 'explain',
    description: 'Code explanation command',
    defaultContent: `Explain the code in: $ARGUMENTS

Provide:
1. High-level overview of what the code does
2. Explanation of key functions and logic
3. Notable patterns or techniques used
4. Potential areas for improvement

Make it understandable for someone new to the codebase.`,
    defaultAllowedTools: ['Read', 'Grep', 'Glob'],
  },
  {
    name: 'refactor',
    description: 'Refactoring command',
    defaultContent: `Refactor the code in: $ARGUMENTS

Focus on:
- Improving code structure and organization
- Reducing complexity
- Enhancing readability
- Maintaining existing functionality
- Following best practices and patterns

Explain each refactoring change and why it improves the code.`,
    defaultAllowedTools: ['Read', 'Edit', 'Write', 'Grep'],
  },
  {
    name: 'debug',
    description: 'Debugging assistance command',
    defaultContent: `Debug the issue in: $ARGUMENTS

Steps:
1. Reproduce and understand the problem
2. Identify the root cause
3. Propose and implement a fix
4. Verify the fix works
5. Suggest how to prevent similar issues

Add logging or debugging output as needed.`,
    defaultAllowedTools: ['Read', 'Edit', 'Write', 'Bash', 'Grep'],
  },
];

// Available tools for commands
export const AVAILABLE_TOOLS = [
  'Read',
  'Write',
  'Edit',
  'Bash',
  'Glob',
  'Grep',
  'WebFetch',
  'Task',
  'LSP',
  'Skill',
  'AskUserQuestion',
  'TodoWrite',
  'NotebookEdit',
  'EnterPlanMode',
  'ExitPlanMode',
];
