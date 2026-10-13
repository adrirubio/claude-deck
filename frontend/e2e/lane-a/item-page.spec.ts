import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #534: each item page links back to Work; a merged item shows no recovery
// remedies and no "unknown" outside "Technical details"; wrong IDs show one
// plain message with a link back, and no invalid ID in the heading.
// Design reference: screens 04 (merged item) and 05 (item that needs attention).
// @active since #534 merged into release/v3.1 (PR #609).

async function textOutsideTechnical(page: import('@playwright/test').Page): Promise<string> {
  return page.locator('main').evaluate(root => {
    const clone = root.cloneNode(true) as Element
    clone.querySelectorAll('details').forEach(details => {
      if (/technical detail/i.test(details.querySelector('summary')?.textContent ?? '')) details.remove()
    })
    return (clone.textContent ?? '').replace(/\s+/g, ' ')
  })
}

test('@active each item page links back to Work', async ({ page }) => {
  for (const id of [1, 2, 4]) {
    await page.goto(`/work/${id}`)
    const back = page.locator('main a[href="/work"], main a[href^="/work?"]').first()
    await expect(back).toBeVisible()
  }
})

test('@active a merged item shows no recovery remedies and no "unknown"', async ({ page }) => {
  await page.goto('/work/4')
  await expect(page.getByRole('heading', { name: /#104/ }).first()).toBeVisible()
  await expect(page.locator('main').getByRole('button', { name: /retry|recover|resume|escalate/i })).toHaveCount(0)
  const text = await textOutsideTechnical(page)
  expect(text).not.toMatch(/\bunknown\b/i)
  expect(text).not.toMatch(/Protected recovery|Existing attempt recovery/i)
})

const WRONG_IDS = [
  { route: '/work/abc', api: /\/api\/v1\/factory\/work-items\/abc$/, status: 422 },
  { route: '/work/99999', api: /\/api\/v1\/factory\/work-items\/99999$/, status: 404 },
  { route: '/repositories/abc', api: /\/api\/v1\/factory\/repositories\/abc$/, status: 422 },
  { route: '/repositories/99999', api: /\/api\/v1\/factory\/repositories\/99999$/, status: 404 },
]

for (const { route, api, status } of WRONG_IDS) {
  test(`@active ${route} shows one plain message with a link back`, async ({ page, guard }) => {
    guard.expectStatus('GET', api, status)
    await page.goto(route)
    const main = page.locator('main')
    await expect(main.getByText(/does not exist|was not found|no such/i)).toHaveCount(1)
    await expect(main.locator('a[href="/work"], a[href="/repositories"]').first()).toBeVisible()
    const id = route.split('/').pop() as string
    for (const heading of await main.getByRole('heading').allInnerTexts()) {
      expect(heading, 'no invalid ID in the heading').not.toContain(id)
    }
    await expect(main).not.toContainText(/422|404|projection_failed|resource_not_found/)
  })
}

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the item page meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/work/1')
    await expect(page.getByRole('heading', { name: /#101/ }).first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
