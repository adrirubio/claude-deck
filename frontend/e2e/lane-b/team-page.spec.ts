import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #542: a team opens as a readable page. At 1440 × 900 the header and all
// members of a 4-member team are visible without scrolling; no editable field
// shows until the person selects Edit team; no charter text shows until a
// member row is expanded.
// Seed (scripts/e2e/scenarios.py, seed_lane_b): "Docs crew" (team 5) has 4
// members and no scope. Each seeded slot has "Synthetic charter for <name>."
// Design reference: screen 06 (Teams).
// @pending until #542 merges.

const TEAM = '/teams/5'
const MEMBERS = ['D2 Docs lead', 'D3 Writer', 'D4 Editor', 'D5 Reviewer']

test.use({ viewport: { width: 1440, height: 900 } })

test('@pending the header and all 4 members are visible without scrolling', async ({ page }) => {
  await page.goto(TEAM)
  await expect(page.locator('main').getByRole('heading', { name: 'Docs crew' }).first()).toBeInViewport()
  for (const member of MEMBERS) {
    await expect(page.locator('main').getByText(member, { exact: true }).first(), member).toBeInViewport()
  }
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
})

test('@pending no editable field shows until Edit team', async ({ page }) => {
  await page.goto(TEAM)
  const main = page.locator('main')
  await expect(main.getByText('D2 Docs lead').first()).toBeVisible()
  await expect(main.locator('input:not([type=checkbox]), textarea, select')).toHaveCount(0)
  await main.getByRole('button', { name: 'Edit team' }).click()
  await expect(main.locator('input:not([type=checkbox]), textarea').first()).toBeVisible()
})

test('@pending no charter shows until a member row is expanded', async ({ page }) => {
  await page.goto(TEAM)
  const main = page.locator('main')
  await expect(main.getByText('D3 Writer').first()).toBeVisible()
  await expect(main.getByText(/Synthetic charter for/)).toHaveCount(0)
  const row = main.getByText('D3 Writer', { exact: true }).first()
    .locator('xpath=ancestor::*[self::li or self::article or self::details or contains(@class,"border")][1]')
  await row.getByRole('button', { name: /expand|details|show|more/i }).first().click()
  await expect(row.getByText('Synthetic charter for D3 Writer.')).toBeVisible()
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@pending the team page meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto(TEAM)
    await expect(page.locator('main').getByText('D2 Docs lead').first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
