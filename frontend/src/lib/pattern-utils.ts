/**
 * Permission pattern validation and migration utilities.
 *
 * Validates permission patterns against Claude Code's current rules
 * and provides migration for deprecated pattern formats.
 */

const MAX_PATTERN_LENGTH = 500

const TOOL_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/
const TOOL_ARG_RE = /^([A-Za-z_][A-Za-z0-9_]*)\((.+)\)$/s
const TOOL_SUBCOMMAND_RE = /^([A-Za-z_][A-Za-z0-9_]*):\*$/
const DEPRECATED_COLON_STAR_RE = /:\*$/

export interface PatternValidation {
  valid: boolean
  error?: string
}

export interface PatternIssue {
  pattern: string
  category: string
  error: string
  suggestion?: string
}

/**
 * Validate a permission pattern against Claude Code's current rules.
 */
export function validatePermissionPattern(pattern: string): PatternValidation {
  if (!pattern || !pattern.trim()) {
    return { valid: false, error: 'Pattern must not be empty' }
  }

  if (pattern.includes('\n') || pattern.includes('\r')) {
    return { valid: false, error: 'Pattern must not contain newline characters' }
  }

  if (pattern.length > MAX_PATTERN_LENGTH) {
    return { valid: false, error: `Pattern exceeds maximum length of ${MAX_PATTERN_LENGTH} characters` }
  }

  // Check Tool(argument) format
  const match = pattern.match(TOOL_ARG_RE)
  if (match) {
    const tool = match[1]
    const arg = match[2]
    // Don't flag MCP patterns — server:* is valid MCP syntax for "all tools from server"
    if (tool !== 'MCP' && DEPRECATED_COLON_STAR_RE.test(arg)) {
      return {
        valid: false,
        error: 'The :* pattern inside Tool(...) is deprecated. Use space-wildcard instead: e.g., Bash(command *) not Bash(command:*)',
      }
    }
    return { valid: true }
  }

  // Check Tool:* format (valid prefix matching)
  if (TOOL_SUBCOMMAND_RE.test(pattern)) {
    return { valid: true }
  }

  // Check simple tool name (including mcp__server__tool format)
  if (TOOL_NAME_RE.test(pattern)) {
    return { valid: true }
  }

  return { valid: false, error: `Invalid pattern format: ${pattern}` }
}

/**
 * Attempt to migrate a deprecated pattern to the current valid format.
 * Returns null if migration is not possible.
 */
export function migrateDeprecatedPattern(pattern: string): string | null {
  if (pattern.includes('\n') || pattern.includes('\r')) return null
  if (pattern.length > MAX_PATTERN_LENGTH) return null

  const match = pattern.match(TOOL_ARG_RE)
  if (match) {
    const tool = match[1]
    const arg = match[2]
    // Don't migrate MCP patterns — server:* is valid MCP syntax
    if (tool !== 'MCP' && DEPRECATED_COLON_STAR_RE.test(arg)) {
      const migratedArg = arg.replace(DEPRECATED_COLON_STAR_RE, ' *')
      return `${tool}(${migratedArg})`
    }
  }

  return null
}

/**
 * Find all invalid patterns in a settings object's permission rules.
 */
export function findPatternIssues(settings: Record<string, unknown>): PatternIssue[] {
  const issues: PatternIssue[] = []
  const permissions = settings.permissions as Record<string, unknown> | undefined
  if (!permissions || typeof permissions !== 'object') return issues

  for (const category of ['allow', 'ask', 'deny'] as const) {
    const rules = permissions[category]
    if (!Array.isArray(rules)) continue

    for (const pattern of rules) {
      if (typeof pattern !== 'string') {
        issues.push({ pattern: String(pattern), category, error: 'Pattern is not a string' })
        continue
      }
      const result = validatePermissionPattern(pattern)
      if (!result.valid) {
        issues.push({
          pattern,
          category,
          error: result.error || 'Invalid pattern',
          suggestion: migrateDeprecatedPattern(pattern) ?? undefined,
        })
      }
    }
  }

  return issues
}

/**
 * Apply fixes to permission rules in a settings object.
 * Migrates deprecated patterns and removes unmigrable ones.
 */
export function applyPatternFixes(settings: Record<string, unknown>): Record<string, unknown> {
  const permissions = settings.permissions as Record<string, unknown> | undefined
  if (!permissions || typeof permissions !== 'object') return settings

  const fixedPermissions = { ...permissions }

  for (const category of ['allow', 'ask', 'deny'] as const) {
    const rules = permissions[category]
    if (!Array.isArray(rules)) continue

    const fixedRules: string[] = []
    for (const pattern of rules) {
      if (typeof pattern !== 'string') continue

      const result = validatePermissionPattern(pattern)
      if (result.valid) {
        fixedRules.push(pattern)
        continue
      }

      const migrated = migrateDeprecatedPattern(pattern)
      if (migrated !== null) {
        const migratedResult = validatePermissionPattern(migrated)
        if (migratedResult.valid) {
          fixedRules.push(migrated)
          continue
        }
      }
      // Invalid and can't migrate — skip (remove)
    }
    fixedPermissions[category] = fixedRules
  }

  return { ...settings, permissions: fixedPermissions }
}
