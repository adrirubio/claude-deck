import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #549: the team card shows a supervisor line derived from the clock, as in
// the design reference (screens/06-teams.png, explainer 06): None, Healthy,
// Late or Absent. Seed (scripts/e2e/scenarios.py, seed_lane_g): Release crew
// has a bound supervisor whose next check is 8 minutes ahead (Healthy), when
// the #549 columns exist. Quiet team has no supervisor (None).
// @pending until #549 merges.

const SUPERVISOR_LINE = /Supervisor\b[^\n]*/

async function supervisorLine(page: import('@playwright/test').Page): Promise<string> {
  const line = page.locator('main').getByText(/^Supervisor\b/).first()
  await expect(line).toBeVisible()
  const text = (await line.locator('xpath=..').innerText()).replace(/\s+/g, ' ')
  return SUPERVISOR_LINE.exec(text)?.[0] ?? text
}

test('@pending a team with a supervisor that checked in shows Healthy', async ({ page }) => {
  await page.goto('/teams/1')
  await expect(page.getByRole('heading', { name: 'Agent Teams', exact: true })).toBeVisible()
  expect(await supervisorLine(page)).toMatch(/Healthy/)
})

test('@pending a team without a supervisor shows None, not an error', async ({ page }) => {
  await page.goto('/teams/2')
  await expect(page.getByRole('heading', { name: 'Agent Teams', exact: true })).toBeVisible()
  const line = await supervisorLine(page)
  expect(line).toMatch(/None|No supervisor/)
  expect(line).not.toMatch(/error|late|absent/i)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@pending the team card meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/teams/1')
    await expect(page.locator('main').getByText(/^Supervisor\b/).first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
