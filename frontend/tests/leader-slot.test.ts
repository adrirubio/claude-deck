import { describe, expect, it } from 'vitest'
import { autonomousLeaderSlotId } from '../src/features/agent-teams/leaderSlot'

describe('autonomous Leader selection', () => {
  it('uses the first enabled slot by position, not descriptive Role text', () => {
    const slots = [
      { id: 1, position: 0, enabled: false, role: 'leader' },
      { id: 2, position: 3, enabled: true, role: 'leader' },
      { id: 3, position: 1, enabled: true, role: 'developer' },
    ]
    expect(autonomousLeaderSlotId(slots)).toBe(3)
    expect(autonomousLeaderSlotId(slots.map((slot) => ({ ...slot, enabled: false })))).toBeNull()
  })
})
