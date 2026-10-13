import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #536: Repositories is the single home for repository setup and settings.
// Settings are viewed and edited in one place only; there is one flow to add a
// repository; no repository page shows a copy of the Work table or an internal
// scope number in its title.
// Design reference: screens 07 (list), 08 (repository page), 09 (add).
// @pending until #536 merges.

test('@pending repository settings are viewed and edited only on the repository page', async ({ page }) => {
  await page.goto('/repositories/1')
  await expect(page.locator('main').getByRole('heading', { name: /example-org\/sample-app/ }).first()).toBeVisible()
  await expect(page.locator('main').getByRole('button', { name: /edit|save/i }).first()).toBeVisible()
  await page.goto('/teams/1?tab=autonomy')
  await expect(page.locator('main')).toBeVisible()
  await page.waitForLoadState('networkidle').catch(() => undefined)
  await expect(page.locator('main').getByRole('button', { name: /edit (repository|scope|watched)|save (repository|scope)/i })).toHaveCount(0)
  await expect(page.locator('main a[href="/repositories/1"]').first()).toBeVisible()
})

test('@pending there is one flow to add a repository', async ({ page }) => {
  await page.goto('/repositories')
  await expect(page.locator('main a[href="/repositories/new"]').first()).toBeVisible()
  await page.goto('/teams/1?tab=autonomy')
  await page.waitForLoadState('networkidle').catch(() => undefined)
  await expect(page.locator('main').getByRole('button', { name: /add (a )?(repository|scope|watched repo)/i })).toHaveCount(0)
})

test('@pending a repository page shows no Work table copy and no scope number in its title', async ({ page }) => {
  await page.goto('/repositories/1')
  const title = page.locator('main').getByRole('heading').first()
  await expect(title).toBeVisible()
  await expect(title).not.toContainText(/scope\s*\d+/i)
  expect(await page.title()).not.toMatch(/scope\s*\d+/i)
  await expect(page.locator('main table').filter({ hasText: /Add the CSV export button/ })).toHaveCount(0)
  await expect(page.locator('main a[href^="/work?"]').first()).toBeVisible()
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@pending Repositories meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    for (const route of ['/repositories', '/repositories/1']) {
      await page.goto(route)
      await expect(page.locator('main').getByRole('heading').first()).toBeVisible()
      const failures = await contrastFailures(page.locator('main'))
      expect(failures, `${route}: ${JSON.stringify(failures)}`).toEqual([])
    }
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
