import type { Locator, Page } from '@playwright/test'
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

// The cards stay skeletons until each harness's operations response arrives. A keyboard check
// that starts before the card links exist finds no controls (the failure seen on the hosted run).
const OPERATIONS = /\/api\/v1\/providers\/[^/]+\/operations/
const SLOW_RELEASE_MS = 2_500
const SLOW_HOLD_LIMIT_MS = 10_000
const READY_TIMEOUT_MS = 15_000

function cardLink(page: Page, harness: string): Locator {
  return page.locator('main').locator(`a[href="/harnesses/${harness}"]`).first()
}

/** The actual card links of every harness are on the page. A heading or a page load is not enough. */
async function expectCardLinksReady(page: Page): Promise<void> {
  for (const harness of HARNESSES) {
    await expect(cardLink(page, harness), `the ${harness} card link is ready`).toBeVisible({ timeout: READY_TIMEOUT_MS })
  }
}

/**
 * Holds the operations responses of the next page load. They are released after SLOW_RELEASE_MS
 * or by release(), and never wait longer than SLOW_HOLD_LIMIT_MS. dispose() always removes the route
 * and the timer, so a failing test cannot leave a request hanging.
 */
async function holdOperations(page: Page) {
  let held = 0
  let release = () => {}
  const released = new Promise<void>(resolve => { release = resolve })
  const handler = async (route: import('@playwright/test').Route) => {
    held += 1
    await Promise.race([released, new Promise(resolve => setTimeout(resolve, SLOW_HOLD_LIMIT_MS))])
    await route.fallback()
  }
  // Registered after the guard route, so it runs first; fallback() hands the request to the guard.
  await page.route(OPERATIONS, handler)
  const timer = setTimeout(release, SLOW_RELEASE_MS)
  return {
    held: () => held,
    async dispose() {
      clearTimeout(timer)
      release()
      await page.unroute(OPERATIONS, handler)
    },
  }
}

// The normal and the slow case run the same sequence. Only the slow case holds the operations
// responses of the second visit, and it proves the cards are still loading before they are released.
for (const slow of [false, true]) {
  const name = slow
    ? '@active a card opens its harness page by click and by keyboard while the cards load slowly'
    : '@active a card opens its harness page by click and by keyboard'
  test(name, async ({ page }) => {
    await page.goto('/harnesses')
    await card(page, 'codex-cli').click()
    await expect(page).toHaveURL(/\/harnesses\/codex-cli$/)
    const hold = slow ? await holdOperations(page) : null
    try {
      await page.goto('/harnesses')
      if (hold) {
        await expect.poll(hold.held, 'the operations requests are held').toBeGreaterThan(0)
        await expect(page.getByRole('heading', { name: 'Harnesses', exact: true })).toBeVisible()
        await expect(page.locator('main').locator('a[href^="/harnesses/"]'), 'no card link exists while the cards load').toHaveCount(0)
        await expect(page.getByRole('status').filter({ hasText: /^Loading /i }).first(), 'a loading state is shown').toBeVisible()
      }
      await expectCardLinksReady(page)
      await expectKeyboardReachable(page, page.locator('main'), 3)
      await cardLink(page, 'claude-code').focus()
      await page.keyboard.press('Enter')
      await expect(page).toHaveURL(/\/harnesses\/claude-code$/)
    } finally {
      await hold?.dispose()
    }
  })
}

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the harness list meets AA contrast in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/harnesses')
    await expect(page.getByRole('heading', { name: 'Harnesses', exact: true })).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
  })
}
