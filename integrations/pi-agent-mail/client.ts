import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { closeSync, constants, lstatSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { manifest, privateTools } from './manifest.ts'

export type Envelope = Record<string, unknown> & { ok: boolean }
export type MailResult = {
  content: Array<{ type: 'text'; text: string } | { type: 'image'; data: string; mimeType: string }>
  details: { deck: Envelope; deckError: boolean; mappingError?: string }
}

export function failure(code: string, uncertain = false): MailResult {
  const deck: Envelope = { ok: false, error: { code }, ...(uncertain && {
    outcome: 'unknown', suggestion: 'Do not repeat the mutation blindly. Reconcile its outcome with read-only inspection or the operator.',
  }) }
  return { content: [{ type: 'text', text: JSON.stringify(deck) }], details: { deck, deckError: true } }
}

export function adaptResult(result: unknown): MailResult {
  if (!result || typeof result !== 'object') return failure('malformed_mcp_result')
  const raw = result as Record<string, unknown>
  const blocks = Array.isArray(raw.content) ? raw.content : []
  let envelope: unknown = raw.structuredContent
  if (!envelope) {
    const text = blocks.filter(block => block.type === 'text').map(block => block.text).join('\n')
    try { envelope = JSON.parse(text) } catch { return failure('malformed_mcp_result') }
  }
  if (!envelope || typeof envelope !== 'object' || typeof (envelope as Envelope).ok !== 'boolean') {
    return failure(raw.isError === true ? 'mcp_protocol_error' : 'malformed_mcp_result')
  }
  const deck = envelope as Envelope
  const images = blocks.filter(block => block.type === 'image')
  const mappingError = blocks.some(block => !['text', 'image'].includes(block.type))
    ? 'unsupported_mcp_content'
    : images.some(block => typeof block.data !== 'string' || typeof block.mimeType !== 'string')
      ? 'malformed_mcp_content' : undefined
  if (mappingError) return {
    content: [{ type: 'text', text: JSON.stringify(deck) }, { type: 'text', text: JSON.stringify({ mappingError }) }],
    details: { deck, deckError: true, mappingError },
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(deck) }, ...images],
    details: { deck, deckError: !deck.ok || raw.isError === true },
  }
}

export function toolResultOverride(event: { toolName: string; content: MailResult['content']; details: unknown }) {
  if (!manifest.some(tool => tool.name === event.toolName)) return
  const details = event.details as MailResult['details'] | undefined
  if (details?.deckError) return { content: event.content, details, isError: true }
}

export function childEnvironment(environment: NodeJS.ProcessEnv): Record<string, string> {
  const allowed = ['PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'TMPDIR', 'TMUX', 'TMUX_PANE',
    'CLAUDE_DECK_URL', 'CLAUDE_DECK_TEAM_PRESET_ID', 'CLAUDE_DECK_TEAM_SLOT_ID']
  const clean: Record<string, string> = { CLAUDE_DECK_PROVIDER: 'pi-cli', PYTHONUNBUFFERED: '1' }
  for (const key of allowed) if (environment[key]) clean[key] = environment[key]!
  return clean
}

function processIdentity(pid: number) {
  const stat = readFileSync(`/proc/${pid}/stat`, 'utf8')
  const fields = stat.slice(stat.lastIndexOf(')') + 2).split(' ')
  return { parent: Number(fields[1]), start: fields[19] }
}

export function resolvePaneIdentity(): { pid: number; start: string } {
  const pane = process.env.TMUX_PANE
  if (!pane || !/^%\d+$/.test(pane)) throw new Error('pane_unresolved')
  const pid = Number(execFileSync('tmux', ['display-message', '-p', '-t', pane, '#{pane_pid}'], { timeout: 1000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim())
  if (!Number.isSafeInteger(pid) || pid < 1) throw new Error('pane_unresolved')
  let ancestor = process.pid
  for (let depth = 0; depth < 32 && ancestor > 0; depth++) {
    const identity = processIdentity(ancestor)
    if (ancestor === pid) return { pid, start: identity.start }
    ancestor = identity.parent
  }
  throw new Error('pane_unresolved')
}

export class PaneFence {
  readonly generation = randomUUID()
  readonly file: string

  constructor(pane: { pid: number; start: string }, root = process.env.XDG_RUNTIME_DIR || `/tmp/claude-deck-pi-${process.getuid!()}`) {
    if (!Number.isSafeInteger(pane.pid) || pane.pid < 1 || !/^\d+$/.test(pane.start)) throw new Error('pane_unresolved')
    mkdirSync(root, { mode: 0o700, recursive: true })
    const directory = join(root, 'claude-deck-pi')
    for (const candidate of [root, directory]) {
      if (candidate === directory) mkdirSync(candidate, { mode: 0o700, recursive: true })
      const stat = lstatSync(candidate)
      if (!stat.isDirectory() || stat.uid !== process.getuid!() || (stat.mode & 0o077) !== 0) throw new Error('fence_directory_unsafe')
    }
    this.file = join(directory, `${pane.pid}-${pane.start}.json`)
    const descriptor = openSync(this.file, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600)
    try { writeFileSync(descriptor, JSON.stringify({ generation: this.generation, pane, piPid: process.pid, piStart: processIdentity(process.pid).start })) }
    finally { closeSync(descriptor) }
  }

  release() {
    const descriptor = openSync(this.file, constants.O_RDONLY | constants.O_NOFOLLOW)
    try {
      const stored = JSON.parse(readFileSync(descriptor, 'utf8'))
      if (stored.generation !== this.generation) throw new Error('fence_generation_changed')
      unlinkSync(this.file)
    } finally { closeSync(descriptor) }
  }
}

const readOnlyTools = new Set<string>()

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, entry]) => `${JSON.stringify(key)}:${canonical(entry)}`).join(',')}}`
  return JSON.stringify(value)
}

export class MailGeneration {
  private client = new Client({ name: 'claude-deck-pi', version: '1.0.0' })
  private transport?: StdioClientTransport
  private ready = false
  private closing = false
  private closePromise?: Promise<void>
  private registrationDispatched = false

  constructor(private fence: PaneFence, private environment = process.env) {}

  async start(cwd: string) {
    const command = this.environment.CLAUDE_DECK_MAIL_PYTHON
    const shim = this.environment.CLAUDE_DECK_MAIL_SHIM
    if (!command?.startsWith('/') || !shim?.startsWith('/')) throw new Error('mail_paths_invalid')
    this.transport = new StdioClientTransport({ command, args: [shim], cwd, env: childEnvironment(this.environment), stderr: 'ignore' })
    try {
      await this.client.connect(this.transport, { timeout: 5000 })
      if (this.closing) throw new Error('mail_generation_closing')
      const actual = await this.client.listTools({}, { timeout: 5000 })
      if (this.closing) throw new Error('mail_generation_closing')
      const expected = [...manifest, ...privateTools]
      if (actual.tools.length !== expected.length || expected.some(tool => {
        const found = actual.tools.find(candidate => candidate.name === tool.name)
        return !found || canonical(found.inputSchema) !== canonical(tool.inputSchema)
      })) throw new Error('mail_schema_mismatch')
      this.registrationDispatched = true
      const identity = adaptResult(await this.client.callTool({ name: 'deck_whoami', arguments: {} }, undefined, { timeout: 20000 }))
      if (identity.details.deckError || this.closing) throw new Error('mail_registration_failed')
      this.ready = true
    } catch {
      await this.close()
      throw new Error('mail_startup_failed')
    }
  }

  async call(name: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<MailResult> {
    if (!this.ready || this.closing) return failure('mail_not_ready')
    if (signal?.aborted) return failure('tool_not_dispatched')
    try {
      const result = adaptResult(await this.client.callTool({ name, arguments: args }, undefined, { signal, timeout: 30000 }))
      const code = (result.details.deck.error as { code?: string })?.code
      if (!readOnlyTools.has(name) && (result.details.deck.outcome === 'unknown'
        || (result.details.deck.ok && result.details.deckError && !result.details.mappingError) || [
        'deck_unreachable', 'malformed_mcp_result', 'unsupported_mcp_content', 'mcp_protocol_error',
      ].includes(code || ''))) {
        return failure('mutation_outcome_unknown', true)
      }
      return result
    } catch {
      return failure(readOnlyTools.has(name) ? 'mail_transport_unavailable' : 'mutation_outcome_unknown', !readOnlyTools.has(name))
    }
  }

  close(): Promise<void> {
    if (this.closePromise) return this.closePromise
    this.closing = true
    this.ready = false
    this.closePromise = this.finishClose()
    return this.closePromise
  }

  private async finishClose() {
    try {
      if (!this.registrationDispatched) this.fence.release()
      else {
        const result = adaptResult(await this.client.callTool({ name: '__deck_mail_close_generation', arguments: {} }, undefined, { timeout: 5000 }))
        if (!result.details.deckError && result.details.deck.ok && result.details.deck.closed === true) this.fence.release()
      }
    } catch {
    } finally {
      await this.client.close().catch(() => undefined)
    }
  }
}
