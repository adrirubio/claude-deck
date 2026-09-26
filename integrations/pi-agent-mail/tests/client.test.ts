import assert from 'node:assert/strict'
import { test } from 'node:test'
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import deckMail from '../extension.ts'
import { adaptResult, childEnvironment, MailGeneration, PaneFence, toolResultOverride } from '../client.ts'
import { manifest, privateTools } from '../manifest.ts'
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'deck-pi-test-'))
  const fence = new PaneFence({ pid: process.pid, start: '1' }, root)
  const generation = new MailGeneration(fence, {
    PATH: process.env.PATH, HOME: root,
    CLAUDE_DECK_MAIL_PYTHON: process.execPath,
    CLAUDE_DECK_MAIL_SHIM: join(import.meta.dirname, 'fake-server.mjs'),
    OPENROUTER_API_KEY: 'synthetic-secret', GITHUB_TOKEN: 'synthetic-secret', OPERATOR_TOKEN: 'synthetic-secret',
  })
  return { root, fence, generation }
}

test('no opt-in means no tools, listeners, transport or prompts', () => {
  const old = process.env.CLAUDE_DECK_MAIL_OPT_IN
  delete process.env.CLAUDE_DECK_MAIL_OPT_IN
  try { deckMail(new Proxy({}, { get() { throw new Error('unexpected side effect') } }) as ExtensionAPI) }
  finally { if (old !== undefined) process.env.CLAUDE_DECK_MAIL_OPT_IN = old }
})

test('public tools contain authority schemas but never private close', () => {
  assert(manifest.some(tool => tool.name === 'deck_decide_continuation' && tool.inputSchema.required.includes('approval_request_id' as never)))
  assert(manifest.every(tool => tool.name.startsWith('deck_')))
  assert.equal(privateTools[0].name, '__deck_mail_close_generation')
  assert.equal(privateTools[0].inputSchema.additionalProperties, false)
})

for (const status of [403, 409]) test(`final Pi result event preserves ${status} and error semantics`, () => {
  const result = adaptResult({ content: [], structuredContent: { ok: false, error: { code: 'conflict', status_code: status } } })
  const override = toolResultOverride({ toolName: 'deck_send_message', ...result })
  assert.equal(override?.isError, true)
  assert.equal((override?.details.deck.error as { status_code: number }).status_code, status)
  assert.match(result.content[0].type === 'text' ? result.content[0].text : '', new RegExp(String(status)))
  assert.equal(toolResultOverride({ toolName: 'unrelated', ...result }), undefined)
})

test('supported images survive and unsupported or malformed blocks refuse', () => {
  const envelope = { ok: true }
  const result = adaptResult({ structuredContent: envelope, content: [{ type: 'image', data: 'AA==', mimeType: 'image/png' }] })
  assert.equal(result.content[1].type, 'image')
  assert.equal(adaptResult({ structuredContent: envelope, content: [{ type: 'resource' }] }).details.deckError, true)
  assert.equal(adaptResult({ content: [{ type: 'text', text: 'not JSON' }] }).details.deckError, true)
})

test('pane-scoped fence blocks new Pi generation, preserves unresolved close, and rejects stale unlink', () => {
  const root = mkdtempSync(join(tmpdir(), 'deck-pi-fence-'))
  try {
    const fence = new PaneFence({ pid: 12, start: '23' }, root)
    assert.throws(() => new PaneFence({ pid: 12, start: '23' }, root))
    const replacement = new PaneFence({ pid: 12, start: '24' }, root)
    replacement.release()
    writeFileSync(fence.file, JSON.stringify({ generation: 'replacement' }))
    assert.throws(() => fence.release(), /fence_generation_changed/)
    assert(existsSync(fence.file))
  } finally { rmSync(root, { recursive: true }) }
})

test('unsafe runtime directory refuses before creating fence', () => {
  const root = mkdtempSync(join(tmpdir(), 'deck-pi-unsafe-'))
  try {
    chmodSync(root, 0o755)
    assert.throws(() => new PaneFence({ pid: 12, start: '23' }, root), /fence_directory_unsafe/)
  } finally { rmSync(root, { recursive: true }) }
})

test('environment allowlist excludes credentials', () => {
  const environment = childEnvironment({ HOME: '/fixture', OPENROUTER_API_KEY: 'secret', OPERATOR_TOKEN: 'secret', GH_TOKEN: 'secret' })
  assert.equal(environment.OPENROUTER_API_KEY, undefined)
  assert.equal(environment.OPERATOR_TOKEN, undefined)
  assert.equal(environment.GH_TOKEN, undefined)
})

test('real stdio transport has parity, one registration, safe env and acknowledged teardown', async () => {
  const { root, fence, generation } = fixture()
  try {
    await generation.start(root)
    const results = await Promise.all([generation.call('deck_list_team', {}), generation.call('deck_list_team', {})])
    assert.deepEqual(results.map(result => result.details.deck.calls), [2, 3])
    for (const result of results) {
      const keys = result.details.deck.environmentKeys as string[]
      assert(!keys.some(key => /TOKEN|KEY/.test(key)))
    }
    await generation.close()
    await generation.close()
    assert(!existsSync(fence.file))
    assert.equal(generation.call && (await generation.call('deck_list_team', {})).details.deckError, true)
  } finally { await generation.close(); rmSync(root, { recursive: true }) }
})

for (const body of ['offline', 'disconnect', 'protocol-error', 'malformed-json', 'malformed-envelope', 'unsupported-content']) test(`uncertain mutation (${body}) is never retried`, async () => {
  const { root, fence, generation } = fixture()
  try {
    await generation.start(root)
    const result = await generation.call('deck_send_message', { body_markdown: body })
    assert.equal((result.details.deck.error as { code: string }).code, 'mutation_outcome_unknown')
    assert.equal(result.details.deck.outcome, 'unknown')
    if (body === 'disconnect') { await generation.close(); assert(existsSync(fence.file)) }
  } finally { await generation.close(); rmSync(root, { recursive: true }) }
})

for (const body of ['lose-close', 'error-close']) test(`${body} persists the fence across runtime replacement`, async () => {
  const { root, fence, generation } = fixture()
  try {
    await generation.start(root)
    await generation.call('deck_send_message', { body_markdown: body })
    await generation.close()
    assert(existsSync(fence.file))
    assert.throws(() => new PaneFence({ pid: process.pid, start: '1' }, root))
    assert(!readFileSync(fence.file, 'utf8').includes('synthetic-secret'))
  } finally { await generation.close(); rmSync(root, { recursive: true }) }
})

test('mapping failure preserves a definitive Deck outcome rather than replacing it', () => {
  const envelope = { ok: false, error: { code: 'stale_nonce', status_code: 409 } }
  const result = adaptResult({ structuredContent: envelope, content: [{ type: 'resource' }] })
  assert.deepEqual(result.details.deck, envelope)
  assert.equal(result.details.mappingError, 'unsupported_mcp_content')
  assert.equal(toolResultOverride({ toolName: 'deck_send_message', ...result })?.isError, true)
})

test('abort before dispatch is definite; abort after dispatch is unknown', async () => {
  const { root, generation } = fixture()
  try {
    await generation.start(root)
    const before = AbortSignal.abort()
    const result = await generation.call('deck_send_message', {}, before)
    assert.equal((result.details.deck.error as { code: string }).code, 'tool_not_dispatched')
    const controller = new AbortController()
    const pending = generation.call('deck_send_message', { body_markdown: 'delay' }, controller.signal)
    controller.abort()
    assert.equal((await pending).details.deck.outcome, 'unknown')
  } finally { await generation.close(); rmSync(root, { recursive: true }) }
})
