import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createAgentTeamFromBridge,
  createAgentTeamFromMail,
  createAgentTeamPreset,
  duplicateAgentTeamPreset,
  fetchConfigurationObservation,
} from '@/features/agent-teams/api'
import { ApiHttpError } from '@/lib/api'

// V20 client matrix: every creation-family browser client carries the shared
// operator credential header and surfaces 401 to the protected helper for
// re-prompt. Valid-operator admission is proven at the route layer; these
// cases prove the client-side authorization contract only.

const families: Array<[string, (token: string) => Promise<unknown>]> = [
  ['ordinary create', (token) => createAgentTeamPreset({ name: 'Client family', slots: [] }, token)],
  ['mail import', (token) => createAgentTeamFromMail({ name: 'Client mail', member_ids: [1] }, token)],
  ['bridge import', (token) => createAgentTeamFromBridge({ name: 'Client bridge' }, token)],
  ['duplicate', (token) => duplicateAgentTeamPreset(7, { name: 'Client duplicate' }, token)],
]

describe('creation-family client authorization', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each(families)('%s sends the shared operator credential header', async (_label, invoke) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await invoke('client-operator-token')
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['X-Deck-Operator-Token']).toBe('client-operator-token')
  })

  it.each(families)('%s surfaces 401 for the protected credential helper', async (_label, invoke) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'operator_token_invalid' }), { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(invoke('stale-token')).rejects.toMatchObject({
      name: 'ApiHttpError',
      status: 401,
    })
    const error = await invoke('stale-token').catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiHttpError)
    expect((error as ApiHttpError).status).toBe(401)
  })
})

// The bounded configuration observation is a separate operator-protected read.
// These cases prove its client contract; route-level anonymous and agent
// refusals are covered in test_operator_auth.py separately from the
// four-family creation matrix.
describe('configuration observation client authorization', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the shared operator credential header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      observed_at: '2026-10-06T00:00:00Z', complete: true, presets: [], scopes: [],
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await fetchConfigurationObservation('observation-operator-token')
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['X-Deck-Operator-Token']).toBe('observation-operator-token')
  })

  it('surfaces 401 for the protected credential helper', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'operator_token_invalid' }), { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    const error = await fetchConfigurationObservation('stale-token').catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiHttpError)
    expect((error as ApiHttpError).status).toBe(401)
  })
})
