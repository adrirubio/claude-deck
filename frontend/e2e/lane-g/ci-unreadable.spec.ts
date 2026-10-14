import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #550: when required CI cannot be read for longer than the grace period,
// the Work item page shows the signal and its next steps, as in the design
// reference (screens/05-work-item-attention.png).
// Seed: item #102 (PR #202) has had unreadable required CI for 2 hours
// (scripts/e2e/scenarios.py, seed_lane_g).
// Active since #550 (backend PR #621, pages PR for #622).

const SIGNAL = /required (CI|checks?) cannot be read/i

test('@active the work item page shows the unreadable-CI signal and its next steps', async ({ page }) => {
  await page.goto('/work/2')
  await expect(page.getByRole('heading', { name: /#102/ }).first()).toBeVisible()
  const signal = page.locator('main').getByText(SIGNAL).first()
  await expect(signal).toBeVisible()
  // The next steps sit with the signal: at least one instruction or link.
  const block = signal.locator('xpath=ancestor::*[self::section or self::article or contains(@class,"border")][1]')
  await expect(block).toContainText(/next step|check|retry|token|access/i)
})

test('@active the Overview lists the unreadable-CI item as needing attention', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page.locator('main').getByText(SIGNAL).first()).toBeVisible()
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the signal meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/work/2')
    await expect(page.locator('main').getByText(SIGNAL).first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
