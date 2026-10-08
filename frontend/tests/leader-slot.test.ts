import { describe, expect, it } from 'vitest'
import { autonomousLeaderSlotId } from '../src/features/agent-teams/leaderSlot'

describe('autonomous Leader selection', () => {
  it('uses the assigned enabled slot, not order or descriptive Role text', () => {
    const slots = [
      { id: 1, position: 0, enabled: false, role: 'leader' },
      { id: 2, position: 3, enabled: true, role: 'leader' },
      { id: 3, position: 1, enabled: true, role: 'developer' },
    ]
    expect(autonomousLeaderSlotId(2, slots)).toBe(2)
    expect(autonomousLeaderSlotId(3, slots)).toBe(3)
    expect(autonomousLeaderSlotId(1, slots)).toBeNull()
    expect(autonomousLeaderSlotId(null, slots)).toBeNull()
    expect(autonomousLeaderSlotId(2, slots.map((slot) => ({ ...slot, enabled: false })))).toBeNull()
  })
})
