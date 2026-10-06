import assert from 'node:assert/strict'
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent'
import { SessionManager } from '@earendil-works/pi-coding-agent'
import deckMail from '../extension.ts'

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'deck-pi-owned-activity-'))
  const bin = join(root, 'bin')
  mkdirSync(bin)
  const executable = join(bin, 'tmux')
  writeFileSync(executable, '#!/bin/sh\nprintf "%s\\n" "$DECK_TEST_PANE_PID"\n')
  chmodSync(executable, 0o700)
  const values = {
    PATH: `${bin}:${process.env.PATH}`, TMUX_PANE: '%1', XDG_RUNTIME_DIR: root,
    DECK_TEST_PANE_PID: String(process.pid), CLAUDE_DECK_MAIL_OPT_IN: '1',
    CLAUDE_DECK_MAIL_PYTHON: process.execPath,
    CLAUDE_DECK_MAIL_SHIM: join(import.meta.dirname, 'fake-server.mjs'),
  }
  const previous = new Map<string, string | undefined>()
  for (const [key, value] of Object.entries(values)) {
    previous.set(key, process.env[key])
    process.env[key] = value
  }
  const fields = readFileSync(`/proc/${process.pid}/stat`, 'utf8').split(')').at(-1)!.trim().split(/\s+/)
  const marker = join(root, 'sessions', `.deck-native-${process.pid}-${fields[19]}.json`)
  const runtime = () => {
    const handlers = new Map<string, (event: never, ctx: ExtensionContext) => unknown>()
    const notifications: string[] = []
    const pi = {
      on: (event: string, handler: (event: never, ctx: ExtensionContext) => unknown) => {
        handlers.set(event, handler)
        return () => handlers.delete(event)
      },
      registerTool: () => {},
    } as unknown as ExtensionAPI
    const manager = SessionManager.create(root, join(root, 'sessions'))
    const ctx = { cwd: root, sessionManager: manager,
      ui: { notify: (message: string) => notifications.push(message) } } as unknown as ExtensionContext
    deckMail(pi)
    return { notifications, emit: async (event: string) => { await handlers.get(event)?.({} as never, ctx) } }
  }
  return { root, marker, runtime, close: () => {
    for (const [key, value] of previous) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
    rmSync(root, { recursive: true, force: true })
  } }
}

test('real Mail startup permits only the owning generation to record native activity', async () => {
  const f = fixture()
  const owner = f.runtime()
  const refused = f.runtime()
  try {
    await owner.emit('session_start')
    assert.deepEqual(owner.notifications, [])
    await owner.emit('agent_start')
    const original = readFileSync(f.marker, 'utf8')
    assert.equal(JSON.parse(original).state, 'working')
    await refused.emit('session_start')
    assert.equal(refused.notifications.length, 1)
    await refused.emit('agent_start')
    await refused.emit('ui_prompt_start')
    await refused.emit('session_shutdown')
    assert.equal(readFileSync(f.marker, 'utf8'), original)
    await owner.emit('agent_settled')
    assert.equal(JSON.parse(readFileSync(f.marker, 'utf8')).state, 'idle')
  } finally {
    await refused.emit('session_shutdown')
    await owner.emit('session_shutdown')
    f.close()
  }
})

test('a refused authenticated startup creates no activity even after native callbacks', async () => {
  const f = fixture()
  process.env.CLAUDE_DECK_MAIL_SHIM = join(f.root, 'missing-fixture-server.mjs')
  const failed = f.runtime()
  try {
    await failed.emit('session_start')
    assert.equal(failed.notifications.length, 1)
    await failed.emit('agent_start')
    await failed.emit('agent_settled')
    assert.equal(existsSync(f.marker), false)
  } finally { await failed.emit('session_shutdown'); f.close() }
})

test('a stale runtime callback cannot overwrite the replacement generation', async () => {
  const f = fixture()
  const old = f.runtime()
  const current = f.runtime()
  try {
    await old.emit('session_start')
    await old.emit('agent_start')
    await old.emit('session_shutdown')
    await current.emit('session_start')
    await current.emit('agent_start')
    const original = readFileSync(f.marker, 'utf8')
    await old.emit('agent_settled')
    await old.emit('ui_prompt_start')
    await old.emit('session_shutdown')
    assert.equal(readFileSync(f.marker, 'utf8'), original)
  } finally {
    await old.emit('session_shutdown')
    await current.emit('session_shutdown')
    f.close()
  }
})
