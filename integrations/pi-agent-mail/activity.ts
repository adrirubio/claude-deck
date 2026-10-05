import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent'
import { randomUUID } from 'node:crypto'
import { closeSync, constants, existsSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { resolvePaneIdentity } from './client.ts'

type Activity = 'working' | 'idle' | 'unknown'
type Identity = { pid: number; start: string }

function nativeIdentity(): Identity {
  const stat = readFileSync(`/proc/${process.pid}/stat`, 'utf8')
  const fields = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/)
  if (!/^\d+$/.test(fields[19])) throw new Error('native_identity_unavailable')
  return { pid: process.pid, start: fields[19] }
}

/** Local observation only. A failed write must never change Mail or agent work. */
export function registerNativeActivity(pi: ExtensionAPI, paneIdentity = resolvePaneIdentity) {
  let pane: Identity | undefined
  let native: Identity | undefined
  let active = false
  let inputPending = 0
  let lastWrite = 0
  let terminalReason = 'native_turn_completed'

  const publish = (ctx: ExtensionContext, state: Activity, reason: string, progress = false) => {
    if (!pane || !native) return
    const now = Date.now()
    if (progress && now - lastWrite < 2000) return
    let temporary: string | undefined
    try {
      const sessionFile = ctx.sessionManager.getSessionFile()
      const header = ctx.sessionManager.getHeader()
      if (!sessionFile || !header) return  // --no-session has no native session identity
      const path = resolve(sessionFile)
      const marker = join(dirname(path), `.deck-native-${pane.pid}-${pane.start}.json`)
      const data = JSON.stringify({
        version: 1, pane, native, cwd: resolve(ctx.cwd),
        session_id: ctx.sessionManager.getSessionId(), session_file: path,
        session_header: { type: header.type, version: header.version, id: header.id, cwd: header.cwd },
        session_persisted: existsSync(path),
        state, reason, observed_at: new Date(now).toISOString(),
      })
      if (Buffer.byteLength(data) > 16384) return
      temporary = `${marker}.${randomUUID()}.tmp`
      const descriptor = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o640)
      try { writeFileSync(descriptor, data) } finally { closeSync(descriptor) }
      renameSync(temporary, marker)
      temporary = undefined
      lastWrite = now
    } catch {
      // The controller reports unknown if these metadata cannot be read.
    } finally {
      if (temporary) { try { unlinkSync(temporary) } catch {} }
    }
  }
  const progress = (ctx: ExtensionContext, force = false) => {
    if (active && !inputPending) publish(ctx, 'working', 'native_progress', !force)
  }

  pi.on('session_start', (_event, ctx) => {
    pane = undefined
    native = undefined
    active = false
    inputPending = 0
    lastWrite = 0
    terminalReason = 'native_turn_completed'
    try { pane = paneIdentity(); native = nativeIdentity() } catch { return }
    // Do not inherit old turns when a file is resumed or the extension reloads.
    publish(ctx, 'unknown', 'no_native_event')
  })
  pi.on('session_shutdown', (_event, ctx) => {
    active = false
    inputPending = 0
    publish(ctx, 'unknown', 'native_session_ended')
    pane = undefined
    native = undefined
  })
  pi.on('agent_start', (_event, ctx) => {
    active = true
    terminalReason = 'native_turn_completed'
    if (!inputPending) publish(ctx, 'working', 'native_turn_started')
  })
  pi.on('turn_start', (_event, ctx) => progress(ctx, true))
  pi.on('message_start', (_event, ctx) => progress(ctx, true))
  pi.on('message_update', (_event, ctx) => progress(ctx))
  pi.on('message_end', (event, ctx) => {
    if (event.message.role === 'assistant') {
      terminalReason = ['error', 'aborted', 'length'].includes(event.message.stopReason)
        ? 'native_turn_interrupted' : 'native_turn_completed'
    }
    progress(ctx, true)
  })
  pi.on('tool_execution_start', (_event, ctx) => progress(ctx, true))
  pi.on('tool_execution_update', (_event, ctx) => progress(ctx))
  pi.on('tool_execution_end', (_event, ctx) => progress(ctx, true))
  // agent_end can precede a retry or queued continuation. It does not prove idle.
  pi.on('agent_settled', (_event, ctx) => {
    active = false
    if (!inputPending) publish(ctx, 'idle', terminalReason)
  })
  pi.on('ui_prompt_start', (_event, ctx) => {
    inputPending++
    publish(ctx, 'idle', 'native_input_requested')
  })
  pi.on('ui_prompt_end', (_event, ctx) => {
    inputPending = Math.max(0, inputPending - 1)
    if (!inputPending) {
      if (active) publish(ctx, 'working', 'native_progress')
      else publish(ctx, 'idle', terminalReason)
    }
  })
}
