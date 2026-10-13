import { expect, test } from '../support/guard'
import { openUnlockedAudit, plainText } from './support'

// #517: at 1440 × 900 the coverage sentence, all headline results and the
// "Needs a look" panel are visible without scrolling; no timestamp shows
// microseconds or ISO interval notation outside the technical section; the
// technical table fits its card with no horizontal scrollbar.
// Design reference: screens 16 and 17 (Audit).

test.use({ viewport: { width: 1440, height: 900 } })

test('@active the delivery summary and Needs a look fit the first screen', async ({ page }) => {
  await openUnlockedAudit(page)
  const needs = page.getByRole('heading', { name: /Needs a look/i })
  await expect(needs).toBeInViewport()
  await expect(page.locator('main').getByText(/coverage/i).first()).toBeInViewport()
  const scrollY = await page.evaluate(() => window.scrollY)
  expect(scrollY).toBe(0)
})

test('@active no microseconds or ISO intervals outside the technical section', async ({ page }) => {
  await openUnlockedAudit(page)
  const text = await plainText(page.locator('main'))
  expect(text, 'no microsecond timestamps').not.toMatch(/\d{2}:\d{2}:\d{2}\.\d{3,}/)
  expect(text, 'no ISO timestamps').not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/)
  expect(text, 'no ISO interval notation').not.toMatch(/\bto \d{4}-\d{2}-\d{2}|\/P\d|--\d{4}-/)
})

test('@active the technical table fits its card without a horizontal scrollbar', async ({ page }) => {
  await openUnlockedAudit(page)
  const disclosure = page.locator('main details').filter({ hasText: /technical/i }).first()
  await disclosure.locator('summary').click()
  const table = disclosure.locator('table').first()
  await expect(table).toBeVisible()
  const overflow = await table.evaluate(element => {
    const scroller = element.closest('[class*="overflow"]') ?? element.parentElement ?? element
    return scroller.scrollWidth - scroller.clientWidth
  })
  expect(overflow, 'horizontal overflow in pixels').toBeLessThanOrEqual(1)
})
