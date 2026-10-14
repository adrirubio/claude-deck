// Team lanes show a window of four members that shifts through all team members.

export const LANE_COUNT = 4

/** Keeps the first visible index inside 0 and (total - 4). */
export function clampStart(start: number, total: number): number {
  return Math.max(0, Math.min(start, Math.max(0, total - LANE_COUNT)))
}

/** Moves the window by delta members, for example 1 for right and -1 for left. */
export function shiftStart(start: number, total: number, delta: number): number {
  return clampStart(start + delta, total)
}

/** The first visible index that puts the member at index into view with the fewest moves. */
export function startToShow(start: number, total: number, index: number): number {
  if (index < start) return clampStart(index, total)
  if (index >= start + LANE_COUNT) return clampStart(index - LANE_COUNT + 1, total)
  return clampStart(start, total)
}

/** "Showing 3–6 of 8". */
export function windowLabel(start: number, total: number): string {
  if (total === 0) return 'No members'
  const first = clampStart(start, total) + 1
  const last = Math.min(total, first - 1 + LANE_COUNT)
  return `Showing ${first}–${last} of ${total}`
}

export function canShiftLeft(start: number): boolean {
  return start > 0
}

export function canShiftRight(start: number, total: number): boolean {
  return start < total - LANE_COUNT
}
