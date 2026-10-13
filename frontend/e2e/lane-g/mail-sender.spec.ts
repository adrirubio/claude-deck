import type { Locator, Page } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #527: no message that the scheduler or a service created is shown as sent
// by the Director. Seed (scripts/e2e/scenarios.py): "Progress check: issue #101"
// comes from the scheduler (payload kind github_dispatch_idle_nudge);
// "Director note: keep #101 small" is a message that the Director wrote.
// The Requests tab shows each message as "<sender> to <recipient>".
// Design reference: screen 14 (Agent Mail).

const SYSTEM_SUBJECT = 'Progress check: issue #101'
const DIRECTOR_SUBJECT = 'Director note: keep #101 small'

async function openRequests(page: Page): Promise<void> {
  await page.goto('/agent-mail')
  await expect(page.getByRole('heading', { name: 'Agent Mail', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: 'Requests' }).click()
}

/** The "<sender> to <recipient>" line of the message card with this subject. */
async function senderLine(page: Page, subject: string): Promise<string> {
  const title = page.getByText(subject, { exact: true }).first()
  await expect(title).toBeVisible()
  const card: Locator = title.locator('xpath=ancestor::*[contains(@class,"border") or self::li or self::article][1]')
  const text = (await card.innerText()).replace(/\s+/g, ' ')
  const match = /([A-Z][\w ().-]*?) to (B1 Backend)/.exec(text)
  expect(match, `a sender line in: ${text}`).not.toBeNull()
  return match?.[1].trim() ?? ''
}

test('@active a scheduler message is not shown as sent by the Director', async ({ page }) => {
  await openRequests(page)
  expect(await senderLine(page, SYSTEM_SUBJECT)).not.toMatch(/Director/)
  expect(await senderLine(page, DIRECTOR_SUBJECT)).toMatch(/Director/)
})

// The contrast check covers the two message cards that #527 changes. Other
// badges on the Requests tab fail AA in the dark theme today ("1" 2.68:1,
// "2" 3.57:1, "stale" 3.57:1); they are reported separately.
for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the changed message cards meet AA contrast and are keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await openRequests(page)
    for (const subject of [SYSTEM_SUBJECT, DIRECTOR_SUBJECT]) {
      const card = page.getByText(subject, { exact: true }).first()
        .locator('xpath=ancestor::*[contains(@class,"border") or self::li or self::article][1]')
      await expect(card).toBeVisible()
      const failures = await contrastFailures(card)
      expect(failures, JSON.stringify(failures)).toEqual([])
    }
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
