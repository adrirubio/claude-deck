import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #550: when required CI cannot be read for longer than the grace period,
// the Work item page shows the signal and its next steps, as in the design
// reference (screens/05-work-item-attention.png).
// Seed: the #550 implementer adds the stored "required CI cannot be read"
// state for item #102 (PR #202) in scripts/e2e/scenarios.py (seed_lane_g),
// in the PR that activates these journeys.
// @pending until #550 merges.

const SIGNAL = /required (CI|checks?) cannot be read/i

test('@pending the work item page shows the unreadable-CI signal and its next steps', async ({ page }) => {
  await page.goto('/work/2')
  await expect(page.getByRole('heading', { name: 'Work details', exact: true })).toBeVisible()
  const signal = page.locator('main').getByText(SIGNAL).first()
  await expect(signal).toBeVisible()
  // The next steps sit with the signal: at least one instruction or link.
  const block = signal.locator('xpath=ancestor::*[self::section or self::article or contains(@class,"border")][1]')
  await expect(block).toContainText(/next step|check|retry|token|access/i)
})

test('@pending the Overview lists the unreadable-CI item as needing attention', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page.locator('main').getByText(SIGNAL).first()).toBeVisible()
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@pending the signal meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/work/2')
    await expect(page.locator('main').getByText(SIGNAL).first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
