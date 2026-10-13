import { describe, expect, it } from 'vitest'
import { canShiftLeft, canShiftRight, clampStart, shiftStart, startToShow, windowLabel } from '../src/features/cc-bridge/teamLanesWindow'

describe('team lanes window', () => {
  it('clamps the first visible index to 0 and total - 4', () => {
    expect(clampStart(-3, 8)).toBe(0)
    expect(clampStart(2, 8)).toBe(2)
    expect(clampStart(9, 8)).toBe(4)
    expect(clampStart(3, 3)).toBe(0)
    expect(clampStart(1, 0)).toBe(0)
  })

  it('shifts by one member and stops at both ends', () => {
    expect(shiftStart(0, 8, 1)).toBe(1)
    expect(shiftStart(4, 8, 1)).toBe(4)
    expect(shiftStart(0, 8, -1)).toBe(0)
    expect(shiftStart(3, 8, -1)).toBe(2)
  })

  it('brings a member into view with the fewest moves', () => {
    expect(startToShow(0, 8, 2)).toBe(0)
    expect(startToShow(0, 8, 4)).toBe(1)
    expect(startToShow(0, 8, 7)).toBe(4)
    expect(startToShow(4, 8, 0)).toBe(0)
    expect(startToShow(4, 8, 3)).toBe(3)
  })

  it('says which members are shown', () => {
    expect(windowLabel(2, 8)).toBe('Showing 3–6 of 8')
    expect(windowLabel(0, 8)).toBe('Showing 1–4 of 8')
    expect(windowLabel(0, 3)).toBe('Showing 1–3 of 3')
    expect(windowLabel(0, 0)).toBe('No members')
  })

  it('knows when a shift is possible', () => {
    expect(canShiftLeft(0)).toBe(false)
    expect(canShiftLeft(1)).toBe(true)
    expect(canShiftRight(4, 8)).toBe(false)
    expect(canShiftRight(3, 8)).toBe(true)
    expect(canShiftRight(0, 4)).toBe(false)
  })
})
