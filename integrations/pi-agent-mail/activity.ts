import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent'
import { randomUUID } from 'node:crypto'
import { closeSync, constants, existsSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

type Activity = 'working' | 'idle' | 'unknown'
type Identity = { pid: number; start: string }
type NativeEvent = { id: string; at: string; source: string; state: Activity; reason: string }

function nativeIdentity(): Identity {
  const stat = readFileSync(`/proc/${process.pid}/stat`, 'utf8')
  const fields = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/)
  if (!/^\d+$/.test(fields[19])) throw new Error('native_identity_unavailable')
  return { pid: process.pid, start: fields[19] }
}

/** Local observation only. A failed write must never change Mail or agent work. */
export function registerNativeActivity(pi: ExtensionAPI) {
  let pane: Identity | undefined
  let native: Identity | undefined
  let owns = () => false
  let session: { id: string; file: string; cwd: string; header: object } | undefined
  let active = false
  let inputPending = 0
  let lastWrite = 0
  let terminalReason = 'native_turn_completed'
  let context: ExtensionContext | undefined
  let latest: NativeEvent | undefined
  let attestationTimer: ReturnType<typeof setInterval> | undefined

  const matches = (ctx: ExtensionContext) => {
    try {
      return !!session && owns() && ctx.sessionManager.getSessionId() === session.id
        && ctx.sessionManager.getSessionFile() === session.file && resolve(ctx.cwd) === session.cwd
    } catch { return false }
  }

  const publish = (state: Activity, reason: string, progress = false, source = 'native_progress',
    attested?: NativeEvent) => {
    if (!pane || !native || !session || !owns()) return
    const now = Date.now()
    if (progress && now - lastWrite < 2000) return
    const event = attested ?? { id: randomUUID(), at: new Date(now).toISOString(), source, state, reason }
    if (!attested) latest = event
    let temporary: string | undefined
    try {
      const path = session.file
      const marker = join(dirname(path), `.deck-native-${pane.pid}-${pane.start}.json`)
      const data = JSON.stringify({
        version: 1, pane, native, cwd: session.cwd,
        session_id: session.id, session_file: path, session_header: session.header,
        session_persisted: existsSync(path),
        state, reason, observed_at: event.at,
        event_id: event.id, event_source: event.source,
        attested_at: new Date(now).toISOString(), attestation_source: attested ? 'sdk_idle' : 'native_event',
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
    if (matches(ctx) && active && !inputPending) publish('working', 'native_progress', !force)
  }

  const attest = () => {
    try {
      // Observe current SDK state. Do not renew cached completion or a Mail heartbeat.
      if (context && matches(context) && !active && !inputPending && context.isIdle()
        && latest?.state === 'idle' && latest.source === 'agent_settled') {
        publish(latest.state, latest.reason, false, latest.source, latest)
      }
    } catch { /* Missing SDK evidence remains unknown after its bounded expiry. */ }
  }

  const stop = () => {
    // Only the successful owning generation can invalidate its observation.
    publish('unknown', 'native_session_ended', false, 'session_reset')
    pane = undefined
    native = undefined
    session = undefined
    owns = () => false
    active = false
    inputPending = 0
    context = undefined
    latest = undefined
    clearInterval(attestationTimer)
    attestationTimer = undefined
  }
  const start = (ctx: ExtensionContext, identity: Identity, ownership: () => boolean) => {
    stop()
    lastWrite = 0
    terminalReason = 'native_turn_completed'
    try {
      if (!ownership()) return
      const file = ctx.sessionManager.getSessionFile()
      const header = ctx.sessionManager.getHeader()
      if (!file || !header) return
      pane = identity
      native = nativeIdentity()
      session = { id: ctx.sessionManager.getSessionId(), file: resolve(file), cwd: resolve(ctx.cwd),
        header: { type: header.type, version: header.version, id: header.id, cwd: header.cwd } }
      owns = ownership
      context = ctx
    } catch { return }
    // Do not inherit old turns when a file is resumed or the extension reloads.
    publish('unknown', 'no_native_event', false, 'session_reset')
    attestationTimer = setInterval(attest, 15000)
    attestationTimer.unref()
  }
  pi.on('agent_start', (_event, ctx) => {
    if (!matches(ctx)) return
    active = true
    terminalReason = 'native_turn_completed'
    if (!inputPending) publish('working', 'native_turn_started', false, 'agent_start')
  })
  pi.on('turn_start', (_event, ctx) => progress(ctx, true))
  pi.on('message_start', (_event, ctx) => progress(ctx, true))
  pi.on('message_update', (_event, ctx) => progress(ctx))
  pi.on('message_end', (event, ctx) => {
    if (!matches(ctx)) return
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
    if (!matches(ctx)) return
    active = false
    if (!inputPending) publish('idle', terminalReason, false, 'agent_settled')
  })
  pi.on('ui_prompt_start', (_event, ctx) => {
    if (!matches(ctx)) return
    inputPending++
    publish('idle', 'native_input_requested', false, 'ui_prompt_start')
  })
  pi.on('ui_prompt_end', (_event, ctx) => {
    if (!matches(ctx)) return
    inputPending = Math.max(0, inputPending - 1)
    if (!inputPending) {
      if (active) publish('working', 'native_progress')
      else publish('idle', terminalReason, false, 'ui_prompt_end')
    }
  })
  return { start, stop, attest }
}
