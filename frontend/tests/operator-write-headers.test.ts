import { afterEach, describe, expect, it } from 'vitest'
import { clearOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { operatorWriteHeaders } from '../src/lib/api'

describe('operatorWriteHeaders', () => {
  afterEach(() => clearOperatorToken())

  it('sends the stored Director key on writes only', () => {
    setOperatorToken('director-key')
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'post']) {
      expect(operatorWriteHeaders(method)).toEqual({ 'X-Deck-Operator-Token': 'director-key' })
    }
    for (const method of ['GET', 'HEAD', 'OPTIONS', undefined]) {
      expect(operatorWriteHeaders(method)).toEqual({})
    }
  })

  it('sends nothing when no key is stored', () => {
    expect(operatorWriteHeaders('POST')).toEqual({})
  })
})
