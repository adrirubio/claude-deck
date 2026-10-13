import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #508: the Overview answers the Director's three questions. In the idle
// state the page fits one viewport and states "idle and paused" once; with
// open Director actions, the first visible item is the action list; no empty
// section shows a filter message when no filter is set.
// Seed: Release crew has open Director actions (#101 attention, #102 review);
// Quiet team is idle and paused (autonomy off, scope intake disabled).
// Design reference: screens 01 (Needs you), 02 (Idle and paused), 21 (light).
// @pending until #508 merges.

test.use({ viewport: { width: 1440, height: 900 } })

test('@pending with open Director actions, the first visible item is the action list', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  const first = page.locator('main').getByRole('heading').nth(1)
  await expect(first).toHaveText(/Needs you|Your actions|Do I need to act/i)
  await expect(first).toBeInViewport()
})

test('@pending the idle state fits one viewport and says "idle and paused" once', async ({ page }) => {
  await page.goto('/?team_id=2')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page.locator('main').getByText(/idle and paused/i)).toHaveCount(1)
  const height = await page.evaluate(() => document.documentElement.scrollHeight)
  expect(height, 'the idle Overview fits 900 px').toBeLessThanOrEqual(900)
})

test('@pending no empty section shows a filter message when no filter is set', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await page.waitForLoadState('networkidle').catch(() => undefined)
  await expect(page.locator('main')).not.toContainText(/(no|nothing) (items? )?(match|matches|matching) (the|this|these|your) filters?/i)
  await expect(page.locator('main')).not.toContainText(/reset filters to see/i)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@pending the Overview meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
