import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #544 (merged, PR #660): a team URL that names no team shows no team and no
// editable form; no slot shows a charter under the routing label. PR #660 also
// gives the backlog assessment age a short form and makes the Plan launch key
// dialog say why it needs the key.
// Seed (scripts/e2e/scenarios.py, seed_lane_b): B1 Backend has the routing
// label "backend"; F1 Frontend has no label and an expertise text.
// Design reference: screen 06 (Teams).
// @active since #544 merged into release/v3.1 (PR #660).

for (const id of ['abc', '999', '0']) {
  test(`@active /teams/${id} shows no team and no editable form`, async ({ page }) => {
    const perTeam: string[] = []
    page.on('request', request => {
      if (new RegExp(`/api/v1/agent-teams/presets/${id}(/|$)`).test(request.url())) perTeam.push(request.url())
    })
    await page.goto(`/teams/${id}`)
    const main = page.locator('main')
    await expect(main.getByText('This team does not exist. Select a team from the list.')).toBeVisible()
    await expect(main.getByRole('button', { name: /^Release crew/ })).toBeVisible()
    await expect(main.locator('input, textarea')).toHaveCount(0)
    await expect(main.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
    await page.waitForLoadState('networkidle').catch(() => undefined)
    expect(perTeam, 'no per-team request for an unknown team').toEqual([])
  })
}

test('@active the routing block shows labels, and expertise has its own label', async ({ page }) => {
  await page.goto('/teams/1?tab=roster')
  const main = page.locator('main')
  await expect(main.getByText('B1 Backend').first()).toBeVisible()
  const text = (await main.innerText()).replace(/\s+/g, ' ')
  expect(text).toMatch(/B1 Backend .*?GitHub dispatch routing backend/i)
  expect(text).toMatch(/F1 Frontend .*?GitHub dispatch routing None Expertise Frontend pages and accessibility\./i)
  expect(text, 'no charter under the routing label').not.toContain('Synthetic charter')
})

test('@active the backlog assessment age uses the short form', async ({ page }) => {
  await page.goto('/teams/1?tab=autonomy')
  await expect(page.getByText(/Last Leader assessment:/).first()).toBeVisible()
  const line = (await page.getByText(/Last Leader assessment:/).first().innerText()).replace(/\s+/g, ' ')
  expect(line).toMatch(/\((\d+ min ago|\d+ h ago|just now)\)/)
  expect(line).not.toMatch(/minutes ago|hours ago/)
})

test('@active Plan launch asks for the key and says why', async ({ page }) => {
  await page.goto('/teams/1?tab=roster')
  await page.getByRole('button', { name: 'Plan launch' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Deck needs the key to plan a launch.')
  await dialog.getByRole('button', { name: /cancel/i }).first().click()
  await expect(dialog).toHaveCount(0)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the Teams roster and the not-found page meet AA contrast and are keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    for (const route of ['/teams/1?tab=roster', '/teams/abc']) {
      await page.goto(route)
      await expect(page.getByRole('heading', { name: 'Teams', exact: true })).toBeVisible()
      const failures = await contrastFailures(page.locator('main'))
      expect(failures, `${route}: ${JSON.stringify(failures)}`).toEqual([])
    }
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
