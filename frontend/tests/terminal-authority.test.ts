import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildTerminalWsUrl, fetchTerminalToken, pasteBridgeAttachment } from '@/features/cc-bridge/api'
import { setOperatorToken } from '@/features/agent-teams/operatorAuth'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('terminal authority', () => {
  it('requests read-only grants for one target without operator credentials', async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ token: 'readonly-grant' }), { status: 200 }))
    vi.stubGlobal('fetch', request)

    expect(await fetchTerminalToken('deck:0.0', 'readonly')).toEqual({ token: 'readonly-grant' })
    expect(request).toHaveBeenCalledWith(
      '/api/v1/agent-bridge/token?target=deck%3A0.0&purpose=readonly',
      expect.objectContaining({ headers: expect.not.objectContaining({ 'X-Deck-Operator-Token': expect.anything() }) }),
    )
  })

  it('sends the operator credential only when requesting an interactive grant', async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ token: 'interactive-grant' }), { status: 200 }))
    vi.stubGlobal('fetch', request)
    setOperatorToken('operator-secret')

    await fetchTerminalToken('deck:0.0', 'interactive')
    expect(request).toHaveBeenCalledWith(
      '/api/v1/agent-bridge/token?target=deck%3A0.0&purpose=interactive',
      expect.objectContaining({ headers: expect.objectContaining({ 'X-Deck-Operator-Token': 'operator-secret' }) }),
    )
    expect(buildTerminalWsUrl('deck:0.0', 'interactive')).not.toContain('interactive-grant')
    expect(buildTerminalWsUrl('deck:0.0', 'interactive')).toContain('mode=interactive')
  })

  it('requires an operator credential to paste attachments while using an attachment grant', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'attachment-grant' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ pasted: true, submitted: false, target: 'deck:0.0' }), { status: 200 }))
    vi.stubGlobal('fetch', request)

    await expect(pasteBridgeAttachment('deck:0.0', 7, { submit: false })).rejects.toThrow('Operator token required')
    expect(request).not.toHaveBeenCalled()

    setOperatorToken('operator-secret')
    await pasteBridgeAttachment('deck:0.0', 7, { submit: false })
    expect(request.mock.calls[0][0]).toBe('/api/v1/agent-bridge/token?target=deck%3A0.0&purpose=attachment')
    expect(request.mock.calls[1][1].headers.get('X-Claude-Deck-Terminal-Token')).toBe('attachment-grant')
    expect(request.mock.calls[1][1].headers.get('X-Deck-Operator-Token')).toBe('operator-secret')
  })
})
