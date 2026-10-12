import { expect, type Locator } from '@playwright/test'

// The browser runs in a fixed zone that is not UTC, so a UTC value shown as
// local time is visible as a wrong hour. Change both values together.
export const E2E_TIMEZONE = 'America/New_York'
export const E2E_LOCALE = 'en-US'

// The seed writes every timestamp relative to this moment (naive UTC in SQLite).
// Keep it equal to SEED_NOW in scripts/e2e/seed.py.
export const SEED_NOW = new Date('2026-10-01T14:00:00Z')

/** One seeded moment: the UTC instant and the zone the browser shows it in. */
export function seededMoment(isoUtc: string): Date {
  const moment = new Date(isoUtc)
  if (Number.isNaN(moment.getTime())) throw new Error(`Invalid seeded moment: ${isoUtc}`)
  return moment
}

/** Wall-clock parts of a moment in the browser zone, for format-neutral checks. */
export function localParts(moment: Date): { date: string; hour: string; minute: string } {
  const parts = new Intl.DateTimeFormat(E2E_LOCALE, {
    timeZone: E2E_TIMEZONE,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(moment)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(p => p.type === type)?.value ?? ''
  return {
    date: `${part('month')} ${part('day')}, ${part('year')}`,
    hour: part('hour').padStart(2, '0'),
    minute: part('minute'),
  }
}

/** The local HH:MM of a moment. A UTC rendering fails this check by the zone offset. */
export function localClock(moment: Date): string {
  const { hour, minute } = localParts(moment)
  return `${hour}:${minute}`
}

/** Assert that a locator shows the local clock time of the moment. */
export async function expectLocalTime(locator: Locator, moment: Date): Promise<void> {
  await expect(locator).toContainText(localClock(moment))
}

/** Read the visible time text of each locator; all must be identical. */
export async function expectSameTimeText(locators: Locator[]): Promise<string> {
  const texts = await Promise.all(locators.map(async l => (await l.innerText()).trim()))
  expect(new Set(texts).size, `time texts differ: ${JSON.stringify(texts)}`).toBe(1)
  return texts[0]
}
