import type { Page } from '@playwright/test'
import { expect, test } from '../support/guard'
import { localTimeText, seedAgo } from '../support/time'

// #533: the Work item page is the single home of a work item. Item actions
// (retry, recovery, remedies) exist only there; other screens link to Work
// with a filter instead of listing work items in full; one item shows the
// same status words and the same time on every screen.
// Design reference: screens 03-05.
// @active since #533 merged into release/v3.1 (PR #615).

const ITEM_ACTIONS = /^(Retry|Retry issue|Recover|Resume attempt|Escalate attempt|Authorize retry)\b/i

test('@active item actions exist only on the Work item page', async ({ page }) => {
  await page.goto('/work/1')
  await expect(page.getByRole('heading', { name: /#101/ }).first()).toBeVisible()
  await expect(page.locator('main').getByRole('button', { name: ITEM_ACTIONS }).first()).toBeVisible()
  for (const route of ['/', '/teams/1?tab=autonomy', '/repositories/1']) {
    await page.goto(route)
    await expect(page.locator('main')).toBeVisible()
    await page.waitForLoadState('networkidle').catch(() => undefined)
    await expect(page.locator('main').getByRole('button', { name: ITEM_ACTIONS }), `no item action on ${route}`).toHaveCount(0)
  }
})

test('@active other screens link to Work with a filter instead of listing work in full', async ({ page }) => {
  // Teams and the repository page list no work items; they link to Work with a filter.
  for (const route of ['/teams/1?tab=autonomy', '/repositories/1']) {
    await page.goto(route)
    await expect(page.locator('main')).toBeVisible()
    await page.waitForLoadState('networkidle').catch(() => undefined)
    await expect(page.locator('main table'), `no work table on ${route}`).toHaveCount(0)
    await expect(page.locator('main a[href^="/work?"]').first(), `a filtered Work link on ${route}`).toBeVisible()
  }
  // The Overview shows short previews only; each one links to the full, filtered list.
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await page.waitForLoadState('networkidle').catch(() => undefined)
  for (const table of await page.locator('main table').all()) {
    const section = table.locator('xpath=ancestor::section[1]')
    await expect(section.locator('a[href^="/work?"]').first(), 'a "View all" link to filtered Work').toBeVisible()
  }
})

async function statusAndTime(page: Page, route: string): Promise<{ status: string; time: string | null }> {
  await page.goto(route)
  const scope = page.locator(route.startsWith('/work/') ? 'main' : 'main [data-work-table]')
  const title = scope.getByText('Fix the settings page layout').first()
  await expect(title).toBeVisible()
  const block = title.locator('xpath=ancestor::*[self::tr or self::li or self::article or self::main or contains(@class,"border")][1]')
  const text = (await block.innerText()).replace(/\s+/g, ' ')
  const status = /\b(Needs review|Ready for human review|Waiting for review)\b/.exec(text)?.[1] ?? ''
  return { status, time: localTimeText(text, seedAgo({ hours: 1 })) }
}

test('@active one item shows the same status words and time on every screen that shows it', async ({ page }) => {
  const views = {
    work: await statusAndTime(page, '/work'),
    item: await statusAndTime(page, '/work/2'),
    overview: await statusAndTime(page, '/'),
  }
  const statuses = new Set(Object.values(views).map(view => view.status))
  expect(statuses.size, `status words: ${JSON.stringify(views)}`).toBe(1)
  expect([...statuses][0]).not.toBe('')
  const times = new Set(Object.values(views).map(view => view.time))
  expect(times.size, `times: ${JSON.stringify(views)}`).toBe(1)
})
