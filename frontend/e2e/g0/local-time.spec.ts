import type { Page } from '@playwright/test'
import { chooseUnlockEvents, enterDirectorKey } from '../support/director-key'
import { expect, test } from '../support/guard'
import { localClockPattern, localTimeText, seedAgo } from '../support/time'

// #521: one seeded moment shows the same local time on Work and Audit.
// Teams no longer lists work items (#533): its Activity table moved to Work.
// The moment is SHARED_MOMENT in scripts/e2e/scenarios.py: item #103
// "Document the import format" was dispatched at seed time minus 3 h 17 min,
// and its work_lifecycle audit event has the same time.
// @pending until #521 and PR #532 merge.

const moment = seedAgo({ hours: 3, minutes: 17 })

/** The full visible time text around the moment's clock on the page. */
async function timeText(page: Page, near: string): Promise<string> {
  const pattern = localClockPattern(moment)
  const row = page.getByText(near).first().locator('xpath=ancestor-or-self::*[self::tr or self::li or self::article][1]')
  const scope = (await row.count()) ? row : page.locator('main')
  const cell = scope.getByText(pattern).first()
  await expect(cell, `local time ${pattern} near "${near}"`).toBeVisible()
  const text = localTimeText(await cell.innerText(), moment)
  expect(text, `a date and time near "${near}"`).not.toBeNull()
  return text as string
}

test('@active one seeded moment shows the same local time on Work and Audit', async ({ page }) => {
  await page.goto('/work/3')
  await expect(page.getByText('Document the import format').first()).toBeVisible()
  const work = await timeText(page, 'Document the import format')

  await page.goto('/audit')
  await chooseUnlockEvents(page)
  await enterDirectorKey(page)
  const audit = await timeText(page, 'dispatched')

  expect(new Set([work, audit]).size, `time texts differ: ${JSON.stringify({ work, audit })}`).toBe(1)
})
