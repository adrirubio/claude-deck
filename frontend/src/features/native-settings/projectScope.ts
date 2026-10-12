// Native pages whose data depends on a project folder. Each one reads the
// project from its own URL (?project=<path>), not from a server-wide setting.
const PROJECT_SCOPED_SURFACES = new Set([
  'summary', 'config', 'mcp', 'plugins', 'commands', 'hooks', 'permissions', 'agents',
  'skills', 'memory', 'backup', 'output-styles', 'plans',
])

/** The project-scoped native surface that a URL path shows, or null. */
export function projectScopedSurface(pathname: string): string | null {
  const parts = pathname.split('/').filter(Boolean)
  const surface = parts[0] === 'harnesses' ? parts[2] : parts[0]
  return surface && PROJECT_SCOPED_SURFACES.has(surface) ? surface : null
}
