import { expect, test } from '../support/guard'
import { openUnlockedAudit } from './support'

// #516: a Director filters Audit by team, repository and window without
// typing; a deleted team or repository can still be selected with its
// history; two teams with the same name are two entries; the filters appear
// above everything that they filter.
// Seed: the deleted team "Retired crew" (history kept) and a live team with
// the same name (DUPLICATE_NAME_TEAM in scripts/e2e/scenarios.py).
// @pending until #516 merges.

test('@pending Audit filters by team, repository and window with selects, not typed keys', async ({ page }) => {
  await openUnlockedAudit(page)
  await expect(page.getByLabel(/context key/i)).toHaveCount(0)
  for (const name of [/^Team$/, /^Repository$/, /^Window$/]) {
    await expect(page.getByRole('combobox', { name })).toBeVisible()
  }
})

test('@pending the deleted team can be selected and shows its history', async ({ page }) => {
  await openUnlockedAudit(page)
  const team = page.getByRole('combobox', { name: /^Team$/ })
  const deleted = team.locator('option').filter({ hasText: /Retired crew.*deleted|deleted.*Retired crew/i })
  await expect(deleted).toHaveCount(1)
  await team.selectOption({ label: (await deleted.innerText()).trim() })
  await expect(page.locator('main').getByText(/Publish the launch page|team retired|#7\b/).first()).toBeVisible()
})

test('@pending two teams with the same name are two distinct entries', async ({ page }) => {
  await openUnlockedAudit(page)
  const options = page.getByRole('combobox', { name: /^Team$/ }).locator('option').filter({ hasText: 'Retired crew' })
  await expect(options).toHaveCount(2)
  const labels = (await options.allInnerTexts()).map(label => label.trim())
  expect(new Set(labels).size, `distinct labels: ${JSON.stringify(labels)}`).toBe(2)
})

test('@pending the filters sit above everything that they filter', async ({ page }) => {
  await openUnlockedAudit(page)
  const filterBox = await page.getByRole('combobox', { name: /^Team$/ }).boundingBox()
  const firstResult = await page.locator('main').getByText(/Needs a look|delivery|events?/i).first().boundingBox()
  expect(filterBox && firstResult && filterBox.y < firstResult.y, 'the Team filter is above the first result').toBe(true)
})
