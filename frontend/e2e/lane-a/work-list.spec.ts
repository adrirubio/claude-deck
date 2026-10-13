import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #511: compact the Work list and default it to active work. At 1440 × 900,
// at least 12 rows are visible; no finished row shows a waiting message.
// "Active work" means every item that is not finished: the backend `open`
// category, the default chip "Active".
// The seed has 5 items, so the journey measures the row height: the rows that
// fit below the list top must be at least 12.
// Design reference: screen 03 (Work list).
// @active: these journeys must pass (#511).

test.use({ viewport: { width: 1440, height: 900 } })

const ROW = 'main table tbody tr, main [role="row"]:not(:has([role="columnheader"]))'

test('@active at 1440 × 900 the list has room for at least 12 rows', async ({ page }) => {
  await page.goto('/work')
  await expect(page.getByRole('heading', { name: 'Work', exact: true })).toBeVisible()
  const first = await page.locator(ROW).first().boundingBox()
  expect(first, 'a first row').not.toBeNull()
  const rowsThatFit = Math.floor((900 - (first?.y ?? 0)) / (first?.height ?? 900))
  expect(rowsThatFit, `row height ${first?.height}px at y=${first?.y}`).toBeGreaterThanOrEqual(12)
})

test('@active the list defaults to active work, chosen by the "Active" chip', async ({ page }) => {
  await page.goto('/work')
  const active = page.locator('main').getByRole('button', { name: /^Active\b/ }).or(page.locator('main').getByRole('tab', { name: /^Active\b/ }))
  await expect(active.first()).toBeVisible()
  const chosen = await active.first().evaluate(element =>
    element.getAttribute('aria-pressed') === 'true' || element.getAttribute('aria-selected') === 'true')
  expect(chosen, 'the "Active" chip is chosen by default').toBe(true)
  // Every unfinished item is listed; the merged item #104 is not.
  for (const title of ['Add the CSV export button', 'Fix the settings page layout', 'Document the import format', 'Add keyboard shortcuts']) {
    await expect(page.locator(ROW).filter({ hasText: title })).toHaveCount(1)
  }
  await expect(page.locator(ROW).filter({ hasText: 'Rename the sync command' })).toHaveCount(0)
})

test('@active no finished row shows a waiting message', async ({ page }) => {
  await page.goto('/work?category=finished')
  const finished = page.locator(ROW).filter({ hasText: 'Rename the sync command' })
  await expect(finished).toHaveCount(1)
  await expect(finished).not.toContainText(/waiting/i)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the Work list meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/work')
    await expect(page.locator(ROW).first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
