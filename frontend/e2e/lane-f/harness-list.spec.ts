import type { Locator } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #523: all 5 harnesses fit in one viewport at 1440 × 900, and no card shows
// "unknown", "adapter", "binding" or an access code outside "Technical details".
// Design reference: screen 18 (harness list).
// @active since #523 merged.

const HARNESSES = ['claude-code', 'codex-cli', 'copilot-cli', 'opencode-cli', 'pi-cli', 'muse-cli']
// Words and codes that belong only inside "Technical details".
const TECHNICAL = /\bunknown\b|\badapter\b|\bbinding\b|\b[a-z]+(?:_[a-z]+)+\b|write capable|read only/i

/** The visible text of a region without its "Technical details" disclosures. */
async function plainText(region: Locator): Promise<string> {
  return region.evaluate(root => {
    const clone = root.cloneNode(true) as Element
    clone.querySelectorAll('details').forEach(details => {
      const summary = details.querySelector('summary')?.textContent ?? ''
      if (/technical details/i.test(summary)) details.remove()
    })
    return (clone.textContent ?? '').replace(/\s+/g, ' ')
  })
}

function card(page: import('@playwright/test').Page, harness: string): Locator {
  return page.locator('main').locator(`a[href="/harnesses/${harness}"]`).first()
    .locator('xpath=ancestor-or-self::*[self::article or self::li or contains(@class,"border")][1]')
}

test.use({ viewport: { width: 1440, height: 900 } })

test('@active all 6 harness cards fit in one 1440 × 900 viewport', async ({ page }) => {
  await page.goto('/harnesses')
  await expect(page.getByRole('heading', { name: 'Harnesses', exact: true })).toBeVisible()
  for (const harness of HARNESSES) {
    const box = await card(page, harness).boundingBox()
    expect(box, `a card for ${harness}`).not.toBeNull()
    expect((box?.y ?? 0) + (box?.height ?? 0), `${harness} card inside the viewport`).toBeLessThanOrEqual(900)
  }
})

test('@active no card shows technical words outside Technical details', async ({ page }) => {
  await page.goto('/harnesses')
  await expect(page.getByRole('heading', { name: 'Harnesses', exact: true })).toBeVisible()
  for (const harness of HARNESSES) {
    const text = await plainText(card(page, harness))
    expect(text, `${harness} card`).not.toMatch(TECHNICAL)
  }
})

test('@active a card opens its harness page by click and by keyboard', async ({ page }) => {
  await page.goto('/harnesses')
  await card(page, 'codex-cli').click()
  await expect(page).toHaveURL(/\/harnesses\/codex-cli$/)
  await page.goto('/harnesses')
  await expectKeyboardReachable(page, page.locator('main'), 3)
  await page.locator('main').locator('a[href="/harnesses/claude-code"]').first().focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/harnesses\/claude-code$/)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the harness list meets AA contrast in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/harnesses')
    await expect(page.getByRole('heading', { name: 'Harnesses', exact: true })).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
  })
}
