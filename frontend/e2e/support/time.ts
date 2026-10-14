import { expect, type Locator } from '@playwright/test'

// The browser runs in a fixed zone that is not UTC, so a UTC value shown as
// local time is visible as a wrong hour. Change both values together.
export const E2E_TIMEZONE = 'America/New_York'
export const E2E_LOCALE = 'en-US'

// The seed writes every timestamp relative to this moment (naive UTC in
// SQLite). playwright.config.ts sets E2E_SEED_NOW once per run; the instance
// and every worker read the same value.
// Read lazily: playwright.config.ts imports this module before it sets the value.
export function seedNow(): Date {
  const value = process.env.E2E_SEED_NOW
  if (!value) throw new Error('E2E_SEED_NOW is not set; run the journeys through playwright.config.ts')
  return new Date(value)
}

/** seedNow() minus an offset, the way scripts/e2e/scenarios.py writes it. */
export function seedAgo(offset: { days?: number; hours?: number; minutes?: number }): Date {
  const ms = (((offset.days ?? 0) * 24 + (offset.hours ?? 0)) * 60 + (offset.minutes ?? 0)) * 60_000
  return new Date(seedNow().getTime() - ms)
}

/** One seeded moment: the UTC instant and the zone the browser shows it in. */
export function seededMoment(isoUtc: string): Date {
  const moment = new Date(isoUtc)
  if (Number.isNaN(moment.getTime())) throw new Error(`Invalid seeded moment: ${isoUtc}`)
  return moment
}

/** Assert that a locator shows the moment's local clock time (any of Deck's formats). */
export async function expectLocalTime(locator: Locator, moment: Date): Promise<void> {
  await expect(locator).toContainText(localClockPattern(moment))
}

/** Read the visible time text of each locator; all must be identical. */
export async function expectSameTimeText(locators: Locator[]): Promise<string> {
  const texts = await Promise.all(locators.map(async l => (await l.innerText()).trim()))
  expect(new Set(texts).size, `time texts differ: ${JSON.stringify(texts)}`).toBe(1)
  return texts[0]
}

/**
 * The moment's hour and minute in the browser zone, as a 12- or 24-hour clock
 * with an optional leading zero. It matches any of Deck's current formats; a
 * UTC rendering does not match, because the zone offset changes the hour.
 */
export function localClockPattern(moment: Date): RegExp {
  const parts = new Intl.DateTimeFormat(E2E_LOCALE, {
    timeZone: E2E_TIMEZONE, hour: 'numeric', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(moment)
  const hour24 = Number(parts.find(p => p.type === 'hour')?.value)
  const minute = parts.find(p => p.type === 'minute')?.value
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12
  return new RegExp(`\\b0?(${hour24}|${hour12}):${minute}\\b`)
}

/**
 * The date-and-time text around the moment's clock, without labels around it.
 * For example "Oct 12, 10:43 AM" from "repo · updated Oct 12, 10:43 AM".
 */
export function localTimeText(text: string, moment: Date): string | null {
  const clock = localClockPattern(moment).source.replace(/^\\b|\\b$/g, '')
  const date = String.raw`(?:[A-Z][a-z]{2,8}\.? \d{1,2},? (?:\d{4},? )?|\d{1,2}/\d{1,2}/\d{2,4},? |\d{4}-\d{2}-\d{2}[ T])?`
  const match = new RegExp(`${date}(?:at )?${clock}(?::\\d{2})?(?: ?[AP]M)?`).exec(text)
  return match ? match[0].trim() : null
}
