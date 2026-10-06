import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent'
import { SessionManager } from '@earendil-works/pi-coding-agent'
import { registerNativeActivity } from '../activity.ts'

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'deck-pi-activity-'))
  const manager = SessionManager.create(root, join(root, 'sessions'))
  const fields = readFileSync(`/proc/${process.pid}/stat`, 'utf8').split(')').at(-1)!.trim().split(/\s+/)
  const pane = { pid: process.pid, start: fields[19] }
  const handlers = new Map<string, (event: never, ctx: ExtensionContext) => void>()
  const pi = { on: (name: string, callback: (event: never, ctx: ExtensionContext) => void) => {
    handlers.set(name, callback)
    return () => handlers.delete(name)
  } } as unknown as ExtensionAPI
  let idle = true
  const ctx = { cwd: root, sessionManager: manager, isIdle: () => idle } as unknown as ExtensionContext
  const recorder = registerNativeActivity(pi)
  let owned = true
  const emit = (name: string, event: Record<string, unknown> = {}) => {
    if (name === 'session_start') recorder.start(ctx, pane, () => owned)
    else if (name === 'session_shutdown') recorder.stop()
    else handlers.get(name)?.(event as never, ctx)
  }
  const marker = join(manager.getSessionDir(), `.deck-native-${pane.pid}-${pane.start}.json`)
  const read = () => JSON.parse(readFileSync(marker, 'utf8'))
  return { root, manager, pane, handlers, ctx, emit, marker, read, recorder,
    setOwned: (value: boolean) => { owned = value },
    setIdle: (value: boolean) => { idle = value },
    close: () => { recorder.stop(); rmSync(root, { recursive: true, force: true }) } }
}

test('a first pending turn has exact native SDK identity before Pi flushes a file', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    assert.equal(f.read().state, 'unknown')
    f.emit('agent_start')
    const value = f.read()
    assert.equal(value.state, 'working')
    assert.equal(value.reason, 'native_turn_started')
    assert.deepEqual(value.pane, f.pane)
    assert.deepEqual(value.native, f.pane)
    assert.equal(value.session_id, f.manager.getSessionId())
    assert.equal(value.session_file, f.manager.getSessionFile())
    assert.equal(value.session_header.version, 3)
    assert.equal(value.session_header.cwd, f.root)
    assert.equal(value.session_persisted, false)
    assert.equal(existsSync(f.manager.getSessionFile()!), false)
    assert.equal(readdirSync(f.manager.getSessionDir()).filter(name => name.endsWith('.tmp')).length, 0)
  } finally { f.close() }
})

test('tools and an agent end before a retry remain working until the native run settles', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    f.emit('agent_start')
    for (const event of ['turn_start', 'message_start', 'tool_execution_start', 'tool_execution_update', 'tool_execution_end']) {
      f.emit(event, { prompt: 'private input', args: { credential: 'private credential' } })
      assert.equal(f.read().state, 'working')
    }
    f.emit('message_end', { message: { role: 'assistant', stopReason: 'toolUse', content: 'private reply' } })
    f.emit('agent_end')
    assert.equal(f.read().state, 'working')
    f.emit('agent_start')
    f.emit('message_end', { message: { role: 'assistant', stopReason: 'stop' } })
    f.emit('agent_settled')
    assert.equal(f.read().state, 'idle')
    assert.equal(f.read().reason, 'native_turn_completed')
    assert(!readFileSync(f.marker, 'utf8').includes('private'))
  } finally { f.close() }
})

for (const stopReason of ['error', 'aborted', 'length']) {
  test(`a settled ${stopReason} is static`, () => {
    const f = fixture()
    try {
      f.emit('session_start')
      f.emit('agent_start')
      f.emit('message_end', { message: { role: 'assistant', stopReason } })
      assert.equal(f.read().state, 'working')
      f.emit('agent_settled')
      assert.equal(f.read().state, 'idle')
      assert.equal(f.read().reason, 'native_turn_interrupted')
    } finally { f.close() }
  })
}

test('nested blocking UI prompts stay static until the last prompt ends', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    f.emit('agent_start')
    f.emit('ui_prompt_start', { title: 'private title' })
    f.emit('ui_prompt_start')
    f.emit('message_start')
    f.emit('tool_execution_end')
    assert.equal(f.read().state, 'idle')
    assert.equal(f.read().reason, 'native_input_requested')
    f.emit('ui_prompt_end')
    assert.equal(f.read().state, 'idle')
    f.emit('ui_prompt_end')
    assert.equal(f.read().state, 'working')
    assert(!readFileSync(f.marker, 'utf8').includes('private title'))
  } finally { f.close() }
})

test('a shutdown invalidates the old session and a switch identifies the new session', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    f.emit('agent_start')
    const oldId = f.read().session_id
    f.emit('session_shutdown')
    assert.equal(f.read().state, 'unknown')
    assert.equal(f.read().reason, 'native_session_ended')
    f.manager.newSession()
    f.emit('session_start')
    assert.notEqual(f.read().session_id, oldId)
    assert.equal(f.read().state, 'unknown')
    f.emit('agent_start')
    assert.equal(f.read().state, 'working')
  } finally { f.close() }
})

test('resume or reload cannot inherit a completed or active turn', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    f.emit('agent_start')
    f.emit('session_shutdown')
    f.emit('session_start', { reason: 'reload' })
    assert.equal(f.read().state, 'unknown')
    assert.equal(f.read().reason, 'no_native_event')
  } finally { f.close() }
})

test('stream progress writes are bounded and state transitions remain immediate', () => {
  const f = fixture()
  const oldNow = Date.now
  let now = oldNow()
  Date.now = () => now
  try {
    f.emit('session_start')
    f.emit('agent_start')
    const started = f.read().observed_at
    now += 100
    f.emit('message_update', { message: { content: 'private token' } })
    assert.equal(f.read().observed_at, started)
    now += 2000
    f.emit('message_update')
    assert.notEqual(f.read().observed_at, started)
    f.emit('agent_settled')
    assert.equal(f.read().state, 'idle')
  } finally { Date.now = oldNow; f.close() }
})

test('an unavailable native observation cannot throw or change Mail tool authority', () => {
  const f = fixture()
  try {
    rmSync(f.manager.getSessionDir(), { recursive: true, force: true })
    assert.doesNotThrow(() => f.emit('session_start'))
    assert.doesNotThrow(() => f.emit('agent_start'))
    assert.doesNotThrow(() => f.emit('agent_settled'))
    assert.equal(existsSync(f.marker), false)
    assert(!f.handlers.has('tool_call'))
  } finally { f.close() }
})

test('a refused Mail generation cannot create or overwrite the current pane marker', () => {
  const f = fixture()
  try {
    f.setOwned(false)
    f.emit('session_start')
    f.emit('agent_start')
    assert.equal(existsSync(f.marker), false)
    f.setOwned(true)
    f.emit('session_start')
    f.emit('agent_start')
    const owner = readFileSync(f.marker, 'utf8')
    const refused = registerNativeActivity({ on: () => () => {} } as unknown as ExtensionAPI)
    refused.start(f.ctx, f.pane, () => false)
    refused.stop()
    assert.equal(readFileSync(f.marker, 'utf8'), owner)
  } finally { f.close() }
})

test('ownership loss prevents even shutdown callbacks from overwriting a new owner', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    f.emit('agent_start')
    const owner = readFileSync(f.marker, 'utf8')
    f.setOwned(false)
    f.emit('ui_prompt_start')
    f.emit('agent_settled')
    f.emit('session_shutdown')
    assert.equal(readFileSync(f.marker, 'utf8'), owner)
  } finally { f.close() }
})

test('a callback from an old session cannot stop the current native run', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    const oldId = f.manager.getSessionId()
    const oldFile = f.manager.getSessionFile()
    const stale = { cwd: f.root, sessionManager: {
      getSessionId: () => oldId, getSessionFile: () => oldFile,
    } } as unknown as ExtensionContext
    f.emit('session_shutdown')
    f.manager.newSession()
    f.emit('session_start')
    f.emit('agent_start')
    f.handlers.get('agent_settled')?.({} as never, stale)
    assert.equal(f.read().state, 'working')
  } finally { f.close() }
})

test('UI prompt completion is distinct from SDK agent settlement', () => {
  const f = fixture()
  try {
    f.emit('session_start')
    f.emit('ui_prompt_start')
    f.emit('ui_prompt_end')
    assert.equal(f.read().state, 'idle')
    assert.equal(f.read().event_source, 'ui_prompt_end')
    const inputEvent = f.read().event_id
    f.emit('agent_start')
    f.emit('message_end', { message: { role: 'assistant', stopReason: 'stop' } })
    f.emit('agent_settled')
    assert.equal(f.read().event_source, 'agent_settled')
    assert.notEqual(f.read().event_id, inputEvent)
    assert.match(f.read().event_id, /^[0-9a-f-]{36}$/)
  } finally { f.close() }
})

test('idle attestation reads SDK state and preserves the actual settlement identity', () => {
  const f = fixture()
  const oldNow = Date.now
  let now = oldNow()
  Date.now = () => now
  try {
    f.emit('session_start')
    f.emit('agent_start')
    f.emit('agent_settled')
    const event = f.read()
    now += 600000
    f.recorder.attest()
    const fresh = f.read()
    assert.equal(fresh.event_id, event.event_id)
    assert.equal(fresh.observed_at, event.observed_at)
    assert.equal(fresh.attestation_source, 'sdk_idle')
    assert.notEqual(fresh.attested_at, event.attested_at)
    f.setIdle(false)
    now += 15000
    f.recorder.attest()
    assert.equal(f.read().attested_at, fresh.attested_at)
    f.setIdle(true)
    f.emit('ui_prompt_start')
    const input = f.read()
    now += 15000
    f.recorder.attest()
    assert.equal(f.read().attested_at, input.attested_at)
    f.setOwned(false)
    assert.doesNotThrow(() => f.recorder.attest())
  } finally { Date.now = oldNow; f.close() }
})
