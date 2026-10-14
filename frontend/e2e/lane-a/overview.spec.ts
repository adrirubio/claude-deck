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
// Active since #508 (with the Progress card).

test.use({ viewport: { width: 1440, height: 900 } })

test('@active with open Director actions, the first visible item is the action list', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  const first = page.locator('main').getByRole('heading').nth(1)
  await expect(first).toHaveText(/Needs you|Your actions|Do I need to act/i)
  await expect(first).toBeInViewport()
})

test('@active the idle state fits one viewport and says "idle and paused" once', async ({ page }) => {
  await page.goto('/?team_id=2')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page.locator('main').getByText(/idle and paused/i)).toHaveCount(1)
  const height = await page.evaluate(() => document.documentElement.scrollHeight)
  expect(height, 'the idle Overview fits 900 px').toBeLessThanOrEqual(900)
})

test('@active the idle Overview does not scroll inside the page', async ({ page }) => {
  await page.goto('/?team_id=2')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page.locator('main').getByText('Nothing needs you right now.')).toBeVisible()
  // The page scrolls inside <main>, so the document height proves nothing. Measure <main>.
  const { scroll, client } = await page.locator('main').evaluate(element => ({ scroll: element.scrollHeight, client: element.clientHeight }))
  expect(scroll, 'the idle Overview fits the main area').toBeLessThanOrEqual(client)
})

test('@active the Progress card shows Done, Under way, Still to do and the decisions ahead', async ({ page }) => {
  await page.goto('/')
  const main = page.locator('main')
  await expect(main.getByRole('heading', { name: /^Progress/ })).toBeVisible()
  const card = main.getByRole('article', { name: /^Progress:/ }).first()
  await expect(card).toBeVisible()
  for (const name of [/^Done/, /^Under way/, /^Still to do/]) await expect(card.getByRole('heading', { name })).toBeVisible()
  await expect(card.getByText(/Your decisions ahead/)).toBeVisible()
  // Order: the action list comes before the Progress card.
  const headings = await main.getByRole('heading').allInnerTexts()
  expect(headings.findIndex(text => /^Needs you/.test(text))).toBeLessThan(headings.findIndex(text => /^Progress/.test(text)))
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the Progress card draws a bar over the known work when the backlog is unknown in the ${theme} theme`, async ({ page }) => {
    // Release crew has an unavailable milestone in the offline seed (#652).
    await useTheme(page, theme)
    await page.goto('/')
    const card = page.locator('main').getByRole('article', { name: /^Progress:/ }).filter({ hasText: 'Release crew' })
    await expect(card).toBeVisible()
    const bar = card.getByRole('img')
    await expect(bar).toBeVisible()
    await expect(bar).toHaveAttribute('aria-label', /^\d+ done, \d+ under way, \d+ still to do, backlog unknown$/)
    await expect(card.getByText('backlog unknown', { exact: true })).toBeVisible()
    await expect(card.getByText(/known items? done/)).toBeVisible()
    await expect(bar.getByTestId('unknown-remainder')).toBeVisible()
  })

  test(`@active the Progress card draws the full readable backlog in the ${theme} theme`, async ({ page }) => {
    // The live duplicate-name Retired crew has one not-started issue (#652).
    await useTheme(page, theme)
    await page.goto('/?team_id=4')
    const card = page.locator('main').getByRole('article', { name: /^Progress:/ })
    await expect(card).toBeVisible()
    const bar = card.getByRole('img')
    await expect(bar).toBeVisible()
    await expect(bar).toHaveAttribute('aria-label', '0 done, 0 under way, 1 still to do, backlog known')
    await expect(card.getByText('0 of 1 done', { exact: false })).toBeVisible()
    await expect(card.getByText('1 not started', { exact: false })).toBeVisible()
    await expect(card.getByText('backlog unknown', { exact: true })).toHaveCount(0)
    await expect(bar.getByTestId('unknown-remainder')).toHaveCount(0)
    const segments = await bar.locator(':scope > span').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().width))
    const width = await bar.evaluate(element => element.getBoundingClientRect().width)
    expect(segments.reduce((sum, value) => sum + value, 0)).toBeCloseTo(width, 0)
    expect(segments[2]).toBeCloseTo(width, 0)
    expect(await contrastFailures(card)).toEqual([])
  })
}

test('@active no empty section shows a filter message when no filter is set', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await page.waitForLoadState('networkidle').catch(() => undefined)
  await expect(page.locator('main')).not.toContainText(/(no|nothing) (items? )?(match|matches|matching) (the|this|these|your) filters?/i)
  await expect(page.locator('main')).not.toContainText(/reset filters to see/i)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the Overview meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
