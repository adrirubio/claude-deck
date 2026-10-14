import type { Locator } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #539 (merged, PR #663): a readable session list. At 1440 × 900 there is no
// horizontal scrollbar and full role names are visible; no row shows a hash, a
// tmux target or a reason code outside "Technical details"; Kill is never next
// to the Watch target.
// Seed: 8 fake panes of Release crew.
// Design reference: screen 10 (Live sessions).
// @active since #539 merged into release/v3.1 (PR #663).

test.use({ viewport: { width: 1440, height: 900 } })

const MEMBERS = ['L1 Leader', 'B1 Backend', 'B2 Backend', 'F1 Frontend', 'F2 Frontend', 'D1 Docs', 'E1 E2E', 'V1 Verifier']
const TECHNICAL = /\b[0-9A-Z]{12,}\b|\bdeck-e2e-\d+:\d+\.\d+\b|tmux:|\b[a-z]+(?:_[a-z]+)+\b/

async function plainText(region: Locator): Promise<string> {
  return region.evaluate(root => {
    const clone = root.cloneNode(true) as Element
    clone.querySelectorAll('details').forEach(details => {
      if (/technical details/i.test(details.querySelector('summary')?.textContent ?? '')) details.remove()
    })
    return (clone.textContent ?? '').replace(/\s+/g, ' ')
  })
}

function card(page: import('@playwright/test').Page, member: string): Locator {
  return page.getByRole('button', { name: `Watch ${member}` })
    .locator('xpath=ancestor::*[contains(@class,"border")][1]')
}

test('@active the list has no horizontal scrollbar and shows full role names', async ({ page }) => {
  await page.goto('/agent-bridge')
  await expect(page.getByText('Sessions (8)')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, 'horizontal overflow in pixels').toBeLessThanOrEqual(0)
  for (const role of ['leader', 'implementer', 'reviewer']) {
    await expect(page.locator('main').getByText(new RegExp(`· ${role}\\b`)).first()).toBeVisible()
  }
})

test('@active no row shows a hash, a tmux target or a reason code outside Technical details', async ({ page }) => {
  await page.goto('/agent-bridge')
  await expect(page.getByText('Sessions (8)')).toBeVisible()
  for (const member of MEMBERS) {
    const text = await plainText(card(page, member))
    expect(text, member).not.toMatch(TECHNICAL)
  }
})

test('@active Kill is never next to the Watch target', async ({ page }) => {
  await page.goto('/agent-bridge')
  await expect(page.getByText('Sessions (8)')).toBeVisible()
  for (const member of MEMBERS) {
    const row = card(page, member)
    await expect(row.getByRole('button', { name: /kill/i }), `${member}: no Kill button in the row`).toHaveCount(0)
  }
  // Kill is a menu item behind "More actions".
  await page.getByRole('button', { name: 'More actions for B1 Backend' }).click()
  await expect(page.getByRole('menuitem', { name: /Kill session/ })).toBeVisible()
  await page.keyboard.press('Escape')
})

// The contrast journeys check the filter chip counts ("(8)", "(7)" ...). They
// failed AA while the counts were `span.opacity-70` (#667). They are active
// since #674 (PR #684) removed the opacity.
for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active Live sessions meets AA contrast in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/agent-bridge')
    await expect(page.getByText('Sessions (8)')).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
  })

  test(`@active Live sessions is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/agent-bridge')
    await expect(page.getByText('Sessions (8)')).toBeVisible()
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
