import type { Page } from '@playwright/test'
import { expect, test } from '../support/guard'

// #507: a Director filters by team and by repository without knowing an ID.
// No input value blanks the page: an unknown URL value shows one short message
// with a reset link, and the rest of the page.
// @pending until #507 merges.
// Seeded names: team "Release crew" (items #101-#105) and "Quiet team" (no
// items); repositories "example-org/sample-app" and "example-org/quiet-lib".

const PAGES = [
  { name: 'Overview', route: '/' },
  { name: 'Work', route: '/work' },
]

async function open(page: Page, route: string, heading: string): Promise<void> {
  await page.goto(route)
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
}

for (const { name, route } of PAGES) {
  test(`@pending ${name} filters by team name`, async ({ page }) => {
    await open(page, route, name)
    const team = page.getByRole('combobox', { name: /^Team$/ })
    await expect(team).toBeVisible()
    await expect(page.getByLabel(/Team ID/)).toHaveCount(0)
    await team.selectOption({ label: 'Quiet team' })
    await expect(page.getByText('Fix the settings page layout')).toHaveCount(0)
    await team.selectOption({ label: 'Release crew' })
    if (name === 'Work') await expect(page.getByText('Fix the settings page layout').first()).toBeVisible()
  })

  test(`@pending ${name} filters by repository name`, async ({ page }) => {
    await open(page, route, name)
    const repository = page.getByRole('combobox', { name: /^Repository$/ })
    await expect(repository).toBeVisible()
    await expect(page.getByLabel(/Repository scope ID/)).toHaveCount(0)
    await repository.selectOption({ label: 'example-org/quiet-lib' })
    await expect(page.getByText('Fix the settings page layout')).toHaveCount(0)
    await repository.selectOption({ label: 'example-org/sample-app' })
    if (name === 'Work') await expect(page.getByText('Fix the settings page layout').first()).toBeVisible()
  })

  for (const param of ['team_id=999999', 'scope_id=999999', 'team_id=not-a-number']) {
    test(`@pending ${name} with an unknown ${param} keeps the page and offers a reset`, async ({ page, guard }) => {
      // The API may refuse the value once (404 or 422). The guard still fails
      // a repeat of that request.
      guard.expectStatus('GET', /\/api\/v1\/factory\//, 404)
      guard.expectStatus('GET', /\/api\/v1\/factory\//, 422)
      await open(page, `${route}?${param}`, name)
      const reset = page.getByRole('link', { name: /reset/i })
      await expect(reset).toHaveCount(1)
      await expect(page.getByRole('combobox', { name: /^Team$/ })).toBeVisible()
      await reset.click()
      await expect(page).not.toHaveURL(new RegExp(param))
      await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    })
  }
}
