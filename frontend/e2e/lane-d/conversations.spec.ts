import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'
import { inView, openAgentMail, scrollTop, showMailSetUp } from './mail-page'

// #529 (merged, PR #680): Agent Mail leads with "Waiting on someone" and lists
// one row per thread. At 1440 × 900 the panel and at least 10 thread rows are
// visible without scrolling; the header counts link to the items they count;
// Deck notices with the same subject and recipient collapse into one row.
// Seed: 14 threads; the 4 "Release needed: issue #104" reminders collapse
// into one row, so the list has 11 rows. L1, B1 and V1 wait on someone.
// Design reference: screen 14 (Agent Mail, Conversations).
// @active since #529 merged into release/v3.1 (PR #680).

test.use({ viewport: { width: 1440, height: 900 } })

// The fit journey shows Agent Mail as set up (showMailSetUp): the #552 rule
// keeps the instance without Agent Mail setup, and the "Agent setup required"
// banner (about 134 px) is not on a Director's set-up page.
test('@active at 1440 × 900 the Waiting on someone panel and 10 thread rows are visible', async ({ page }) => {
  await showMailSetUp(page)
  await openAgentMail(page, 'Conversations')
  await expect(page.getByText('Agent setup required')).toHaveCount(0)
  const panel = page.getByRole('region', { name: /^Waiting on someone/ })
  await expect(panel).toBeVisible()
  const rows = page.getByTestId('conversation-row')
  await expect(rows).toHaveCount(11)
  expect(await scrollTop(page)).toBe(0)
  expect(await inView(page, panel), 'the panel is in view').toBe(true)
  for (let index = 0; index < 10; index++) {
    expect(await inView(page, rows.nth(index)), `thread row ${index + 1} is in view`).toBe(true)
  }
})

test('@active the header counts move focus to the items they count', async ({ page }) => {
  await openAgentMail(page, 'Conversations')
  const totals = page.getByRole('group', { name: 'Agent Mail totals' })
  const links = totals.getByRole('button', { name: /Go to Waiting on someone$/ })
  await expect(links).toHaveCount(4)
  for (const name of ['unread', 'pending', 'unseen', 'stale']) {
    await page.locator('body').focus()
    await totals.getByRole('button', { name: new RegExp(`^\\d+ ${name}\\. Go to Waiting on someone$`) }).click()
    await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('#waiting-on-someone'))), name).toBe(true)
  }
  const panel = page.getByRole('region', { name: /^Waiting on someone/ })
  for (const member of ['L1 Leader', 'B1 Backend', 'V1 Verifier']) {
    await expect(panel.getByText(new RegExp(`\\b${member}\\b`)).first(), member).toBeVisible()
  }
})

test('@active Deck notices with one subject and recipient collapse into one row', async ({ page }) => {
  await openAgentMail(page, 'Conversations')
  const notices = page.getByTestId('conversation-row').filter({ hasText: 'Release needed: issue #104' })
  await expect(notices).toHaveCount(1)
  await expect(notices.getByLabel('4 notices')).toBeVisible()
  await expect(notices).toContainText(/Deck\s*→\s*B1 Backend/)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active Conversations meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await openAgentMail(page, 'Conversations')
    const list = page.getByRole('tabpanel')
    await expect(page.getByTestId('conversation-row').first()).toBeVisible()
    for (const region of [list, page.getByRole('region', { name: /^Waiting on someone/ })]) {
      const failures = await contrastFailures(region)
      expect(failures, JSON.stringify(failures)).toEqual([])
    }
    await expectKeyboardReachable(page, list, 3)
  })
}
