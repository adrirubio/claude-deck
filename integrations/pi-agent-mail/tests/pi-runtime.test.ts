import assert from 'node:assert/strict'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { test } from 'node:test'
import { Compile } from 'typebox/compile'
import type { TSchema } from 'typebox'
import { AgentSession, ExtensionRunner } from '@earendil-works/pi-coding-agent'
import { adaptResult } from '../client.ts'
import { manifest } from '../manifest.ts'

const packageRoot = dirname(dirname(fileURLToPath(import.meta.resolve('@earendil-works/pi-coding-agent'))))
const { validateToolArguments } = await import(pathToFileURL(join(packageRoot, '../pi-ai/dist/utils/validation.js')).href)
const { loadExtensions } = await import(pathToFileURL(join(packageRoot, 'dist/core/extensions/loader.js')).href)

test('pinned Pi loader and TypeBox validate every real public schema without starting a session', async () => {
  const previous = process.env.CLAUDE_DECK_MAIL_OPT_IN
  process.env.CLAUDE_DECK_MAIL_OPT_IN = '1'
  try {
    const loaded = await loadExtensions([join(import.meta.dirname, '../extension.ts')], import.meta.dirname)
    assert.deepEqual(loaded.errors, [])
    const definitions = [...loaded.extensions[0].tools.values()].map((tool: { definition: { name: string } }) => tool.definition)
    assert.equal(definitions.length, 25)
    for (const tool of manifest) Compile(tool.inputSchema as unknown as TSchema)
    const validate = (name: string, args: Record<string, unknown>) => {
      const definition = definitions.find((tool: { name: string }) => tool.name === name)
      return validateToolArguments(definition, { id: 'fixture', type: 'toolCall', name, arguments: args })
    }
    assert.deepEqual(validate('deck_check_inbox', { unread_only: false, limit: 10 }), { unread_only: false, limit: 10 })
    assert.throws(() => validate('deck_decide_continuation', { decision: 'approved' }))
    assert.equal(validate('deck_decide_continuation', { approval_request_id: 3, work_item_id: 1, dispatch_nonce: 'fixture', decision: 'approved', reason: 'fixture' }).approval_request_id, 3)
    const report = { work_item_id: 1, status: 'triaging', dispatch_nonce: null, evidence: { paths: ['docs/readme.md'], mode: null } }
    assert.deepEqual(validate('deck_report_dispatch_status', report), report)
    const nested = {
      type: 'object', required: ['scope'], properties: { scope: { $ref: '#/$defs/Scope' } },
      $defs: { Scope: { type: 'object', required: ['paths', 'options'], properties: {
        paths: { type: 'array', items: { type: 'string' } }, options: { type: 'object', additionalProperties: { type: ['string', 'null'] } },
      } } },
    }
    assert(Compile(nested as TSchema).Check({ scope: { paths: ['docs/readme.md'], options: { mode: null } } }))
    assert.throws(() => validateToolArguments({ name: 'fixture', parameters: nested }, { id: 'fixture', name: 'fixture', arguments: { scope: { paths: [false], options: {} } } }))
  } finally {
    if (previous === undefined) delete process.env.CLAUDE_DECK_MAIL_OPT_IN
    else process.env.CLAUDE_DECK_MAIL_OPT_IN = previous
  }
})

test('actual Pi extension runner and AgentSession hook preserve final native tool errors', async () => {
  const previous = process.env.CLAUDE_DECK_MAIL_OPT_IN
  process.env.CLAUDE_DECK_MAIL_OPT_IN = '1'
  try {
    const loaded = await loadExtensions([join(import.meta.dirname, '../extension.ts')], import.meta.dirname)
    assert.deepEqual(loaded.errors, [])
    const runner = new ExtensionRunner(loaded.extensions, loaded.runtime, import.meta.dirname, {} as never, {} as never)
    const context = {
      agent: {} as { afterToolCall: (args: unknown) => Promise<{ isError: boolean; content: unknown; details: unknown }> },
      _extensionRunner: runner,
      settingsManager: { getImageAutoResize: () => false },
      model: undefined,
    }
    const prototype = AgentSession.prototype as unknown as { _installAgentToolHooks: (this: typeof context) => void }
    prototype._installAgentToolHooks.call(context)
    for (const status of [403, 409]) {
      const result = adaptResult({ structuredContent: { ok: false, error: { code: 'fixture_conflict', status_code: status } }, content: [] })
      const final = await context.agent.afterToolCall({ toolCall: { id: 'fixture', name: 'deck_send_message' }, args: {}, result, isError: false })
      assert.equal(final.isError, true)
      assert.deepEqual(final.details, result.details)
      assert.deepEqual(final.content, result.content)
    }
  } finally {
    if (previous === undefined) delete process.env.CLAUDE_DECK_MAIL_OPT_IN
    else process.env.CLAUDE_DECK_MAIL_OPT_IN = previous
  }
})
