import { describe, expect, it } from 'vitest'
import { formatServerTime, parseServerTime } from '../src/lib/serverTime'

describe('server timestamps', () => {
  it('treats a timestamp without an offset as UTC', () => {
    expect(parseServerTime('2026-10-09T06:20:53.083886').getTime())
      .toBe(Date.parse('2026-10-09T06:20:53.083886Z'))
  })

  it('preserves an explicit offset and formats the same instant consistently', () => {
    const options: Intl.DateTimeFormatOptions = {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    }
    expect(parseServerTime('2026-10-09T08:20:53.083886+02:00').getTime())
      .toBe(Date.parse('2026-10-09T06:20:53.083886Z'))
    expect(formatServerTime('2026-10-09T06:20:53.083886', options))
      .toBe(formatServerTime('2026-10-09T06:20:53.083886Z', options))
  })

  it('shows the time of day when no options are given', () => {
    const instant = '2026-10-09T06:20:53Z'
    expect(formatServerTime('2026-10-09T06:20:53')).toBe(new Date(instant).toLocaleString())
    expect(formatServerTime('2026-10-09T06:20:53'))
      .not.toBe(new Date(instant).toLocaleDateString())
  })

  it('does not throw on a value that is not a date', () => {
    expect(formatServerTime('not a date')).toBe('Invalid Date')
  })
})
