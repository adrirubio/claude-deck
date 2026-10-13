import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #537: the setup wizard asks for the Director key only when it is needed,
// step 1 can be completed without typing a path or a branch name, and a
// cancelled key dialog leaves a clear way to enter the key later.
// The seed's team folders (sample-app, quiet-lib) are the choices for step 1.
// Design reference: screen 09 (add a repository).
// @active until #537 merges.

test('@active opening the wizard shows no dialog', async ({ page }) => {
  await page.goto('/repositories/new')
  await expect(page.locator('main').getByText(/^(Set up|Add) a repository$/i).first()).toBeVisible()
  await page.waitForLoadState('networkidle').catch(() => undefined)
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('@active step 1 can be completed without typing a path or a branch name', async ({ page }) => {
  await page.goto('/repositories/new')
  const main = page.locator('main')
  // The checkout path and the base branch are choices, not text inputs.
  await expect(main.getByRole('textbox', { name: /path/i })).toHaveCount(0)
  await expect(main.getByRole('textbox', { name: /branch/i })).toHaveCount(0)
  // No endpoint reads the owner and name from a checkout, so the person gives
  // them in the GitHub repository field. Nothing else is typed.
  await main.getByRole('textbox', { name: /GitHub repository/i }).fill('example-org/sample-app')
  const checkout = main.getByRole('combobox', { name: /checkout|folder|repository/i }).first()
  await expect(checkout).toBeVisible()
  await checkout.selectOption({ index: 1 })
  const branch = main.getByRole('combobox', { name: /branch/i }).first()
  await expect(branch).toBeVisible()
  await main.getByRole('button', { name: /next|continue/i }).first().click()
  await expect(main.getByText(/2\.\s*Team|Team and roles/).first()).toBeVisible()
})

test('@active a cancelled key dialog leaves a clear way to enter the key later', async ({ page }) => {
  await page.goto('/repositories/new')
  const main = page.locator('main')
  const askForKey = main.getByRole('button', { name: /Director key|unlock|enter (the )?key/i }).first()
  await askForKey.click()
  await page.getByRole('dialog').getByRole('button', { name: /cancel/i }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(main.getByRole('button', { name: /Director key|unlock|enter (the )?key/i }).first()).toBeVisible()
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the wizard meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/repositories/new')
    await expect(page.locator('main').getByText(/^(Set up|Add) a repository$/i).first()).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
