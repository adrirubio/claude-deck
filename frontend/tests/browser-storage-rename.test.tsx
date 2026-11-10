import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/hooks/useProviders', () => ({ useProviders: () => ({
  providers: [{ id: 'claude-code' }, { id: 'pi-cli' }, { id: 'codex-cli' }],
  loading: false, error: null, refresh: vi.fn(),
}) }))

const keys = {
  provider: ['claude-deck:selected-provider', 'albiex-synth-city:selected-provider'],
  operator: ['claude-deck.agent-teams.operator-token', 'albiex-synth-city.agent-teams.operator-token'],
  actorKey: ['deck-agent-mail-actor-key', 'albiex-synth-city-agent-mail-actor-key'],
  actorToken: ['deck-agent-mail-actor-token', 'albiex-synth-city-agent-mail-actor-token'],
} as const

beforeEach(() => { vi.resetModules(); localStorage.clear(); sessionStorage.clear() })
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function readProvider() {
  const { ProviderProvider, useProviderContext } = await import('@/contexts/ProviderContext')
  function Probe() { return <output aria-label="provider">{useProviderContext().selectedProviderId}</output> }
  render(<ProviderProvider><Probe /></ProviderProvider>)
  return screen.getByLabelText('provider').textContent
}

async function readOperator() {
  return (await import('@/features/agent-teams/operatorAuth')).getOperatorToken()
}

describe('T-S1: actual localStorage and sessionStorage consumers', () => {
  for (const [name, area, value, consume] of [
    ['provider', 'localStorage', 'pi-cli', readProvider],
    ['operator', 'sessionStorage', 'synthetic-operator', readOperator],
  ] as const) {
    const [oldKey, newKey] = keys[name]

    it(`${name}: copies before deleting, keeps the value usable, and loads twice without copying again`, async () => {
      const store = window[area]
      store.setItem(oldKey, value)
      const events: string[] = []
      const originalSet = Storage.prototype.setItem
      const originalRemove = Storage.prototype.removeItem
      const writes = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (key, data) {
        if (this === store) events.push(`set:${key}`)
        originalSet.call(this, key, data)
      })
      vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function (key) {
        if (this === store) events.push(`remove:${key}`)
        originalRemove.call(this, key)
      })
      expect(await consume()).toBe(value)
      expect(store.getItem(newKey)).toBe(value)
      expect(store.getItem(oldKey)).toBeNull()
      expect(events.indexOf(`set:${newKey}`)).toBeGreaterThanOrEqual(0)
      expect(events.indexOf(`remove:${oldKey}`)).toBeGreaterThan(events.indexOf(`set:${newKey}`))
      cleanup(); vi.resetModules(); writes.mockClear()
      const reads = vi.spyOn(Storage.prototype, 'getItem')
      expect(await consume()).toBe(value)
      expect(writes).not.toHaveBeenCalled()
      expect(reads).not.toHaveBeenCalledWith(oldKey)
    })

    it(`${name}: a pre-existing new key wins over stale old data`, async () => {
      const store = window[area]
      store.setItem(oldKey, name === 'provider' ? 'codex-cli' : 'stale-operator')
      store.setItem(newKey, value)
      expect(await consume()).toBe(value)
      expect(store.getItem(newKey)).toBe(value)
      expect(store.getItem(oldKey)).toBeNull()
    })

    it(`${name}: a failed copy preserves the old value`, async () => {
      const store = window[area]
      store.setItem(oldKey, value)
      const original = Storage.prototype.setItem
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (key, data) {
        if (this === store && key === newKey) throw new DOMException('Full', 'QuotaExceededError')
        original.call(this, key, data)
      })
      await consume()
      expect(store.getItem(oldKey)).toBe(value)
      expect(store.getItem(newKey)).toBeNull()
    })
  }

  it('keeps the migrated operator token usable on a real frontend write without re-entry', async () => {
    sessionStorage.setItem(keys.operator[0], 'synthetic-operator')
    const { operatorWriteHeaders } = await import('@/lib/api')
    expect(operatorWriteHeaders('POST')).toEqual({ 'X-Synth-City-Operator-Token': 'synthetic-operator' })
    expect(operatorWriteHeaders('GET')).toEqual({})
  })

  it('copies operator bytes verbatim while retaining the existing trimmed read behavior', async () => {
    sessionStorage.setItem(keys.operator[0], '  synthetic-operator  ')
    expect(await readOperator()).toBe('synthetic-operator')
    expect(sessionStorage.getItem(keys.operator[1])).toBe('  synthetic-operator  ')
    expect(sessionStorage.getItem(keys.operator[0])).toBeNull()
  })

  it('does not revive an old credential reinserted after a completed conversion and logout', async () => {
    sessionStorage.setItem(keys.operator[0], 'synthetic-operator')
    const auth = await import('@/features/agent-teams/operatorAuth')
    expect(auth.getOperatorToken()).toBe('synthetic-operator')
    auth.clearOperatorToken()
    sessionStorage.setItem(keys.operator[0], 'stale-reinserted')
    expect(auth.getOperatorToken()).toBeNull()
  })

  it('migrates provider state when the native request guard is used before the context mounts', async () => {
    localStorage.setItem(keys.provider[0], 'pi-cli')
    const native = await import('@/features/native-settings/surfaceRegistry')
    native.clearNativeCatalogs()
    window.history.replaceState({}, '', '/config')
    expect(() => native.assertBrowserNativeRequest('config')).toThrow()
    expect(localStorage.getItem(keys.provider[1])).toBe('pi-cli')
    expect(localStorage.getItem(keys.provider[0])).toBeNull()
    window.history.replaceState({}, '', '/')
  })

  for (const kind of ['actorKey', 'actorToken'] as const) {
    it(`${kind}: a refused copy preserves the old value through the actual actor consumer`, async () => {
      sessionStorage.setItem(keys.actorKey[0], 'deck-ui-historical-identity')
      sessionStorage.setItem(keys.actorToken[0], 'synthetic-actor')
      const original = Storage.prototype.setItem
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (key, data) {
        if (this === sessionStorage && key === keys[kind][1]) throw new DOMException('Full', 'QuotaExceededError')
        original.call(this, key, data)
      })
      const request = vi.fn().mockImplementation(async (url: string) => new Response(
        JSON.stringify(url.endsWith('/actors') ? { token: 'synthetic-replacement' } : { ok: true }), { status: 200 },
      ))
      vi.stubGlobal('fetch', request)
      try { await (await import('@/features/agent-mail/actorAuth')).actorFetch('external/agent-mail/team') } catch { /* A write may be refused. */ }
      expect(sessionStorage.getItem(keys[kind][0])).toBe(kind === 'actorKey' ? 'deck-ui-historical-identity' : 'synthetic-actor')
      expect(sessionStorage.getItem(keys[kind][1])).toBeNull()
      for (const [url, options] of request.mock.calls) {
        if (url.endsWith('/actors')) expect(JSON.parse(options.body).actor_key).toBe('deck-ui-historical-identity')
      }
    })
  }

  it('migrates actor key and token verbatim, then rotates only the token on normal recovery', async () => {
    sessionStorage.setItem(keys.actorKey[0], 'deck-ui-historical-identity')
    sessionStorage.setItem(keys.actorToken[0], 'synthetic-actor')
    const request = vi.fn().mockImplementation(async (url: string) => new Response(
      JSON.stringify(url.endsWith('/actors') ? { token: 'synthetic-replacement' } : { ok: true }), { status: 200 },
    ))
    vi.stubGlobal('fetch', request)
    const auth = await import('@/features/agent-mail/actorAuth')
    await auth.actorFetch('external/agent-mail/team')
    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-actor')
    for (const [oldKey, newKey] of [keys.actorKey, keys.actorToken]) {
      expect(sessionStorage.getItem(oldKey)).toBeNull()
      expect(sessionStorage.getItem(newKey)).toBe(newKey === keys.actorKey[1] ? 'deck-ui-historical-identity' : 'synthetic-actor')
    }
    auth.resetActorToken()
    await auth.actorFetch('external/agent-mail/team')
    const registration = request.mock.calls.find(([url]) => url.endsWith('/actors'))!
    expect(JSON.parse(registration[1].body).actor_key).toBe('deck-ui-historical-identity')
    expect(sessionStorage.getItem(keys.actorKey[1])).toBe('deck-ui-historical-identity')
    expect(sessionStorage.getItem(keys.actorToken[1])).toBe('synthetic-replacement')
  })

  it('pre-existing actor state wins without provisioning a new identity', async () => {
    sessionStorage.setItem(keys.actorKey[0], 'stale-key')
    sessionStorage.setItem(keys.actorToken[0], 'stale-token')
    sessionStorage.setItem(keys.actorKey[1], 'current-key')
    sessionStorage.setItem(keys.actorToken[1], 'synthetic-current-token')
    const request = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    vi.stubGlobal('fetch', request)
    await (await import('@/features/agent-mail/actorAuth')).actorFetch('external/agent-mail/team')
    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-current-token')
    expect(sessionStorage.getItem(keys.actorKey[1])).toBe('current-key')
    expect(sessionStorage.getItem(keys.actorKey[0])).toBeNull()
    expect(sessionStorage.getItem(keys.actorToken[0])).toBeNull()
  })
})
