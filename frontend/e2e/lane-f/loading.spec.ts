import { expect, test } from '../support/guard'

// #525: no card shows "unknown" or "unavailable" while its data is still
// loading. The journey delays the operations response in the browser, so the
// cards stay in the loading state for a few seconds.
// @pending until #525 merges.

const LOADING_DELAY_MS = 4_000
const NOT_LOADED = /\b(unknown|unavailable)\b/i

for (const route of ['/harnesses', '/harnesses/claude-code']) {
  test(`@pending ${route} shows no "unknown" or "unavailable" while it loads`, async ({ page }) => {
    let delayed = 0
    // Registered after the guard route, so it runs first; fallback() then
    // hands the request to the guard, which lets the local request through.
    await page.route(/\/api\/v1\/providers\/[^/]+\/operations/, async route => {
      delayed += 1
      await new Promise(resolve => setTimeout(resolve, LOADING_DELAY_MS))
      await route.fallback()
    })
    await page.goto(route)
    await expect.poll(() => delayed, 'the operations request is delayed').toBeGreaterThan(0)
    await page.waitForTimeout(1_000)
    const text = (await page.locator('main').innerText()).replace(/\s+/g, ' ')
    expect(text, 'the loading state names no unknown value').not.toMatch(NOT_LOADED)
  })
}
